# Security Policy

## Reporting a vulnerability

Please do not publish exploitable security details, bot tokens, personal information, database files or private chat exports in public issues. Contact the maintainer through the GitHub profile: https://github.com/OSTAD369.

## Credential handling

- Store `TELEGRAM_BOT_TOKEN` in the process environment or a private secret manager.
- Never commit `.env`, database files, logs or backups.
- If a token is exposed, revoke it immediately with Telegram's @BotFather and issue a new token.
- A token removed in a later commit may still exist in Git history; rotate it and clean repository history before making the repository public.

## Data handling

The bot may store identifiers, settings and inspection history in a local SQLite database. Treat this database as private operational data.
