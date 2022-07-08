# Discord.py bot template

[![Will it lint?](https://github.com/Brettanda/goal-tracker-discord-bot/actions/workflows/push.yml/badge.svg?branch=main)](https://github.com/Brettanda/goal-tracker-discord-bot/actions/workflows/push.yml)
[![Crowdin](https://badges.crowdin.net/goal-tracker-discord-bot/localized.svg)](https://crowdin.com/project/goal-tracker-discord-bot)

Supports Python 3.8 and up

A template for discord.py v2.0 bots with cogs.

## Running

1. Add your bot token to the `config.py` file

```python
token = 'YOUR_TOKEN_HERE'
default_prefix = 'gt!'
postgresql = 'postgresql://user:password@host/database'
bot_stat_webhook = ('[webhook_id]', '[webhook_token]')
dev_server = 1234567891324568
```

2. Setup venv

```bash
python3.8 -m venv venv
```

3. Install the pip dependencies

```bash
pip install -r requirements.txt
```