
import json
import logging
from collections import Counter
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

from .pttavm_api import PTTAVM_MAX_WINDOW_DAYS
from .pttavm_order import PTTAVM_CANCEL_STATUSES, PTTAVM_STATUS_RANK, normalize_status

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

_SYNC_LOCK_NS = 7471021  # mağaza başına senkron kilidi (pg advisory lock ad alanı)


def _digits(value):
    return ''.join(filter(str.isdigit, str(value or '')))


class PttavmOrderSync(models.Model):
    _inherit = 'pttavm.order'

    @api.model
    def sync_orders_from_pttavm(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['pttavm.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("Pttavm %s senkronizasyon hatası: %s", store.name, e)
                store._write_sync_state(error=str(e))

    @api.model
    def _now_turkey(self):
        return datetime.now(pytz.UTC).astimezone(IST).replace(tzinfo=None)

    @api.model
    def _parse_tr_datetime(self, value):
        """PttAVM tarihleri (islemTarihi) Türkiye saatidir — Odoo UTC saklar."""
        if not value:
            return False
        try:
            naive_dt = datetime.strptime(str(value)[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            _logger.warning("PttAVM tarih parse hatası: %s", value)
            return False
        return IST.localize(naive_dt).astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def sync_orders_for_store(self, store):
        """Mağazanın son N gündeki siparişlerini çeker; yenileri açar, mevcutların satır / durum /
        kargo bilgilerini günceller (PttAVM'de değişiklik tarihi filtresi ve sayfalama yok)."""
        # Aynı mağazada tek senkron (cron sürerken manuel senkron aynı siparişleri paralel açmasın)
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (_SYNC_LOCK_NS, store.id))
        if not self.env.cr.fetchone()[0]:
            _logger.info("PttAVM senkronizasyon [%s] atlandı: başka bir senkron çalışıyor", store.name)
            return {'created': 0, 'updated': 0, 'errors': 0, 'busy': True}

        api_client = store.get_api()
        now = fields.Datetime.now()
        # PttAVM en fazla 40 günlük aralık kabul eder (bitişe 5 dk pay eklendiği için 39)
        day_range = min(max(store.order_day_range or 30, 1), PTTAVM_MAX_WINDOW_DAYS - 1)
        # PttAVM API Türkiye saatinde çalışır — sorgu tarihleri Türkiye saatiyle gider
        now_turkey = self._now_turkey()
        start_date = now_turkey - timedelta(days=day_range)
        end_date = now_turkey + timedelta(minutes=5)  # küçük güvenlik marjı

        _logger.info("PttAVM [%s] sipariş çekiliyor (TR saati): %s → %s (son %d gün)",
                     store.name, start_date, end_date, day_range)

        res = api_client.get_orders(start_date=start_date, end_date=end_date)
        if not res.get('success'):
            error = res.get('error') or 'Bilinmeyen hata'
            _logger.error("PttAVM Sipariş Çekme Hatası [%s]: %s", store.name, error)
            store._write_sync_state(error=error)
            return {'created': 0, 'updated': 0, 'errors': 1, 'error': error}

        data_list = self._extract_order_list(res.get('data'))
        counters = Counter()
        counters['received'] = len(data_list)
        cutoff_new = now - timedelta(days=day_range)
        for order_json in data_list:
            try:
                with self.env.cr.savepoint():
                    action = self._sync_order_json(store, order_json, cutoff_new)
                counters[action] += 1
            except Exception as e:
                counters['errors'] += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("Pttavm Sipariş İşleme Hatası (%s): %s", order_json.get('siparisNo'), e)

        # ── Veritabanındaki iptal siparişleri tara (tarih aralığı dışındakiler dahil) ──
        try:
            with self.env.cr.savepoint():
                cancel_count = self._cancel_pending_orders(store)
                if cancel_count:
                    _logger.info("PttAVM — %d sipariş Odoo'da iptal edildi", cancel_count)
        except Exception as e:
            _logger.exception("PttAVM iptal tarama hatası: %s", e)

        # ── Bekleyen kargo barkodu talepleri / fatura gönderimi ──
        for step in (self._poll_cargo_barcodes, self._send_pending_invoices):
            try:
                step(store, api_client)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("PttAVM %s hatası [%s]: %s", step.__name__, store.name, e)

        store._write_sync_state(last_sync=now)
        _logger.info("PttAVM senkronizasyon [%s] tamamlandı: %d sipariş alındı, %d yeni, %d güncellenen, %d hata",
                     store.name, counters['received'], counters['created'], counters['updated'], counters['errors'])
        return {'created': counters['created'], 'updated': counters['updated'], 'errors': counters['errors']}

    @api.model
    def _extract_order_list(self, raw_data):
        data_list = raw_data
        if isinstance(raw_data, dict):
            data_list = raw_data.get('data', raw_data.get('siparisler', raw_data.get('orders', [])))
        if not isinstance(data_list, list):
            return []
        return [o for o in data_list if isinstance(o, dict)]

    # ─── JSON → pttavm.order ─────────────────────────────────

    @api.private
    def _sync_order_json(self, store, order_json, cutoff_new=None):
        """Tek siparişi işler. 'created' / 'updated' / 'unchanged' / 'skipped' döner."""
        order_number = str(order_json.get('siparisNo') or '').strip()
        if not order_number:
            return 'skipped'

        rec = self.search([('store_id', '=', store.id), ('order_number', '=', order_number)], limit=1)
        action = None
        if not rec:
            order_date = self._parse_tr_datetime(order_json.get('islemTarihi'))
            if cutoff_new and order_date and order_date < cutoff_new:
                return 'skipped'
            rec = self.create(self._order_header_vals(store, order_number, order_json, order_date))
            action = 'created'

        changed = rec._apply_order_json(order_json)
        if changed or action == 'created' or not rec.sale_order_id:
            rec._reconcile_sale_order(store)
        if action:
            return action
        return 'updated' if changed else 'unchanged'

    @api.model
    def _commercial_info(self, order_json):
        """(kurumsal mı, VKN/TCKN). PttAVM bazen faturaTip="Bireysel" gönderir ama VKN 10 hanedir
        (ör. PTTEM siparişleri: faturaTip="Bireysel" + vergiNo="7330638410") — hane kontrolü bu yüzden."""
        vergi_no = _digits(order_json.get('vergiNo'))
        is_commercial = order_json.get('faturaTip') == 'Kurumsal' or len(vergi_no) == 10
        return is_commercial, vergi_no or _digits(order_json.get('tckn'))

    @api.model
    def _order_header_vals(self, store, order_number, order_json, order_date):
        is_commercial, _vat = self._commercial_info(order_json)
        shipment_addr = {
            'address': order_json.get('siparisAdresi'),
            'city': order_json.get('siparisIli'),
            'district': order_json.get('siparisIlce'),
            'ilKod': order_json.get('ilKod'),
            'ilceKod': order_json.get('ilceKod'),
        }
        billing_addr = {
            'address': order_json.get('faturaAdresi'),
            'city': order_json.get('faturaIli'),
            'district': order_json.get('faturaIlce'),
            'company_name': order_json.get('firmaUnvani') or order_json.get('tedarikciFirmaAdi'),
            'tax_office': order_json.get('vergiDaire'),
            'tax_number': order_json.get('vergiNo'),
            'tckn': order_json.get('tckn'),
            'farkliAdres': order_json.get('farkliAdres'),
            'isCommercial': is_commercial,
        }
        return {
            'store_id': store.id,
            'order_id': order_number,
            'order_number': order_number,
            'order_date': order_date or fields.Datetime.now(),
            'payment_type': 1,
            'invoice_type': 2 if is_commercial else 1,
            'customer_id': str(order_json.get('musteriId') or ''),
            'customer_name': f"{order_json.get('musteriAdi') or ''} {order_json.get('musteriSoyadi') or ''}".strip(),
            'customer_email': order_json.get('eposta') or '',
            'shipment_address': json.dumps(shipment_addr, ensure_ascii=False),
            'billing_address': json.dumps(billing_addr, ensure_ascii=False),
            'shipping_city': shipment_addr['city'] or '',
            'shipping_district': shipment_addr['district'] or '',
            'tax_office': order_json.get('vergiDaire') or '',
            'currency': 'TRY',
        }

    @api.model
    def _line_vals(self, item, order_json):
        qty = int(item.get('toplamIslemAdedi') or 1)
        kdv_dahil = float(item.get('kdvDahilToplamTutar') or 0.0)
        indirim = float(item.get('indirimToplam') or 0.0)
        # Net fiyat = KDV dahil toplam - indirim toplam
        price = kdv_dahil - indirim
        variant_code = (item.get('variantBarkod') or '').strip()
        if ',' in variant_code:
            variant_code = ''  # virgülle ayrılmış varyant ID listesi — barkod değil
        return {
            'item_id': str(item.get('lineItemId') or ''),
            'product_id': str(item.get('urunId') or ''),
            'product_name': item.get('urun') or order_json.get('urunAdi') or '',
            'product_code': variant_code or item.get('urunBarkod') or order_json.get('urunKodu') or '',
            'quantity': qty,
            'sale_price': price / qty if qty else price,
            'vat_rate': float(item.get('kdvOrani') or 0),
            'status': normalize_status(item.get('siparisDurumu')),
            'cargo_tracking': str(order_json.get('kargoBarkod') or ''),
            'cargo_company': item.get('kargoKimden') or '',
        }

    def _apply_order_json(self, order_json):
        """Satırları (lineItemId ile) ve başlık durumunu günceller. Değişiklik olduysa True."""
        self.ensure_one()
        existing = {l.item_id: l for l in self.line_ids if l.item_id}
        commands = []
        line_vals = []
        seen = set()
        for item in order_json.get('siparisUrunler') or []:
            vals = self._line_vals(item, order_json)
            if not vals['item_id'] or vals['item_id'] in seen:
                continue
            seen.add(vals['item_id'])
            line_vals.append(vals)
            line = existing.get(vals['item_id'])
            if line:
                diff = {k: v for k, v in vals.items() if line[k] != v}
                if diff:
                    commands.append((1, line.id, diff))
            else:
                commands.append((0, 0, vals))

        header = {}
        if commands:
            header['line_ids'] = commands
        header.update(self._header_status_vals(line_vals))
        header['cargo_tracking_number'] = str(order_json.get('kargoBarkod') or '') or self.cargo_tracking_number or ''
        provider = next((v['cargo_company'] for v in line_vals if v['cargo_company']), '')
        header['cargo_provider'] = provider or self.cargo_provider or ''
        header['raw_data'] = json.dumps(order_json, ensure_ascii=False, sort_keys=True)
        header = {k: v for k, v in header.items() if k == 'line_ids' or self[k] != v}
        if not header:
            return False
        self.write(header)
        return bool(commands) or any(k != 'raw_data' for k in header)

    @api.model
    def _header_status_vals(self, line_vals):
        """Sipariş durumu satır durumlarından: tümü iptalse iptal, değilse en geride kalan aktif satır."""
        if not line_vals:
            return {}
        statuses = [v['status'] for v in line_vals]
        live = [v for v in line_vals if v['status'] not in PTTAVM_CANCEL_STATUSES]
        if not live:
            status = 'odeme_gecersiz' if set(statuses) == {'odeme_gecersiz'} else 'iptal'
            partial = False
        else:
            status = min((v['status'] for v in live), key=lambda s: PTTAVM_STATUS_RANK.get(s, 0))
            partial = len(live) < len(line_vals)
        return {
            'order_status': status,
            'partially_cancelled': partial,
            'total_price': round(sum(v['sale_price'] * v['quantity'] for v in (live or line_vals)), 2),
        }

    def _raw_json(self):
        self.ensure_one()
        try:
            data = json.loads(self.raw_data or '{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ─── pttavm.order → sale.order ───────────────────────────

    def _active_lines(self):
        return self.line_ids.filtered(lambda l: l.status not in PTTAVM_CANCEL_STATUSES)

    def _reconcile_sale_order(self, store):
        """Odoo siparişini PttAVM satırlarıyla eşitler: yoksa açar, tamamen iptalse iptal eder,
        satır düştüyse (kısmi iptal) kalanlarla yeniden kurar."""
        self.ensure_one()
        lines = self._active_lines()
        cancelled = self.order_status in PTTAVM_CANCEL_STATUSES or not lines
        so = self.sale_order_id
        if not so:
            if cancelled:
                return
            so = self._create_odoo_sale_order(store)
            if so:
                self.write({'sale_order_id': so.id, 'error_message': False})
                if store.auto_confirm and so.state in ('draft', 'sent'):
                    so.action_confirm()
            return
        if so.state == 'cancel':
            return
        if cancelled:
            self._cancel_odoo_order(self, store)
            return
        product_map, missing = self._match_products(lines)
        if missing:
            return  # karşılaştırılamaz; mevcut sipariş korunur
        wanted = Counter()
        for line in lines:
            wanted[product_map[line.product_code].id] += line.quantity
        current = Counter()
        for sol in so.order_line.filtered(lambda l: l.pttavm_item_id and l.product_id):
            current[sol.product_id.id] += int(sol.product_uom_qty)
        if wanted == current:
            if self.error_message:
                self.error_message = False
        elif any(qty > wanted.get(product_id, 0) for product_id, qty in current.items()):
            reason = 'Kısmi iptal' if self.partially_cancelled else 'PttAVM sipariş satırları değişti'
            self._rebuild_sale_order(store, reason)
        else:
            msg = (f"Odoo siparişi {so.name} PttAVM satırlarıyla uyuşmuyor (Odoo'da eksik ürün var); "
                   f"elle kontrol edin.")
            if self.error_message != msg:
                self.error_message = msg

    def _match_products(self, lines):
        Product = self.env['product.product'].sudo()
        codes = [c for c in lines.mapped('product_code') if c]
        product_map = Product.batch_find_by_marketplace_barcodes(codes) if codes else {}
        missing = []
        for line in lines:
            code = line.product_code
            product = product_map.get(code) if code else None
            if not product and code:
                product = Product.find_by_marketplace_barcode(code)
                if product:
                    product_map[code] = product
            if not product:
                missing.append(code or line.product_name or line.item_id)
        return product_map, missing

    def _rebuild_sale_order(self, store, reason):
        """Mevcut Odoo siparişini iptal eder (Nebim'den de silinir), kalan satırlarla yenisini açar."""
        old = self.sale_order_id
        if old.state == 'cancel':
            return
        if not store.auto_cancel:
            msg = (f"{reason}: PttAVM siparişi değişti ancak 'İptalleri Otomatik İptal Et' kapalı; "
                   f"Odoo siparişi {old.name} elle güncellenmeli.")
            if self.error_message != msg:
                self.error_message = msg
                old.message_post(body=msg)
            return
        if old.picking_ids.filtered(lambda p: p.state == 'done'):
            msg = f"{reason}: {old.name} sevk edildiği için otomatik güncellenmedi; elle kontrol edin."
            if self.error_message != msg:
                self.error_message = msg
                old.message_post(body=msg)
            return
        new = self._create_odoo_sale_order(store, partners=(old.partner_id, old.partner_invoice_id,
                                                              old.partner_shipping_id))
        if not new:
            return
        with self.env.cr.savepoint():
            old._action_cancel()
        self.write({'sale_order_id': new.id, 'error_message': False})
        if store.auto_confirm and new.state in ('draft', 'sent'):
            new.action_confirm()
        new.message_post(body=f"{reason}: önceki sipariş {old.name} iptal edildi, kalan ürünlerle yeniden oluşturuldu.")
        old.message_post(body=f"{reason}: yerine {new.name} oluşturuldu.")
        _logger.info("PttAVM sipariş %s: %s → %s yerine %s", self.order_number, reason, old.name, new.name)

    @api.model
    def _sale_tax_field(self):
        fields_ = self.env['sale.order.line']._fields
        return 'tax_ids' if 'tax_ids' in fields_ else ('tax_id' if 'tax_id' in fields_ else False)

    def _create_odoo_sale_order(self, store, partners=None):
        """Aktif PttAVM satırlarından Odoo siparişi oluşturur. Eşleşmeyen ürün varsa sipariş açılmaz."""
        self.ensure_one()
        lines = self._active_lines()
        product_map, missing = self._match_products(lines)
        if missing:
            msg = 'Ürün bulunamadı: ' + ', '.join(sorted(set(missing)))
            if self.error_message != msg:
                self.error_message = msg
            _logger.warning("PttAVM %s: %s", self.order_number, msg)
            return False

        if partners:
            partner, invoice_partner, shipping_partner = partners
        else:
            partner, invoice_partner = self._find_or_create_partner(store)
            shipping_partner = partner

        # Depo ayarını config'den al — Ayarlar > PttAVM > Depo Ayarları
        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param('pttavm_integration.warehouse_id')
        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id,
            'pttavm_store_id': store.id,
            'pttavm_order_id': self.id,
            'client_order_ref': self.order_number,
            'date_order': self.order_date or fields.Datetime.now(),
            'order_line': [],
        }
        if warehouse_id_str:
            sale_vals['warehouse_id'] = int(warehouse_id_str)

        tax_field = self._sale_tax_field()
        tax_cache = {}
        for line in lines:
            ol_vals = {
                'product_id': product_map[line.product_code].id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price,  # KDV DAHİL fiyat
                'pttavm_item_id': line.item_id,
            }
            vat_rate = line.vat_rate or 0
            if vat_rate > 0:
                if vat_rate not in tax_cache:
                    tax_cache[vat_rate] = self.env['account.tax'].sudo().search([
                        ('type_tax_use', '=', 'sale'),
                        ('amount', '=', vat_rate),
                        ('price_include', '=', True),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)
                include_tax = tax_cache[vat_rate]
                if include_tax and tax_field:
                    ol_vals[tax_field] = [(6, 0, [include_tax.id])]
                else:
                    # KDV dahil vergi bulunamadı — KDV'yi düşerek KDV hariç fiyat ata
                    ol_vals['price_unit'] = line.sale_price / (1 + vat_rate / 100)
                    _logger.warning("PttAVM: %%%d KDV dahil vergi bulunamadi, manuel donusum", int(vat_rate))
            sale_vals['order_line'].append((0, 0, ol_vals))

        return self.env['sale.order'].create(sale_vals)

    def _find_or_create_partner(self, store):
        """(ana partner, fatura partneri) döndürür.

        Ana partner teslimat adresini taşır; kurumsal siparişte firma unvanı + VKN ile açılır.
        farkliAdres=1 ise fatura adresi ayrı (type=invoice) alt partnerdir (PTTEM modeli).
        Telefon PttAVM'de maskeli geldiği için eşleştirmede kullanılmaz."""
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        country_tr = self.env.ref('base.tr').id
        raw = self._raw_json()
        is_commercial, vat = self._commercial_info(raw)
        company_name = raw.get('firmaUnvani') or raw.get('tedarikciFirmaAdi') or ''
        phone = raw.get('telefonNo') or ''
        email = '' if store.skip_customer_email else (self.customer_email or '')
        street = raw.get('siparisAdresi') or ''
        city = self.shipping_city or raw.get('siparisIli') or ''

        customer_ref = ''
        if store.customer_prefix and self.customer_id:
            customer_ref = f"{store.customer_prefix}{self.customer_id}"

        partner = Partner
        new_ref = customer_ref
        # Fatura alt partnerleri de aynı ref'i taşır — ana partner yalnızca üst kayıtlarda aranır
        top = [('parent_id', '=', False)]
        if customer_ref:
            if is_commercial and vat:
                # Firma kaydı aynı müşterinin bireysel kaydını ezmesin: firma ayrı ref taşır
                new_ref = f"{customer_ref}-{vat}"
                partner = (Partner.search(top + [('ref', '=', new_ref)], limit=1)
                           or Partner.search(top + [('ref', '=', customer_ref), ('vat', '=', vat)], limit=1))
            else:
                partner = Partner.search(top + [('ref', '=', customer_ref), ('is_company', '=', bool(is_commercial))],
                                         limit=1)
        else:
            # Müşteri no yoksa yalnızca aynı isim + aynı il (+ kurumsalda aynı VKN) eşleşmesi kabul edilir
            name = (company_name if is_commercial else self.customer_name) or ''
            if name:
                domain = [('name', '=ilike', name), ('parent_id', '=', False), ('city', '=ilike', city)]
                if is_commercial and vat:
                    domain.append(('vat', '=', vat))
                partner = Partner.search(domain, limit=1)

        einvoice = 'is_subject_to_einvoice' in Partner._fields
        if not partner:
            vals = {
                'name': (company_name if is_commercial else self.customer_name) or self.customer_name or 'PttAVM Müşteri',
                'email': email,
                'phone': phone,
                'street': street,
                'city': city,
                'country_id': country_tr,
                'ref': new_ref,
                'company_type': 'company' if is_commercial else 'person',
            }
            if is_commercial:
                vals['vat'] = vat
                if einvoice:
                    vals['is_subject_to_einvoice'] = raw.get('isInvoice', False)
            partner = Partner.create(vals)
        else:
            # Teslimat adresi ana partnerde: değiştiyse güncelle (yeni sipariş eski adrese gitmesin)
            update_vals = {}
            if street and partner.street != street:
                update_vals['street'] = street
            if city and partner.city != city:
                update_vals['city'] = city
            if email and not partner.email:
                update_vals['email'] = email
            if is_commercial and vat and not partner.vat:
                update_vals['vat'] = vat
            if update_vals:
                partner.write(update_vals)

        invoice_partner = partner
        if str(raw.get('farkliAdres') or '0').strip() == '1':
            bill_street = raw.get('faturaAdresi') or ''
            # Fatura adı: kurumsal ise firma ünvanı (faturaMusteriAdi), bireysel ise kişi adı
            if is_commercial:
                invoice_name = company_name or raw.get('faturaMusteriAdi') or ''
            else:
                invoice_name = f"{raw.get('faturaMusteriAdi') or ''} {raw.get('faturaMusteriSoyadi') or ''}".strip()
            invoice_name = invoice_name or partner.name
            invoice_partner = Partner.search([
                ('parent_id', '=', partner.id), ('type', '=', 'invoice'),
                ('street', '=', bill_street), ('name', '=', invoice_name),
            ], limit=1)
            if not invoice_partner:
                inv_vals = {
                    'name': invoice_name,
                    'type': 'invoice',
                    'parent_id': partner.id,
                    'street': bill_street,
                    'city': raw.get('faturaIli') or '',
                    'country_id': country_tr,
                    'vat': vat,
                    'company_type': 'company' if is_commercial else 'person',
                    'ref': new_ref,
                }
                if einvoice:
                    inv_vals['is_subject_to_einvoice'] = raw.get('isInvoice', False)
                invoice_partner = Partner.create(inv_vals)
        return partner, invoice_partner

    # ─── İPTAL YÖNETİMİ ────────────────────────────────────────

    @api.private
    def _cancel_odoo_order(self, pttavm_order, store=None):
        """Odoo siparişini iptal et."""
        store = store or pttavm_order.store_id
        if store and not store.auto_cancel:
            return
        so = pttavm_order.sale_order_id
        if so and so.state not in ('cancel', 'done'):
            try:
                with self.env.cr.savepoint():
                    so._action_cancel()
                _logger.info("PttAVM — Odoo sipariş iptal edildi: %s (PttAVM: %s)", so.name, pttavm_order.order_number)
            except Exception as e:
                _logger.warning("PttAVM — Sipariş iptal hatası: %s - %s", so.name, e)

    @api.private
    def _cancel_pending_orders(self, store):
        """Veritabanındaki iptal / ödemesi geçersiz PttAVM siparişlerini tara."""
        if not store.auto_cancel:
            return 0
        cancelled_orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'in', list(PTTAVM_CANCEL_STATUSES)),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', 'not in', ['cancel', 'done']),
        ])
        for pt_order in cancelled_orders:
            self._cancel_odoo_order(pt_order, store)
        return len(cancelled_orders)
