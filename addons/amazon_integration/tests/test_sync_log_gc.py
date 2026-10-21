from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'amazon_integration')
class TestAmazonSyncLogGc(TransactionCase):

    def test_logs_older_than_30_days_are_deleted(self):
        store = self.env['amazon.store'].create(
            {'name': 'Amazon GC', 'lwa_client_id': 'x', 'lwa_client_secret': 'y',
             'default_warehouse_id': self.env['stock.warehouse'].search([], limit=1).id})
        Log = self.env['amazon.sync.log']
        old, new = (Log.create({'store_id': store.id, 'sync_type': 'order'}) for _i in range(2))
        self.env.cr.execute("UPDATE amazon_sync_log SET create_date = %s WHERE id = %s",
                            (fields.Datetime.subtract(fields.Datetime.now(), days=31), old.id))
        Log._gc_old_logs()
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
