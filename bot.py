"""ASCII Adventure — Discord slash command bot.

Art commands:  /wizard /dragon /goblin /orc /troll /undead /skull /castle /spell
               /class /summon /bestiary /reload

DM commands:   /dm /encounter /npc /lore

Campaign:      /campaign list|set|info

Rules:         /rules

Character:     /character new       — walkthrough (system → class → name+password)
               /character sheet     — view your sheet (or any public character)
               /character list      — all characters
               /character update    — edit notes/gear (password required)
               /character delete    — delete (password required)
               /character hp        — update HP (password required)

Dice:          /roll <expression>   — e.g. d20, 2d6+3, d8-1
               /check <ability>     — roll d20 + ability modifier
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).parent))
import character as char_module

BASE_DIR   = Path(__file__).parent
CAMPAIGNS  = BASE_DIR / "data" / "campaigns"
RULES_DIR  = BASE_DIR / "data" / "rules"
ART_CATALOG = BASE_DIR / "data" / "art_catalog.json"
ENV_FILE   = Path.home() / "nanoclaw" / ".env"
CLAUDE_BIN = Path.home() / ".local" / "bin" / "claude"

GUILD_ID = 1498390292901007420
LOG_FILE = BASE_DIR / "logs" / "bot.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
_fh  = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3)
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler()
_sh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger("ascii_adventure")

# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def _load_token() -> str:
    tok = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if tok:
        return tok
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DISCORD_BOT_TOKEN not set")


# ---------------------------------------------------------------------------
# Art catalog
# ---------------------------------------------------------------------------

def load_catalog() -> dict:
    try:
        return json.loads(ART_CATALOG.read_text())
    except Exception as e:
        log.error("art catalog error: %s", e)
        return {}


def get_art(category: str) -> str | None:
    pieces = load_catalog().get(category.lower())
    if not pieces:
        return None
    entry = random.choice(pieces)
    flavor = entry.get("flavor", "")
    art = entry.get("art", "")
    return f"*{flavor}*\n{art}" if flavor else art


def list_categories() -> list[str]:
    return sorted(load_catalog().keys())


# ---------------------------------------------------------------------------
# Campaign state
# ---------------------------------------------------------------------------

_STATE_FILE = BASE_DIR / "data" / "state.json"


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {"active_campaign": "default"}


def _save_state(s: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(s, indent=2))


def get_active_campaign() -> str:
    return _load_state().get("active_campaign", "default")


def set_active_campaign(name: str) -> bool:
    if not (CAMPAIGNS / f"{name}.md").exists():
        return False
    s = _load_state(); s["active_campaign"] = name; _save_state(s)
    return True


def load_campaign_text(name: str) -> str | None:
    p = CAMPAIGNS / f"{name}.md"
    return p.read_text() if p.exists() else None


def list_campaigns() -> list[str]:
    return [p.stem for p in sorted(CAMPAIGNS.glob("*.md"))]


# ---------------------------------------------------------------------------
# Local Claude DM
# ---------------------------------------------------------------------------

DM_SYSTEM = """\
You are a Dungeon Master running a tabletop RPG session on Discord.
Speak in second-person ("you see...", "before you..."). Be dramatic and immersive.
Keep responses under 1800 characters. No markdown headers.

CAMPAIGN SETTING:
{campaign}
"""

ENCOUNTER_PROMPTS = [
    "The party suddenly faces an ambush. Describe it.",
    "The party rounds a corner and discovers something unexpected. What is it?",
    "A strange traveler approaches. Who are they and what do they want?",
    "The party hears a sound in the darkness ahead. What do they find?",
    "Describe an environmental hazard the party must navigate.",
]

NPC_PROMPTS = [
    "Introduce a new NPC. Give them a name, memorable appearance, personality quirk, and a secret.",
    "A merchant approaches with unusual wares. Describe them.",
    "A mysterious figure has been following the party. Reveal them.",
    "A desperate child runs up to the party needing help. Who are they?",
]


def call_dm(prompt: str, campaign_name: str) -> str:
    campaign = load_campaign_text(campaign_name) or "Generic fantasy adventure."
    system = DM_SYSTEM.format(campaign=campaign[:3000])
    full = f"{system}\n\nPlayer: {prompt}\n\nDM:"
    try:
        r = subprocess.run(
            [str(CLAUDE_BIN), "-p", full, "--model", "haiku", "--output-format", "text"],
            capture_output=True, text=True, timeout=60,
        )
        out = r.stdout.strip()
        return out[:1900] if out else "(The DM is silent...)"
    except subprocess.TimeoutExpired:
        return "(The DM is consulting ancient tomes... timed out)"
    except Exception as e:
        return f"(DM error: {e})"


# ---------------------------------------------------------------------------
# Dice rolling
# ---------------------------------------------------------------------------

def parse_roll(expr: str) -> tuple[int, str]:
    """Parse expressions like d20, 2d6, d8+3, 3d6-1. Returns (result, breakdown)."""
    expr = expr.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr)
    if not m:
        raise ValueError(f"Invalid dice expression: {expr}")
    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    if count < 1 or count > 20 or sides < 2 or sides > 100:
        raise ValueError("Dice out of range (1–20 dice, d2–d100)")
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + mod
    dice_str = "+".join(str(r) for r in rolls)
    mod_str = f" {m.group(3)}" if mod else ""
    breakdown = f"[{dice_str}]{mod_str} = **{total}**"
    return total, breakdown


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)
G       = discord.Object(id=GUILD_ID)


def _log_cmd(i: discord.Interaction, **kwargs):
    """Structured log line for every command invocation."""
    user = f"{i.user.name}#{i.user.discriminator}" if hasattr(i.user, "discriminator") else i.user.name
    channel = getattr(i.channel, "name", "DM") or "unknown"
    cmd = i.command.name if i.command else "unknown"
    extras = " ".join(f"{k}={v!r}" for k, v in kwargs.items() if v)
    log.info("CMD /%s user=%s channel=#%s %s", cmd, user, channel, extras)


@client.event
async def on_ready():
    log.info("Logged in as %s (id=%s)", client.user, client.user.id if client.user else "?")
    tree.copy_global_to(guild=G)
    await tree.sync(guild=G)
    log.info("Slash commands synced to guild %s", GUILD_ID)


# ---------------------------------------------------------------------------
# Art commands
# ---------------------------------------------------------------------------

async def _art(i: discord.Interaction, cat: str):
    _log_cmd(i, category=cat)
    art = get_art(cat)
    if art:
        await i.response.send_message(art)
    else:
        await i.response.send_message(
            f"No art for `{cat}`. Try `/bestiary` for options.", ephemeral=True
        )


@tree.command(name="wizard",  description="Summon a wizard",    guild=G)
async def cmd_wizard(i: discord.Interaction): await _art(i, "wizard")
@tree.command(name="dragon",  description="Unleash a dragon",   guild=G)
async def cmd_dragon(i: discord.Interaction): await _art(i, "dragon")
@tree.command(name="goblin",  description="A goblin appears!",  guild=G)
async def cmd_goblin(i: discord.Interaction): await _art(i, "goblin")
@tree.command(name="orc",     description="For the Horde!",     guild=G)
async def cmd_orc(i: discord.Interaction): await _art(i, "orc")
@tree.command(name="troll",   description="SMASH",              guild=G)
async def cmd_troll(i: discord.Interaction): await _art(i, "troll")
@tree.command(name="undead",  description="The dead rise...",   guild=G)
async def cmd_undead(i: discord.Interaction): await _art(i, "undead")
@tree.command(name="skull",   description="Memento Mori",       guild=G)
async def cmd_skull(i: discord.Interaction): await _art(i, "skull")
@tree.command(name="castle",  description="A fortress rises",   guild=G)
async def cmd_castle(i: discord.Interaction): await _art(i, "castle")
@tree.command(name="spell",   description="Cast a spell!",      guild=G)
async def cmd_spell(i: discord.Interaction): await _art(i, "spell")

@tree.command(name="class", description="Show a character class", guild=G)
@app_commands.describe(name="rogue · mage · ranger · knight")
async def cmd_class(i: discord.Interaction, name: str): await _art(i, name.lower().strip())

@tree.command(name="summon", description="Summon any creature from the catalog", guild=G)
@app_commands.describe(creature="Category or 'random'")
async def cmd_summon(i: discord.Interaction, creature: str = "random"):
    if creature.lower() == "random":
        cats = list_categories()
        creature = random.choice(cats) if cats else "wizard"
    await _art(i, creature.lower().strip())

@tree.command(name="bestiary", description="List all available creatures", guild=G)
async def cmd_bestiary(i: discord.Interaction):
    _log_cmd(i)
    catalog = load_catalog()
    lines = ["**📖 Bestiary**"]
    for cat, pieces in sorted(catalog.items()):
        ids = ", ".join(p["id"] for p in pieces)
        lines.append(f"  `{cat}` — {ids}")
    lines.append("\nUse `/summon <type>` for anything not listed as its own command.")
    await i.response.send_message("\n".join(lines))

@tree.command(name="reload", description="Hot-reload art catalog from JSON", guild=G)
async def cmd_reload(i: discord.Interaction):
    _log_cmd(i)
    try:
        catalog = load_catalog()
        count = sum(len(v) for v in catalog.values())
        await i.response.send_message(f"✅ Reloaded — {len(catalog)} categories, {count} pieces.")
    except Exception as e:
        await i.response.send_message(f"❌ Reload failed: {e}", ephemeral=True)


# ---------------------------------------------------------------------------
# DM commands
# ---------------------------------------------------------------------------

@tree.command(name="dm", description="Ask the Dungeon Master anything", guild=G)
@app_commands.describe(prompt="What do you say or ask?")
async def cmd_dm(i: discord.Interaction, prompt: str):
    _log_cmd(i, prompt=prompt[:80])
    await i.response.defer()
    campaign = get_active_campaign()
    r = await client.loop.run_in_executor(None, call_dm, prompt, campaign)
    log.info("DM response user=%s campaign=%s len=%d", i.user.name, campaign, len(r))
    await i.followup.send(f"🎲 **DM:** {r}")

@tree.command(name="encounter", description="DM narrates a random encounter", guild=G)
async def cmd_encounter(i: discord.Interaction):
    _log_cmd(i)
    await i.response.defer()
    r = await client.loop.run_in_executor(None, call_dm, random.choice(ENCOUNTER_PROMPTS), get_active_campaign())
    await i.followup.send(f"⚔️ **ENCOUNTER:** {r}")

@tree.command(name="npc", description="DM introduces a random NPC", guild=G)
async def cmd_npc(i: discord.Interaction):
    _log_cmd(i)
    await i.response.defer()
    r = await client.loop.run_in_executor(None, call_dm, random.choice(NPC_PROMPTS), get_active_campaign())
    await i.followup.send(f"🧙 **NPC:** {r}")

@tree.command(name="lore", description="Ask the DM about lore", guild=G)
@app_commands.describe(topic="What do you want to know about?")
async def cmd_lore(i: discord.Interaction, topic: str):
    _log_cmd(i, topic=topic)
    await i.response.defer()
    r = await client.loop.run_in_executor(None, call_dm, f"Explain the lore around: {topic}", get_active_campaign())
    await i.followup.send(f"📜 **LORE — {topic}:** {r}")


# ---------------------------------------------------------------------------
# Campaign commands
# ---------------------------------------------------------------------------

@tree.command(name="campaign", description="Manage campaign settings", guild=G)
@app_commands.describe(action="list · info · set", name="Campaign name (for 'set')")
async def cmd_campaign(i: discord.Interaction, action: str = "info", name: str = ""):
    _log_cmd(i, action=action, name=name)
    action = action.lower().strip()
    if action == "list":
        camps = list_campaigns(); active = get_active_campaign()
        lines = ["**📋 Campaigns:**"]
        for c in camps:
            lines.append(f"  `{c}`{' ← active' if c == active else ''}")
        await i.response.send_message("\n".join(lines))
    elif action == "set":
        if not name:
            await i.response.send_message("Usage: `/campaign set <name>`", ephemeral=True); return
        if set_active_campaign(name):
            await i.response.send_message(f"✅ Campaign set to **{name}**.")
        else:
            await i.response.send_message(f"❌ Campaign `{name}` not found. Use `/campaign list`.", ephemeral=True)
    else:
        active = get_active_campaign()
        content = load_campaign_text(active) or "(no content)"
        preview = content[:1500] + ("..." if len(content) > 1500 else "")
        await i.response.send_message(f"**Campaign: {active}**\n```\n{preview}\n```")


# ---------------------------------------------------------------------------
# Rules command
# ---------------------------------------------------------------------------

@tree.command(name="rules", description="Show rules for a system", guild=G)
@app_commands.describe(system="morkborg · cyborg · dying_light")
async def cmd_rules(i: discord.Interaction, system: str = "morkborg"):
    _log_cmd(i, system=system)
    path = RULES_DIR / f"{system.lower().strip()}.md"
    if not path.exists():
        available = ", ".join(p.stem for p in sorted(RULES_DIR.glob("*.md")))
        await i.response.send_message(f"No rules for `{system}`. Available: {available}", ephemeral=True)
        return
    content = path.read_text()
    preview = content[:1800] + ("..." if len(content) > 1800 else "")
    await i.response.send_message(f"```md\n{preview}\n```")


# ---------------------------------------------------------------------------
# Dice commands
# ---------------------------------------------------------------------------

@tree.command(name="roll", description="Roll dice — e.g. d20, 2d6, d8+3", guild=G)
@app_commands.describe(expression="Dice expression: NdS[+/-M]")
async def cmd_roll(i: discord.Interaction, expression: str):
    _log_cmd(i, expression=expression)
    try:
        total, breakdown = parse_roll(expression)
        log.info("ROLL user=%s expr=%s result=%d", i.user.name, expression, total)
        await i.response.send_message(f"🎲 `{expression}` → {breakdown}")
    except ValueError as e:
        await i.response.send_message(f"❌ {e}", ephemeral=True)

@tree.command(name="check", description="Roll d20 + ability modifier for a character", guild=G)
@app_commands.describe(character_name="Your character name", ability="STR · AGI · PRE · TOU · SYNTH", dr="Difficulty Rating (default 12)")
async def cmd_check(i: discord.Interaction, character_name: str, ability: str, dr: int = 12):
    _log_cmd(i, char=character_name, ability=ability, dr=dr)
    char = char_module.get_character(character_name)
    if not char:
        await i.response.send_message(f"Character `{character_name}` not found.", ephemeral=True); return
    ab_data = char.get("abilities", {}).get(ability.upper())
    if not ab_data:
        abs_list = ", ".join(char.get("abilities", {}).keys())
        await i.response.send_message(f"Ability `{ability}` not found. Available: {abs_list}", ephemeral=True); return
    mod = ab_data["mod"]
    d20 = random.randint(1, 20)
    total = d20 + mod
    sign = "+" if mod >= 0 else ""
    result = "✅ **SUCCESS**" if total >= dr else "❌ **FAILURE**"
    crit = " *(natural 20!)*" if d20 == 20 else (" *(fumble!)*" if d20 == 1 else "")
    await i.response.send_message(
        f"🎲 **{character_name}** — {ability.upper()} check vs DR {dr}\n"
        f"d20({d20}) {sign}{mod} = **{total}** {result}{crit}"
    )


# ---------------------------------------------------------------------------
# Character creation — multi-step walkthrough using Views
# ---------------------------------------------------------------------------

class SystemSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="💀 MörK Borg", style=discord.ButtonStyle.danger)
    async def pick_morkborg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_class_select(interaction, "morkborg")

    @discord.ui.button(label="🤖 CY_BORG", style=discord.ButtonStyle.primary)
    async def pick_cyborg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_class_select(interaction, "cyborg")

    @discord.ui.button(label="🌆 Dying Light", style=discord.ButtonStyle.secondary)
    async def pick_dying_light(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_class_select(interaction, "dying_light")


async def _show_class_select(interaction: discord.Interaction, system_key: str):
    sys_def = char_module.SYSTEMS[system_key]
    options = [
        discord.SelectOption(label=cls, value=f"{system_key}|{cls}")
        for cls in sys_def["classes"]
    ]
    view = ClassSelectView(options)
    label = sys_def["label"]
    await interaction.response.edit_message(
        content=f"**{label}** selected.\nChoose your class:",
        view=view,
    )


class ClassSelectView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        select = discord.ui.Select(placeholder="Choose a class...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        system_key, char_class = value.split("|", 1)
        abilities = char_module.roll_abilities(system_key)
        preview = char_module.format_abilities_preview(abilities, system_key)
        abilities_json = json.dumps(abilities)
        view = ConfirmAbilitiesView(system_key, char_class, abilities_json)
        await interaction.response.edit_message(
            content=(
                f"**Class:** {char_class}\n\n"
                f"**Rolled abilities:**\n{preview}\n\n"
                f"Happy with these? Set your name and password to lock it in, or reroll."
            ),
            view=view,
        )


class ConfirmAbilitiesView(discord.ui.View):
    def __init__(self, system_key: str, char_class: str, abilities_json: str):
        super().__init__(timeout=120)
        self.system_key = system_key
        self.char_class = char_class
        self.abilities_json = abilities_json

    @discord.ui.button(label="✅ Set Name & Password", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = FinalizeModal(self.system_key, self.char_class, self.abilities_json)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🎲 Reroll", style=discord.ButtonStyle.secondary)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        abilities = char_module.roll_abilities(self.system_key)
        preview = char_module.format_abilities_preview(abilities, self.system_key)
        abilities_json = json.dumps(abilities)
        view = ConfirmAbilitiesView(self.system_key, self.char_class, abilities_json)
        await interaction.response.edit_message(
            content=(
                f"**Class:** {self.char_class}\n\n"
                f"**Rolled abilities (rerolled):**\n{preview}\n\n"
                f"Happy with these? Set your name and password to lock it in, or reroll."
            ),
            view=view,
        )


class FinalizeModal(discord.ui.Modal, title="Create Your Character"):
    char_name  = discord.ui.TextInput(label="Character Name", min_length=2, max_length=40)
    password   = discord.ui.TextInput(label="Password (only you will know this)", min_length=4, max_length=64)
    equipment  = discord.ui.TextInput(label="Starting Gear (comma separated)", required=False, max_length=300)
    notes      = discord.ui.TextInput(label="Notes / Backstory", required=False, max_length=500, style=discord.TextStyle.paragraph)

    def __init__(self, system_key: str, char_class: str, abilities_json: str):
        super().__init__()
        self._system_key    = system_key
        self._char_class    = char_class
        self._abilities_json = abilities_json

    async def on_submit(self, interaction: discord.Interaction):
        name = self.char_name.value.strip()
        pw   = self.password.value
        gear = [g.strip() for g in self.equipment.value.split(",") if g.strip()] if self.equipment.value else []
        notes = self.notes.value.strip()
        abilities = json.loads(self._abilities_json)

        if char_module.get_character(name):
            log.warning("CHARACTER create failed — name taken: %s by user=%s", name, interaction.user.name)
            await interaction.response.send_message(
                f"❌ A character named `{name}` already exists.", ephemeral=True
            )
            return

        char = char_module.create_character(
            name=name,
            system_key=self._system_key,
            char_class=self._char_class,
            password=pw,
            discord_user_id=str(interaction.user.id),
            abilities=abilities,
            notes=notes,
        )
        char["equipment"] = gear
        char_module.save_character(char)
        log.info("CHARACTER created name=%s system=%s class=%s user=%s",
                 name, self._system_key, self._char_class, interaction.user.name)

        sheet = char_module.format_sheet(char)
        await interaction.response.send_message(
            f"🎉 **Character created!** Your password is locked in — don't lose it.\n\n{sheet}",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Character commands
# ---------------------------------------------------------------------------

@tree.command(name="character", description="Character management", guild=G)
@app_commands.describe(
    action="new · sheet · list · update · delete · hp",
    name="Character name",
    value="For hp: new current HP value",
    password="Required for update/delete/hp",
)
async def cmd_character(
    i: discord.Interaction,
    action: str = "sheet",
    name: str = "",
    value: str = "",
    password: str = "",
):
    _log_cmd(i, action=action, name=name)
    action = action.lower().strip()

    # --- new ---
    if action == "new":
        view = SystemSelectView()
        await i.response.send_message(
            "**⚔️ Character Creation**\n\nStep 1: Choose your system.",
            view=view,
            ephemeral=True,
        )
        return

    # --- list ---
    if action == "list":
        chars = char_module.list_characters()
        if not chars:
            await i.response.send_message("No characters yet. Use `/character new` to create one.")
            return
        lines = ["**🧙 Characters:**"]
        for c in chars:
            sys_key = c.get("system", "?")
            sys_label = char_module.SYSTEMS.get(sys_key, {}).get("label", sys_key)
            hp = c.get("hp", {})
            lines.append(f"  **{c['name']}** — {c.get('class','?')} ({sys_label}) HP:{hp.get('current','?')}/{hp.get('max','?')}")
        await i.response.send_message("\n".join(lines))
        return

    # --- sheet ---
    if action == "sheet":
        target = name or ""
        if not target:
            await i.response.send_message("Usage: `/character sheet <name>`", ephemeral=True); return
        char = char_module.get_character(target)
        if not char:
            await i.response.send_message(f"Character `{target}` not found.", ephemeral=True); return
        await i.response.send_message(char_module.format_sheet(char))
        return

    # --- delete ---
    if action == "delete":
        if not name or not password:
            await i.response.send_message("Usage: `/character delete <name> password:<pw>`", ephemeral=True); return
        ok, msg = char_module.delete_character(name, password)
        if ok:
            log.info("CHARACTER deleted name=%s by user=%s", name, i.user.name)
        else:
            log.warning("CHARACTER delete failed name=%s user=%s reason=%s", name, i.user.name, msg)
        await i.response.send_message(("✅ " if ok else "❌ ") + msg, ephemeral=True)
        return

    # --- hp ---
    if action == "hp":
        if not name or not password or not value:
            await i.response.send_message("Usage: `/character hp <name> value:<new_hp> password:<pw>`", ephemeral=True); return
        char = char_module.get_character(name)
        if not char:
            await i.response.send_message(f"Character `{name}` not found.", ephemeral=True); return
        if not char_module.verify_password(password, name, char["password_hash"]):
            await i.response.send_message("❌ Wrong password.", ephemeral=True); return
        try:
            new_hp = int(value)
        except ValueError:
            await i.response.send_message("HP must be a number.", ephemeral=True); return
        char["hp"]["current"] = new_hp
        char_module.save_character(char)
        log.info("CHARACTER hp updated name=%s hp=%d/%d user=%s", name, new_hp, char["hp"]["max"], i.user.name)
        await i.response.send_message(f"✅ **{name}** HP updated to {new_hp}/{char['hp']['max']}.", ephemeral=True)
        return

    # --- update ---
    if action == "update":
        if not name or not password:
            await i.response.send_message("Usage: `/character update <name> password:<pw>`", ephemeral=True); return
        char = char_module.get_character(name)
        if not char:
            await i.response.send_message(f"Character `{name}` not found.", ephemeral=True); return
        if not char_module.verify_password(password, name, char["password_hash"]):
            await i.response.send_message("❌ Wrong password.", ephemeral=True); return
        modal = UpdateModal(char)
        await i.response.send_modal(modal)
        return

    await i.response.send_message(
        "Unknown action. Try: `new` · `sheet` · `list` · `update` · `delete` · `hp`",
        ephemeral=True,
    )


class UpdateModal(discord.ui.Modal, title="Update Character"):
    equipment = discord.ui.TextInput(label="Gear (comma separated)", required=False, max_length=400)
    notes     = discord.ui.TextInput(label="Notes / Backstory", required=False, max_length=600, style=discord.TextStyle.paragraph)

    def __init__(self, char: dict):
        super().__init__()
        self._char = char
        self.equipment.default = ", ".join(char.get("equipment", []))
        self.notes.default = char.get("notes", "")

    async def on_submit(self, interaction: discord.Interaction):
        char = self._char
        char["equipment"] = [g.strip() for g in self.equipment.value.split(",") if g.strip()]
        char["notes"] = self.notes.value.strip()
        char_module.save_character(char)
        log.info("CHARACTER updated name=%s user=%s", char["name"], interaction.user.name)
        await interaction.response.send_message(
            f"✅ **{char['name']}** updated.\n\n{char_module.format_sheet(char)}",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client.run(_load_token(), log_handler=None)


if __name__ == "__main__":
    main()
