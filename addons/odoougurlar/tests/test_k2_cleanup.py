"""K2 (P3 temizlik): ürün senkronu karşılaştırması normalize, cron log gürültüsü."""
import logging
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

QUEUE_LOGGER = 'odoo.addons.odoougurlar.models.nebim_product_queue'
SERVICE_LOGGER = 'odoo.addons.odoougurlar.services.nebim_service'
STOCK_LOGGER = 'odoo.addons.odoougurlar.processors.stock_processor'
INVOICE_LOGGER = 'odoo.addons.odoougurlar.processors.invoice_processor'


@tagged('post_install', '-at_install')
class TestK2Normalize(TransactionCase):
    """`_changed_vals`: sahte write yok, gerçek değişiklik kaçmaz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.processor = cls.env['odoougurlar.product.processor']
        cls.categ = cls.env['product.category'].create({'name': 'K2 Kategori'})
        cls.categ2 = cls.env['product.category'].create({'name': 'K2 Kategori 2'})
        cls.tmpl = cls.env['product.template'].create({
            'name': 'K2 Ürün', 'list_price': 100.0, 'categ_id': cls.categ.id,
            'nebim_code': 'K2-ABC', 'description_sale': False, 'sale_ok': True,
        })

    def _changed(self, vals):
        return self.processor._changed_vals(self.tmpl, vals)

    def test_float_rounding_noise_is_not_a_change(self):
        self.assertEqual(self._changed({'list_price': 100.0004}), {})
        self.assertEqual(self._changed({'list_price': 99.9996}), {})
        self.assertIn('list_price', self._changed({'list_price': None}))  # 100 → 0: gerçek fark

    def test_float_real_change_detected(self):
        self.assertEqual(self._changed({'list_price': 100.01}), {'list_price': 100.01})
        self.assertEqual(self._changed({'list_price': 0}), {'list_price': 0})

    def test_char_whitespace_and_empty_equivalence(self):
        self.assertEqual(self._changed({'nebim_code': 'K2-ABC  '}), {})
        self.assertEqual(self._changed({'nebim_code': ' K2-ABC'}), {})
        self.assertEqual(self._changed({'description_sale': ''}), {})
        self.assertEqual(self._changed({'description_sale': None}), {})
        self.assertEqual(self._changed({'description_sale': False}), {})

    def test_char_real_change_detected(self):
        self.assertEqual(self._changed({'nebim_code': 'K2-XYZ'}), {'nebim_code': 'K2-XYZ'})
        self.assertEqual(self._changed({'description_sale': 'Yeni'}), {'description_sale': 'Yeni'})
        self.tmpl.description_sale = 'Var'
        self.assertEqual(self._changed({'description_sale': ''}), {'description_sale': ''})
        self.assertEqual(self._changed({'description_sale': None}), {'description_sale': None})

    def test_char_number_incoming_is_compared_as_text(self):
        self.tmpl.nebim_code = '123'
        self.assertEqual(self._changed({'nebim_code': 123}), {})
        self.assertEqual(self._changed({'nebim_code': 124}), {'nebim_code': 124})

    def test_many2one_id_or_record_or_empty(self):
        self.assertEqual(self._changed({'categ_id': self.categ.id}), {})
        self.assertEqual(self._changed({'categ_id': self.categ}), {})
        self.assertEqual(self._changed({'categ_id': self.categ2.id}), {'categ_id': self.categ2.id})
        self.assertEqual(self._changed({'categ_id': self.categ2}), {'categ_id': self.categ2})
        self.assertEqual(self._changed({'categ_id': False}), {'categ_id': False})  # kategori silinir: gerçek fark

    def test_many2one_empty_none_false_equivalent(self):
        variant = self.tmpl.product_variant_id
        self.assertFalse(variant.nebim_variant_code)
        self.assertEqual(self.processor._value_differs(variant._fields['product_tmpl_id'], variant, False, None), False)
        self.assertEqual(self.processor._value_differs(variant._fields['product_tmpl_id'], variant,
                                                       variant.product_tmpl_id, variant.product_tmpl_id.id), False)

    def test_boolean_integer(self):
        self.assertEqual(self._changed({'sale_ok': 1}), {})
        self.assertEqual(self._changed({'sale_ok': False}), {'sale_ok': False})
        field = self.tmpl._fields['sequence']
        self.assertFalse(self.processor._value_differs(field, self.tmpl, self.tmpl.sequence, str(self.tmpl.sequence)))
        self.assertTrue(self.processor._value_differs(field, self.tmpl, self.tmpl.sequence, self.tmpl.sequence + 1))


@tagged('post_install', '-at_install')
class TestK2CronLogs(TransactionCase):
    """İş yoksa dakikalık cron satırları DEBUG; iş varsa INFO özet kalır."""

    def test_queue_empty_batch_logs_no_info(self):
        Queue = self.env['odoougurlar.product.queue']
        self.env['odoougurlar.product.queue'].sudo().search([('state', '=', 'pending')]).unlink()
        with self.assertNoLogs(QUEUE_LOGGER, logging.INFO):
            Queue.process_queue_batch()

    def test_auto_sync_cron_empty_run_logs_no_info_but_work_does(self):
        Queue = self.env['odoougurlar.product.queue']
        Queue.sudo().search([('state', 'in', ['pending', 'processing'])]).unlink()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('odoougurlar.nebim_auto_sync', 'True')
        ICP.set_param('odoougurlar.nebim_sync_mode', 'daily')
        empty = {'total_items': 0, 'total_groups': 0, 'batch_id': None}
        with patch.object(type(Queue), 'enqueue_products', return_value=empty), \
                self.assertNoLogs(QUEUE_LOGGER, logging.INFO):
            Queue.auto_sync_cron()
        busy = {'total_items': 9, 'total_groups': 3, 'batch_id': 'b'}
        with patch.object(type(Queue), 'enqueue_products', return_value=busy), \
                self.assertLogs(QUEUE_LOGGER, logging.INFO) as logs:
            Queue.auto_sync_cron()
        self.assertTrue(any('3 ürün kuyruğa eklendi' in r.getMessage() for r in logs.records))

    def test_stock_summary_level_follows_work(self):
        proc = self.env['odoougurlar.stock.processor']
        idle = {'processed': 5, 'updated': 0, 'skipped_warehouse': 1, 'skipped_same': 4,
                'not_found': 0, 'failed': 0}
        with self.assertNoLogs(STOCK_LOGGER, logging.INFO):
            proc._finalize_stats(dict(idle))
        with self.assertLogs(STOCK_LOGGER, logging.INFO):
            proc._finalize_stats(dict(idle, updated=1))

    def test_invoice_cron_summary_level_follows_work(self):
        service = self.env['odoougurlar.nebim.service']
        proc_cls = type(self.env['odoougurlar.invoice.processor'])
        idle = {'processed': 0, 'updated': 0, 'failed': 0}
        with patch.object(proc_cls, 'process_invoices', return_value=idle), \
                self.assertNoLogs(SERVICE_LOGGER, logging.INFO):
            service.sync_invoices()
        with patch.object(proc_cls, 'process_invoices', return_value={'processed': 2, 'updated': 2, 'failed': 0}), \
                self.assertLogs(SERVICE_LOGGER, logging.INFO):
            service.sync_invoices()

    def test_invoice_processor_nothing_to_send_is_debug(self):
        proc = self.env['odoougurlar.invoice.processor']
        with patch.object(type(self.env['account.move']), 'search', return_value=self.env['account.move']), \
                self.assertNoLogs(INVOICE_LOGGER, logging.INFO):
            proc.process_invoices()
