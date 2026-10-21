"""J6 / TODO-31: durum cron'u aday sınırı ve İYS cron'unda ara commit."""
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import SmsTestCase
from .test_delivery_status import StatusMixin

MODEL = 'odoo.addons.sms_system.models.sms_message'


@tagged('post_install', '-at_install')
class TestStatusCandidateLimit(StatusMixin, SmsTestCase):

    def test_status_cron_loads_at_most_limit_newest_first(self):
        msgs = [self.make_tracked('053212300%02d' % i, message_id=str(900100 + i)) for i in range(3)]
        seen = []
        original = type(self.Message)._apply_status_rows

        def spy(recs, rows):
            seen.append(recs.ids)
            return original(recs, rows)

        with patch(MODEL + '.STATUS_MAX_CANDIDATES', 2), \
                patch.object(type(self.Message), '_apply_status_rows', spy):
            self.cron_status()
        self.assertTrue(seen, 'durum sorgusu yapılmadı')
        queried = {i for ids in seen for i in ids}
        # NEDEN: sınır aşılınca en yeni kayıtlar işlenir, en eskisi sonraki çalışmaya kalır
        self.assertEqual(queried, {msgs[1].id, msgs[2].id})


@tagged('post_install', '-at_install')
class TestIysCronCommits(SmsTestCase):

    def test_refresh_contacts_commits_every_n_answers(self):
        self.configure_sms(iys=True)
        lst = self.env['sms.system.list'].create({'name': 'L'})
        contacts = self.env['sms.system.contact'].create(
            [{'mobile': '53210000%02d' % i, 'list_ids': [(6, 0, lst.ids)]} for i in range(5)])
        before = len([e for e in self.events if e[0] == 'commit'])
        stats = self.env['sms.system.iys'].refresh_contacts(contacts, commit_every=2)
        commits = len([e for e in self.events if e[0] == 'commit']) - before
        self.assertEqual(stats['done'], 5)
        self.assertEqual(commits, 2)   # 2. ve 4. yanıttan sonra

    def test_interactive_refresh_does_not_commit(self):
        self.configure_sms(iys=True)
        lst = self.env['sms.system.list'].create({'name': 'L'})
        contacts = self.env['sms.system.contact'].create(
            [{'mobile': '53210000%02d' % i, 'list_ids': [(6, 0, lst.ids)]} for i in range(3)])
        before = len([e for e in self.events if e[0] == 'commit'])
        self.env['sms.system.iys'].refresh_contacts(contacts)
        self.assertEqual(len([e for e in self.events if e[0] == 'commit']), before)
