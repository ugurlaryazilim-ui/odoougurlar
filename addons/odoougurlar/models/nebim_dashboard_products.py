import logging
import json
from collections import defaultdict

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class NebimDashboardProducts(models.TransientModel):
    """Nebim Dashboard — Ürün çekme ve test aksiyonları."""
    _inherit = 'odoougurlar.nebim.dashboard'

    # -----------------------------------------------------------------
    #  Ürün Senkronizasyonu — Kuyruk Tabanlı
    # -----------------------------------------------------------------
    def action_sync_products(self):
        """
        Manuel ürün senkronizasyonu.
        Nebim'den veriyi çekip kuyruğa ekler.
        Cron görevi batch batch işler.
        """
        try:
            ICP = self.env['ir.config_parameter'].sudo()
            mode = ICP.get_param('odoougurlar.nebim_sync_mode', 'daily')

            queue = self.env['odoougurlar.product.queue']
            result = queue.enqueue_products(mode=mode)

            if result['total_groups'] == 0:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Ürün Senkronizasyonu',
                        'message': 'Nebim\'den veri gelmedi.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Ürün Senkronizasyonu Başlatıldı',
                    'message': (
                        f'{result["total_groups"]} ürün kuyruğa eklendi '
                        f'({result["total_items"]} satır). '
                        f'Batch işleme arka planda devam edecek. '
                        f'İlerlemeyi Senkronizasyon → Loglar sayfasından takip edin.'
                    ),
                    'type': 'success',
                    'sticky': True,
                }
            }

        except Exception as e:
            _logger.error("Ürün kuyruğa ekleme hatası: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Ürün Senkronizasyonu Hatası',
                    'message': f'Hata: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # -----------------------------------------------------------------
    #  Ürün Kodu İle Çek
    # -----------------------------------------------------------------
    def action_fetch_by_code(self):
        """
        Girilen ürün koduna göre Nebim'den çekip Odoo'ya kaydeder.
        Tek ürün için inline işler (kuyruğa gerek yok).
        """

        product_code = (self.nebim_fetch_code or '').strip()
        if not product_code:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Ürün Kodu Gerekli',
                    'message': 'Lütfen çekmek istediğiniz ürün kodunu girin.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        try:
            connector = self.env['odoougurlar.nebim.connector']
            sp_name = connector._get_sp_name('item_details')

            _logger.info("Ürün kodu ile çekme: %s", product_code)
            # NOT: Nebim SP'si ItemCode filtresi desteklemez → tüm ürünler çekilip
            # Python tarafında filtrelenir. Day=36500 (~100 yıl) tüm kayıtları getirir.
            all_items = connector.run_proc(sp_name, [{'Name': 'Day', 'Value': '36500'}])

            if not all_items:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Ürün Kodu İle Çek',
                        'message': 'Nebim\'den veri gelmedi.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            items_list = all_items if isinstance(all_items, list) else [all_items]

            search_codes = [c.strip() for c in product_code.split(',') if c.strip()]
            matched_items = [
                item for item in items_list
                if (item.get('ItemCode') or '').strip() in search_codes
            ]

            if not matched_items:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Ürün Bulunamadı',
                        'message': f'\'{product_code}\' kodlu ürün Nebim\'de bulunamadı.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            grouped = defaultdict(list)
            for item in matched_items:
                code = (item.get('ItemCode') or '').strip()
                grouped[code].append(item)

            processor = self.env['odoougurlar.product.processor']
            errors = []
            created = 0
            updated = 0

            for item_code, variants in grouped.items():
                try:
                    with self.env.cr.savepoint():
                        result = processor._process_product_group(item_code, variants)
                        if result == 'created':
                            created += 1
                        else:
                            updated += 1
                except Exception as e:
                    errors.append(f"{item_code}: {str(e)}")
                    _logger.error("Ürün kodu çekme hatası [%s]: %s", item_code, str(e))

            summary_lines = []
            summary_lines.append(f"Aranan kod(lar): {product_code}")
            summary_lines.append(f"Bulunan: {len(grouped)} ürün ({len(matched_items)} varyant)")
            summary_lines.append(f"")
            summary_lines.append(f"✅ Oluşturulan: {created}")
            summary_lines.append(f"✏️ Güncellenen: {updated}")
            summary_lines.append(f"❌ Hatalı: {len(errors)}")

            if errors:
                summary_lines.append(f"\n--- HATALAR ---")
                for err in errors:
                    summary_lines.append(f"❌ {err}")

            for code in grouped:
                variants = grouped[code]
                first = variants[0]
                desc = first.get('ItemDescription', '?')
                summary_lines.append(f"\n📦 {code} - {desc} ({len(variants)} varyant)")

            return {
                'type': 'ir.actions.act_window',
                'name': f'Ürün Kodu Sonuçları (✅{created} ✏️{updated} ❌{len(errors)})',
                'res_model': 'odoougurlar.test.result.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': f'Ürün Kodu: {product_code}',
                    'default_result_text': '\n'.join(summary_lines),
                    'default_result_json': json.dumps(matched_items[:50], indent=2, ensure_ascii=False),
                },
            }

        except Exception as e:
            _logger.error("Ürün kodu çekme genel hatası: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Hata',
                    'message': f'Hata: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # -----------------------------------------------------------------
    #  Test Ürün Çekme (Limitli)
    # -----------------------------------------------------------------
    def action_test_product(self):
        """
        Nebim'den test amaçlı sınırlı sayıda ürün çeker ve Odoo'ya kaydeder.
        """

        try:
            ICP = self.env['ir.config_parameter'].sudo()
            test_count = int(ICP.get_param('odoougurlar.nebim_test_product_count', '1'))

            connector = self.env['odoougurlar.nebim.connector']
            sp_name = connector._get_sp_name('item_details')

            all_items = connector.run_proc(sp_name, [{'Name': 'Day', 'Value': '1'}])

            if not all_items:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Test Ürün',
                        'message': 'Nebim\'den veri gelmedi.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            items_list = all_items if isinstance(all_items, list) else [all_items]
            total_nebim = len(items_list)

            grouped = defaultdict(list)
            for item in items_list:
                code = (item.get('ItemCode') or '').strip()
                if code:
                    grouped[code].append(item)

            test_codes = list(grouped.keys())[:test_count]
            test_items = []
            for code in test_codes:
                test_items.extend(grouped[code])

            _logger.info(
                "Test ürün: Nebim'den %d satır, %d benzersiz ürün, test: %d ürün (%d satır)",
                total_nebim, len(grouped), len(test_codes), len(test_items)
            )

            processor = self.env['odoougurlar.product.processor']
            errors = []
            created = 0
            updated = 0

            for item_code in test_codes:
                variants = grouped[item_code]
                try:
                    with self.env.cr.savepoint():
                        result = processor._process_product_group(item_code, variants)
                        if result == 'created':
                            created += 1
                        else:
                            updated += 1
                    _logger.info("✅ %s işlendi: %s", item_code, result)
                except Exception as e:
                    error_msg = f"{item_code}: {str(e)}"
                    errors.append(error_msg)
                    _logger.exception("❌ Ürün hatası [%s]: %s", item_code, str(e))

            summary_lines = []
            summary_lines.append(f"Nebim'den toplam {total_nebim} satır çekildi ({len(grouped)} benzersiz ürün).")
            summary_lines.append(f"Test edilen: {len(test_codes)} ürün ({len(test_items)} satır/varyant)")
            summary_lines.append(f"")
            summary_lines.append(f"✅ Oluşturulan: {created}")
            summary_lines.append(f"✏️ Güncellenen: {updated}")
            summary_lines.append(f"❌ Hatalı: {len(errors)}")

            if errors:
                summary_lines.append(f"\n--- HATALAR ---")
                for err in errors:
                    summary_lines.append(f"❌ {err}")

            summary_lines.append(f"\n--- TEST ÜRÜNLERİ ---")
            for code in test_codes:
                variants = grouped[code]
                first = variants[0]
                desc = first.get('ItemDescription', first.get('Description', '?'))
                colors = set()
                sizes = set()
                for v in variants:
                    c = v.get('ColorDescription', v.get('ColorCode', ''))
                    s = v.get('ItemDim1Code', '')
                    if c:
                        colors.add(c)
                    if s:
                        sizes.add(s)
                summary_lines.append(
                    f"  {code} - {desc} | "
                    f"Renkler: {', '.join(sorted(colors)) or '-'} | "
                    f"Bedenler: {', '.join(sorted(sizes)) or '-'} | "
                    f"{len(variants)} varyant"
                )

            message = '\n'.join(summary_lines)

            return {
                'type': 'ir.actions.act_window',
                'name': f'Test Ürün Sonuçları (✅{created} ✏️{updated} ❌{len(errors)})',
                'res_model': 'odoougurlar.test.result.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': f'Test Ürün ({len(test_codes)} ürün işlendi)',
                    'default_result_text': message,
                    'default_result_json': json.dumps(test_items[:50], indent=2, ensure_ascii=False),
                },
            }

        except Exception as e:
            _logger.exception("Test ürün genel hatası: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Test Ürün Hatası',
                    'message': f'Hata: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }
