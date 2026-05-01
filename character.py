"""Character storage, creation logic, and password management for ASCII Adventure."""

from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

CHAR_FILE = Path(__file__).parent / "data" / "characters.json"

# ---------------------------------------------------------------------------
# Systems and classes
# ---------------------------------------------------------------------------

SYSTEMS = {
    "morkborg": {
        "label": "MörK Borg",
        "emoji": "💀",
        "abilities": ["STR", "AGI", "PRE", "TOU"],
        "currency": "silver",
        "omens_label": "Omens",
        "classes": [
            "Gutterborn Scum", "Wretched Royalty", "Esoteric Hermit",
            "Occult Herbmaster", "Fanged Deserter", "Cursed Skinwalker",
            "Sacrilegious Songbird", "Pale One", "Dead God's Prophet", "Heretical Priest",
        ],
    },
    "cyborg": {
        "label": "CY_BORG",
        "emoji": "🤖",
        "abilities": ["STR", "AGI", "PRE", "TOU", "SYNTH"],
        "currency": "credits",
        "omens_label": "Glitch",
        "classes": [
            "Nano-Mystic", "Renegade", "Abandoned", "Dock Rat",
            "Data Witch", "Chrome Avenger", "Flesh Merchant", "Punk",
        ],
    },
    "dying_light": {
        "label": "Dying Light",
        "emoji": "🕯️",
        "abilities": ["STR", "AGI", "PRE", "TOU", "KNOWLEDGE"],
        "currency": "chips",
        "omens_label": "Omens",
        "classes": [
            # MörK Borg origins (wasteland-born, outside the city)
            "Fanged Deserter", "Gutterborn Scum", "Esoteric Hermit",
            "Wretched Royalty", "Heretical Priest", "Occult Herbmaster",
            "Doomed", "Disinherited Noble", "Exiled Knight", "Pale One",
            # CY_BORG origins (born in Lux-9's neon rot)
            "Burned Hacker", "Discharged Corp Killer", "Forsaken Gang-Goon",
            "Renegade Cyberslasher", "Orphaned Gearhead", "Broken Body",
            "Shunned Nanomancer", "Waste Runner", "Punk Preacher", "Corporate Drone",
        ],
    },
}


# ---------------------------------------------------------------------------
# Dice
# ---------------------------------------------------------------------------

def roll(sides: int, count: int = 1) -> list[int]:
    return [random.randint(1, sides) for _ in range(count)]


def ability_modifier(total: int) -> int:
    # Standard MörK Borg / Dying Light table: 1-4=-3, 5-6=-2, 7-8=-1, 9-12=0, 13-14=+1, 15-16=+2, 17-18=+3
    table = [(4, -3), (6, -2), (8, -1), (12, 0), (14, 1), (16, 2), (18, 3)]
    for threshold, mod in table:
        if total <= threshold:
            return mod
    return 3


def roll_abilities(system_key: str) -> dict[str, dict]:
    sys_def = SYSTEMS[system_key]
    abilities: dict[str, dict] = {}
    for ab in sys_def["abilities"]:
        dice = roll(6, 3)
        total = sum(dice)
        mod = ability_modifier(total)
        abilities[ab] = {"roll": total, "dice": dice, "mod": mod}
    return abilities


def roll_hp(tou_mod: int) -> int:
    hp = tou_mod + random.randint(1, 8)
    return max(1, hp)


def roll_starting_currency(system_key: str) -> int:
    if system_key == "morkborg":
        return random.randint(1, 6) * 10
    return random.randint(1, 6) * 100


def roll_omens(system_key: str) -> int:
    return random.randint(1, 2) if system_key == "morkborg" else random.randint(1, 4)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash_password(password: str, char_name: str) -> str:
    salt = char_name.lower().strip()
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def verify_password(password: str, char_name: str, stored_hash: str) -> bool:
    return _hash_password(password, char_name) == stored_hash


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> dict:
    if CHAR_FILE.exists():
        try:
            return json.loads(CHAR_FILE.read_text())
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    CHAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHAR_FILE.write_text(json.dumps(data, indent=2))


def get_character(name: str) -> dict | None:
    return _load().get(name.lower())


def list_characters() -> list[dict]:
    return list(_load().values())


def save_character(char: dict) -> None:
    data = _load()
    data[char["name"].lower()] = char
    _save(data)


def delete_character(name: str, password: str) -> tuple[bool, str]:
    data = _load()
    key = name.lower()
    char = data.get(key)
    if not char:
        return False, f"No character named `{name}` found."
    if not verify_password(password, name, char["password_hash"]):
        return False, "Wrong password."
    del data[key]
    _save(data)
    return True, f"Character `{name}` deleted."


def create_character(
    name: str,
    system_key: str,
    char_class: str,
    password: str,
    discord_user_id: str,
    abilities: dict | None = None,
    notes: str = "",
) -> dict:
    if abilities is None:
        abilities = roll_abilities(system_key)
    tou_mod = abilities.get("TOU", {}).get("mod", 0)
    hp = roll_hp(tou_mod)
    currency = roll_starting_currency(system_key)
    omens = roll_omens(system_key)
    sys_def = SYSTEMS[system_key]

    char = {
        "name": name,
        "system": system_key,
        "class": char_class,
        "discord_user_id": discord_user_id,
        "abilities": abilities,
        "hp": {"current": hp, "max": hp},
        sys_def["currency"]: currency,
        "omens": {"current": omens, "max": omens, "label": sys_def["omens_label"]},
        "equipment": [],
        "cyberware": [] if system_key in ("cyborg", "dying_light") else None,
        "notes": notes,
        "password_hash": _hash_password(password, name),
    }
    save_character(char)
    return char


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_sheet(char: dict, public: bool = True) -> str:
    sys_key = char.get("system", "morkborg")
    sys_def = SYSTEMS.get(sys_key, SYSTEMS["morkborg"])
    emoji = sys_def["emoji"]
    label = sys_def["label"]

    ab_lines = []
    for ab, val in char.get("abilities", {}).items():
        mod = val.get("mod", 0)
        sign = "+" if mod >= 0 else ""
        ab_lines.append(f"  {ab}: {sign}{mod} (rolled {val.get('roll', '?')})")

    hp = char.get("hp", {})
    omens = char.get("omens", {})
    currency_key = sys_def["currency"]
    currency = char.get(currency_key, char.get("silver", char.get("credits", "?")))

    gear = char.get("equipment", [])
    gear_str = ", ".join(gear) if gear else "none"

    cyber = char.get("cyberware")
    cyber_str = ""
    if cyber is not None:
        cyber_str = f"\n**Cyberware:** {', '.join(cyber) if cyber else 'none'}"

    notes = char.get("notes", "")
    notes_str = f"\n**Notes:** {notes}" if notes else ""

    lines = [
        f"{emoji} **{char['name']}** — {char['class']} ({label})",
        "```",
        "\n".join(ab_lines),
        f"  HP: {hp.get('current','?')}/{hp.get('max','?')}",
        f"  {omens.get('label','Omens')}: {omens.get('current','?')}/{omens.get('max','?')}",
        f"  {currency_key.capitalize()}: {currency}",
        "```",
        f"**Gear:** {gear_str}",
        cyber_str,
        notes_str,
    ]
    return "\n".join(l for l in lines if l)


def format_abilities_preview(abilities: dict, system_key: str) -> str:
    lines = []
    for ab, val in abilities.items():
        mod = val["mod"]
        sign = "+" if mod >= 0 else ""
        dice_str = "+".join(str(d) for d in val["dice"])
        lines.append(f"  {ab}: {dice_str} = {val['roll']} → **{sign}{mod}**")
    tou_mod = abilities.get("TOU", {}).get("mod", 0)
    hp_range = f"{max(1, tou_mod+1)}–{max(1, tou_mod+8)}"
    lines.append(f"\n  *HP will be: d8 + TOU({tou_mod:+d}) = {hp_range}*")
    return "\n".join(lines)
