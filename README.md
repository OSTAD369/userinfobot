# ⚡ Telegram Intelligence Bot

<p align="center">
  <strong>A feature-rich Telegram bot for inspecting messages, users, chats, forwards, media and Bot API metadata.</strong><br>
  <em>Built with Python · Async · python-telegram-bot · SQLite</em>
</p>

<p align="center">
  <a href="https://github.com/OSTAD369">GitHub: OSTAD369</a> ·
  <a href="https://t.me/ounen">Telegram: @ounen</a>
</p>

---

## ✨ About the project

**Telegram Intelligence Bot** is an ambitious, carefully assembled Python project created by **OSTAD369**. It brings a broad set of Telegram inspection and reporting tools into one interactive bot, with a Persian-first interface, inline menus, structured reports and local SQLite storage.

This is a hands-on project built around the Telegram Bot API and the `python-telegram-bot` framework. The goal is to make the information Telegram actually exposes to bots easier to inspect, understand and export — without pretending to access private data that Telegram does not provide.

> A lot of functionality, one codebase, and a serious focus on practical details. This is a showcase project by **OSTAD369**.

## 🚀 Features

- User and bot profile information available through the Telegram Bot API
- Chat, group and channel information, including available membership and administrator details
- Message inspection and reply analysis
- Forward-origin inspection, including correct handling of hidden forward senders
- Parsing of many message types: text, photo, video, animation, document, audio, voice, sticker, location, venue, contact, poll, dice, game, payments and service messages where supported by the installed Bot API library
- Message entities, captions, reply markup and available file metadata
- Profile-photo listing and optional temporary file processing
- Structured JSON output and paginated HTML-style Telegram reports
- Telegram link parsing and chat-ID format conversion helpers
- Jalali and Gregorian date formatting
- Inline keyboards, settings, local history and SQLite caching
- Logging with token redaction and an offline self-test suite

Feature availability depends on the message fields Telegram sends to the bot, the bot's permissions and the installed Bot API library version.

## 🧰 Tech stack

- Python 3.11+
- `python-telegram-bot` 22.x (async API)
- SQLite3 (Python standard library)
- Long polling

## 📦 Setup

### 1. Get the project

```bash
git clone https://github.com/OSTAD369/telegram-intelligence-bot.git
cd telegram-intelligence-bot
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

- Windows PowerShell: `.venv\Scripts\Activate.ps1`
- macOS / Linux: `source .venv/bin/activate`

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure credentials

Create a `.env` file from `.env.example`, then set the values in your shell. The project intentionally does not load `.env` automatically; export the variables before running it.

**Windows PowerShell:**

```powershell
$env:TELEGRAM_BOT_TOKEN="YOUR_NEW_BOT_TOKEN"
$env:TELEGRAM_OWNER_ID="YOUR_NUMERIC_TELEGRAM_USER_ID"  # optional
```

**macOS / Linux:**

```bash
export TELEGRAM_BOT_TOKEN="YOUR_NEW_BOT_TOKEN"
export TELEGRAM_OWNER_ID="YOUR_NUMERIC_TELEGRAM_USER_ID"  # optional
```

Create a bot with [@BotFather](https://t.me/BotFather) if you do not already have one. If `TELEGRAM_OWNER_ID` is left empty or set to `0`, owner-only features are not assigned to a personal account.

### 5. Start the bot

```bash
python telegram_intelligence_bot.py
```

## ⌨️ Commands

| Command | Purpose |
|---|---|
| `/start` | Start the bot and open the main menu |
| `/help` | Show the command guide |
| `/get` | Inspect a replied-to user, message or chat |
| `/id` | Show numeric IDs |
| `/info` | Generate a user report |
| `/user` | Look up a user by ID, username or reply (subject to API access) |
| `/chat` | Inspect a group or channel |
| `/forward` | Inspect a forwarded message's origin |
| `/reply` | Inspect the author of a replied-to message |
| `/photo` | View available profile photos |
| `/json` | Export structured JSON |
| `/version` | Show version information |
| `/menu` | Open the interactive menu |

The bot also includes interactive menu actions and additional owner-oriented commands/features when an owner ID is configured.

## 🔐 Privacy, security and Telegram API limits

- **Never commit your real bot token, `.env` file, database, logs or backups.**
- The bot can only inspect information Telegram makes available to it. It cannot reveal a user's phone number, IP address, email, password, contacts, private chats, account creation date or last-seen status unless Telegram explicitly provides relevant information through a supported interaction.
- Hidden forward senders remain hidden; the bot does not guess their identity.
- The bot's local SQLite database may contain user IDs, chat IDs, message metadata, settings and inspection history from your own bot usage. Keep it private and do not upload it to a public repository.
- Obtain appropriate consent and follow Telegram's terms and applicable privacy laws before collecting, storing or sharing data.

## 🧪 Self-test

The source includes an offline self-test that uses synthetic Telegram objects and a temporary database:

```bash
python telegram_intelligence_bot.py --selftest
```

It does not require a real bot token or connect to Telegram.

## 🗂 Repository contents

```text
telegram-intelligence-bot/
├── telegram_intelligence_bot.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── LICENSE
├── SECURITY.md
└── CONTRIBUTING.md
```

## 🤝 Contributing

Bug reports, reproducible issues, documentation improvements and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and never include credentials, personal data, private chat exports or database files in an issue or pull request.

## 📜 License

Released under the MIT License. See [LICENSE](LICENSE).

## 👨‍💻 Creator

**OSTAD369**  
GitHub: <https://github.com/OSTAD369>  
Telegram: [@ounen](https://t.me/ounen)

---

<p align="center"><strong>Crafted with Python, persistence and a love for building useful tools — OSTAD369.</strong></p>
