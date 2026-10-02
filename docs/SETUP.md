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

The bot runs as its own unprivileged system user, `remindlet`, which can touch
only its code (`/opt/remindlet`) and its home (`/var/lib/remindlet`). The clone
uses HTTPS: the server only ever pulls, and the repository is public, so no SSH
key is needed. (If the repository goes private, add a read-only deploy key.)

As root:

```sh
adduser --system --group --home /var/lib/remindlet remindlet
git clone https://github.com/alackles/remindlet.git /opt/remindlet
chown -R remindlet:remindlet /opt/remindlet
cd /opt/remindlet

sudo -u remindlet python3 -m venv .venv      # needs: apt install python3-venv
sudo -u remindlet .venv/bin/pip install -r requirements.txt
sudo -u remindlet cp .env.example .env && chmod 600 .env    # then fill in DISCORD_TOKEN and GUILD_ID

sed -e "s|__USER__|remindlet|" -e "s|__DIR__|/opt/remindlet|g" deploy/remindlet.service \
    > /etc/systemd/system/remindlet.service
systemctl daemon-reload
systemctl enable --now remindlet
```

The database (`remindlet.db`) is created in `/opt/remindlet` on first start.

Day to day (as root, from `/opt/remindlet`). Run git and pip as `remindlet`:
git refuses to work in a folder owned by another user.

| Task | Command |
|---|---|
| Follow the logs | `journalctl -u remindlet -f` |
| Recent logs | `journalctl -u remindlet --since "1 hour ago"` |
| Status | `systemctl status remindlet` |
| Restart | `systemctl restart remindlet` |
| Update | `sudo -u remindlet git pull && sudo -u remindlet .venv/bin/pip install -r requirements.txt && systemctl restart remindlet` |
| Back up the database | `sudo -u remindlet sqlite3 remindlet.db ".backup remindlet-backup.db"` (needs: `apt install sqlite3`) |
