"""Tests for db.py — schema, character CRUD, session CRUD, memory, story events."""
import pytest
import db
import character as char_module


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_all_tables_created(self, tmp_db):
        tables = {r[0] for r in db._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert {"characters", "sessions", "session_memory", "story_events"}.issubset(tables)

    def test_memory_index_created(self, tmp_db):
        indexes = {r[0] for r in db._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        assert "idx_memory_session" in indexes

    def test_wal_mode(self, tmp_db):
        row = db._get_conn().execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"


# ---------------------------------------------------------------------------
# Character CRUD
# ---------------------------------------------------------------------------

def _make_char(name="Grim"):
    return char_module.create_character(name, "dying_light", "Gutterborn Scum", "pw", "1")


class TestCharacterCRUD:
    def test_save_and_get_roundtrip(self, tmp_db):
        _make_char("RoundTrip")
        got = db.char_get("roundtrip")
        assert got is not None
        assert got["name"] == "RoundTrip"
        assert got["system"] == "dying_light"

    def test_get_returns_none_for_missing(self, tmp_db):
        assert db.char_get("nobody") is None

    def test_get_case_insensitive(self, tmp_db):
        _make_char("CaseTest")
        assert db.char_get("CASETEST") is not None
        assert db.char_get("casetest") is not None

    def test_list_returns_all(self, tmp_db):
        for name in ("Alpha", "Beta", "Gamma"):
            _make_char(name)
        names = {c["name"] for c in db.char_list()}
        assert {"Alpha", "Beta", "Gamma"}.issubset(names)

    def test_list_empty_db(self, tmp_db):
        assert db.char_list() == []

    def test_delete_removes_entry(self, tmp_db):
        _make_char("ToDelete")
        db.char_delete("todelete")
        assert db.char_get("todelete") is None

    def test_upsert_updates_existing(self, tmp_db):
        c = _make_char("Upsert")
        c["notes"] = "updated"
        db.char_save(c)
        assert db.char_get("upsert")["notes"] == "updated"

    def test_abilities_round_trip(self, tmp_db):
        _make_char("AbilChar")
        got = db.char_get("abilchar")
        assert "STR" in got["abilities"]
        assert "KNOWLEDGE" in got["abilities"]
        assert isinstance(got["abilities"]["STR"]["mod"], int)

    def test_equipment_round_trip(self, tmp_db):
        c = char_module.create_character("GearTest", "dying_light", "Waste Runner", "pw", "1")
        c["equipment"] = ["torch", "knife", "respirator"]
        db.char_save(c)
        got = db.char_get("geartest")
        assert got["equipment"] == ["torch", "knife", "respirator"]

    def test_hp_stored_correctly(self, tmp_db):
        c = _make_char("HpStore")
        c["hp"]["current"] = 3
        db.char_save(c)
        got = db.char_get("hpstore")
        assert got["hp"]["current"] == 3
        assert got["hp"]["max"] == c["hp"]["max"]


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def _acts():
    return [
        {"num": 0, "title": "SETUP",   "content": "Setup content here"},
        {"num": 1, "title": "ACT ONE", "content": "First act content"},
        {"num": 2, "title": "ACT TWO", "content": "Second act content"},
    ]


class TestSessionCRUD:
    def test_create_returns_session_with_id(self, tmp_db):
        sess = db.session_create("dying_light", 1, "Neon Baptism", ["Grim"], _acts(), 123)
        assert sess is not None
        assert sess["id"] is not None
        assert sess["session_title"] == "Neon Baptism"

    def test_get_active_returns_most_recent(self, tmp_db):
        db.session_create("dying_light", 1, "S1", ["Grim"], _acts(), 1)
        active = db.session_get_active()
        assert active["session_title"] == "S1"

    def test_create_ends_previous_active(self, tmp_db):
        s1 = db.session_create("dying_light", 1, "S1", ["Grim"], _acts(), 1)
        db.session_create("dying_light", 2, "S2", ["Nox"], _acts(), 1)
        history = db.session_history("dying_light")
        ended = next(s for s in history if s["session_title"] == "S1")
        assert ended["status"] == "ended"
        assert ended["ended_at"] is not None

    def test_only_one_active_at_a_time(self, tmp_db):
        for i in range(3):
            db.session_create("dying_light", i + 1, f"S{i}", ["G"], _acts(), 1)
        active_count = db._get_conn().execute(
            "SELECT COUNT(*) FROM sessions WHERE status='active'"
        ).fetchone()[0]
        assert active_count == 1

    def test_update_persists_act_and_doom(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], _acts(), 1)
        sess["current_act"] = 2
        sess["doom_segments"] = 3
        db.session_update(sess)
        updated = db.session_get_active()
        assert updated["current_act"] == 2
        assert updated["doom_segments"] == 3

    def test_end_session_sets_status(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], _acts(), 1)
        db.session_end(sess["id"])
        assert db.session_get_active() is None
        history = db.session_history("dying_light")
        assert history[0]["status"] == "ended"

    def test_acts_stored_and_retrieved(self, tmp_db):
        sess = db.session_create("dying_light", 1, "T", ["G"], _acts(), 1)
        assert len(sess["acts"]) == len(_acts())
        assert sess["acts"][0]["title"] == "SETUP"

    def test_character_names_round_trip(self, tmp_db):
        party = ["Grim", "Nox", "Vex"]
        sess = db.session_create("dying_light", 1, "T", party, _acts(), 1)
        assert sess["characters"] == party

    def test_history_ordered_newest_first(self, tmp_db):
        for i in range(3):
            sess = db.session_create("dying_light", i + 1, f"S{i}", ["G"], _acts(), 1)
            if i < 2:
                db.session_end(sess["id"])
        history = db.session_history("dying_light")
        for j in range(len(history) - 1):
            assert history[j]["started_at"] >= history[j + 1]["started_at"]


# ---------------------------------------------------------------------------
# Session memory
# ---------------------------------------------------------------------------

def _fresh_session(campaign="dying_light", num=1):
    return db.session_create(campaign, num, f"Session {num}", ["Grim"], [], 1)


class TestMemory:
    def test_append_and_retrieve(self, tmp_db):
        sess = _fresh_session()
        db.memory_append(sess["id"], "Grim", "action", "tried to pick the lock")
        events = db.memory_get_recent(sess["id"])
        assert len(events) == 1
        assert events[0]["content"] == "tried to pick the lock"
        assert events[0]["actor"] == "Grim"
        assert events[0]["event_type"] == "action"

    def test_returns_oldest_first(self, tmp_db):
        sess = _fresh_session()
        for i in range(5):
            db.memory_append(sess["id"], "G", "action", f"event {i}")
        events = db.memory_get_recent(sess["id"])
        assert [e["content"] for e in events] == [f"event {i}" for i in range(5)]

    def test_limit_returns_most_recent(self, tmp_db):
        sess = _fresh_session()
        for i in range(20):
            db.memory_append(sess["id"], "DM", "narration", f"narration {i}")
        events = db.memory_get_recent(sess["id"], limit=5)
        assert len(events) == 5
        assert events[-1]["content"] == "narration 19"
        assert events[0]["content"] == "narration 15"

    def test_content_truncated_at_600(self, tmp_db):
        sess = _fresh_session()
        db.memory_append(sess["id"], "DM", "narration", "x" * 1000)
        events = db.memory_get_recent(sess["id"])
        assert len(events[0]["content"]) <= 600

    def test_isolated_between_sessions(self, tmp_db):
        s1 = _fresh_session(num=1)
        db.memory_append(s1["id"], "G", "action", "session 1 only")
        db.session_end(s1["id"])
        s2 = _fresh_session(num=2)
        db.memory_append(s2["id"], "G", "action", "session 2 only")
        events = db.memory_get_recent(s2["id"])
        assert len(events) == 1
        assert events[0]["content"] == "session 2 only"

    def test_empty_session_returns_empty_list(self, tmp_db):
        sess = _fresh_session()
        assert db.memory_get_recent(sess["id"]) == []

    def test_multiple_event_types(self, tmp_db):
        sess = _fresh_session()
        db.memory_append(sess["id"], "Grim",   "action",   "smashed the door")
        db.memory_append(sess["id"], "Grim",   "roll",     "STR DR12 → 16 ✅")
        db.memory_append(sess["id"], "SYSTEM", "doom",     "d6→1: segment lost (1/6)")
        db.memory_append(sess["id"], "DM",     "narration","The door splinters.")
        db.memory_append(sess["id"], "SYSTEM", "scene",    "Advanced to ACT 2")
        events = db.memory_get_recent(sess["id"])
        types = {e["event_type"] for e in events}
        assert types == {"action", "roll", "doom", "narration", "scene"}

    def test_format_returns_non_empty_string(self, tmp_db):
        sess = _fresh_session()
        db.memory_append(sess["id"], "Grim", "action", "picked the lock")
        db.memory_append(sess["id"], "Grim", "roll",   "AGI DR12 → 14 ✅")
        result = db.memory_format(sess["id"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_contains_actors(self, tmp_db):
        sess = _fresh_session()
        db.memory_append(sess["id"], "Grim",   "action",   "ran down the alley")
        db.memory_append(sess["id"], "SYSTEM", "doom",     "d4→1: segment lost")
        result = db.memory_format(sess["id"])
        assert "Grim" in result
        assert "SYSTEM" in result or "doom" in result.lower() or "DOOM" in result

    def test_format_empty_returns_no_events_message(self, tmp_db):
        sess = _fresh_session()
        result = db.memory_format(sess["id"])
        assert "no events" in result.lower()


# ---------------------------------------------------------------------------
# Story events
# ---------------------------------------------------------------------------

class TestStoryEvents:
    def test_add_and_get(self, tmp_db):
        db.story_add("dying_light", 1, "npc_met", "Party met Sola Vekt at Station 7")
        events = db.story_get("dying_light")
        assert any("Sola Vekt" in e["summary"] for e in events)

    def test_campaign_isolation(self, tmp_db):
        db.story_add("dying_light", 1, "plot", "DL event")
        db.story_add("other", 1, "plot", "Other campaign event")
        dl_events = db.story_get("dying_light")
        assert all(e["campaign"] == "dying_light" for e in dl_events)

    def test_limit_respected(self, tmp_db):
        for i in range(25):
            db.story_add("dying_light", 1, "plot", f"event {i}")
        events = db.story_get("dying_light", limit=10)
        assert len(events) == 10

    def test_stores_session_num(self, tmp_db):
        db.story_add("dying_light", 3, "artifact", "Artifact first seen")
        events = db.story_get("dying_light")
        assert events[0]["session_num"] == 3
