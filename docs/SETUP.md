# Setup

How to run remindlet locally and deploy it on a Linux server. For what the bot
does, see [SPEC.md](SPEC.md).

## Discord setup

1. Create an application and bot user in the Discord Developer Portal.
2. Under **Bot → Privileged Gateway Intents**, turn on **Server Members Intent**.
3. Invite the bot with the `bot` and `applications.commands` scopes and the
   Send Messages, Embed Links, and Read Message History permissions.

## Local development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # then fill in DISCORD_TOKEN and GUILD_ID
.venv/bin/python bot.py
.venv/bin/pytest
```

Only one copy of the bot should run per token: two copies would both fire every
reminder. Stop the local bot before starting the server one.

## Deploying on a Linux server (systemd)

From the clone's directory, as the account that should run the bot:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env    # then fill in DISCORD_TOKEN and GUILD_ID

sed -e "s|__USER__|$USER|" -e "s|__DIR__|$PWD|g" deploy/remindlet.service \
    | sudo tee /etc/systemd/system/remindlet.service
sudo systemctl daemon-reload
sudo systemctl enable --now remindlet
```

The database (`remindlet.db`) is created next to `config.py` on first start.

Day to day:

| Task | Command |
|---|---|
| Follow the logs | `journalctl -u remindlet -f` |
| Recent logs | `journalctl -u remindlet --since "1 hour ago"` |
| Status | `systemctl status remindlet` |
| Restart | `sudo systemctl restart remindlet` |
| Update | `git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart remindlet` |
| Back up the database | `sqlite3 remindlet.db ".backup remindlet-backup.db"` |
