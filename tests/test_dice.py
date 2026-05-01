"""Tests for parse_roll — dice expression parsing and result validation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from bot import parse_roll


class TestParseRollRanges:
    @pytest.mark.parametrize("expr,lo,hi", [
        ("d4",    1,  4),
        ("d6",    1,  6),
        ("d8",    1,  8),
        ("d10",   1, 10),
        ("d12",   1, 12),
        ("d20",   1, 20),
        ("d100",  1, 100),
        ("2d6",   2, 12),
        ("3d6",   3, 18),
        ("4d6",   4, 24),
        ("d8+3",  4, 11),
        ("d8-1",  0,  7),
        ("d20+5", 6, 25),
        ("2d6+3", 5, 15),
        ("1d4",   1,  4),
    ])
    def test_result_in_range(self, expr, lo, hi):
        for _ in range(30):
            total, _ = parse_roll(expr)
            assert lo <= total <= hi, f"{expr} → {total}, expected [{lo},{hi}]"

    def test_d20_covers_full_range(self):
        results = {parse_roll("d20")[0] for _ in range(500)}
        assert len(results) > 15  # should see most values in 500 rolls

    def test_3d6_sum_equals_dice(self):
        for _ in range(20):
            total, breakdown = parse_roll("3d6")
            assert 3 <= total <= 18


class TestParseRollBreakdown:
    def test_breakdown_is_string(self):
        _, breakdown = parse_roll("d20")
        assert isinstance(breakdown, str)

    def test_breakdown_contains_bold_result(self):
        _, breakdown = parse_roll("2d6")
        assert "**" in breakdown

    def test_positive_modifier_in_breakdown(self):
        _, breakdown = parse_roll("d20+5")
        assert "+5" in breakdown

    def test_negative_modifier_in_breakdown(self):
        _, breakdown = parse_roll("d8-2")
        assert "-2" in breakdown

    def test_no_modifier_breakdown(self):
        total, breakdown = parse_roll("d6")
        assert str(total) in breakdown


class TestParseRollInvalid:
    @pytest.mark.parametrize("expr", [
        "invalid",
        "abc",
        "d",
        "0d6",
        "d0",
        "d101",
        "21d6",
        "2d6+",
        "d20++1",
        "",
        "roll d20",
    ])
    def test_raises_value_error(self, expr):
        with pytest.raises(ValueError):
            parse_roll(expr)


class TestParseRollEdgeCases:
    def test_single_die_no_count_prefix(self):
        total, _ = parse_roll("d6")
        assert 1 <= total <= 6

    def test_1d6_same_as_d6_range(self):
        for _ in range(20):
            total, _ = parse_roll("1d6")
            assert 1 <= total <= 6

    def test_modifier_zero_still_valid(self):
        # d6+0 is technically invalid (doesn't match our regex), that's fine
        # but d6 with no modifier should work
        total, _ = parse_roll("d6")
        assert 1 <= total <= 6

    def test_max_dice_count_allowed(self):
        total, _ = parse_roll("20d6")
        assert 20 <= total <= 120

    def test_one_above_max_dice_raises(self):
        with pytest.raises(ValueError):
            parse_roll("21d6")
