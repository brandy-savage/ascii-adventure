"""Tests for session.py — plan parsing, doom clock, party summary, lifecycle."""
from unittest.mock import patch

import pytest
import db
import character as char_module
import session as sess_module


SAMPLE_PLAN = """\
# SESSION 2: THE EMBER EXCHANGE
**Location:** Lux-9 Underground
**Theme:** Gear up, faction choice

## SETUP
The players survived Neon Baptism. Now they need to prepare.
Jorvak Nul has pointed them toward the Black Bazaar.

---

## ACT 1: ENTER THE BAZAAR
**Goal:** Navigate the underground market.

Some content about the bazaar.

### Scene 1A: Arrival
The tunnels descend here.

## ACT 2: FACTION PRESSURE
The factions make their plays.

Content about faction encounters.

## ACT 3: THE WRONG DOOR
Someone opens the wrong door.

The horror begins early this session.

## DOOM CLOCK — SESSION 2
Roll d6 at dawn.
- 1: Cross off a sun segment.
"""

MINIMAL_PLAN = "# SESSION 1: NEON BAPTISM\n## SETUP\nIntro.\n## ACT 1: FIRST ACT\nContent.\n"


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

class TestParseSessionTitle:
    def test_extracts_title(self):
        assert sess_module.get_session_title(SAMPLE_PLAN) == "THE EMBER EXCHANGE"

    def test_extracts_session_one(self):
        assert sess_module.get_session_title(MINIMAL_PLAN) == "NEON BAPTISM"

    def test_missing_title_returns_unknown(self):
        assert sess_module.get_session_title("no header here") == "Unknown Session"


class TestParseActs:
    def test_finds_setup_section(self):
        acts = sess_module.parse_acts(SAMPLE_PLAN)
        setup = next((a for a in acts if a["title"] == "SETUP"), None)
        assert setup is not None
        assert "Black Bazaar" in setup["content"]

    def test_finds_numbered_acts(self):
        acts = sess_module.parse_acts(SAMPLE_PLAN)
        nums = sorted(a["num"] for a in acts if 1 <= a["num"] <= 98)
        assert nums == [1, 2, 3]

    def test_act_titles_correct(self):
        acts = sess_module.parse_acts(SAMPLE_PLAN)
        by_num = {a["num"]: a for a in acts}
        assert by_num[1]["title"] == "ENTER THE BAZAAR"
        assert by_num[2]["title"] == "FACTION PRESSURE"
        assert by_num[3]["title"] == "THE WRONG DOOR"

    def test_act_content_captured(self):
        acts = sess_module.parse_acts(SAMPLE_PLAN)
        act1 = next(a for a in acts if a["num"] == 1)
        assert "bazaar" in act1["content"].lower()

    def test_doom_clock_is_act_99(self):
        acts = sess_module.parse_acts(SAMPLE_PLAN)
        doom = next((a for a in acts if a["num"] == 99), None)
        assert doom is not None
        assert "d6" in doom["content"]

    def test_setup_is_act_0(self):
        acts = sess_module.parse_acts(SAMPLE_PLAN)
        setup = next((a for a in acts if a["num"] == 0), None)
        assert setup is not None

    def test_empty_plan_returns_empty(self):
        assert sess_module.parse_acts("") == []

    def test_plan_without_setup(self):
        plan = "# SESSION 1: TITLE\n## ACT 1: FIRST\nContent.\n"
        acts = sess_module.parse_acts(plan)
        assert all(a["title"] != "SETUP" for a in acts)
        assert any(a["num"] == 1 for a in acts)


# ---------------------------------------------------------------------------
# Doom clock
# ---------------------------------------------------------------------------

class TestDoomBar:
    def test_empty(self):
        assert sess_module.doom_bar({"doom_segments": 0, "doom_max": 6}) == "□□□□□□  0/6"

    def test_full(self):
        assert sess_module.doom_bar({"doom_segments": 6, "doom_max": 6}) == "■■■■■■  6/6"

    def test_partial(self):
        assert sess_module.doom_bar({"doom_segments": 3, "doom_max": 6}) == "■■■□□□  3/6"

    def test_one_segment(self):
        bar = sess_module.doom_bar({"doom_segments": 1, "doom_max": 6})
        assert bar.startswith("■")
        assert "1/6" in bar


class TestRollDoom:
    def test_returns_three_tuple(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], [], 1)
        result = sess_module.roll_doom(sess)
        assert len(result) == 3
        lost, die_result, die_sides = result
        assert isinstance(lost, bool)
        assert 1 <= die_result <= die_sides

    @pytest.mark.parametrize("session_num,expected_die", [
        (1, 6), (2, 6), (3, 4), (4, 4), (5, 2),
    ])
    def test_correct_die_per_session(self, session_num, expected_die, tmp_db):
        sess = db.session_create("dying_light", session_num, "T", ["G"], [], 1)
        _, _, die = sess_module.roll_doom(sess)
        assert die == expected_die
        db.session_end(sess["id"])

    def test_segment_lost_on_roll_of_1(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], [], 1)
        before = sess["doom_segments"]
        with patch("random.randint", return_value=1):
            lost, _, _ = sess_module.roll_doom(sess)
        assert lost is True
        updated = db.session_get_active()
        assert updated["doom_segments"] == before + 1

    def test_no_segment_lost_on_roll_above_1(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], [], 1)
        before = sess["doom_segments"]
        with patch("random.randint", return_value=3):
            lost, _, _ = sess_module.roll_doom(sess)
        assert lost is False
        updated = db.session_get_active()
        assert updated["doom_segments"] == before

    def test_segments_capped_at_6(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], [], 1)
        sess["doom_segments"] = 6
        db.session_update(sess)
        with patch("random.randint", return_value=1):
            sess_module.roll_doom(sess)
        updated = db.session_get_active()
        assert updated["doom_segments"] == 6


# ---------------------------------------------------------------------------
# Party summary
# ---------------------------------------------------------------------------

class TestBuildPartySummary:
    def test_missing_character(self, tmp_db):
        summary = sess_module.build_party_summary(["nobody"])
        assert "nobody" in summary
        assert "not found" in summary.lower()

    def test_found_character(self, tmp_db):
        char_module.create_character("Grimbold", "dying_light", "Doomed", "pw", "1")
        summary = sess_module.build_party_summary(["Grimbold"])
        assert "Grimbold" in summary
        assert "Doomed" in summary

    def test_mixed_found_and_missing(self, tmp_db):
        char_module.create_character("Found", "morkborg", "Pale One", "pw", "1")
        summary = sess_module.build_party_summary(["Found", "Missing"])
        assert "Found" in summary
        assert "Missing" in summary

    def test_empty_party(self, tmp_db):
        summary = sess_module.build_party_summary([])
        assert "no characters" in summary.lower()


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_start_creates_active_session(self, tmp_db):
        sess, acts = sess_module.start_session("dying_light", 1, ["Grim", "Nox"], 123)
        assert sess is not None
        assert sess["session_title"] == "NEON BAPTISM"
        assert sess["characters"] == ["Grim", "Nox"]
        assert db.session_get_active() is not None

    def test_start_returns_parsed_acts(self, tmp_db):
        _, acts = sess_module.start_session("dying_light", 1, ["G"], 1)
        assert isinstance(acts, list)
        assert len(acts) > 0

    def test_get_session_returns_active(self, tmp_db):
        sess_module.start_session("dying_light", 1, ["G"], 1)
        sess = sess_module.get_session()
        assert sess is not None
        assert sess["status"] == "active"

    def test_get_current_act_initial(self, tmp_db):
        sess, _ = sess_module.start_session("dying_light", 1, ["G"], 1)
        act = sess_module.get_current_act(sess)
        assert act is not None
        assert act["num"] == 0  # starts at SETUP

    def test_advance_act_moves_forward(self, tmp_db):
        sess, _ = sess_module.start_session("dying_light", 1, ["G"], 1)
        updated, new_act = sess_module.advance_act(sess)
        assert new_act is not None
        assert updated["current_act"] > 0

    def test_advance_through_all_acts(self, tmp_db):
        sess, _ = sess_module.start_session("dying_light", 1, ["G"], 1)
        prev_act = -1
        for _ in range(10):
            sess, new_act = sess_module.advance_act(sess)
            if new_act is None:
                break
            assert new_act["num"] > prev_act
            prev_act = new_act["num"]

    def test_advance_past_last_returns_none(self, tmp_db):
        sess, _ = sess_module.start_session("dying_light", 1, ["G"], 1)
        for _ in range(20):
            sess, new_act = sess_module.advance_act(sess)
            if new_act is None:
                break
        _, final = sess_module.advance_act(sess)
        assert final is None

    def test_end_session_marks_inactive(self, tmp_db):
        sess, _ = sess_module.start_session("dying_light", 1, ["G"], 1)
        sess_module.end_session(sess)
        assert db.session_get_active() is None
        assert sess_module.get_session() is None
