# راهنمای انتشار در GitHub

این فایل برای صاحب پروژه است؛ لازم نیست داخل توضیحات عمومی صفحهٔ GitHub بماند.

## ۱) ساخت مخزن

1. وارد حساب https://github.com/OSTAD369 شوید.
2. روی **New repository** بزنید.
3. نام مخزن را دقیقاً `telegram-intelligence-bot` بگذارید.
4. توضیح کوتاه پیشنهادی:

   `A feature-rich Telegram bot for inspecting messages, users, chats, forwards, media and Bot API metadata — built with Python by OSTAD369.`

5. مخزن را Public انتخاب کنید.
6. گزینه‌های افزودن README، .gitignore و License را انتخاب نکنید؛ همهٔ این فایل‌ها از قبل داخل بسته هستند.
7. روی **Create repository** بزنید.

## ۲) بارگذاری فایل‌ها بدون Git

1. ZIP را روی کامپیوتر Extract کنید.
2. وارد مخزن تازه‌ساخته‌شده شوید.
3. **Add file → Upload files** را انتخاب کنید.
4. محتویات پوشهٔ `telegram-intelligence-bot-public` را (نه خود پوشهٔ بیرونی را) بکشید و داخل صفحه رها کنید.
5. پیام Commit پیشنهادی: `Initial public release — sanitized project by OSTAD369`
6. روی **Commit changes** بزنید.

## ۳) تنظیم About و Topics

در بخش About مخزن، توضیح بالا را وارد کنید و این Topics را اضافه کنید:

`telegram-bot` · `python` · `python-telegram-bot` · `telegram-api` · `sqlite` · `message-parser` · `telegram-tools` · `open-source`

## ۴) موارد مهم امنیتی

- فایل اصلی این نسخه دیگر توکن قبلی را ندارد و توکن را فقط از `TELEGRAM_BOT_TOKEN` می‌خواند.
- توکن قبلی که قبلاً در فایل اصلی وجود داشته، باید در @BotFather فوراً Revoke شود و یک توکن جدید ساخته شود؛ حذف آن از نسخهٔ فعلی، نسخه‌های قبلی یا تاریخچهٔ Git را امن نمی‌کند.
- فایل دیتابیس، فایل لاگ، `.env` واقعی و فایل `index.html` خراب قبلی عمداً در بسته قرار نگرفته‌اند.
- فایل `.env.example` نمونه و خالی است و نباید اطلاعات واقعی در آن قرار دهید.

## ۵) راه‌اندازی ربات پس از انتشار

در ویندوز PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="توکن جدید از BotFather"
$env:TELEGRAM_OWNER_ID="آیدی عددی مالک (اختیاری)"
python telegram_intelligence_bot.py
```

در صورت خالی گذاشتن `TELEGRAM_OWNER_ID`، قابلیت‌های مخصوص مالک به حساب شخصی خاصی متصل نمی‌شوند.
