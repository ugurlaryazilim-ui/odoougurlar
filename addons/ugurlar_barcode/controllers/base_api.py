"""Ortak yardımcı fonksiyonlar — tüm controller'lar bu mixin'i kullanır."""
import json
import logging
import math
from datetime import datetime
import time
import hashlib

from odoo import _, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request, Response
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY

_logger = logging.getLogger(__name__)


class _ValidationIncomplete(Exception):
    """Doğrulama hatasız döndü ama picking done olmadı: savepoint geri alınsın."""

# Basit in-process duplicate guard (son istek hash'i + timestamp)
_last_requests = {}  # key: user_id + endpoint + args_hash → timestamp
MAX_BULK_ITEMS = 500  # toplu raflama / sayım tek istekte en fazla bu kadar kalem
_DEBOUNCE_SECONDS = 0.5  # 500ms içinde aynı istek tekrarlanırsa atla
# Çok worker'lı çift okutma kilidi (bkz. _check_duplicate_request); testte bozulabilsin diye sabit
_SCAN_LOCK_SQL = 'SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))'


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

    @staticmethod
    def _route_finished(pickings):
        """Rota kapanış kuralı (tek yer): tüm siparişler sevk / iptal edilmiş ve en az biri
        sevk edilmiş. Toplamadan sonra satırı değişen siparişin OUT'u iptal olur ama rotanın
        kalıcı listesinde kalır; önceki "hepsi done" kuralı bu rotayı hiç kapatmıyordu.
        Yalnız iptallerden oluşan rotayı günlük temizlik iptal eder."""
        states = set(pickings.mapped('state'))
        return bool(pickings) and states <= {'done', 'cancel'} and 'done' in states

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
        if picking.env.context.get('ugurlar_skip_invoice_hook'):
            # Sihirbazlar request.env'den açılır: bayrak bağlamla taşınmalı
            ctx['ugurlar_skip_invoice_hook'] = True
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

    def _validate_in_savepoint(self, picking, qty_field='wave_collected_qty', backorder=None):
        """Paketleme doğrulaması tek savepoint'te: packing_done + sevk miktarı + doğrulama.

        Doğrulama hata verir ya da picking done olmazsa bu çağrının yazımları (quantity,
        picked, packing_done) geri alınır; önceden hata yutuluyor, picking yarım yazımla
        kalıyor ve ardından gelen Nebim commit'i onu kalıcılaştırıyordu.
        Nebim, etiket ve commit bu yardımcının İÇİNDE çağrılmaz (savepoint içinde commit yasak).
        backorder=None: kısmi sevkte bekleyen sevkiyat açılır, tam sevkte açılmaz.

        Returns: (done: bool, error: str|None)
        """
        # Faturayı (Nebim) çağıran paketleme tetikler: commit sonrası fatura kancası atlanır
        picking = picking.with_context(ugurlar_skip_invoice_hook=True)
        try:
            with picking.env.cr.savepoint():
                picking.packing_done = True
                _total, partial = self._apply_collected_quantities(picking, qty_field)
                done = self._safe_validate_picking(
                    picking, backorder=partial if backorder is None else backorder)
                if not done:
                    raise _ValidationIncomplete()
        except _ValidationIncomplete:
            _logger.warning("Picking %s doğrulanamadı (sihirbaz tamamlanmadı)", picking.name)
            return False, _('Sevkiyat doğrulanamadı, Odoo onay adımı tamamlanmadı.')
        except PG_CONCURRENCY_EXCEPTIONS_TO_RETRY:
            raise  # eşzamanlı yazım: Odoo isteği baştan yeniden denesin
        except Exception as e:
            _logger.warning("Picking %s doğrulama hatası: %s", picking.name, e)
            return False, self._error_text(e)
        return True, None

    # El terminalinde miktar kutusuna düşen barkod (8690123456789) gibi değerler stok yazmasın
    MAX_QTY = 100000

    def _parse_qty(self, value, default=1, allow_zero=False):
        """İstemciden gelen miktar: sayı değilse (nan/inf dahil), negatifse veya makul üst sınırı aşıyorsa None."""
        try:
            qty = float(value if value not in (None, '') else default)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(qty) or qty > self.MAX_QTY or qty < 0 or (qty == 0 and not allow_zero):
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
        # 1. Kalıcı alan
        pickings = batch.all_picking_ids
        if pickings:
            return pickings

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

            # NEDEN: yukarıdaki sözlük süreç belleğidir; çok worker'da (veya yeniden başlatmada)
            # başka worker'a düşen çift okutmayı görmez. Aynı anahtar için işlemi kilitle:
            # kilit bu isteğin transaction'ı bitene (commit/rollback) kadar tutulur, bu sürede
            # başka worker'dan gelen aynı istek çift sayılır. Bekleme yok (try): kilitlenme
            # riski yok. Kilit yalnız uçuştaki isteği yakalar; ilk istek commit olduktan sonra
            # başka worker'a düşen 500ms içindeki ikinci istek bu kilitle yakalanmaz.
            # EKIP-BORC: tam 500ms penceresi için ortak (DB) zaman damgası gerekir (yeni model =
            # modül yükseltmesi); uçuştaki çift okutma asıl riskti, o yüzden yalnız kilit.
            # NEDEN (A5 Ö-2): savepoint olmadan başarısız SQL transaction'ı abort eder, dıştaki
            # except yutar ve isteğin geri kalanı "current transaction is aborted" ile düşerdi.
            # Kilit alınamazsa (hata) istek geçer: çift okutma koruması en iyi çaba, işi engellemez.
            try:
                with request.env.cr.savepoint(flush=False):
                    request.env.cr.execute(_SCAN_LOCK_SQL, ('ugurlar_scan:' + key,))
                    locked = request.env.cr.fetchone()[0]
            except Exception:
                _logger.warning("Çift okutma kilidi alınamadı (%s); istek kilitsiz işleniyor.", endpoint, exc_info=True)
                locked = True
            if not locked:
                return True  # başka worker aynı isteği işliyor

            # Bellek temizliği: 1000'den fazla kayıt varsa eski olanları sil
            if len(_last_requests) > 1000:
                cutoff = now - 60
                expired = [k for k, v in _last_requests.items() if v < cutoff]
                for k in expired:
                    del _last_requests[k]
        except Exception:
            _logger.warning("Çift istek denetimi atlandı (%s).", endpoint, exc_info=True)
        return False

    def _find_product(self, barcode):
        """Barkod ile ürün bul (barcode + nebim_barcode + default_code)."""
        Product = request.env['product.product'].sudo()
        product = Product.search([('barcode', '=', barcode)], limit=1)
        if not product:
            # nebim_barcode: virgülle ayrılmış çoklu barkod alanı; tek değer de listedir.
            # NEDEN: `=` + `ilike '%x%'` her okutmada ürün tablosunu tarıyordu; liste içi TAM
            # eşleşme GIN ifade indeksiyle yapılır. ilike yolu kaldırıldı: sonucu zaten Python'da
            # tam eşleşmeye süzüyordu, yani indeksli aramanın alt kümesiydi (alt dize eşleşmesi yok).
            product = Product._search_nebim_barcodes([barcode])[:1]
        if not product:
            product = Product.search([('default_code', '=', barcode)], limit=1)
        return product

    @staticmethod
    def _clamp_days(days, default=7, lo=1, hi=90):
        """Gün sayısını [lo, hi] aralığına kısar (metin gelirse sayıya çevirir)."""
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = default
        return max(lo, min(days, hi))

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
        request.env['stock.quant'].flush_model(['quantity', 'reserved_quantity'])
        sql = ("SELECT id, quantity, reserved_quantity FROM stock_quant "
               "WHERE product_id=%s AND location_id=%s")
        params = [product_id, location_id]
        if positive_only:
            sql += " AND quantity > 0"
        sql += " FOR UPDATE"
        request.env.cr.execute(sql, params)
        return request.env.cr.fetchone()

    # ─── Raf stoğu: Odoo stok hareketi ile ──────────────
    # Önceden quant miktarı doğrudan yazılıyor / siliniyordu: stok hareketi, iz ve rezervasyon
    # koruması yoktu. Artık her raf işlemi tamamlanmış bir stok hareketi oluşturur
    # (raflama / kaldırma / sayım farkı = envanter düzeltmesi, taşıma = raflar arası iç hareket).
    # Nebim stok cron'u bu depoyu (İnternet, 002) atlar; çakışma yok.

    def _shelf_qty(self, product, location):
        """Raftaki (alt konumlar hariç) toplam ve rezerve miktar — satırlar kilitlenir."""
        # Aynı istekte ORM'de bekleyen değişiklikler (rezervasyon vb.) SQL'den önce yazılsın
        request.env['stock.quant'].flush_model(['quantity', 'reserved_quantity'])
        request.env.cr.execute(
            "SELECT id FROM stock_quant WHERE product_id=%s AND location_id=%s FOR UPDATE",
            [product.id, location.id])
        request.env.cr.execute(
            "SELECT COALESCE(SUM(quantity), 0), COALESCE(SUM(reserved_quantity), 0) "
            "FROM stock_quant WHERE product_id=%s AND location_id=%s",
            [product.id, location.id])
        qty, reserved = request.env.cr.fetchone()
        return float(qty or 0), float(reserved or 0)

    def _shelf_qty_map(self, products, location):
        """Birden çok ürünün raf miktarı: {product_id: (toplam, rezerve)}; tek kilit + tek toplam
        sorgusu (ürün başına 2 sorgu yerine). Satırlar id sırasıyla kilitlenir: iki eşzamanlı
        toplu işlem ters sırada kilitleyip kilitlenmesin."""
        ids = tuple(sorted({getattr(p, 'id', p) for p in products}))
        if not ids:
            return {}
        request.env['stock.quant'].flush_model(['quantity', 'reserved_quantity'])
        request.env.cr.execute(
            "SELECT id FROM stock_quant WHERE product_id IN %s AND location_id=%s "
            "ORDER BY id FOR UPDATE", [ids, location.id])
        request.env.cr.execute(
            "SELECT product_id, COALESCE(SUM(quantity), 0), COALESCE(SUM(reserved_quantity), 0) "
            "FROM stock_quant WHERE product_id IN %s AND location_id=%s GROUP BY product_id",
            [ids, location.id])
        return {pid: (float(qty or 0), float(res or 0))
                for pid, qty, res in request.env.cr.fetchall()}

    def _check_bulk_items(self, items):
        """Toplu uçlarda liste üst sınırı: sınırsız liste tek istekte binlerce hareket üretirdi."""
        if len(items) > MAX_BULK_ITEMS:
            return {'error': f'Tek seferde en fazla {MAX_BULK_ITEMS} kalem işlenebilir '
                             f'({len(items)} gönderildi). Listeyi bölüp tekrar gönderin.'}
        return None

    def _mobile_stock_moves(self, entries, reason, is_inventory=False):
        """Tamamlanmış stok hareketlerini TEK create/confirm/done turunda oluşturur.

        entries: [(ürün, kaynak, hedef, miktar)]. Hareket ürün başınadır (Odoo hareketi tek
        ürünlüdür); ORM çağrıları ise parti başına bir kez yapılır. Dönen kayıt kümesi
        entries sırasındadır."""
        Move = request.env['stock.move'].sudo()
        if not entries:
            return Move
        vals_list, line_vals = [], []
        for product, source, dest, quantity in entries:
            company = (dest if dest.usage == 'internal' else source).company_id or request.env.company
            vals_list.append({
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': quantity,
                'location_id': source.id,
                'location_dest_id': dest.id,
                'company_id': company.id,
                'origin': reason,
                'is_inventory': is_inventory,
            })
            line_vals.append({
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'quantity': quantity,
                'location_id': source.id,
                'location_dest_id': dest.id,
                'company_id': company.id,
            })
        moves = Move.create(vals_list)
        # NEDEN: merge=False — aynı ürün iki kez gelirse hareketler birleşmesin (tek hareketli
        # eski davranışla aynı sonuç, dönen küme entries ile hizalı kalır)
        moves._action_confirm(merge=False)
        moves.move_line_ids.unlink()
        request.env['stock.move.line'].sudo().create([
            {**vals, 'move_id': move.id} for vals, move in zip(line_vals, moves)])
        moves.picked = True
        moves._action_done()
        return moves

    def _mobile_stock_move(self, product, source, dest, quantity, reason, is_inventory=False):
        """Tamamlanmış stok hareketi oluşturur (kaynaktan hedefe, verilen miktar)."""
        return self._mobile_stock_moves(
            [(product, source, dest, quantity)], reason, is_inventory)

    def _mobile_stock_moves_isolated(self, entries, reason, is_inventory=False):
        """Toplu hareket; parti başarısızsa kalem kalem (her biri kendi savepoint'inde) dener.

        Returns: entries ile hizalı [(hareket | None, hata | None)]. Sayımda bir kalemin hatası
        diğerlerini düşürmemeli; sağlıklı yolda tüm parti tek turda gider."""
        try:
            with request.env.cr.savepoint():
                moves = self._mobile_stock_moves(entries, reason, is_inventory)
            return [(m, None) for m in moves]
        except Exception as e:
            _logger.warning('Toplu stok hareketi başarısız, kalem kalem deneniyor: %s', e)
        out = []
        for entry in entries:
            try:
                with request.env.cr.savepoint():
                    out.append((self._mobile_stock_move(*entry, reason, is_inventory), None))
            except Exception as e:
                out.append((None, e))
        return out

    def _inventory_location(self, product, location):
        company = location.company_id or request.env.company
        return product.with_company(company).property_stock_inventory

    def _safe_update_quant(self, product, location, qty_delta, reason='Mobil: Raf Düzeltme'):
        """Raf stoğunu envanter düzeltmesi hareketiyle değiştirir (+ ekle, - çıkar; 0'ın altına inmez).

        Returns:
            Güncellenmiş raf miktarı
        """
        current, _reserved = self._shelf_qty(product, location)
        if qty_delta > 0:
            self._mobile_stock_move(product, self._inventory_location(product, location), location,
                                    qty_delta, reason, is_inventory=True)
            return current + qty_delta
        out_qty = min(-qty_delta, current)
        if out_qty > 0:
            self._mobile_stock_move(product, location, self._inventory_location(product, location),
                                    out_qty, reason, is_inventory=True)
        return max(current - out_qty, 0.0)

    def _safe_move_quant(self, product, source_loc, target_loc, quantity, reason='Mobil: Raf Transferi'):
        """Ürünü bir raftan diğerine iç stok hareketiyle taşır.

        Returns:
            (success: bool, error_msg: str or None)
        """
        source_qty, reserved = self._shelf_qty(product, source_loc)
        if source_qty <= 0:
            return False, f'{product.name} kaynak rafta bulunamadı'
        available = source_qty - reserved
        if available < quantity:
            if reserved:
                return False, (f'Yetersiz stok! Kaynak: {source_qty:g} ({reserved:g} adedi '
                               f'siparişe ayrılmış), İstenen: {quantity:g}')
            return False, f'Yetersiz stok! Kaynak: {source_qty:g}, İstenen: {quantity:g}'
        self._mobile_stock_move(product, source_loc, target_loc, quantity, reason)
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

