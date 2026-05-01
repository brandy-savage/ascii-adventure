"""SQLite persistence layer — characters, sessions, memory, story events.

Separate from logging; this is game state, not debug output.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_FILE  = BASE_DIR / "data" / "ascii_adventure.db"

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    name            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    system          TEXT NOT NULL,
    class           TEXT NOT NULL,
    discord_user_id TEXT,
    abilities       TEXT NOT NULL,
    hp_current      INTEGER NOT NULL DEFAULT 1,
    hp_max          INTEGER NOT NULL DEFAULT 1,
    currency        INTEGER DEFAULT 0,
    currency_label  TEXT    DEFAULT 'silver',
    omens_current   INTEGER DEFAULT 1,
    omens_max       INTEGER DEFAULT 1,
    omens_label     TEXT    DEFAULT 'Omens',
    equipment       TEXT    DEFAULT '[]',
    cyberware       TEXT,
    notes           TEXT    DEFAULT '',
    password_hash   TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign        TEXT    NOT NULL,
    session_num     INTEGER NOT NULL,
    session_title   TEXT,
    character_names TEXT    NOT NULL,
    current_act     INTEGER DEFAULT 0,
    acts            TEXT    NOT NULL DEFAULT '[]',
    doom_segments   INTEGER DEFAULT 0,
    doom_max        INTEGER DEFAULT 6,
    channel_id      INTEGER,
    started_at      TEXT    NOT NULL,
    ended_at        TEXT,
    status          TEXT    DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS session_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    actor       TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_session ON session_memory(session_id, id);

CREATE TABLE IF NOT EXISTS story_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign    TEXT    NOT NULL,
    session_num INTEGER,
    event_type  TEXT    NOT NULL,
    summary     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""


def init_db() -> None:
    """Create schema and migrate existing JSON data."""
    conn = _get_conn()
    with _lock:
        conn.executescript(SCHEMA)
        conn.commit()
    _migrate_characters_json()
    _migrate_session_json()


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

def _migrate_characters_json() -> None:
    char_file = BASE_DIR / "data" / "characters.json"
    if not char_file.exists():
        return
    try:
        data = json.loads(char_file.read_text())
    except Exception:
        return
    if not data:
        return
    conn = _get_conn()
    with _lock:
        existing = {r[0] for r in conn.execute("SELECT name FROM characters")}
        now = _now()
        for key, c in data.items():
            if key in existing:
                continue
            hp   = c.get("hp", {})
            omens = c.get("omens", {})
            sys_def_label = c.get("system", "morkborg")
            currency_key = "silver" if sys_def_label == "morkborg" else "chips" if sys_def_label == "dying_light" else "credits"
            conn.execute(
                """INSERT OR IGNORE INTO characters
                   (name, display_name, system, class, discord_user_id,
                    abilities, hp_current, hp_max, currency, currency_label,
                    omens_current, omens_max, omens_label,
                    equipment, cyberware, notes, password_hash, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["name"].lower(), c["name"],
                    c.get("system", "morkborg"), c.get("class", "Unknown"),
                    c.get("discord_user_id"),
                    json.dumps(c.get("abilities", {})),
                    hp.get("current", 1), hp.get("max", 1),
                    c.get(currency_key, c.get("silver", c.get("credits", c.get("chips", 0)))),
                    currency_key,
                    omens.get("current", 1), omens.get("max", 1),
                    omens.get("label", "Omens"),
                    json.dumps(c.get("equipment", [])),
                    json.dumps(c.get("cyberware")) if c.get("cyberware") is not None else None,
                    c.get("notes", ""),
                    c.get("password_hash", ""),
                    now, now,
                ),
            )
        conn.commit()
    # rename migrated file so we don't re-migrate
    char_file.rename(char_file.with_suffix(".json.migrated"))


def _migrate_session_json() -> None:
    state_file = BASE_DIR / "data" / "state.json"
    if not state_file.exists():
        return
    try:
        state = json.loads(state_file.read_text())
    except Exception:
        return
    sess = state.get("active_session")
    if not sess:
        return
    conn = _get_conn()
    with _lock:
        existing = conn.execute(
            "SELECT id FROM sessions WHERE status='active' LIMIT 1"
        ).fetchone()
        if existing:
            return
        conn.execute(
            """INSERT INTO sessions
               (campaign, session_num, session_title, character_names, current_act,
                acts, doom_segments, doom_max, channel_id, started_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sess.get("campaign", "dying_light"),
                sess.get("session_num", 1),
                sess.get("session_title"),
                json.dumps(sess.get("characters", [])),
                sess.get("current_act", 0),
                json.dumps(sess.get("acts", [])),
                sess.get("doom_segments", 0),
                sess.get("doom_max", 6),
                sess.get("channel_id"),
                sess.get("started_at", _now()),
                "active",
            ),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

def char_to_dict(row: sqlite3.Row) -> dict:
    """Convert a DB row back to the character dict format used throughout the bot."""
    hp_cur  = row["hp_current"]
    hp_max  = row["hp_max"]
    label   = row["currency_label"]
    cyb     = json.loads(row["cyberware"]) if row["cyberware"] else None
    return {
        "name":            row["display_name"],
        "system":          row["system"],
        "class":           row["class"],
        "discord_user_id": row["discord_user_id"],
        "abilities":       json.loads(row["abilities"]),
        "hp":              {"current": hp_cur, "max": hp_max},
        label:             row["currency"],
        "omens": {
            "current": row["omens_current"],
            "max":     row["omens_max"],
            "label":   row["omens_label"],
        },
        "equipment":     json.loads(row["equipment"]),
        "cyberware":     cyb,
        "notes":         row["notes"],
        "password_hash": row["password_hash"],
    }


def char_get(name: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT * FROM characters WHERE name = ?", (name.lower(),)
    ).fetchone()
    return char_to_dict(row) if row else None


def char_list() -> list[dict]:
    rows = _get_conn().execute("SELECT * FROM characters ORDER BY display_name").fetchall()
    return [char_to_dict(r) for r in rows]


def char_save(char: dict) -> None:
    key   = char["name"].lower()
    hp    = char.get("hp", {})
    omens = char.get("omens", {})
    sys_key = char.get("system", "morkborg")
    currency_label = (
        "chips" if sys_key == "dying_light" else
        "credits" if sys_key == "cyborg" else "silver"
    )
    currency = char.get(currency_label, char.get("silver", char.get("credits", char.get("chips", 0))))
    cyb = char.get("cyberware")
    now = _now()
    conn = _get_conn()
    with _lock:
        conn.execute(
            """INSERT INTO characters
               (name, display_name, system, class, discord_user_id,
                abilities, hp_current, hp_max, currency, currency_label,
                omens_current, omens_max, omens_label,
                equipment, cyberware, notes, password_hash, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 display_name=excluded.display_name,
                 system=excluded.system, class=excluded.class,
                 discord_user_id=excluded.discord_user_id,
                 abilities=excluded.abilities,
                 hp_current=excluded.hp_current, hp_max=excluded.hp_max,
                 currency=excluded.currency, currency_label=excluded.currency_label,
                 omens_current=excluded.omens_current, omens_max=excluded.omens_max,
                 omens_label=excluded.omens_label,
                 equipment=excluded.equipment, cyberware=excluded.cyberware,
                 notes=excluded.notes, password_hash=excluded.password_hash,
                 updated_at=excluded.updated_at""",
            (
                key, char["name"], sys_key, char.get("class", "Unknown"),
                char.get("discord_user_id"),
                json.dumps(char.get("abilities", {})),
                hp.get("current", 1), hp.get("max", 1),
                currency, currency_label,
                omens.get("current", 1), omens.get("max", 1), omens.get("label", "Omens"),
                json.dumps(char.get("equipment", [])),
                json.dumps(cyb) if cyb is not None else None,
                char.get("notes", ""),
                char.get("password_hash", ""),
                now, now,
            ),
        )
        conn.commit()


def char_delete(name: str) -> None:
    with _lock:
        _get_conn().execute("DELETE FROM characters WHERE name = ?", (name.lower(),))
        _get_conn().commit()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def session_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id":            row["id"],
        "campaign":      row["campaign"],
        "session_num":   row["session_num"],
        "session_title": row["session_title"],
        "characters":    json.loads(row["character_names"]),
        "current_act":   row["current_act"],
        "acts":          json.loads(row["acts"]),
        "doom_segments": row["doom_segments"],
        "doom_max":      row["doom_max"],
        "channel_id":    row["channel_id"],
        "started_at":    row["started_at"],
        "ended_at":      row["ended_at"],
        "status":        row["status"],
    }


def session_get_active() -> dict | None:
    row = _get_conn().execute(
        "SELECT * FROM sessions WHERE status='active' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return session_row_to_dict(row) if row else None


def session_create(
    campaign: str, session_num: int, session_title: str,
    characters: list[str], acts: list[dict], channel_id: int,
) -> dict:
    # End any existing active session first
    with _lock:
        _get_conn().execute(
            "UPDATE sessions SET status='ended', ended_at=? WHERE status='active'",
            (_now(),),
        )
        cur = _get_conn().execute(
            """INSERT INTO sessions
               (campaign, session_num, session_title, character_names, current_act,
                acts, doom_segments, doom_max, channel_id, started_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                campaign, session_num, session_title,
                json.dumps(characters), 0,
                json.dumps([
                    {"num": a["num"], "title": a["title"], "content": a["content"][:1800]}
                    for a in acts
                ]),
                0, 6, channel_id, _now(), "active",
            ),
        )
        _get_conn().commit()
        session_id = cur.lastrowid
    return session_get_active()


def session_update(sess: dict) -> None:
    with _lock:
        _get_conn().execute(
            """UPDATE sessions SET
               current_act=?, acts=?, doom_segments=?,
               character_names=?, session_title=?
               WHERE id=?""",
            (
                sess["current_act"],
                json.dumps(sess["acts"]),
                sess["doom_segments"],
                json.dumps(sess["characters"]),
                sess.get("session_title"),
                sess["id"],
            ),
        )
        _get_conn().commit()


def session_end(session_id: int) -> None:
    with _lock:
        _get_conn().execute(
            "UPDATE sessions SET status='ended', ended_at=? WHERE id=?",
            (_now(), session_id),
        )
        _get_conn().commit()


def session_history(campaign: str, limit: int = 10) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM sessions WHERE campaign=? ORDER BY started_at DESC LIMIT ?",
        (campaign, limit),
    ).fetchall()
    return [session_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Session memory
# ---------------------------------------------------------------------------

def memory_append(
    session_id: int,
    actor: str,
    event_type: str,
    content: str,
) -> None:
    with _lock:
        _get_conn().execute(
            "INSERT INTO session_memory (session_id, actor, event_type, content, created_at) VALUES (?,?,?,?,?)",
            (session_id, actor, event_type, content[:600], _now()),
        )
        _get_conn().commit()


def memory_get_recent(session_id: int, limit: int = 15) -> list[dict]:
    rows = _get_conn().execute(
        """SELECT actor, event_type, content, created_at
           FROM session_memory WHERE session_id=?
           ORDER BY id DESC LIMIT ?""",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def memory_format(session_id: int, limit: int = 15) -> str:
    """Return recent memory as a compact string for DM context."""
    events = memory_get_recent(session_id, limit)
    if not events:
        return "(no events yet this session)"
    lines: list[str] = []
    for e in events:
        actor = e["actor"]
        etype = e["event_type"]
        content = e["content"][:200]
        if etype == "roll":
            lines.append(f"• [ROLL] {content}")
        elif etype == "doom":
            lines.append(f"• [DOOM] {content}")
        elif etype == "scene":
            lines.append(f"• [SCENE] {content}")
        elif etype == "action":
            lines.append(f"• [{actor}] {content}")
        else:
            lines.append(f"• [{actor}] {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Story events (cross-session)
# ---------------------------------------------------------------------------

def story_add(campaign: str, session_num: int, event_type: str, summary: str) -> None:
    with _lock:
        _get_conn().execute(
            "INSERT INTO story_events (campaign, session_num, event_type, summary, created_at) VALUES (?,?,?,?,?)",
            (campaign, session_num, event_type, summary[:800], _now()),
        )
        _get_conn().commit()


def story_get(campaign: str, limit: int = 20) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM story_events WHERE campaign=? ORDER BY id DESC LIMIT ?",
        (campaign, limit),
    ).fetchall()
    return [dict(r) for r in rows]
