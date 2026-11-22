from datetime import date

import pytest

from screener.core.amfi_client import fetch_nav_bars


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def get(self, url, timeout=30):
        self.calls += 1
        return FakeResp(self.payload)


def test_bars_ascending_and_zero_navs_skipped(tmp_path):
    payload = {"data": [{"date": "20-11-2026", "nav": "11.0"},
                        {"date": "19-11-2026", "nav": "0"},
                        {"date": "18-11-2026", "nav": "10.0"}]}
    sess = FakeSession(payload)
    bars = fetch_nav_bars(12345, tmp_path, session=sess)
    assert [(b.date, b.close, b.open) for b in bars] == [(date(2026, 11, 18), 10.0, None),
                                                         (date(2026, 11, 20), 11.0, None)]
    fetch_nav_bars(12345, tmp_path, session=sess)      # second call served from the cache
    assert sess.calls == 1


def test_unit_split_is_rescaled_not_a_crash(tmp_path):
    payload = {"data": [{"date": "04-11-2026", "nav": "10.3"},     # after a 1:10 split
                        {"date": "03-11-2026", "nav": "10.2"},
                        {"date": "02-11-2026", "nav": "101.0"},
                        {"date": "01-11-2026", "nav": "100.0"}]}
    bars = fetch_nav_bars(7, tmp_path, session=FakeSession(payload))
    assert bars[-1].close / bars[0].close == pytest.approx(1.01 * 10.3 / 10.2)


def test_core_amfi_client_does_not_need_pandas():
    import subprocess
    import sys
    code = "import sys, screener.core.amfi_client; assert 'pandas' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
