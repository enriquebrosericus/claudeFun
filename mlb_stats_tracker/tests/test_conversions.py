"""
Tests for safe type-conversion helpers and IP notation utilities.
These functions are duplicated across scraper.py and the backfill scripts
with identical logic — testing the scraper versions covers all of them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import sf, si, ip_to_thirds, thirds_to_ip


class TestSf:
    """sf(val, default) — safe cast to float."""

    def test_normal_float_string(self):
        assert sf("3.14") == pytest.approx(3.14)

    def test_integer_string(self):
        assert sf("5") == 5.0

    def test_negative_float(self):
        assert sf("-2.5") == -2.5

    def test_actual_float(self):
        assert sf(3.5) == 3.5

    def test_actual_int(self):
        assert sf(7) == 7.0

    # Sentinel values that should return the default
    def test_none(self):             assert sf(None) == 0.0
    def test_empty_string(self):     assert sf("") == 0.0
    def test_dash_dash(self):        assert sf("--") == 0.0
    def test_dot_dash_dash_dash(self): assert sf(".---") == 0.0
    def test_dash_dot_dash_dash(self): assert sf("-.--") == 0.0
    def test_inf_upper(self):        assert sf("Inf") == 0.0
    def test_inf_lower(self):        assert sf("inf") == 0.0

    def test_non_numeric_string(self):
        assert sf("abc") == 0.0

    def test_custom_default(self):
        assert sf(None, 9.99) == 9.99

    def test_custom_default_none(self):
        assert sf(None, None) is None

    def test_sentinel_uses_custom_default(self):
        assert sf("Inf", None) is None

    def test_era_infinity_string(self):
        # ERA can come back as "Inf" for pitchers with 0 IP and earned runs
        assert sf("Inf", None) is None


import pytest  # noqa: E402 — needed for approx above


class TestSi:
    """si(val, default) — safe cast to int."""

    def test_normal_int_string(self):    assert si("5") == 5
    def test_zero_string(self):          assert si("0") == 0
    def test_negative_string(self):      assert si("-3") == -3
    def test_actual_int(self):           assert si(42) == 42
    def test_none(self):                 assert si(None) == 0
    def test_empty_string(self):         assert si("") == 0
    def test_custom_default(self):       assert si(None, -1) == -1
    def test_non_numeric(self):          assert si("abc") == 0

    def test_float_string_truncates(self):
        # int("3.7") raises ValueError → returns default
        assert si("3.7") == 0

    def test_actual_float_truncates(self):
        assert si(3.9) == 3


class TestIpToThirds:
    """ip_to_thirds — convert innings-pitched notation to integer thirds."""

    def test_zero_ip(self):          assert ip_to_thirds("0.0") == 0
    def test_one_third(self):        assert ip_to_thirds("0.1") == 1
    def test_two_thirds(self):       assert ip_to_thirds("0.2") == 2
    def test_one_full_inning(self):  assert ip_to_thirds("1.0") == 3
    def test_mixed(self):            assert ip_to_thirds("5.2") == 17
    def test_seven_innings(self):    assert ip_to_thirds("7.0") == 21
    def test_nine_innings(self):     assert ip_to_thirds("9.0") == 27
    def test_complete_game(self):    assert ip_to_thirds("9.0") == 27

    def test_invalid_string(self):   assert ip_to_thirds("bad") == 0
    def test_empty_string(self):     assert ip_to_thirds("") == 0
    def test_none_like(self):        assert ip_to_thirds("0") == 0  # no dot → exception → 0


class TestThirdsToIp:
    """thirds_to_ip — convert integer thirds back to innings-pitched float."""

    def test_zero(self):             assert thirds_to_ip(0) == 0.0
    def test_one_third(self):        assert thirds_to_ip(1) == 0.1
    def test_two_thirds(self):       assert thirds_to_ip(2) == 0.2
    def test_one_inning(self):       assert thirds_to_ip(3) == 1.0
    def test_five_two(self):         assert thirds_to_ip(17) == 5.2
    def test_seven_innings(self):    assert thirds_to_ip(21) == 7.0
    def test_nine_innings(self):     assert thirds_to_ip(27) == 9.0

    def test_roundtrip_whole_innings(self):
        for whole in range(10):
            ip_str = f"{whole}.0"
            assert thirds_to_ip(ip_to_thirds(ip_str)) == float(whole)

    def test_roundtrip_one_third(self):
        for whole in range(9):
            assert thirds_to_ip(ip_to_thirds(f"{whole}.1")) == pytest.approx(whole + 0.1)

    def test_roundtrip_two_thirds(self):
        for whole in range(9):
            assert thirds_to_ip(ip_to_thirds(f"{whole}.2")) == pytest.approx(whole + 0.2)
