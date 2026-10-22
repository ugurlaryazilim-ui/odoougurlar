"""Masaüstü ajanının yoklama döngüsü testleri (Odoo dışı, ağ yok, gerçek bekleme yok).

Çalıştırma: python -m unittest discover -s addons/ugurlar_images/sync_agent/tests
(pytest için: --rootdir ve --confcutdir bu klasöre verilmeli; yoksa üst addon'un __init__'i odoo import eder)
"""
import os
import sys
import unittest

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT_DIR)
_cwd = os.getcwd()
# NEDEN: sync_agent içe aktarılırken çalışma dizinini ve log dosyasını kendi klasörüne alır
# (Görev Zamanlayıcı düzeltmesi); testin çalışma dizinini bozmamak için geri alınır.
from sync_agent import DEFAULT_CONFIG, SCAN_INTERVAL_ENV, poll_loop, resolve_scan_interval  # noqa: E402
os.chdir(_cwd)


class StopAfter:
    """should_stop: N kez True olmadan önce çağrıldıktan sonra durdurur (sonsuz döngüye karşı emniyet)."""

    def __init__(self, turns):
        self.turns = turns

    def __call__(self):
        self.turns -= 1
        return self.turns < 0


class TestResolveScanInterval(unittest.TestCase):

    def test_default_is_30(self):
        self.assertEqual(DEFAULT_CONFIG['scan_interval_seconds'], 30)
        self.assertEqual(resolve_scan_interval({}, environ={}), 30)

    def test_config_value_is_used(self):
        self.assertEqual(resolve_scan_interval({'scan_interval_seconds': 45}, environ={}), 45)

    def test_env_overrides_config(self):
        env = {SCAN_INTERVAL_ENV: '120'}
        self.assertEqual(resolve_scan_interval({'scan_interval_seconds': 45}, environ=env), 120)

    def test_legacy_config_3_becomes_default_but_env_3_is_respected(self):
        # Eski sürümlerin config.json'a yazdığı 3, güncellemeden sonra 3 sn'lik yoklamayı sürdürmesin
        self.assertEqual(resolve_scan_interval({'scan_interval_seconds': 3}, environ={}), 30)
        self.assertEqual(resolve_scan_interval({}, environ={SCAN_INTERVAL_ENV: '3'}), 3)

    def test_invalid_values_fall_back(self):
        self.assertEqual(resolve_scan_interval({'scan_interval_seconds': 'abc'}, environ={}), 30)
        self.assertEqual(resolve_scan_interval({}, environ={SCAN_INTERVAL_ENV: 'x'}), 30)
        self.assertEqual(resolve_scan_interval({'scan_interval_seconds': 0}, environ={}), 1)


class TestPollLoop(unittest.TestCase):

    def run_loop(self, results, interval=30, turns=None):
        """results: her turun dönüşü (Exception örneği ise fırlatılır). Bekleme çağrılarını döndürür."""
        waits, calls = [], []
        queue = list(results)

        def run_once():
            calls.append(1)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        poll_loop(run_once, interval, waits.append, should_stop=StopAfter(len(results) if turns is None else turns))
        return waits, len(calls)

    def test_empty_round_waits_interval(self):
        waits, calls = self.run_loop([0, 0])
        self.assertEqual(waits, [30, 30])
        self.assertEqual(calls, 2)

    def test_busy_rounds_repoll_without_waiting_until_queue_empty(self):
        # 5 ve 2 yükleme bulan turlardan sonra bekleme yok; boş turda 30 sn bekler
        waits, calls = self.run_loop([5, 2, 0])
        self.assertEqual(waits, [30])
        self.assertEqual(calls, 3)

    def test_error_waits_then_retries_via_hook(self):
        waits, retried, queue = [], [], [RuntimeError('odoo kapalı'), 0]

        def run_once():
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        poll_loop(run_once, 30, waits.append, should_stop=StopAfter(2),
                  on_retry=retried.append, error_wait=7)
        self.assertEqual(waits, [7, 30])
        self.assertEqual([str(e) for e in retried], ['odoo kapalı'])

    def test_keyboard_interrupt_is_not_swallowed(self):
        def run_once():
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            poll_loop(run_once, 30, lambda s: None, should_stop=StopAfter(3))

    def test_should_stop_ends_loop_before_first_round(self):
        waits, calls = self.run_loop([1], turns=0)
        self.assertEqual((waits, calls), ([], 0))


if __name__ == '__main__':
    unittest.main()
