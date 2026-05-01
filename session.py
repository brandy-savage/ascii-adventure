"""Session management for ASCII Adventure — Dying Light campaign."""
from __future__ import annotations

import random
import re
from pathlib import Path

import character as char_module
import db

BASE_DIR = Path(__file__).parent

CAMPAIGN_CHAPTER_DIRS: dict[str, Path] = {
    "dying_light": Path("/opt/Dying-Light/chapters"),
}
MAX_SESSIONS: dict[str, int] = {"dying_light": 5}
DOOM_DIE:    dict[int, int]  = {1: 6, 2: 6, 3: 4, 4: 4, 5: 2}


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_session_plan(campaign: str, session_num: int) -> str | None:
    d = CAMPAIGN_CHAPTER_DIRS.get(campaign)
    if not d:
        return None
    p = d / f"chapter{session_num}" / "session_plan.md"
    return p.read_text() if p.exists() else None


def load_session_map(campaign: str, session_num: int) -> str | None:
    d = CAMPAIGN_CHAPTER_DIRS.get(campaign)
    if not d:
        return None
    p = d / f"chapter{session_num}" / "map.txt"
    return p.read_text() if p.exists() else None


# ---------------------------------------------------------------------------
# Session plan parsing
# ---------------------------------------------------------------------------

def get_session_title(plan_text: str) -> str:
    m = re.search(r'^# SESSION \d+: (.+)$', plan_text, re.MULTILINE)
    return m.group(1).strip() if m else "Unknown Session"


def parse_acts(plan_text: str) -> list[dict]:
    """Extract SETUP + numbered ACT sections. Returns list of {num, title, content}."""
    acts: list[dict] = []

    m = re.search(r'## SETUP\s*\n(.*?)(?=\n## |\Z)', plan_text, re.DOTALL)
    if m:
        acts.append({"num": 0, "title": "SETUP", "content": m.group(1).strip()})

    for m in re.finditer(
        r'## ACT (\d+): ([^\n]+)\n(.*?)(?=\n## ACT \d+|\n## DOOM|\n## SESSION|\n## GM |\Z)',
        plan_text, re.DOTALL,
    ):
        acts.append({
            "num": int(m.group(1)),
            "title": m.group(2).strip(),
            "content": m.group(3).strip(),
        })

    m = re.search(r'## DOOM CLOCK[^\n]*\n(.*?)(?=\n## |\Z)', plan_text, re.DOTALL)
    if m:
        acts.append({"num": 99, "title": "DOOM CLOCK", "content": m.group(1).strip()})

    return acts


# ---------------------------------------------------------------------------
# Session state management — backed by SQLite via db module
# ---------------------------------------------------------------------------

def get_session() -> dict | None:
    return db.session_get_active()


def start_session(
    campaign: str,
    session_num: int,
    characters: list[str],
    channel_id: int,
) -> tuple[dict, list[dict]]:
    """Start a new session. Returns (session_state, full_acts_list)."""
    plan  = load_session_plan(campaign, session_num) or ""
    acts  = parse_acts(plan)
    title = get_session_title(plan) if plan else f"Session {session_num}"
    sess  = db.session_create(campaign, session_num, title, characters, acts, channel_id)
    return sess, acts


def advance_act(session: dict) -> tuple[dict, dict | None]:
    """Advance to next act. Returns (updated_session, new_act | None)."""
    acts    = session.get("acts", [])
    current = session.get("current_act", 0)
    nums    = sorted(a["num"] for a in acts if a["num"] != 99)
    idx     = nums.index(current) if current in nums else -1

    new_act: dict | None = None
    if idx + 1 < len(nums):
        next_num             = nums[idx + 1]
        session["current_act"] = next_num
        new_act              = next((a for a in acts if a["num"] == next_num), None)
        db.session_update(session)

    return session, new_act


def end_session(session: dict) -> None:
    db.session_end(session["id"])


def roll_doom(session: dict) -> tuple[bool, int, int]:
    """Roll doom clock. Returns (segment_lost, die_result, die_sides)."""
    session_num = session.get("session_num", 1)
    die    = DOOM_DIE.get(session_num, 6)
    result = random.randint(1, die)
    lost   = result == 1

    if lost:
        session["doom_segments"] = min(session.get("doom_segments", 0) + 1, 6)
        db.session_update(session)

    return lost, result, die


def get_current_act(session: dict) -> dict | None:
    current_num = session.get("current_act", 0)
    return next((a for a in session.get("acts", []) if a["num"] == current_num), None)


def doom_bar(session: dict) -> str:
    """Render doom clock as a text bar: ■■■□□□"""
    filled = session.get("doom_segments", 0)
    total  = session.get("doom_max", 6)
    return "■" * filled + "□" * (total - filled) + f"  {filled}/{total}"


# ---------------------------------------------------------------------------
# Party helpers
# ---------------------------------------------------------------------------

def build_party_summary(characters: list[str]) -> str:
    lines: list[str] = []
    for name in characters:
        char = char_module.get_character(name)
        if char:
            hp   = char.get("hp", {})
            abs_ = char.get("abilities", {})
            ab_str = " | ".join(f"{ab}:{v['mod']:+d}" for ab, v in abs_.items())
            lines.append(
                f"  {char['name']} ({char['class']}, {char.get('system','?')}) "
                f"HP {hp.get('current','?')}/{hp.get('max','?')} — {ab_str}"
            )
        else:
            lines.append(f"  {name} — (not found in character records)")
    return "\n".join(lines) if lines else "  (no characters registered)"
