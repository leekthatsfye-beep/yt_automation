# SECURITY NOTICE — credential exposure, 2026-09-23

## What happened

`.jwt_secret` and `localhost.key` were committed to this **public** repository in
commit `580c4ef` (2026-09-13) and have been publicly readable since.

`.jwt_secret` is the **live HS256 signing key** for the FastAPI service in
`app/backend/` (`app/backend/auth.py::_get_secret`). The committed blob is byte-identical
to the file the running service reads, so the exposed value is the active one.

**Anyone holding it can mint a valid session token for any username in `users.json`**
without knowing a password. The service's routers include `youtube.py`, `render.py`,
`files.py` and `system.py`, so a forged token is full control of whatever that service
can reach — including the stored YouTube OAuth tokens.

`bot_watchdog.sh` contained a **hardcoded live Telegram bot token**, in `HEAD`, in a
public repository. A bot token is full control of the bot: read every message sent to
it and send messages as it. `telegram_bot.py` is the control surface for this entire
system -- renders, uploads, scheduling, channel management -- so this is not a
notification-only credential. The owner's Telegram chat ID was beside it.

This one was missed by a first, hand-written scan whose pattern was anchored to the
start of a line; the token sits mid-line inside a shell assignment. That is why
`scan_secrets.py` in the Media Engine exists and why it runs in CI.

`localhost.key` is a self-signed `CN=localhost` certificate key used by `ig_auth.py`
for the Instagram OAuth loopback. It cannot authenticate anything on the public
internet; exposure is low severity but it still does not belong here.

## Required action — ROTATION IS MANDATORY

**Rotating the JWT secret is the only remedy that actually works.** Removing the file
from git history does not undo ten days of public exposure: GitHub keeps unreachable
objects addressable by commit SHA until it garbage-collects, and automated scrapers
index public repositories continuously. Treat the value as compromised.

To rotate, on whatever host runs `app/backend`:

1. Stop the service.
2. Delete `.jwt_secret`, or set `FY3_JWT_SECRET` to a new value — `_get_secret()` reads
   the environment variable first and regenerates the file when it is absent.
3. Start the service. Every existing session token becomes invalid, which is the point.
4. Review `users.json` for accounts you do not recognise, and reset their passwords.
5. Because a forged token could have reached `youtube.py`, review the YouTube account's
   recent activity and **revoke and re-issue the OAuth tokens** in
   `token*.json` at https://myaccount.google.com/permissions.

**Revoke the Telegram bot token.** Message `@BotFather`, select the bot, then
`/revoke`. The old token stops working immediately and you get a new one. Supply it to
`bot_watchdog.sh` through `TELEGRAM_BOT_TOKEN` -- the script now refuses to start
without it rather than silently sending nothing. Review the bot's recent activity
while you are there.

Regenerate `localhost.key` / `localhost.crt` at the same time. It is a one-line
`openssl req` and costs nothing.

## History

The files are removed from `HEAD` as of this commit, and `.gitignore` now covers all
key material. **They remain in the history of commit `580c4ef` and earlier.** Purging
them needs a history rewrite, which rewrites every commit hash and requires a
force-push:

    pip install git-filter-repo
    git filter-repo --force --invert-paths --path .jwt_secret --path localhost.key
    # bot_watchdog.sh must be kept, so its token is replaced rather than the file dropped:
    # git filter-repo --replace-text <(echo 'regex:[0-9]{8,10}:AA[A-Za-z0-9_-]{33}==>REDACTED')
    git remote add origin https://github.com/leekthatsfye-beep/yt_automation.git
    git push --force --all && git push --force --tags

This repository has 0 forks, 0 stars and 0 watchers, so the collateral is limited to
your own clones, which must be re-cloned afterwards. Afterwards, ask GitHub Support to
garbage-collect the repository so the old commit SHAs stop resolving.

**Do this after rotating, not instead of it.**
