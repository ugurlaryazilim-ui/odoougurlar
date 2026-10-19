"""KK-A24: sms_campaign.py sabit açıklamaları (kod incelemesi + statik denetim)."""
import re
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCodeHygiene(TransactionCase):

    def _line(self, startswith):
        path = Path(__file__).resolve().parents[1] / 'models' / 'sms_campaign.py'
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith(startswith):
                return line
        self.fail('%s satırı bulunamadı' % startswith)

    def test_kk_a24_create_chunk_satirinda_yalniz_kendi_aciklamasi(self):
        line = self._line('CREATE_CHUNK')
        self.assertEqual(line.count('#'), 1, 'CREATE_CHUNK satırında tek açıklama olmalı: %r' % line)
        self.assertNotIn('gönderiliyor', line)
        self.assertNotIn('belirsiz', line)
        self.assertRegex(line, r'#.*parça parça')

    def test_kk_a24_stuck_minutes_aciklamasi_kendi_satirinda(self):
        line = self._line('STUCK_MINUTES')
        self.assertEqual(line.count('#'), 1, 'STUCK_MINUTES satırında tek açıklama olmalı: %r' % line)
        self.assertRegex(line, r"#.*gönderiliyor.*belirsiz",
                         "STUCK_MINUTES açıklaması ('gönderiliyor'da ... belirsiz sayılır) kendi satırında olmalı")
        self.assertIsNotNone(re.match(r'STUCK_MINUTES\s*=\s*15\b', line))
