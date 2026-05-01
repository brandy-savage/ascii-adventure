"""Tests for character.py — modifier table, dice, password, storage."""
import pytest
import character as char


# ---------------------------------------------------------------------------
# Ability modifier table
# ---------------------------------------------------------------------------

class TestAbilityModifier:
    @pytest.mark.parametrize("roll,expected", [
        (1, -3), (2, -3), (3, -3), (4, -3),     # 1–4  → -3
        (5, -2), (6, -2),                         # 5–6  → -2
        (7, -1), (8, -1),                         # 7–8  → -1
        (9,  0), (10, 0), (11, 0), (12, 0),      # 9–12 →  0
        (13, 1), (14, 1),                         # 13–14 → +1
        (15, 2), (16, 2),                         # 15–16 → +2
        (17, 3), (18, 3),                         # 17–18 → +3
    ])
    def test_full_table(self, roll, expected):
        assert char.ability_modifier(roll) == expected

    def test_boundary_4_is_minus3(self):
        # Previously broken — was returning -2 for a roll of 4
        assert char.ability_modifier(4) == -3

    def test_boundary_14_is_plus1(self):
        assert char.ability_modifier(14) == 1

    def test_boundary_16_is_plus2(self):
        assert char.ability_modifier(16) == 2


# ---------------------------------------------------------------------------
# Roll abilities
# ---------------------------------------------------------------------------

class TestRollAbilities:
    @pytest.mark.parametrize("system,expected_keys", [
        ("morkborg",    {"STR", "AGI", "PRE", "TOU"}),
        ("cyborg",      {"STR", "AGI", "PRE", "TOU", "SYNTH"}),
        ("dying_light", {"STR", "AGI", "PRE", "TOU", "KNOWLEDGE"}),
    ])
    def test_correct_ability_keys(self, system, expected_keys):
        abilities = char.roll_abilities(system)
        assert set(abilities.keys()) == expected_keys

    def test_dying_light_has_knowledge_not_synth(self):
        abilities = char.roll_abilities("dying_light")
        assert "KNOWLEDGE" in abilities
        assert "SYNTH" not in abilities

    def test_roll_values_in_3d6_range(self):
        for _ in range(20):
            abilities = char.roll_abilities("morkborg")
            for ab, val in abilities.items():
                assert 3 <= val["roll"] <= 18
                assert len(val["dice"]) == 3
                assert all(1 <= d <= 6 for d in val["dice"])
                assert sum(val["dice"]) == val["roll"]

    def test_modifier_consistent_with_roll(self):
        for _ in range(20):
            abilities = char.roll_abilities("dying_light")
            for ab, val in abilities.items():
                assert char.ability_modifier(val["roll"]) == val["mod"]


# ---------------------------------------------------------------------------
# HP rolling
# ---------------------------------------------------------------------------

class TestRollHp:
    def test_never_below_one(self):
        for _ in range(100):
            assert char.roll_hp(-3) >= 1

    def test_upper_bound_with_zero_mod(self):
        for _ in range(100):
            hp = char.roll_hp(0)
            assert 1 <= hp <= 8

    def test_bonus_toughness_shifts_range(self):
        highs = [char.roll_hp(3) for _ in range(50)]
        assert max(highs) > 8  # at least one roll should exceed base max


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestPassword:
    def test_hash_is_deterministic(self):
        assert char._hash_password("secret", "Grim") == char._hash_password("secret", "Grim")

    def test_different_passwords_differ(self):
        assert char._hash_password("aaa", "Grim") != char._hash_password("bbb", "Grim")

    def test_different_names_differ(self):
        assert char._hash_password("secret", "Grim") != char._hash_password("secret", "Nox")

    def test_name_is_case_insensitive(self):
        assert char._hash_password("pw", "GRIM") == char._hash_password("pw", "grim")

    def test_verify_correct_password(self):
        h = char._hash_password("correct", "Hero")
        assert char.verify_password("correct", "Hero", h) is True

    def test_verify_wrong_password(self):
        h = char._hash_password("correct", "Hero")
        assert char.verify_password("wrong", "Hero", h) is False

    def test_verify_wrong_name(self):
        h = char._hash_password("correct", "Hero")
        assert char.verify_password("correct", "OtherHero", h) is False


# ---------------------------------------------------------------------------
# Character creation and storage
# ---------------------------------------------------------------------------

class TestCreateCharacter:
    def test_all_required_fields_present(self, tmp_db):
        c = char.create_character("Spawn", "dying_light", "Gutterborn Scum", "pw", "42")
        for field in ("name", "system", "class", "hp", "abilities", "omens", "password_hash"):
            assert field in c, f"Missing field: {field}"

    def test_hp_at_least_one(self, tmp_db):
        for _ in range(10):
            c = char.create_character(f"Char{_}", "morkborg", "Pale One", "pw", "1")
            assert c["hp"]["max"] >= 1
            assert c["hp"]["current"] == c["hp"]["max"]

    def test_dying_light_uses_chips(self, tmp_db):
        c = char.create_character("Chipper", "dying_light", "Waste Runner", "pw", "1")
        assert "chips" in c

    def test_morkborg_uses_silver(self, tmp_db):
        c = char.create_character("Silver", "morkborg", "Pale One", "pw", "1")
        assert "silver" in c

    def test_password_hash_stored(self, tmp_db):
        c = char.create_character("Hashed", "morkborg", "Doomed", "mypassword", "1")
        assert char.verify_password("mypassword", "Hashed", c["password_hash"])


class TestStorageRoundTrip:
    def test_save_and_retrieve(self, tmp_db, sample_abilities):
        c = char.create_character("Grimdark", "dying_light", "Doomed", "pw", "1")
        retrieved = char.get_character("Grimdark")
        assert retrieved is not None
        assert retrieved["name"] == "Grimdark"
        assert retrieved["class"] == "Doomed"

    def test_get_is_case_insensitive(self, tmp_db):
        char.create_character("CaseChar", "morkborg", "Pale One", "pw", "1")
        assert char.get_character("casechar") is not None
        assert char.get_character("CASECHAR") is not None

    def test_get_missing_returns_none(self, tmp_db):
        assert char.get_character("doesnotexist") is None

    def test_list_all_characters(self, tmp_db):
        char.create_character("Aaa", "morkborg", "Pale One", "pw", "1")
        char.create_character("Bbb", "cyborg", "Punk", "pw", "2")
        names = {c["name"] for c in char.list_characters()}
        assert {"Aaa", "Bbb"}.issubset(names)

    def test_save_updates_existing(self, tmp_db):
        c = char.create_character("Updatable", "morkborg", "Pale One", "pw", "1")
        c["notes"] = "new notes"
        char.save_character(c)
        assert char.get_character("Updatable")["notes"] == "new notes"

    def test_delete_wrong_password(self, tmp_db):
        char.create_character("Protected", "morkborg", "Pale One", "correct", "1")
        ok, _ = char.delete_character("Protected", "wrong")
        assert ok is False
        assert char.get_character("Protected") is not None

    def test_delete_correct_password(self, tmp_db):
        char.create_character("Deletable", "morkborg", "Pale One", "correct", "1")
        ok, _ = char.delete_character("Deletable", "correct")
        assert ok is True
        assert char.get_character("Deletable") is None

    def test_delete_missing_character(self, tmp_db):
        ok, msg = char.delete_character("ghost", "pw")
        assert ok is False
        assert "ghost" in msg.lower() or "no character" in msg.lower()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class TestFormatSheet:
    def test_returns_string_with_character_name(self, tmp_db):
        c = char.create_character("Fmttest", "dying_light", "Waste Runner", "pw", "1")
        sheet = char.format_sheet(c)
        assert isinstance(sheet, str)
        assert "Fmttest" in sheet
        assert "Waste Runner" in sheet

    def test_contains_hp(self, tmp_db):
        c = char.create_character("Hptest", "morkborg", "Pale One", "pw", "1")
        assert "HP" in char.format_sheet(c)

    def test_abilities_preview_contains_all_keys(self, tmp_db, sample_abilities):
        preview = char.format_abilities_preview(sample_abilities, "dying_light")
        for ab in ("STR", "AGI", "PRE", "TOU", "KNOWLEDGE"):
            assert ab in preview

    def test_abilities_preview_shows_modifier_sign(self, tmp_db, sample_abilities):
        preview = char.format_abilities_preview(sample_abilities, "dying_light")
        assert "+" in preview or "−" in preview or "-" in preview
