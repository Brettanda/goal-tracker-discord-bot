# Goal Tracker

[![Will it lint?](https://github.com/Brettanda/goal-tracker-discord-bot/actions/workflows/push.yml/badge.svg?branch=main)](https://github.com/Brettanda/goal-tracker-discord-bot/actions/workflows/push.yml)
[![Crowdin](https://badges.crowdin.net/goal-tracker-discord-bot/localized.svg)](https://crowdin.com/project/goal-tracker-discord-bot)
[![Discord Server](https://img.shields.io/discord/991443052625412116?label=discord)](https://discord.gg/PSgfZ5MzTg)
[![Vote](https://img.shields.io/badge/Vote-Goal%20Tracker-blue)](https://top.gg/bot/990139482273628251/vote)
[![Add Goal Tracker to your server](https://img.shields.io/badge/Invite-to%20your%20server-green)](https://discord.com/api/oauth2/authorize?client_id=990139482273628251&permissions=18432&scope=bot+applications.commands)
[![GitHub license](https://img.shields.io/github/license/Brettanda/goal-tracker-discord-bot)](https://github.com/Brettanda/goal-tracker-discord-bot/blob/main/LICENSE)

Supports Python 3.8 and up

I would prefer if you didn't run your own instance of this bot, and instead just inviting it. This repo is for educational purposes only.

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