"""Ortak yardımcı fonksiyonlar — tüm controller'lar bu mixin'i kullanır."""
import json
import logging
from datetime import datetime
import time
import hashlib

from odoo import _, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Basit in-process duplicate guard (son istek hash'i + timestamp)
_last_requests = {}  # key: user_id + endpoint + args_hash → timestamp
_DEBOUNCE_SECONDS = 0.5  # 500ms içinde aynı istek tekrarlanırsa atla


class BarcodeApiBase(http.Controller):
    """Ortak yardımcı fonksiyonlar."""

    # ─── Yetki ───────────────────────────────────────────
    def _check_internal_user(self):
        """auth='user' portal / e-ticaret müşterisini de kabul eder; tüm API'ler sudo ile
        stok ve müşteri verisine eriştiğinden yalnız iç kullanıcılar çağırabilir."""
        if not request.env.user._is_internal():
            raise AccessError(_('Bu işlem için yetkiniz yok.'))

    def _error_text(self, exc, prefix=''):
        """İstemciye dönen hata: UserError/ValidationError mesajı operatöre gösterilir;
        beklenmeyen hatalar (SQL, iç yol, traceback ayrıntısı) yalnız log'a yazılır."""
        if isinstance(exc, (UserError, ValidationError, AccessError)):
            text = exc.args[0] if exc.args else str(exc)
        else:
            _logger.exception("Mobil API hatası")
            text = _('Beklenmeyen bir hata oluştu, işlem kaydedilmedi. Lütfen tekrar deneyin.')
        return f'{prefix}{text}' if prefix else text

    # ─── Toplanan miktarla sevkiyat ─────────────────────
    def _missing_moves(self, pickings, qty_field='wave_collected_qty'):
        """Toplanan < talep olan ve "Eksik" işaretlenmemiş hareketler (tamamlamayı engeller)."""
        missing = []
        for picking in pickings:
            if picking.state in ('done', 'cancel'):
                continue
            for move in picking.move_ids:
                if move.state == 'cancel' or move.product_uom_qty <= 0:
                    continue
                qty = getattr(move, qty_field) or 0
                if qty < move.product_uom_qty and not move.wave_skipped:
                    missing.append({
                        'move_id': move.id,
                        'picking_name': picking.name,
                        'product_name': move.product_id.display_name,
                        'demand_qty': move.product_uom_qty,
                        'collected_qty': qty,
                    })
        return missing

    def _missing_error(self, missing, action='tamamlanamaz'):
        names = ', '.join(f"{m['product_name']} ({int(m['collected_qty'])}/{int(m['demand_qty'])})"
                          for m in missing[:5])
        more = f' ve {len(missing) - 5} ürün daha' if len(missing) > 5 else ''
        return {
            'error': f'{len(missing)} üründe eksik var, rota {action}: {names}{more}. '
                     f'Ürünü toplayın veya "Eksik" olarak işaretleyin.',
            'missing': missing,
        }

    def _apply_collected_quantities(self, picking, qty_field='wave_collected_qty'):
        """Sevk miktarı = toplanan (talebi aşmaz). Önceden ml.reserved_uom_qty (Odoo 17+'da yok)
        hata verip her move line'a tüm talep yazılıyordu: eksik ürün tam / iki katı sevk ediliyordu.

        Returns: (toplanan toplam, kısmi var mı)
        """
        total = 0.0
        partial = False
        for move in picking.move_ids:
            if move.state == 'cancel':
                continue
            if move.product_uom_qty == 0:
                move._action_cancel()  # 0 talepli move doğrulamayı engelliyor
                continue
            qty = min(getattr(move, qty_field) or 0, move.product_uom_qty)
            if qty < move.product_uom_qty:
                partial = True
            move.quantity = qty
            move.picked = True
            total += qty
        return total, partial

    def _safe_validate_picking(self, picking, backorder=False):
        """Picking'i doğrular; Odoo sihirbazlarını (SMS, backorder, anında transfer) otomatik işler.

        backorder=True: kısmi sevkte kalan miktar için bekleyen sevkiyat açılır
        (False: kalan iptal — tam toplanmış / tam okutulmuş picking'ler için).

        Returns: bool — picking done oldu mu
        """
        if picking.state in ('done', 'cancel'):
            return picking.state == 'done'

        for move in picking.move_ids:
            if move.product_uom_qty == 0 and move.state != 'cancel':
                move._action_cancel()

        ctx = {
            'skip_backorder': True,
            'skip_immediate': True,
            'button_validate_picking_ids': picking.ids,
        }
        if not backorder:
            ctx['picking_ids_not_to_backorder'] = picking.ids
        result = picking.with_context(**ctx).button_validate()

        # Sihirbaz döndüyse otomatik işle (en fazla 3 — zincirleme sihirbazlar)
        for _attempt in range(3):
            if not isinstance(result, dict) or not result.get('res_model'):
                break
            wiz_model = result['res_model']
            try:
                wiz_ctx = {**ctx, **result.get('context', {})}
                if result.get('res_id'):
                    wizard = request.env[wiz_model].sudo().with_context(**wiz_ctx).browse(result['res_id'])
                else:
                    wizard = request.env[wiz_model].sudo().with_context(**wiz_ctx).create({})
                if hasattr(wizard, 'dont_send_sms'):
                    result = wizard.dont_send_sms() or True
                elif hasattr(wizard, 'process'):
                    result = wizard.process() or True
                elif hasattr(wizard, 'action_done'):
                    result = wizard.action_done() or True
                else:
                    _logger.warning("Bilinmeyen sihirbaz: %s — atlanıyor", wiz_model)
                    break
            except Exception as e:
                _logger.warning("Sihirbaz %s hatası: %s", wiz_model, e)
                break

        picking.invalidate_recordset(['state'])
        return picking.state == 'done'

    # El terminalinde miktar kutusuna düşen barkod (8690123456789) gibi değerler stok yazmasın
    MAX_QTY = 100000

    def _parse_qty(self, value, default=1, allow_zero=False):
        """İstemciden gelen miktar: sayı değilse, negatifse veya makul üst sınırı aşıyorsa None."""
        try:
            qty = float(value if value not in (None, '') else default)
        except (TypeError, ValueError):
            return None
        if qty != qty or qty > self.MAX_QTY or qty < 0 or (qty == 0 and not allow_zero):
            return None
        return qty

    # ─── Yerel saat ─────────────────────────────────────
    def _local_dt(self, dt):
        """UTC (naive) datetime → kullanıcının saat dilimi (yoksa İstanbul), naive döner.

        Ekranlara / etikete yazılan saatler 3 saat geri görünüyordu.
        """
        if not dt:
            return dt
        import pytz
        tz = pytz.timezone(request.env.user.tz or 'Europe/Istanbul')
        return pytz.utc.localize(dt).astimezone(tz).replace(tzinfo=None)

    def _local_today(self):
        return self._local_dt(datetime.utcnow()).date()

    def _is_stock_manager(self):
        user = request.env.user
        return user.has_group('stock.group_stock_manager') or user.has_group('base.group_system')

    def _get_outgoing_picking(self, picking_id):
        """İstemciden gelen id yalnız giden sevkiyat ise döner (başka belgeye yazılmasın)."""
        try:
            picking = request.env['stock.picking'].sudo().browse(int(picking_id or 0))
        except (TypeError, ValueError):
            return request.env['stock.picking'].browse()
        if not picking.exists() or picking.picking_type_code != 'outgoing':
            return request.env['stock.picking'].browse()
        return picking

    def _get_all_pickings(self, batch):
        """Batch'e ait tüm picking'leri döndür (done dahil).

        Odoo picking done olunca batch_id'yi temizliyor.
        all_picking_ids kalıcı alanı varsa onu kullan, yoksa fallback'ler.
        """
        # 1. Kalıcı alan (tablo yoksa hata verir — yakala)
        try:
            pickings = batch.all_picking_ids
            if pickings:
                return pickings
        except Exception:
            # Tablo henüz oluşturulmamış (modül upgrade edilmemiş)
            _logger.debug("all_picking_ids tablosu mevcut değil — fallback kullanılacak")

        # 2. DB sorgusu (batch_id henüz temizlenmemiş olanlar)
        pickings = request.env['stock.picking'].sudo().search([
            ('batch_id', '=', batch.id),
        ])
        if pickings:
            try:
                batch.sudo().all_picking_ids = [(6, 0, pickings.ids)]
            except Exception:
                pass
            return pickings

        # 3. Eski batch migrasyon — sale.order.picking_batch_names
        try:
            orders = request.env['sale.order'].sudo().search([
                ('picking_batch_names', '=', batch.name),
            ])
            if orders:
                pickings = request.env['stock.picking'].sudo().search([
                    ('origin', 'in', orders.mapped('name')),
                    ('picking_type_code', '=', 'outgoing'),
                ])
                if pickings:
                    try:
                        batch.sudo().all_picking_ids = [(6, 0, pickings.ids)]
                        _logger.info(
                            "Eski batch %s için %d picking migre edildi",
                            batch.name, len(pickings))
                    except Exception:
                        pass
                    return pickings
        except Exception as e:
            _logger.warning("Eski batch picking tespiti hatası (%s): %s", batch.name, e)

        # 4. Son çare — picking_ids (done olanlar burada görünmeyebilir)
        return batch.picking_ids

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False, default=str),
            content_type='application/json',
            status=status,
        )

    def _check_duplicate_request(self, endpoint, *args):
        """Aynı kullanıcıdan 500ms içinde tekrarlanan aynı isteği algıla.

        Returns:
            True if duplicate (should skip), False if OK to proceed
        """
        try:
            uid = request.env.uid or 0
            args_str = str(args)
            key = f"{uid}:{endpoint}:{hashlib.md5(args_str.encode()).hexdigest()}"
            now = time.time()

            last_time = _last_requests.get(key, 0)
            if now - last_time < _DEBOUNCE_SECONDS:
                return True  # Duplicated

            _last_requests[key] = now

            # Bellek temizliği: 1000'den fazla kayıt varsa eski olanları sil
            if len(_last_requests) > 1000:
                cutoff = now - 60
                expired = [k for k, v in _last_requests.items() if v < cutoff]
                for k in expired:
                    del _last_requests[k]
        except Exception:
            pass
        return False

    def _find_product(self, barcode):
        """Barkod ile ürün bul (barcode + nebim_barcode + default_code)."""
        Product = request.env['product.product'].sudo()
        product = Product.search([('barcode', '=', barcode)], limit=1)
        if not product:
            # nebim_barcode: virgülle ayrılmış çoklu barkod alanı
            product = Product.search([('nebim_barcode', '=', barcode)], limit=1)
            if not product:
                products = Product.search([('nebim_barcode', 'ilike', barcode)])
                for p in products:
                    if barcode in (p.nebim_barcode or '').split(','):
                        return p
        if not product:
            product = Product.search([('default_code', '=', barcode)], limit=1)
        return product

    def _get_physical_barcode(self, product):
        """Ürünün fiziksel barkodunu döndür (okutulabilir barkod).

        Öncelik:
        1. Paket ürünse → ikame ürünün barkodunu kullan
        2. nebim_barcode varsa → onu kullan
        3. product.barcode → fallback
        """
        # Paket ürünse (substitute_product_id varsa), ikame ürünün barkodunu al
        target = product
        if hasattr(product, 'substitute_product_id') and product.substitute_product_id:
            target = product.substitute_product_id

        # nebim_barcode fiziksel barkod
        if hasattr(target, 'nebim_barcode') and target.nebim_barcode:
            return (target.nebim_barcode or '').split(',')[0].strip()
        return target.barcode or ''

    def _find_location(self, barcode):
        """Barkod veya isim ile stok lokasyonu bul."""
        Location = request.env['stock.location'].sudo()
        location = Location.search([
            ('barcode', '=', barcode), ('usage', '=', 'internal'),
        ], limit=1)
        if not location:
            location = Location.search([
                '|', ('name', '=', barcode), ('complete_name', '=', barcode),
                ('usage', '=', 'internal'),
            ], limit=1)
        if not location:
            # "A-1" yazınca "A-10" gelmesin: kısmi aramada yalnız tek eşleşme kabul edilir
            matches = Location.search([
                ('name', 'ilike', barcode), ('usage', '=', 'internal'),
            ], limit=2)
            if len(matches) == 1:
                location = matches
        return location

    def _get_marka(self, tmpl, cache=None):
        """Template'tan marka bilgisini al (cache destekli)."""
        if cache is not None and tmpl.id in cache:
            return cache[tmpl.id]
        marka = ''
        marka_line = tmpl.attribute_line_ids.filtered(
            lambda l: l.attribute_id.name == 'Marka' and l.attribute_id.create_variant == 'no_variant'
        )
        if marka_line:
            marka = ', '.join(marka_line[0].value_ids.mapped('name'))
        if cache is not None:
            cache[tmpl.id] = marka
        return marka

    # ═══ GÜVENLİ STOK İŞLEMLERİ ═══

    def _lock_quant(self, product_id, location_id, positive_only=False):
        """Row-level lock al ve quant id + miktarını döndür.

        FOR UPDATE concurrency için gerekli — ORM'de doğrudan karşılığı yok.
        Sadece lock + id çekmek için raw SQL, geri kalan ORM ile yapılır.

        Returns:
            (quant_id, quantity) veya None
        """
        sql = ("SELECT id, quantity, reserved_quantity FROM stock_quant "
               "WHERE product_id=%s AND location_id=%s")
        params = [product_id, location_id]
        if positive_only:
            sql += " AND quantity > 0"
        sql += " FOR UPDATE"
        request.env.cr.execute(sql, params)
        return request.env.cr.fetchone()

    def _safe_update_quant(self, product, location, qty_delta):
        """Stok miktarını güvenli şekilde güncelle (concurrency-safe, ORM tabanlı).

        Args:
            product: product.product recordset
            location: stock.location recordset
            qty_delta: + ekle, - çıkar

        Returns:
            Güncellenmiş toplam miktar
        """
        StockQuant = request.env['stock.quant'].sudo()

        row = self._lock_quant(product.id, location.id)

        if row:
            existing = StockQuant.browse(row[0])
            new_qty = existing.quantity + qty_delta
            if new_qty <= 0:
                existing.unlink()
                return 0
            else:
                existing.write({'quantity': new_qty})
                return new_qty
        elif qty_delta > 0:
            StockQuant.create({
                'product_id': product.id,
                'location_id': location.id,
                'quantity': qty_delta,
            })
            return qty_delta
        return 0

    def _safe_move_quant(self, product, source_loc, target_loc, quantity):
        """Ürünü bir raftan diğerine güvenli şekilde taşı (concurrency-safe, ORM tabanlı).

        Args:
            product: product.product
            source_loc: kaynak stock.location
            target_loc: hedef stock.location
            quantity: taşınacak miktar

        Returns:
            (success: bool, error_msg: str or None)
        """
        StockQuant = request.env['stock.quant'].sudo()

        # Kaynak kontrol ve lock
        source_row = self._lock_quant(product.id, source_loc.id, positive_only=True)

        if not source_row:
            return False, f'{product.name} kaynak rafta bulunamadı'

        source_qty = source_row[1]
        available = source_qty - (source_row[2] or 0)
        if available < quantity:
            if available < source_qty:
                return False, (f'Yetersiz stok! Kaynak: {source_qty} ({source_qty - available} adedi '
                               f'siparişe ayrılmış), İstenen: {quantity}')
            return False, f'Yetersiz stok! Kaynak: {source_qty}, İstenen: {quantity}'

        source_quant = StockQuant.browse(source_row[0])

        # Kaynaktan düş
        new_source = source_qty - quantity
        if new_source <= 0:
            source_quant.unlink()
        else:
            source_quant.write({'quantity': new_source})

        # Hedefe ekle (lock ile)
        target_row = self._lock_quant(product.id, target_loc.id)

        if target_row:
            target_quant = StockQuant.browse(target_row[0])
            target_quant.write({'quantity': target_quant.quantity + quantity})
        else:
            StockQuant.create({
                'product_id': product.id,
                'location_id': target_loc.id,
                'quantity': quantity,
            })

        return True, None

    def _log_chatter(self, record, body, subtype='mail.mt_note'):
        """Kayıt chatter'ına bildirim yaz (güvenli)."""
        try:
            record.sudo().message_post(
                body=body, message_type='notification',
                subtype_xmlid=subtype)
        except Exception as e:
            _logger.warning('Chatter log hatası: %s', e)

    # ═══ TTS CONFIG ═══

    @http.route('/ugurlar_barcode/api/tts_config', type='jsonrpc', auth='user')
    def tts_config(self, **kw):
        """Tüm aktif TTS mesajlarını key→message dict olarak döndür."""
        self._check_internal_user()
        try:
            messages = request.env['ugurlar.tts.message'].sudo().search([
                ('active', '=', True),
            ])
            return {
                'messages': {msg.key: msg.message for msg in messages},
            }
        except Exception as e:
            _logger.warning('TTS config hatası: %s', e)
            return {'messages': {}}

