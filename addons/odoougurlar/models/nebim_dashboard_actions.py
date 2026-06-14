import logging
import json

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Türkçe normalize
_TR_MAP = str.maketrans({
    'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g',
    'Ü': 'U', 'ü': 'u', 'Ş': 'S', 'ş': 's',
    'Ö': 'O', 'ö': 'o', 'Ç': 'C', 'ç': 'c',
})


class NebimDashboardWarehouse(models.TransientModel):
    """Nebim Dashboard — Depo, stok, raf, fatura ve bağlantı aksiyonları."""
    _inherit = 'odoougurlar.nebim.dashboard'

    # -----------------------------------------------------------------
    #  Depo Bilgilerini Çek ve Odoo'ya Kaydet
    # -----------------------------------------------------------------
    def action_fetch_warehouses(self):
        """Nebim'den depo listesini çeker ve Odoo stock.warehouse'a kaydeder."""
        try:
            connector = self.env['odoougurlar.nebim.connector']
            sp_name = connector._get_sp_name('warehouse')
            warehouses = connector.run_proc(sp_name)

            if not warehouses:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Depolar',
                        'message': 'Nebim\'den depo verisi gelmedi.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            wh_list = warehouses if isinstance(warehouses, list) else [warehouses]
            Warehouse = self.env['stock.warehouse'].sudo()

            created = 0
            updated = 0
            summary_lines = []

            for wh in wh_list:
                if not isinstance(wh, dict):
                    continue

                nebim_code = wh.get('WarehouseCode', wh.get('Code', '')).strip()
                nebim_desc = wh.get('WarehouseDescription', wh.get('Description', wh.get('Name', ''))).strip()

                if not nebim_code:
                    continue

                odoo_code = nebim_code[:5].upper()

                existing = Warehouse.search([
                    ('nebim_warehouse_code', '=', nebim_code)
                ], limit=1)

                if existing:
                    existing.write({
                        'name': nebim_desc or existing.name,
                    })
                    updated += 1
                    summary_lines.append(f"✏️ Güncellendi: {nebim_code} - {nebim_desc}")
                else:
                    code_exists = Warehouse.search([('code', '=', odoo_code)], limit=1)
                    if code_exists:
                        odoo_code = f"N{nebim_code[:4]}"

                    Warehouse.create({
                        'name': nebim_desc or nebim_code,
                        'code': odoo_code,
                        'nebim_warehouse_code': nebim_code,
                    })
                    created += 1
                    summary_lines.append(f"✅ Oluşturuldu: {nebim_code} - {nebim_desc} (Kod: {odoo_code})")

            summary = '\n'.join(summary_lines)
            message = (
                f"Nebim'den {len(wh_list)} depo çekildi.\n"
                f"✅ {created} yeni oluşturuldu, ✏️ {updated} güncellendi.\n\n{summary}"
            )

            return {
                'type': 'ir.actions.act_window',
                'name': f'Depo Senkronizasyonu ({created} yeni, {updated} güncellendi)',
                'res_model': 'odoougurlar.test.result.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': f'Depo Senkronizasyonu ({created} yeni, {updated} güncellendi)',
                    'default_result_text': message,
                    'default_result_json': json.dumps(wh_list, indent=2, ensure_ascii=False),
                },
            }

        except Exception as e:
            _logger.error("Depo çekme hatası: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Depo Çekme Hatası',
                    'message': f'Hata: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # -----------------------------------------------------------------
    #  Stok & Fiyat
    # -----------------------------------------------------------------
    def action_sync_stock(self):
        """Manuel stok güncelleme — son 1 günün değişimleri."""
        self.env['odoougurlar.nebim.service'].sync_stock_prices(mode='incremental')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Stok Güncelleme',
                'message': 'Stok güncelleme tamamlandı! Sonuçları Loglar\'dan kontrol edin.',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_sync_stock_full(self):
        """Tüm stokları Nebim'den çek (İlk Kurulum)."""
        self.env['odoougurlar.nebim.service'].sync_stock_prices(mode='full')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tüm Stoklar Çekildi',
                'message': 'Tüm ürün stokları Nebim\'den çekilip güncellendi!',
                'type': 'success',
                'sticky': True,
            }
        }

    # -----------------------------------------------------------------
    #  Fatura Gönderimi
    # -----------------------------------------------------------------
    def action_sync_invoices(self):
        """Manuel fatura gönderimi tetikle."""
        self.env['odoougurlar.nebim.service'].sync_invoices()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Fatura Gönderimi',
                'message': 'Fatura gönderim işlemi tamamlandı!',
                'type': 'success',
                'sticky': False,
            }
        }

    # -----------------------------------------------------------------
    #  Bağlantı Testi
    # -----------------------------------------------------------------
    def action_test_connection(self):
        """Nebim bağlantı testi."""
        try:
            connector = self.env['odoougurlar.nebim.connector']
            token = connector._connect()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Bağlantı Testi',
                    'message': f'Nebim bağlantısı başarılı! Token: {str(token)[:20]}...',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Bağlantı Hatası',
                    'message': f'Nebim bağlantısı başarısız: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # -----------------------------------------------------------------
    #  Raf Import
    # -----------------------------------------------------------------
    def action_import_shelves(self):
        """HamurLabs Excel dosyalarından raf lokasyonları import."""
        log = self.env['odoougurlar.sync.log'].sudo().create({
            'name': 'Raf Import (HamurLabs)',
            'sync_type': 'stock',
            'state': 'running',
        })

        try:
            processor = self.env['odoougurlar.shelf.import.processor']
            stats = processor.import_shelves()

            if stats.get('error'):
                log.sudo().write({
                    'state': 'error',
                    'end_date': fields.Datetime.now(),
                    'error_details': stats['error'],
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Raf Import Hatası',
                        'message': stats['error'],
                        'type': 'danger',
                        'sticky': True,
                    }
                }

            note = (
                f"Raf Import Tamamlandı:\n"
                f"  Sıfırlanan stok kaydı: {stats.get('quants_cleared', 0)}\n"
                f"  Oluşturulan lokasyon: {stats.get('locations_created', 0)}\n"
                f"  Yerleştirilen ürün: {stats.get('products_placed', 0)}\n"
                f"  Bulunamayan ürün: {stats.get('products_not_found', 0)}\n"
                f"  Hata: {stats.get('errors', 0)}"
            )
            log.sudo().write({
                'state': 'done',
                'end_date': fields.Datetime.now(),
                'records_created': stats.get('locations_created', 0),
                'records_updated': stats.get('products_placed', 0),
                'records_failed': stats.get('products_not_found', 0),
                'log_details': note,
            })

            msg = (
                f"🗑️ {stats.get('quants_cleared', 0)} stok sıfırlandı, "
                f"✅ {stats.get('locations_created', 0)} lokasyon oluşturuldu, "
                f"{stats.get('products_placed', 0)} ürün yerleştirildi"
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Raf Import Tamamlandı',
                    'message': msg,
                    'type': 'success',
                    'sticky': True,
                }
            }
        except Exception as e:
            log.sudo().write({
                'state': 'error',
                'end_date': fields.Datetime.now(),
                'error_details': str(e),
            })
            _logger.error("Raf import hatası: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Raf Import Hatası',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # -----------------------------------------------------------------
    #  İlçe/Bölge Senkronizasyonu
    # -----------------------------------------------------------------
    def action_sync_districts(self):
        """Nebim'den İl/İlçe/Bölge verilerini çekip Odoo tablosuna kaydeder."""
        try:
            district_model = self.env['odoougurlar.nebim.district'].sudo()
            result = district_model.sync_from_nebim()
            
            if result.get('error'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'İlçe Senkronizasyonu Hatası',
                        'message': result['error'],
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            created = result.get('created', 0)
            updated = result.get('updated', 0)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'İlçe Senkronizasyonu Tamamlandı',
                    'message': f'✅ {created} yeni, ✏️ {updated} güncellendi (toplam: {created + updated} ilçe)',
                    'type': 'success',
                    'sticky': True,
                }
            }
        except Exception as e:
            _logger.error("İlçe senkronizasyonu hatası: %s", e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'İlçe Senkronizasyonu Hatası',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # -----------------------------------------------------------------
    #  İptal Siparişleri Nebim'den Toplu Silme
    # -----------------------------------------------------------------
    def action_nebim_cancel_cleanup(self):
        """İptal edilmiş ama Nebim'de hâlâ duran siparişleri toplu siler.

        Koşul: state='cancel' AND nebim_order_sent=True
        Timeout önleme: Her seferinde max 10 sipariş işler.
        """
        BATCH_SIZE = 10  # Timeout önleme — her seferinde max 10

        SaleOrder = self.env['sale.order'].sudo()
        all_orders = SaleOrder.search([
            ('state', '=', 'cancel'),
            ('nebim_order_sent', '=', True),
        ])
        total_pending = len(all_orders)

        if not all_orders:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Nebim İptal Temizliği',
                    'message': 'Nebim\'de silinecek iptal sipariş bulunamadı. Tümü zaten temiz! ✅',
                    'type': 'success',
                    'sticky': False,
                }
            }

        # Batch olarak işle
        orders = all_orders[:BATCH_SIZE]
        deleted = 0
        failed = 0
        details = []

        for order in orders:
            try:
                with self.env.cr.savepoint():
                    SaleOrder._nebim_delete_order(order)
                deleted += 1
                details.append(f"✅ {order.name} ({order.client_order_ref}) silindi")
            except Exception as e:
                failed += 1
                details.append(f"❌ {order.name} ({order.client_order_ref}): {str(e)[:200]}")
                _logger.error("Nebim toplu silme hatası (%s): %s", order.name, e)

        remaining = total_pending - deleted
        message = (
            f"Toplam {total_pending} iptal sipariş bulundu.\n"
            f"Bu turda {len(orders)} işlendi: ✅ {deleted} silindi, ❌ {failed} başarısız\n"
        )
        if remaining > 0:
            message += f"⏳ Kalan: {remaining} sipariş — tekrar basarak devam edin.\n"
        message += "\n" + '\n'.join(details)

        _logger.info("Nebim iptal temizliği: %d silindi, %d başarısız, %d kalan", deleted, failed, remaining)

        return {
            'type': 'ir.actions.act_window',
            'name': f'Nebim İptal Temizliği ({deleted} silindi, {remaining} kalan)',
            'res_model': 'odoougurlar.test.result.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_title': f'Nebim İptal Temizliği ({deleted}/{total_pending})',
                'default_result_text': message,
            },
        }

    @api.model
    def cron_nebim_cancel_cleanup(self):
        """Cron: İptal siparişleri Nebim'den otomatik sil.

        Ayarlardaki toggle açıksa çalışır.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = ICP.get_param('odoougurlar.nebim_cancel_cleanup_auto', 'False') == 'True'

        if not enabled:
            _logger.info("Nebim iptal temizliği cron'u devre dışı — ayarlardan aktif edin.")
            return

        SaleOrder = self.env['sale.order'].sudo()
        orders = SaleOrder.search([
            ('state', '=', 'cancel'),
            ('nebim_order_sent', '=', True),
        ])

        if not orders:
            _logger.info("Nebim iptal temizliği: Silinecek sipariş yok.")
            return

        deleted = 0
        failed = 0

        for order in orders:
            try:
                with self.env.cr.savepoint():
                    SaleOrder._nebim_delete_order(order)
                deleted += 1
            except Exception as e:
                failed += 1
                _logger.error("Cron: Nebim silme hatası (%s): %s", order.name, e)

        _logger.info(
            "Nebim iptal temizliği cron tamamlandı: %d silindi, %d başarısız (toplam %d)",
            deleted, failed, len(orders)
        )

    # -----------------------------------------------------------------
    #  Nebim Delete Debug Testi
    # -----------------------------------------------------------------
    def action_nebim_delete_debug(self):
        """İptal siparişlerden İLK BİRİNİ alıp farklı Delete yöntemlerini dener.
        
        Her yöntemin raw HTTP yanıtını, status code'unu ve headers'ını gösterir.
        Böylece Nebim'in hangi yönteme gerçek silme yanıtı verdiğini anlayabiliriz.
        """
        import json as _json
        import requests as _requests

        SaleOrder = self.env['sale.order'].sudo()
        
        # nebim_order_sent True olan iptal siparişi bul
        order = SaleOrder.search([
            ('state', '=', 'cancel'),
            ('nebim_order_sent', '=', True),
        ], limit=1)

        if not order:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Delete Debug',
                    'message': 'İptal + nebim_order_sent=True sipariş bulunamadı.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        connector = self.env['odoougurlar.nebim.connector'].sudo()
        doc_number = order.client_order_ref or order.name
        customer_code = order.nebim_customer_code or ''

        results = []
        results.append(f"📋 Sipariş: {order.name}")
        results.append(f"📋 DocumentNumber (client_order_ref): {doc_number}")
        results.append(f"📋 CurrAccCode (nebim_customer_code): {customer_code}")
        results.append(f"📋 nebim_order_request var mı: {'EVET' if order.nebim_order_request else 'HAYIR'}")
        results.append("")

        # ─── TOKEN al ───
        try:
            token = connector._connect()
            root_url = connector._get_root_url(
                self.env['ir.config_parameter'].sudo().get_param('odoougurlar.nebim_url', '')
            )
            results.append(f"✅ Token alındı: {token[:20]}...")
        except Exception as e:
            results.append(f"❌ Token hatası: {e}")
            return self._show_debug_result(results)

        # ─── YÖNTEM 1: Orijinal request payload ile Delete ───
        results.append("\n═══ YÖNTEM 1: Orijinal payload → Delete endpoint ═══")
        try:
            if order.nebim_order_request:
                payload1 = _json.loads(order.nebim_order_request)
            else:
                payload1 = {
                    'ModelType': 13,
                    'InternalDescription': doc_number,
                    'DocumentNumber': doc_number,
                    'OfficeCode': 'M',
                    'StoreCode': '002',
                    'WarehouseCode': '002',
                    'CurrAccCode': customer_code,
                    'CustomerCode': customer_code,
                }

            url1 = f"{root_url}/(S({token}))/IntegratorService/Delete"
            results.append(f"URL: {url1}")
            results.append(f"Payload keys: {list(payload1.keys())}")

            resp1 = _requests.post(url1, json=payload1, timeout=30)
            results.append(f"HTTP Status: {resp1.status_code}")
            results.append(f"Response Headers: {dict(resp1.headers)}")
            results.append(f"Response Body: {resp1.text[:500]}")
        except Exception as e:
            results.append(f"❌ Hata: {e}")

        # ─── YÖNTEM 2: Minimal payload (sadece ModelType + InternalDescription) ───
        results.append("\n═══ YÖNTEM 2: Minimal payload → Delete endpoint ═══")
        try:
            payload2 = {
                'ModelType': 5,
                'InternalDescription': doc_number,
            }
            url2 = f"{root_url}/(S({token}))/IntegratorService/Delete"
            results.append(f"Payload: {_json.dumps(payload2)}")

            resp2 = _requests.post(url2, json=payload2, timeout=30)
            results.append(f"HTTP Status: {resp2.status_code}")
            results.append(f"Response Body: {resp2.text[:500]}")
        except Exception as e:
            results.append(f"❌ Hata: {e}")

        # ─── YÖNTEM 3: ModelType 13 + tüm alanlar ───
        results.append("\n═══ YÖNTEM 3: ModelType 13 + CurrAccCode → Delete ═══")
        try:
            payload3 = {
                'ModelType': 13,
                'InternalDescription': doc_number,
                'DocumentNumber': doc_number,
                'Description': doc_number,
                'OfficeCode': 'M',
                'StoreCode': '002',
                'WarehouseCode': '002',
                'CurrAccCode': customer_code,
                'CustomerCode': customer_code,
            }
            results.append(f"Payload: {_json.dumps(payload3, ensure_ascii=False)}")

            resp3 = _requests.post(url2, json=payload3, timeout=30)
            results.append(f"HTTP Status: {resp3.status_code}")
            results.append(f"Response Body: {resp3.text[:500]}")
        except Exception as e:
            results.append(f"❌ Hata: {e}")

        # ─── YÖNTEM 4: HTTP DELETE metodu ───
        results.append("\n═══ YÖNTEM 4: HTTP DELETE metodu ═══")
        try:
            url4 = f"{root_url}/(S({token}))/IntegratorService/Delete"
            payload4 = {
                'ModelType': 5,
                'InternalDescription': doc_number,
                'DocumentNumber': doc_number,
                'CurrAccCode': customer_code,
            }
            results.append(f"HTTP DELETE → {url4}")

            resp4 = _requests.delete(url4, json=payload4, timeout=30)
            results.append(f"HTTP Status: {resp4.status_code}")
            results.append(f"Response Body: {resp4.text[:500]}")
        except Exception as e:
            results.append(f"❌ Hata: {e}")

        return self._show_debug_result(results)

    def _show_debug_result(self, results):
        """Debug sonuçlarını wizard'da göster."""
        message = '\n'.join(results)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nebim Delete Debug Sonuçları',
            'res_model': 'odoougurlar.test.result.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_title': 'Nebim Delete Debug',
                'default_result_text': message,
            },
        }
