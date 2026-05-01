# ASCII Adventure — Discord Slash Command Bot

## Goal
A standalone Discord bot that serves ASCII art via `/` slash commands.
Wizards, dragons, knights, skulls, castles — all in glorious text art.

## Slash Commands

| Command | Description |
|---|---|
| `/wizard` | Summon a random wizard |
| `/dragon` | Unleash a dragon |
| `/knight` | Call forth a knight |
| `/skull` | Drop a skull |
| `/castle` | Build a castle |
| `/spell` | Cast a random magic spell effect |
| `/ascii <name>` | Look up art by name |
| `/ascii list` | Show all available pieces |
| `/ascii random` | Random piece from the full collection |

## Project Structure

```
/opt/ascii_adventure/
├── PLAN.md              ← this file
├── bot.py               ← main bot, registers slash commands
├── art/                 ← ASCII art library (.txt files, one per piece)
│   ├── wizard_1.txt
│   ├── wizard_2.txt
│   ├── dragon_1.txt
│   ├── dragon_2.txt
│   ├── knight_1.txt
│   ├── skull_1.txt
│   ├── castle_1.txt
│   └── spell_1.txt
├── requirements.txt
├── setup.sh
└── ascii-adventure.service  ← systemd user service
```

## Tech Stack
- Python 3.12
- discord.py 2.x with `app_commands` (slash commands)
- Art stored as plain .txt files — easy to add new ones
- Token loaded from `~/nanoclaw/.env` → `DISCORD_ASCII_BOT_TOKEN`
  (needs a second bot token, or can reuse `DISCORD_BOT_TOKEN` for testing)

## Implementation Steps
1. Write ASCII art library (8+ pieces across 5 categories)
2. Write `bot.py` with slash command handlers
3. Write `setup.sh` (venv + pip install)
4. Write systemd service file
5. Register commands with Discord (sync on startup)
6. Install + start service

## Art Format
Each .txt file is a fenced code block ready for Discord:
```
\`\`\`
  ASCII ART HERE
\`\`\`
```
Discord renders monospace inside ``` blocks — essential for ASCII art alignment.

## Notes
- Slash commands must be synced with Discord on first run (or after changes)
- Global sync takes up to 1 hour; guild-specific sync is instant
- Bot needs `applications.commands` scope in the OAuth invite URL
- Art pieces longer than 1900 chars get split across messages
