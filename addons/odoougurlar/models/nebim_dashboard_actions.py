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
