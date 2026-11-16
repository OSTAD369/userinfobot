#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 TELEGRAM INTELLIGENCE BOT  —  ربات اطلاعات و بازرسی پیشرفته تلگرام
=====================================================================

Runtime   : Python 3.11+
Framework : python-telegram-bot v22.x  (async / long polling)
Database  : SQLite3 (standard library)

این ربات تمام اطلاعاتی را که Telegram Bot API به‌صورت قانونی در اختیار
ربات‌ها قرار می‌دهد (کاربر، ربات، فوروارد، ریپلای، گروه، کانال، فایل،
مدیا، لوکیشن، مخاطب و ...) استخراج و با رابط شیشه‌ای (Inline) نمایش می‌دهد.

نکته‌ی امنیتی بسیار مهم:
    توکن و شناسه‌ی مالک فقط از متغیرهای محیطی خوانده می‌شوند.
    هیچ راز یا شناسه‌ی شخصی در این نسخه‌ی عمومی ذخیره نشده است.

ساختار فایل (بخش‌ها):
    01  Imports & Configuration
    02  Constants & Labels
    03  Logging (با حذف خودکار توکن از لاگ‌ها)
    04  Persian Texts
    05  Utilities (formatters, dates, Jalali, report builder, caches)
    06  Database layer
    07  User information engine
    08  Chat information engine
    09  Forward intelligence engine
    10  Message type parsers
    11  Message / Reply report builders & JSON engine
    12  Extra tools (file-id decoder, link parser, id converter)
    13  Keyboards & message sending helpers
    14  Profile photo engine
    15  Handlers: commands
    16  Handlers: callbacks (menus, settings, history, ...)
    17  Chat selector flow (KeyboardButtonRequestChat)
    18  Owner panel, chat-member tracking, error handler
    19  Registration, main(), self-test
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import html
import io
import json
import logging
import logging.handlers
import mimetypes
import os
import re
import secrets
import sqlite3
import struct
import sys
import tempfile
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

import telegram
from telegram import (
    BotCommand,
    Chat,
    ChatAdministratorRights,
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    KeyboardButtonRequestChat,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    User,
)
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

# اشیای زیر در نسخه‌های جدیدتر PTB اضافه شده‌اند؛ برای سازگاری امن import می‌شوند.
CopyTextButton = getattr(telegram, "CopyTextButton", None)
KeyboardButtonRequestUsers = getattr(telegram, "KeyboardButtonRequestUsers", None)
ReplyParameters = getattr(telegram, "ReplyParameters", None)

# =========================================================
#                  BOT CONFIGURATION
# =========================================================

# Secrets and owner identity are supplied at runtime; never commit them.
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
try:
    OWNER_ID = int(os.environ.get("TELEGRAM_OWNER_ID", "0").strip() or "0")
except ValueError as exc:
    raise ValueError("TELEGRAM_OWNER_ID must be an integer Telegram user ID") from exc

BOT_VERSION = "1.0.0"
VERSION_DATE = "2026-11-13"

BOT_NAME = "TELEGRAM INTELLIGENCE BOT"

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "telegram_intelligence.db"
)

# =========================================================
#                  02 — CONSTANTS & LABELS
# =========================================================

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_intelligence.log")

UNAVAILABLE = "از طریق Telegram Bot API قابل دریافت نیست."
NOT_SENT = "توسط تلگرام ارسال نشده است."
SEP = "━━━━━━━━━━━━━━━━━━"

TG_TEXT_LIMIT = 4096
PAGE_LIMIT = 3600                      # حداکثر طول هر صفحه‌ی گزارش
MAX_VALUE_LEN = 900                    # حداکثر طول یک مقدار در گزارش
TEMP_MAX_BYTES = 8 * 1024 * 1024       # سقف دانلود فایل‌های موقت (۸ مگابایت)
CAPTION_LIMIT = 1000
MAX_ADMINS_SHOWN = 25
MAX_ENTITIES_SHOWN = 20
HISTORY_PAGE_SIZE = 6
CHATS_PAGE_SIZE = 6
MAX_HISTORY_PER_USER = 300
HISTORY_KEEP_DAYS = 90

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

# datetime.weekday(): Monday = 0
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

CHAT_TYPE_LABELS = {
    "private": "گفتگوی خصوصی (کاربر/ربات)",
    "group": "گروه معمولی",
    "supergroup": "سوپرگروه",
    "channel": "کانال",
    "sender": "فرستنده (Sender)",
}

MEMBER_STATUS_LABELS = {
    "creator": "👑 مالک (Creator)",
    "administrator": "🛡 ادمین (Administrator)",
    "member": "👤 عضو عادی",
    "restricted": "⛔ عضو محدودشده",
    "left": "🚪 ترک‌کرده / عضو نیست",
    "kicked": "🚫 مسدودشده (Banned)",
}

ADMIN_RIGHTS_LABELS: list[tuple[str, str]] = [
    ("is_anonymous", "حالت ناشناس"),
    ("can_manage_chat", "مدیریت چت"),
    ("can_delete_messages", "حذف پیام‌ها"),
    ("can_manage_video_chats", "مدیریت ویدیوچت"),
    ("can_restrict_members", "محدود/مسدودکردن اعضا"),
    ("can_promote_members", "افزودن ادمین"),
    ("can_change_info", "تغییر اطلاعات چت"),
    ("can_invite_users", "دعوت کاربران"),
    ("can_post_stories", "انتشار استوری"),
    ("can_edit_stories", "ویرایش استوری"),
    ("can_delete_stories", "حذف استوری"),
    ("can_post_messages", "ارسال پیام در کانال"),
    ("can_edit_messages", "ویرایش پیام‌های کانال"),
    ("can_pin_messages", "پین‌کردن پیام"),
    ("can_manage_topics", "مدیریت تاپیک‌ها"),
    ("can_manage_direct_messages", "مدیریت پیام‌های مستقیم"),
]

PERMISSION_LABELS: list[tuple[str, str]] = [
    ("can_send_messages", "ارسال پیام متنی"),
    ("can_send_audios", "ارسال آهنگ"),
    ("can_send_documents", "ارسال فایل"),
    ("can_send_photos", "ارسال عکس"),
    ("can_send_videos", "ارسال ویدیو"),
    ("can_send_video_notes", "ارسال ویدیو پیام"),
    ("can_send_voice_notes", "ارسال ویس"),
    ("can_send_polls", "ارسال نظرسنجی"),
    ("can_send_other_messages", "ارسال استیکر/گیف/بازی/اینلاین"),
    ("can_add_web_page_previews", "پیش‌نمایش لینک"),
    ("can_change_info", "تغییر اطلاعات گروه"),
    ("can_invite_users", "دعوت کاربران"),
    ("can_pin_messages", "پین‌کردن پیام"),
    ("can_manage_topics", "مدیریت تاپیک‌ها"),
]

# شناسه‌ی حساب‌های سیستمی و شناخته‌شده‌ی تلگرام
WELL_KNOWN_IDS = {
    777000: "حساب رسمی تلگرام (Telegram Service Notifications)",
    1087968824: "GroupAnonymousBot — نماینده‌ی ادمین‌های ناشناس گروه",
    136817688: "Channel_Bot — نماینده‌ی کانال‌ها در پیام‌های قدیمی",
    1271266957: "@replies — ربات داخلی پاسخ‌های کانال",
    93372553: "BotFather — ربات رسمی ساخت ربات",
}

# نوع فایل در File ID (طبق ساختار داخلی تلگرام؛ تحلیل Best-Effort)
FILE_ID_TYPES = {
    0: "Thumbnail (بندانگشتی)",
    1: "Profile Photo (تصویر پروفایل)",
    2: "Photo (عکس)",
    3: "Voice (ویس)",
    4: "Video (ویدیو)",
    5: "Document (فایل)",
    6: "Encrypted",
    7: "Temp",
    8: "Sticker (استیکر)",
    9: "Audio (آهنگ)",
    10: "Animation (گیف)",
    11: "Encrypted Thumbnail",
    12: "Wallpaper",
    13: "Video Note (ویدیو پیام)",
    14: "Secure Raw",
    15: "Secure",
    16: "Background",
    17: "Size",
}

# نگاشت نوع پیام -> (ایموجی، برچسب فارسی)
MESSAGE_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "text": ("💬", "متن"),
    "photo": ("🖼", "عکس"),
    "video": ("🎬", "ویدیو"),
    "animation": ("🎞", "انیمیشن / گیف"),
    "document": ("📄", "فایل (Document)"),
    "audio": ("🎵", "آهنگ (Audio)"),
    "voice": ("🎙", "پیام صوتی (Voice)"),
    "video_note": ("⭕", "ویدیو پیام (Video Note)"),
    "sticker": ("🧩", "استیکر"),
    "location": ("📍", "لوکیشن"),
    "venue": ("🏢", "مکان (Venue)"),
    "contact": ("📇", "مخاطب"),
    "poll": ("📊", "نظرسنجی"),
    "dice": ("🎲", "تاس / بازی‌ایموجی"),
    "game": ("🎮", "بازی (Game)"),
    "web_app_data": ("🕸", "داده‌ی وب‌اپ"),
    "users_shared": ("👥", "کاربران اشتراکی (Users Shared)"),
    "user_shared": ("👤", "کاربر اشتراکی (Legacy)"),
    "chat_shared": ("🏛", "چت اشتراکی (Chat Shared)"),
    "invoice": ("🧾", "فاکتور (Invoice)"),
    "successful_payment": ("💳", "پرداخت موفق"),
    "refunded_payment": ("↩️", "بازگشت وجه"),
    "passport_data": ("🛂", "اطلاعات Passport"),
    "paid_media": ("⭐", "رسانه‌ی پولی"),
    "story": ("📖", "استوری"),
    "giveaway": ("🎁", "قرعه‌کشی"),
    "giveaway_created": ("🎁", "ایجاد قرعه‌کشی"),
    "giveaway_winners": ("🏆", "برندگان قرعه‌کشی"),
    "giveaway_completed": ("🏁", "پایان قرعه‌کشی"),
    "checklist": ("✅", "چک‌لیست"),
    "gift": ("🎀", "هدیه"),
    "unique_gift": ("💎", "هدیه‌ی یکتا"),
    "new_chat_members": ("➕", "ورود عضو جدید"),
    "left_chat_member": ("➖", "خروج عضو"),
    "new_chat_title": ("✏️", "تغییر نام چت"),
    "new_chat_photo": ("🖼", "تغییر عکس چت"),
    "delete_chat_photo": ("🗑", "حذف عکس چت"),
    "group_chat_created": ("🆕", "ساخت گروه"),
    "supergroup_chat_created": ("🆕", "ساخت سوپرگروه"),
    "channel_chat_created": ("🆕", "ساخت کانال"),
    "message_auto_delete_timer_changed": ("⏳", "تغییر تایمر حذف خودکار"),
    "migrate_to_chat_id": ("🔀", "ارتقا به سوپرگروه"),
    "migrate_from_chat_id": ("🔀", "مهاجرت از گروه قدیمی"),
    "pinned_message": ("📌", "پین‌شدن پیام"),
    "forum_topic_created": ("🧵", "ساخت تاپیک"),
    "forum_topic_edited": ("🧵", "ویرایش تاپیک"),
    "forum_topic_closed": ("🔒", "بسته‌شدن تاپیک"),
    "forum_topic_reopened": ("🔓", "بازشدن تاپیک"),
    "general_forum_topic_hidden": ("🙈", "مخفی‌شدن تاپیک General"),
    "general_forum_topic_unhidden": ("👁", "آشکارشدن تاپیک General"),
    "write_access_allowed": ("✍️", "اجازه‌ی نوشتن"),
    "proximity_alert_triggered": ("📡", "هشدار مجاورت"),
    "video_chat_scheduled": ("🗓", "ویدیوچت زمان‌بندی‌شده"),
    "video_chat_started": ("📹", "شروع ویدیوچت"),
    "video_chat_ended": ("📴", "پایان ویدیوچت"),
    "video_chat_participants_invited": ("📨", "دعوت به ویدیوچت"),
    "boost_added": ("🚀", "افزودن بوست"),
    "chat_background_set": ("🎨", "تغییر پس‌زمینه‌ی چت"),
    "connected_website": ("🌐", "وب‌سایت متصل"),
}

# پیام‌های سرویس (برای دسته‌بندی در گزارش)
SERVICE_TYPES = {
    "new_chat_members", "left_chat_member", "new_chat_title", "new_chat_photo",
    "delete_chat_photo", "group_chat_created", "supergroup_chat_created",
    "channel_chat_created", "message_auto_delete_timer_changed", "migrate_to_chat_id",
    "migrate_from_chat_id", "pinned_message", "forum_topic_created", "forum_topic_edited",
    "forum_topic_closed", "forum_topic_reopened", "general_forum_topic_hidden",
    "general_forum_topic_unhidden", "write_access_allowed", "proximity_alert_triggered",
    "video_chat_scheduled", "video_chat_started", "video_chat_ended",
    "video_chat_participants_invited", "boost_added", "chat_background_set",
}

# قوانین نمایش مقدار تاس
DICE_RULES = {
    "🎲": (1, 6, "تاس"),
    "🎯": (1, 6, "دارت (۶ = مرکز)"),
    "🏀": (1, 5, "بسکتبال (۴ و ۵ = گل)"),
    "⚽": (1, 5, "فوتبال (۳ تا ۵ = گل)"),
    "🎳": (1, 6, "بولینگ (۶ = استرایک)"),
    "🎰": (1, 64, "اسلات‌ماشین (۶۴ = جکپات ۷-۷-۷)"),
}
SLOT_SYMBOLS = ["BAR", "🍇", "🍋", "7️⃣"]

# شناسه‌ی درخواست‌ها (request_id) برای KeyboardButtonRequestChat / Users
RQ_CH_CREATED = 101
RQ_GR_CREATED = 102
RQ_FORUM_CREATED = 103
RQ_CH_ADMIN = 104
RQ_GR_ADMIN = 105
RQ_CH_BOT_MEMBER = 106
RQ_GR_BOT_MEMBER = 107
RQ_GR_PUBLIC_CREATED = 108
RQ_CH_ADD_BOT = 109
RQ_GR_ADD_BOT = 110
RQ_USER_ANY = 201
RQ_USER_BOT = 202
RQ_USER_PREMIUM = 203

# request_id -> (کلید نوع، برچسب فارسی، آیا فیلتر «ساخته‌شده توسط من» دارد)
CHAT_REQUESTS: dict[int, tuple[str, str, bool]] = {
    RQ_CH_CREATED: ("channel_created", "کانال ساخته‌شده توسط شما", True),
    RQ_GR_CREATED: ("group_created", "گروه/سوپرگروه ساخته‌شده توسط شما", True),
    RQ_FORUM_CREATED: ("forum_created", "گروه تاپیک‌دار ساخته‌شده توسط شما", True),
    RQ_CH_ADMIN: ("channel_admin", "کانال با دسترسی ادمین شما", False),
    RQ_GR_ADMIN: ("group_admin", "گروه با دسترسی ادمین شما", False),
    RQ_CH_BOT_MEMBER: ("channel_bot_member", "کانالی که ربات عضو آن است", False),
    RQ_GR_BOT_MEMBER: ("group_bot_member", "گروهی که ربات عضو آن است", False),
    RQ_GR_PUBLIC_CREATED: ("group_public_created", "گروه عمومی ساخته‌شده توسط شما", True),
    RQ_CH_ADD_BOT: ("channel_add_bot", "کانال ساخته‌شده (با افزودن ربات به‌عنوان ادمین)", True),
    RQ_GR_ADD_BOT: ("group_add_bot", "گروه ساخته‌شده (با افزودن ربات به‌عنوان ادمین)", True),
}

# توضیح محدودیت‌های Bot API (برای نمایش در گزارش‌ها)
API_LIMITS_TEXT = (
    "شماره تلفن، تاریخ ساخت حساب، آخرین بازدید، آی‌پی، ایمیل، مخاطبین خصوصی، "
    "و فهرست همه‌ی گروه‌ها/کانال‌های یک کاربر از طریق Telegram Bot API قابل دریافت نیست."
)

MAIN_BUTTONS = {
    "me": "👤 اطلاعات حساب من",
    "inspect": "🔎 بررسی پیام",
    "chats": "🏛 گروه‌ها و کانال‌های من",
    "photos": "📷 تصاویر پروفایل",
    "help": "📚 راهنمای دستورات",
    "settings": "⚙️ تنظیمات",
}

BACK_BUTTON_TEXT = "🔙 بازگشت به منوی اصلی"

# دستورهای ثبت‌شده در منوی تلگرام
BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "شروع و منوی اصلی"),
    ("help", "راهنمای کامل"),
    ("get", "اطلاعات کاربر/پیام/چت (ریپلای کنید)"),
    ("id", "نمایش آیدی‌های عددی"),
    ("info", "گزارش کامل کاربر"),
    ("user", "اطلاعات کاربر با آیدی یا ریپلای"),
    ("chat", "اطلاعات گروه یا کانال"),
    ("forward", "تحلیل پیام فوروارد‌شده"),
    ("reply", "تحلیل نویسنده‌ی پیام ریپلای‌شده"),
    ("photo", "تصاویر پروفایل"),
    ("json", "خروجی JSON ساختاریافته"),
    ("version", "نسخه‌ی ربات"),
    ("menu", "منوی شیشه‌ای"),
]

# =========================================================
#                  03 — LOGGING
# =========================================================

TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")


class RedactingFormatter(logging.Formatter):
    """فرمتر لاگ که توکن ربات را هرگز در خروجی نمی‌نویسد."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        try:
            if TOKEN and len(TOKEN) > 10 and TOKEN in text:
                text = text.replace(TOKEN, "<TOKEN-REDACTED>")
        except Exception:  # pragma: no cover
            pass
        return TOKEN_PATTERN.sub("<TOKEN-REDACTED>", text)


def setup_logging() -> logging.Logger:
    fmt = RedactingFormatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):
        root.removeHandler(existing)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        root.warning("امکان ساخت فایل لاگ وجود ندارد؛ فقط خروجی کنسول فعال است.")

    # کتابخانه‌ی httpx آدرس‌های حاوی توکن را در سطح INFO لاگ می‌کند.
    for noisy in ("httpx", "httpcore", "telegram.ext.Application", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("tg-intel")


log = setup_logging()

# =========================================================
#                  04 — PERSIAN TEXTS
# =========================================================

WELCOME_TEXT = (
    "سلام عزیزم 🩵\n\n"
    "من یک ابزار پیشرفته برای بررسی اطلاعات قابل‌دسترسی تلگرام هستم.\n\n"
    "می‌توانی هر نوع پیام، فایل، تصویر، فوروارد، مخاطب، لوکیشن یا پیام ریپلای‌شده را برای من ارسال کنی "
    "تا اطلاعات قابل‌دریافت آن را بررسی کنم.\n\n"
    "با دستور /get اطلاعات کاربر یا گروه را مشاهده کن.\n\n"
    "👇 برای ادامه از دکمه‌های شیشه‌ای زیر استفاده کن."
)

ABOUT_TEXT = (
    "🧠 <b>{name}</b>\n"
    f"{SEP}\n\n"
    "🔖 <b>نسخه:</b> <code>{version}</code>\n"
    "📅 <b>تاریخ انتشار:</b> <code>{date}</code>\n"
    "🐍 <b>پایتون:</b> <code>{python}</code>\n"
    "📦 <b>python-telegram-bot:</b> <code>{ptb}</code>\n"
    "⏱ <b>زمان فعالیت:</b> <code>{uptime}</code>\n\n"
    "این ربات فقط اطلاعاتی را نشان می‌دهد که Telegram Bot API رسماً در اختیار ربات‌ها قرار می‌دهد. "
    "هیچ دور زدن حریم خصوصی، حدس یا جعل اطلاعات در آن وجود ندارد.\n\n"
    "🔒 هیچ فایلی روی سرویس‌های خارجی بارگذاری نمی‌شود و فایل‌های موقت پس از پردازش پاک می‌شوند."
)

HELP_TOPICS: dict[str, tuple[str, str]] = {
    "start": (
        "🚀 شروع سریع",
        "🚀 <b>شروع سریع</b>\n" + SEP + "\n\n"
        "۱️⃣ هر پیام، فایل، عکس، استیکر، لوکیشن، مخاطب یا فوروارد را برای من بفرست؛ "
        "گزارش کامل همان لحظه ساخته می‌شود.\n\n"
        "۲️⃣ در گروه‌ها روی یک پیام ریپلای کن و /get یا /id بزن.\n\n"
        "۳️⃣ از منوی «🏛 گروه‌ها و کانال‌های من» چت‌های ساخته‌شده‌ی خودت را با انتخابگر "
        "رسمی تلگرام انتخاب کن.\n\n"
        "۴️⃣ همه‌ی بخش‌ها دکمه‌ی شیشه‌ای دارند؛ نیازی به حفظ‌کردن دستور نیست."
    ),
    "inspect": (
        "🔎 بررسی پیام",
        "🔎 <b>بررسی پیام</b>\n" + SEP + "\n\n"
        "📨 در گفتگوی خصوصی هر پیامی بفرستی (یا فوروارد کنی) تحلیل می‌شود:\n"
        "• نوع پیام و تمام فیلدهای قابل‌دریافت\n"
        "• اطلاعات فرستنده و منبع اصلی فوروارد\n"
        "• File ID و File Unique ID فایل‌ها\n"
        "• اندازه، ابعاد، مدت، MIME و ...\n"
        "• Entityها، لینک‌ها و منشن‌ها\n\n"
        "⚠️ اگر منبع فوروارد «مخفی» باشد، تلگرام فقط یک نام نمایشی می‌دهد "
        "و آیدی/یوزرنیم واقعی هرگز قابل دریافت نیست."
    ),
    "get": (
        "🧭 دستور /get و /id",
        "🧭 <b>دستورهای /get و /id</b>\n" + SEP + "\n\n"
        "• <code>/get</code> بدون ریپلای: اطلاعات خودت (در گروه: اطلاعات گروه + خودت)\n"
        "• <code>/get</code> روی یک پیام: بررسی کامل همان پیام، فرستنده، فوروارد و مدیا\n"
        "• <code>/id</code> در گروه: آیدی عددی گروه + آیدی تو + اطلاعات گروه\n"
        "• <code>/id</code> روی ریپلای: آیدی پیام، فرستنده و منبع فوروارد\n"
        "• <code>/user 123456</code> یا <code>/user @name</code>: اطلاعات کاربر\n"
        "• <code>/chat -100123...</code> یا <code>/chat @name</code>: اطلاعات چت\n\n"
        "🆔 همیشه بین <b>آیدی کاربر</b>، <b>آیدی چت</b> و <b>آیدی پیام</b> تمایز قائل می‌شوم."
    ),
    "chats": (
        "🏛 گروه‌ها و کانال‌ها",
        "🏛 <b>گروه‌ها و کانال‌های من</b>\n" + SEP + "\n\n"
        "تلگرام هیچ متدی برای فهرست‌کردن خودکار تمام گروه‌ها/کانال‌های یک کاربر ندارد، "
        "پس انتخاب باید توسط خودت و با انتخابگر رسمی تلگرام انجام شود.\n\n"
        "✅ ربات با <code>chat_is_created</code> فقط چت‌های <b>ساخته‌شده توسط تو</b> را پیشنهاد می‌دهد.\n"
        "🔍 سپس با <code>getChat</code> و <code>getChatMember</code> اطلاعات و وضعیت مالکیت بررسی می‌شود.\n"
        "💾 نتیجه در پایگاه‌داده‌ی محلی ذخیره می‌شود تا بعداً دوباره ببینی.\n\n"
        "🔎 «ساخته‌شده توسط من» با «ادمین هستم» فرق دارد؛ این تفاوت در گزارش‌ها مشخص می‌شود."
    ),
    "photos": (
        "📷 تصاویر پروفایل",
        "📷 <b>تصاویر پروفایل</b>\n" + SEP + "\n\n"
        "با <code>getUserProfilePhotos</code> تعداد و اندازه‌ی عکس‌های پروفایل قابل‌دسترسی خوانده می‌شود.\n"
        "• ارسال عکس با خود سیستم فایل تلگرام (بدون هیچ سرویس خارجی)\n"
        "• دانلود موقت به‌صورت فایل اصلی + هش SHA-256\n"
        "• ارسال آلبوم تا ۱۰ عکس\n\n"
        "🔒 اگر کاربر عکس پروفایلش را از دید عموم پنهان کرده باشد، تلگرام آن را به ربات نمی‌دهد."
    ),
    "forward": (
        "↪️ فوروارد و ریپلای",
        "↪️ <b>هوش فوروارد</b>\n" + SEP + "\n\n"
        "از <code>forward_origin</code> مدرن استفاده می‌شود:\n"
        "• <b>MessageOriginUser</b>: آیدی، نام، یوزرنیم و ...\n"
        "• <b>MessageOriginHiddenUser</b>: فقط نام نمایشی؛ ❌ آیدی نامشخص\n"
        "• <b>MessageOriginChat</b>: چتی که به‌نام خودش پیام فرستاده\n"
        "• <b>MessageOriginChannel</b>: آیدی کانال + آیدی پیام اصلی\n\n"
        "ربات هرگز هویت فرستنده‌ی مخفی را حدس نمی‌زند."
    ),
    "tools": (
        "🧰 ابزارها",
        "🧰 <b>ابزارهای جانبی</b>\n" + SEP + "\n\n"
        "• 🔍 جستجوی کاربر/چت با آیدی عددی یا یوزرنیم\n"
        "• 🔢 تبدیل آیدی چت (فرمت Bot API ↔ فرمت کوتاه)\n"
        "• 🔗 تحلیل لینک‌های t.me\n"
        "• 🧬 رمزگشایی File ID (نوع فایل و دیتاسنتر)\n"
        "• 🕒 ساعت و تاریخ شمسی/میلادی\n\n"
        "همه‌ی ابزارها محلی کار می‌کنند و از هیچ API خارجی استفاده نمی‌کنند."
    ),
    "limits": (
        "⚠️ محدودیت‌های Bot API",
        "⚠️ <b>چه چیزهایی قابل دریافت نیست؟</b>\n" + SEP + "\n\n"
        "❌ شماره تلفن (مگر خود کاربر مخاطب را به اشتراک بگذارد)\n"
        "❌ تاریخ ساخت حساب\n"
        "❌ آخرین بازدید / وضعیت آنلاین\n"
        "❌ آی‌پی، ایمیل، رمز و جزئیات مخفی پروفایل\n"
        "❌ فهرست مخاطبین و چت‌های خصوصی\n"
        "❌ هویت فرستنده‌ی فوروارد مخفی\n"
        "❌ فهرست تمام گروه‌ها/کانال‌های یک کاربر\n"
        "❌ اطلاعات چت‌هایی که ربات به آن‌ها دسترسی ندارد\n\n"
        "ربات هیچ‌کدام از موارد بالا را جعل یا حدس نمی‌زند."
    ),
}

SELECTOR_INTRO = (
    "🏛 <b>گروه‌ها و کانال‌های ساخته‌شده توسط من</b>\n" + SEP + "\n\n"
    "یکی از دکمه‌های پایین صفحه را بزن؛ تلگرام فهرست رسمی چت‌ها را باز می‌کند و "
    "فقط چتی را که انتخاب کنی برای ربات ارسال می‌شود.\n\n"
    "ℹ️ تلگرام اجازه‌ی اسکن کل حساب را به ربات نمی‌دهد؛ ربات هرگز ادعای اسکن حساب شما را ندارد.\n"
    "🔐 «ساخته‌شده توسط شما» با «ادمین بودن» تفاوت دارد و این تفاوت در گزارش مشخص می‌شود.\n\n"
    "پس از انتخاب، گزارش کامل و ذخیره‌ی خودکار انجام می‌شود."
)

# =========================================================
#                  05 — UTILITIES
# =========================================================

START_TIME = time.time()


def esc(value: Any) -> str:
    """Escape any value for safe use inside Telegram HTML."""
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def code(value: Any) -> str:
    return f"<code>{esc(value)}</code>"


def bold(value: Any) -> str:
    return f"<b>{esc(value)}</b>"


def italic(value: Any) -> str:
    return f"<i>{esc(value)}</i>"


def html_link(text: Any, url: str) -> str:
    return f'<a href="{html.escape(str(url), quote=True)}">{esc(text)}</a>'


def trunc(value: Any, limit: int = MAX_VALUE_LEN) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"


def one_line(value: Any, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    return trunc(text, limit)


def to_int(value: Any) -> int:
    """Strict integer parsing used for callback data and user input."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    if not re.fullmatch(r"-?\d{1,20}", text):
        raise ValueError("invalid integer")
    return int(text)


def fmt_bool(value: Optional[bool], omit_false: bool = False) -> str:
    """Three-state boolean rendering: True / False / missing."""
    if value is True:
        return "✅ بله"
    if value is False:
        return "❌ خیر"
    if omit_false:
        return "⚪ ارسال نشده (در Bot API معمولاً یعنی «خیر» یا نامشخص)"
    return "⚪ " + UNAVAILABLE


def fmt_size(num: Optional[int]) -> str:
    if num is None:
        return UNAVAILABLE
    size = float(num)
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت"):
        if size < 1024 or unit == "گیگابایت":
            if unit == "بایت":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{num} بایت"


def fmt_duration(value: Any) -> str:
    if value is None:
        return UNAVAILABLE
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
    else:
        total = int(value)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d} ({total} ثانیه)"
    return f"{minutes:02d}:{seconds:02d} ({total} ثانیه)"


def fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes:
        parts.append(f"{minutes} دقیقه")
    parts.append(f"{secs} ثانیه")
    return " و ".join(parts)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().strftime("%Y-%m-%d %H:%M:%S")


def parse_iso(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------
#   Jalali (Persian) calendar conversion — pure Python
# ---------------------------------------------------------

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to Jalali (Solar Hijri)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def to_jalali_text(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(TEHRAN_TZ)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    weekday = WEEKDAYS_FA[local.weekday()]
    return f"{weekday} {jd} {JALALI_MONTHS[jm - 1]} {jy} — {local:%H:%M:%S} (وقت تهران)"


def to_gregorian_text(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass
class Options:
    """Per-user rendering preferences loaded from the settings table."""

    date_mode: str = "both"          # both | jalali | gregorian
    detail: str = "full"             # full | compact
    entities: bool = True
    show_json: bool = True
    save_history: bool = True
    auto_inspect: bool = True
    notify_chat_added: bool = True

    @property
    def compact(self) -> bool:
        return self.detail == "compact"


DEFAULT_OPTIONS = Options()


def fmt_dt(value: Any, opts: Optional[Options] = None) -> str:
    """Return a human readable date (Gregorian / Jalali per preferences)."""
    if value is None:
        return UNAVAILABLE
    opts = opts or DEFAULT_OPTIONS
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=timezone.utc)
    if not isinstance(value, datetime):
        return str(value)
    lines = []
    if opts.date_mode in ("both", "gregorian"):
        lines.append(to_gregorian_text(value))
    if opts.date_mode in ("both", "jalali"):
        lines.append(to_jalali_text(value))
    return "\n".join(lines)


def fmt_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = int((now_utc() - dt).total_seconds())
    if diff < 0:
        return "در آینده"
    if diff < 60:
        return "لحظاتی پیش"
    if diff < 3600:
        return f"{diff // 60} دقیقه پیش"
    if diff < 86400:
        return f"{diff // 3600} ساعت پیش"
    if diff < 86400 * 60:
        return f"{diff // 86400} روز پیش"
    return f"{diff // (86400 * 30)} ماه پیش"


# ---------------------------------------------------------
#   Telegram identifier helpers
# ---------------------------------------------------------

def public_url(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    return f"https://t.me/{username.lstrip('@')}"


def chat_id_forms(chat_id: int) -> dict[str, Any]:
    """Describe the different numeric forms of a chat identifier."""
    text = str(chat_id)
    if chat_id > 0:
        return {"kind": "کاربر/ربات (آیدی مثبت)", "bot_api": chat_id, "short": None}
    if text.startswith("-100"):
        return {"kind": "سوپرگروه یا کانال (پیشوند -100)", "bot_api": chat_id, "short": text[4:]}
    return {"kind": "گروه معمولی (آیدی منفی)", "bot_api": chat_id, "short": text[1:]}


def message_link(chat: Any, message_id: Optional[int]) -> Optional[str]:
    if chat is None or message_id is None:
        return None
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    text = str(getattr(chat, "id", ""))
    if text.startswith("-100"):
        return f"https://t.me/c/{text[4:]}/{message_id}"
    return None


def user_display(user: Any) -> str:
    if user is None:
        return "نامشخص"
    name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
    if name:
        return str(name)
    username = getattr(user, "username", None)
    if username:
        return "@" + username
    return str(getattr(user, "id", "؟"))


def chat_display(chat: Any) -> str:
    if chat is None:
        return "نامشخص"
    title = getattr(chat, "title", None)
    if title:
        return str(title)
    name = " ".join(
        part for part in (getattr(chat, "first_name", None), getattr(chat, "last_name", None)) if part
    )
    if name:
        return name
    username = getattr(chat, "username", None)
    if username:
        return "@" + username
    return str(getattr(chat, "id", "؟"))


def user_mention(user: Any) -> str:
    """Clickable mention (tg://user) that is safe for HTML parse mode."""
    uid = getattr(user, "id", None)
    if uid is None:
        return esc(user_display(user))
    return f'<a href="tg://user?id={int(uid)}">{esc(user_display(user))}</a>'


def type_label(chat_type: Optional[str]) -> str:
    if not chat_type:
        return UNAVAILABLE
    return CHAT_TYPE_LABELS.get(str(chat_type), str(chat_type))


def is_group_type(chat_type: Optional[str]) -> bool:
    return chat_type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup")


def is_chat_like(chat_type: Optional[str]) -> bool:
    return chat_type in ("group", "supergroup", "channel")


def safe_to_dict(obj: Any) -> dict[str, Any]:
    try:
        return obj.to_dict()
    except Exception:  # pragma: no cover - defensive
        return {}


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return str(value)


def dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=json_default)


def flatten_dict(data: Any, prefix: str = "", depth: int = 0, max_depth: int = 3) -> list[tuple[str, str]]:
    """Flatten nested dict/list structures into (key, value) display pairs."""
    pairs: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)) and depth < max_depth:
                pairs.extend(flatten_dict(value, path, depth + 1, max_depth))
            else:
                pairs.append((path, one_line(value if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False, default=json_default), 200)))
    elif isinstance(data, list):
        for index, value in enumerate(data[:10]):
            path = f"{prefix}[{index}]"
            if isinstance(value, (dict, list)) and depth < max_depth:
                pairs.extend(flatten_dict(value, path, depth + 1, max_depth))
            else:
                pairs.append((path, one_line(value, 200)))
        if len(data) > 10:
            pairs.append((prefix, f"... و {len(data) - 10} مورد دیگر"))
    else:
        pairs.append((prefix, one_line(data, 200)))
    return pairs


# ---------------------------------------------------------
#   Report builder
# ---------------------------------------------------------

class Section:
    """A titled block of report rows. Every row is a self-contained HTML string."""

    def __init__(self, title: str, emoji: str = "📌") -> None:
        self.title = title
        self.emoji = emoji
        self.rows: list[str] = []

    @property
    def empty(self) -> bool:
        return not self.rows

    def header_html(self, cont: bool = False) -> str:
        suffix = " (ادامه)" if cont else ""
        return f"{self.emoji} <b>{esc(self.title)}{suffix}</b>\n{SEP}"

    def add(
        self,
        emoji: str,
        label: str,
        value: Any,
        *,
        raw: bool = False,
        as_code: bool = False,
        inline: bool = False,
    ) -> "Section":
        if value is None:
            value = UNAVAILABLE
        text = trunc(value, 1500 if raw else MAX_VALUE_LEN)
        if as_code:
            body = code(text)
        elif raw:
            body = str(value)
        else:
            body = esc(text)
        separator = " " if inline else "\n"
        self.rows.append(f"{emoji} <b>{esc(label)}:</b>{separator}{body}")
        return self

    def add_opt(self, emoji: str, label: str, value: Any, **kwargs: Any) -> "Section":
        if value is None or value == "":
            return self
        return self.add(emoji, label, value, **kwargs)

    def add_bool(self, emoji: str, label: str, value: Optional[bool], *, omit_false: bool = False) -> "Section":
        return self.add(emoji, label, fmt_bool(value, omit_false), inline=True)

    def add_present_bool(self, emoji: str, label: str, value: Optional[bool]) -> "Section":
        """Add only when the Bot API actually returned the field."""
        if value is None:
            return self
        return self.add_bool(emoji, label, value)

    def add_missing(self, emoji: str, label: str) -> "Section":
        self.rows.append(f"{emoji} <b>{esc(label)}:</b>\n⚪ {esc(UNAVAILABLE)}")
        return self

    def add_dt(self, emoji: str, label: str, value: Any, opts: Optional[Options] = None) -> "Section":
        if value is None:
            return self
        return self.add(emoji, label, fmt_dt(value, opts), as_code=True)

    def add_note(self, text: str) -> "Section":
        self.rows.append(f"ℹ️ <i>{esc(trunc(text, 1200))}</i>")
        return self

    def add_warning(self, text: str) -> "Section":
        self.rows.append(f"⚠️ <i>{esc(trunc(text, 1200))}</i>")
        return self

    def add_quote(self, emoji: str, label: str, text: str, limit: int = 1200) -> "Section":
        body = esc(trunc(text, limit))
        tag = "<blockquote expandable>" if len(body) > 300 else "<blockquote>"
        self.rows.append(f"{emoji} <b>{esc(label)}:</b>\n{tag}{body}</blockquote>")
        return self

    def add_raw_row(self, html_text: str) -> "Section":
        self.rows.append(trunc(html_text, 2500))
        return self

    def add_lines(self, emoji: str, label: str, lines: Sequence[str], *, limit: int = 20) -> "Section":
        """List of already-escaped HTML lines."""
        shown = list(lines[:limit])
        extra = len(lines) - len(shown)
        body = "\n".join(shown)
        if extra > 0:
            body += f"\n… و {extra} مورد دیگر"
        self.rows.append(f"{emoji} <b>{esc(label)}:</b>\n{trunc(body, 2500)}")
        return self


class Report:
    """A multi-section report which can be split into Telegram-sized pages."""

    def __init__(self, title: str, emoji: str = "📋", subtitle: Optional[str] = None) -> None:
        self.title = title
        self.emoji = emoji
        self.subtitle = subtitle
        self.sections: list[Section] = []
        self.footer: Optional[str] = None

    def section(self, title: str, emoji: str = "📌") -> Section:
        sec = Section(title, emoji)
        self.sections.append(sec)
        return sec

    def extend(self, sections: Iterable[Section]) -> None:
        for sec in sections:
            if sec is not None and not sec.empty:
                self.sections.append(sec)

    def header_html(self) -> str:
        text = f"{self.emoji} <b>{esc(self.title)}</b>"
        if self.subtitle:
            text += f"\n<i>{esc(self.subtitle)}</i>"
        return text + f"\n\n{SEP}"

    def with_status_footer(self) -> "Report":
        self.footer = (
            f"{SEP}\n\n📊 <b>وضعیت اطلاعات:</b>\n\n"
            "✅ اطلاعات دریافت‌شده از تلگرام\n"
            "⚪ اطلاعات در دسترس نیست"
        )
        return self

    def paginate(self, limit: int = PAGE_LIMIT) -> list[str]:
        pages: list[str] = []
        cur = self.header_html()
        for sec in self.sections:
            if sec.empty:
                continue
            head = sec.header_html()
            started = False
            for row in sec.rows:
                piece = row if started else f"{head}\n\n{row}"
                if cur and len(cur) + 2 + len(piece) > limit:
                    pages.append(cur)
                    cur = ""
                    if started:
                        piece = f"{sec.header_html(cont=True)}\n\n{row}"
                cur = f"{cur}\n\n{piece}" if cur else piece
                started = True
        if self.footer:
            if len(cur) + 2 + len(self.footer) > limit:
                pages.append(cur)
                cur = self.footer
            else:
                cur = f"{cur}\n\n{self.footer}"
        pages.append(cur)
        # حفاظ نهایی: هیچ صفحه‌ای نباید از سقف تلگرام بیشتر شود.
        safe_pages = []
        for page in pages:
            if len(page) > TG_TEXT_LIMIT:
                page = page[: TG_TEXT_LIMIT - 20] + "\n…"
            safe_pages.append(page)
        return safe_pages


# ---------------------------------------------------------
#   In-memory stores, rate limiting
# ---------------------------------------------------------

class LRUStore:
    """Small thread-safe LRU cache used for pagination, message cache, etc."""

    def __init__(self, maxsize: int = 300) -> None:
        self.maxsize = maxsize
        self._data: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.Lock()

    def put(self, value: Any, key: Optional[str] = None) -> str:
        key = key or secrets.token_hex(5)
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
        return key

    def get(self, key: str) -> Any:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def __len__(self) -> int:
        return len(self._data)


class RateLimiter:
    """Sliding-window limiter for expensive operations."""

    def __init__(self) -> None:
        self._events: dict[tuple[int, str], deque] = {}
        self._lock = threading.Lock()

    def check(self, user_id: int, bucket: str, limit: int, window: float) -> float:
        """Return 0 when allowed, otherwise the seconds the user must wait."""
        now = time.monotonic()
        key = (user_id, bucket)
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > window:
                events.popleft()
            if len(events) >= limit:
                return max(window - (now - events[0]), 0.5)
            events.append(now)
            if len(self._events) > 5000:
                self._events.clear()
            return 0.0


PAGES = LRUStore(400)          # گزارش‌های صفحه‌بندی‌شده
MSGS = LRUStore(250)           # پیام‌های بررسی‌شده (برای دکمه‌های بعدی)
MSG_OWNERS = LRUStore(3000)    # مالک هر پیام ربات در گروه‌ها
RATE = RateLimiter()


# ---------------------------------------------------------
#   Telegram error handling helpers
# ---------------------------------------------------------

def explain_error(exc: Optional[BaseException]) -> str:
    """Translate Telegram errors into clear Persian explanations."""
    if exc is None:
        return ""
    if isinstance(exc, RetryAfter):
        retry = exc.retry_after
        seconds = retry.total_seconds() if isinstance(retry, timedelta) else float(retry)
        return f"محدودیت نرخ درخواست تلگرام؛ حدود {int(seconds)} ثانیه بعد دوباره تلاش کنید."
    message = str(getattr(exc, "message", None) or exc or "").lower()
    if isinstance(exc, InvalidToken):
        return "توکن ربات نامعتبر است."
    if "chat not found" in message:
        return (
            "چت پیدا نشد؛ یا آیدی/یوزرنیم اشتباه است یا ربات به این چت دسترسی ندارد "
            "(ربات باید عضو چت باشد یا چت یک یوزرنیم عمومی داشته باشد)."
        )
    if "user not found" in message or "participant_id_invalid" in message or "user_id_invalid" in message:
        return "کاربر پیدا نشد یا آیدی عددی نامعتبر است."
    if "member list is inaccessible" in message:
        return "فهرست اعضای این چت برای ربات قابل‌دسترسی نیست."
    if "chat_admin_required" in message or "not enough rights" in message or "administrator rights" in message:
        return "ربات برای این عملیات دسترسی ادمین کافی ندارد."
    if "kicked" in message:
        return "ربات از این چت حذف (Kick) شده است."
    if "not a member" in message or "bot is not a member" in message:
        return "ربات عضو این چت نیست."
    if "bot was blocked" in message:
        return "کاربر ربات را مسدود کرده است."
    if "user is deactivated" in message:
        return "حساب کاربر حذف یا غیرفعال شده است."
    if "have no rights to send" in message or "need administrator rights in the channel" in message:
        return "ربات اجازه‌ی ارسال پیام در این چت را ندارد."
    if "message is not modified" in message:
        return "محتوا تغییری نکرده است."
    if "message to edit not found" in message or "message can't be edited" in message:
        return "پیام قابل ویرایش نیست."
    if "file is too big" in message:
        return "حجم فایل بیش از حد مجاز دانلود ربات‌ها (۲۰ مگابایت) است."
    if "wrong file identifier" in message or "wrong remote file" in message:
        return "File ID نامعتبر است یا برای این ربات قابل استفاده نیست."
    if isinstance(exc, Forbidden):
        return f"دسترسی ممنوع (Forbidden): {getattr(exc, 'message', exc)}"
    if isinstance(exc, BadRequest):
        return f"درخواست نامعتبر (BadRequest): {getattr(exc, 'message', exc)}"
    if isinstance(exc, TimedOut):
        return "پاسخی از سرور تلگرام دریافت نشد (Timeout)."
    if isinstance(exc, NetworkError):
        return "خطای شبکه در ارتباط با تلگرام."
    return f"خطای ناشناخته: {type(exc).__name__}"


async def safe_call(
    func: Callable[..., Awaitable[Any]], *args: Any, retries: int = 2, **kwargs: Any
) -> tuple[Any, Optional[BaseException]]:
    """Call a Bot API coroutine and return (result, error) without raising."""
    attempt = 0
    while True:
        try:
            return await func(*args, **kwargs), None
        except RetryAfter as exc:
            attempt += 1
            retry = exc.retry_after
            wait = retry.total_seconds() if isinstance(retry, timedelta) else float(retry)
            if attempt > retries or wait > 15:
                return None, exc
            await asyncio.sleep(wait + 0.5)
        except (BadRequest, Forbidden, InvalidToken) as exc:
            return None, exc
        except (TimedOut, NetworkError) as exc:
            attempt += 1
            if attempt > retries:
                return None, exc
            await asyncio.sleep(1.0 * attempt)
        except TelegramError as exc:
            return None, exc
        except Exception as exc:  # pragma: no cover - never crash on one call
            log.exception("Unexpected error in safe_call: %s", type(exc).__name__)
            return None, exc


def short_file_id(file_id: Optional[str], keep: int = 18) -> str:
    if not file_id:
        return UNAVAILABLE
    if len(file_id) <= keep * 2 + 3:
        return file_id
    return f"{file_id[:keep]}…{file_id[-keep:]}"


def guess_mime_from_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    mime, _ = mimetypes.guess_type(name)
    return mime


# =========================================================
#                  06 — DATABASE LAYER (SQLite3)
# =========================================================

SCHEMA_VERSION = 2

SETTINGS_SPEC: dict[str, dict[str, Any]] = {
    "auto_inspect": {
        "default": "1",
        "type": "toggle",
        "emoji": "🔎",
        "label": "بررسی خودکار پیام‌های خصوصی",
        "help": "هر پیامی که در گفتگوی خصوصی بفرستی، فوراً تحلیل می‌شود.",
    },
    "save_history": {
        "default": "1",
        "type": "toggle",
        "emoji": "📜",
        "label": "ذخیره‌ی تاریخچه‌ی بررسی‌ها",
        "help": "فقط خلاصه‌ی کوتاه ذخیره می‌شود؛ متن پیام‌ها ذخیره نمی‌شود.",
    },
    "show_json": {
        "default": "1",
        "type": "toggle",
        "emoji": "🧾",
        "label": "نمایش دکمه‌ی JSON در گزارش‌ها",
        "help": "دکمه‌ی دریافت خروجی ساختاریافته زیر هر گزارش.",
    },
    "entities": {
        "default": "1",
        "type": "toggle",
        "emoji": "🔗",
        "label": "نمایش Entityها (لینک، منشن، هشتگ)",
        "help": "جزئیات entityهای متن و کپشن پیام‌ها.",
    },
    "notify_chat_added": {
        "default": "1",
        "type": "toggle",
        "emoji": "🔔",
        "label": "اعلان افزوده‌شدن ربات به چت",
        "help": "وقتی ربات را به گروه/کانالی اضافه کنی، پیام خصوصی می‌گیری.",
    },
    "date_mode": {
        "default": "both",
        "type": "cycle",
        "emoji": "📅",
        "label": "نمایش تاریخ",
        "choices": [("both", "شمسی + میلادی"), ("jalali", "فقط شمسی"), ("gregorian", "فقط میلادی")],
        "help": "قالب نمایش تاریخ‌ها در گزارش‌ها.",
    },
    "detail": {
        "default": "full",
        "type": "cycle",
        "emoji": "🧮",
        "label": "سطح جزئیات گزارش",
        "choices": [("full", "کامل"), ("compact", "خلاصه")],
        "help": "در حالت خلاصه، جزئیات مجوزها و فیلدهای فرعی نمایش داده نمی‌شود.",
    },
}


@contextlib.contextmanager
def db_conn():
    """Transaction-safe SQLite connection (commit on success, rollback on error)."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def init_db() -> None:
    """Create the database file and all tables automatically."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db_conn() as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users_cache (
                user_id        INTEGER PRIMARY KEY,
                first_name     TEXT,
                last_name      TEXT,
                username       TEXT,
                is_bot         INTEGER NOT NULL DEFAULT 0,
                is_premium     INTEGER,
                language_code  TEXT,
                first_seen     TEXT NOT NULL,
                last_seen      TEXT NOT NULL,
                interactions   INTEGER NOT NULL DEFAULT 0,
                started        INTEGER NOT NULL DEFAULT 0,
                is_blocked     INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS selected_chats (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id     INTEGER NOT NULL,
                chat_id           INTEGER NOT NULL,
                chat_type         TEXT,
                title             TEXT,
                username          TEXT,
                is_forum          INTEGER,
                member_count      INTEGER,
                bot_status        TEXT,
                ownership_code    TEXT,
                ownership_label   TEXT,
                request_kind      TEXT,
                access_level      TEXT,
                selected_at       TEXT NOT NULL,
                last_checked_at   TEXT NOT NULL,
                UNIQUE(owner_user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS inspection_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                chat_id       INTEGER,
                kind          TEXT NOT NULL,
                subject_id    INTEGER,
                subject_name  TEXT,
                summary       TEXT,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                user_id  INTEGER NOT NULL,
                key      TEXT NOT NULL,
                value    TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            );

            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id     INTEGER PRIMARY KEY,
                chat_type   TEXT,
                title       TEXT,
                username    TEXT,
                bot_status  TEXT,
                is_active   INTEGER NOT NULL DEFAULT 1,
                added_by    INTEGER,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_stats (
                key    TEXT PRIMARY KEY,
                value  INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_history_user ON inspection_history(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_selected_owner ON selected_chats(owner_user_id, last_checked_at DESC);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users_cache(username);
            """
        )
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current < SCHEMA_VERSION:
            migrate_db(conn, current)
            conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
    log.info("Database ready: %s", DB_PATH)


def migrate_db(conn: sqlite3.Connection, current: int) -> None:
    """Forward-only schema migrations for databases created by older versions."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(selected_chats)")}
    if "access_level" not in columns:
        conn.execute("ALTER TABLE selected_chats ADD COLUMN access_level TEXT")
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users_cache)")}
    if "is_blocked" not in user_columns:
        conn.execute("ALTER TABLE users_cache ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")
    if "started" not in user_columns:
        conn.execute("ALTER TABLE users_cache ADD COLUMN started INTEGER NOT NULL DEFAULT 0")


async def dbx(func: Callable[..., Any], *args: Any, _default: Any = None, **kwargs: Any) -> Any:
    """Run a blocking DB function in a worker thread; never raise to the caller."""
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except sqlite3.Error as exc:
        log.error("Database error in %s: %s", getattr(func, "__name__", "?"), exc)
        return _default
    except Exception as exc:  # pragma: no cover
        log.exception("Unexpected DB wrapper error: %s", exc)
        return _default


# ---------------------------------------------------------
#   users_cache
# ---------------------------------------------------------

def db_upsert_user(user: Any, started: bool = False) -> None:
    if user is None or getattr(user, "id", None) is None:
        return
    stamp = now_iso()
    premium = getattr(user, "is_premium", None)
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO users_cache
                (user_id, first_name, last_name, username, is_bot, is_premium,
                 language_code, first_seen, last_seen, interactions, started, is_blocked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name    = excluded.first_name,
                last_name     = excluded.last_name,
                username      = excluded.username,
                is_bot        = excluded.is_bot,
                is_premium    = COALESCE(excluded.is_premium, users_cache.is_premium),
                language_code = COALESCE(excluded.language_code, users_cache.language_code),
                last_seen     = excluded.last_seen,
                interactions  = users_cache.interactions + 1,
                started       = MAX(users_cache.started, excluded.started),
                is_blocked    = CASE WHEN excluded.started = 1 THEN 0 ELSE users_cache.is_blocked END
            """,
            (
                int(user.id),
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
                getattr(user, "username", None),
                1 if getattr(user, "is_bot", False) else 0,
                None if premium is None else int(bool(premium)),
                getattr(user, "language_code", None),
                stamp,
                stamp,
                1 if started else 0,
            ),
        )


def db_get_cached_user(user_id: int) -> Optional[dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM users_cache WHERE user_id = ?", (int(user_id),)).fetchone()
    return row_to_dict(row)


def db_find_cached_username(username: str) -> Optional[dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users_cache WHERE LOWER(username) = LOWER(?) ORDER BY last_seen DESC LIMIT 1",
            (username.lstrip("@"),),
        ).fetchone()
    return row_to_dict(row)


def db_mark_user_blocked(user_id: int, blocked: bool) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE users_cache SET is_blocked = ? WHERE user_id = ?",
            (1 if blocked else 0, int(user_id)),
        )


def db_broadcast_targets() -> list[int]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT user_id FROM users_cache WHERE started = 1 AND is_blocked = 0 AND is_bot = 0"
        ).fetchall()
    return [int(row["user_id"]) for row in rows]


# ---------------------------------------------------------
#   settings
# ---------------------------------------------------------

def db_get_settings(user_id: int) -> dict[str, str]:
    values = {key: spec["default"] for key, spec in SETTINGS_SPEC.items()}
    with db_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings WHERE user_id = ?", (int(user_id),)).fetchall()
    for row in rows:
        if row["key"] in SETTINGS_SPEC:
            values[row["key"]] = row["value"]
    return values


def db_set_setting(user_id: int, key: str, value: str) -> None:
    if key not in SETTINGS_SPEC:
        raise ValueError("unknown setting key")
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings(user_id, key, value) VALUES (?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
            """,
            (int(user_id), key, str(value)),
        )


def db_reset_settings(user_id: int) -> None:
    with db_conn() as conn:
        conn.execute("DELETE FROM settings WHERE user_id = ?", (int(user_id),))


def options_from_settings(values: dict[str, str]) -> Options:
    return Options(
        date_mode=values.get("date_mode", "both"),
        detail=values.get("detail", "full"),
        entities=values.get("entities", "1") == "1",
        show_json=values.get("show_json", "1") == "1",
        save_history=values.get("save_history", "1") == "1",
        auto_inspect=values.get("auto_inspect", "1") == "1",
        notify_chat_added=values.get("notify_chat_added", "1") == "1",
    )


async def load_options(user_id: Optional[int]) -> Options:
    if user_id is None:
        return Options()
    values = await dbx(db_get_settings, user_id, _default=None)
    if not values:
        return Options()
    return options_from_settings(values)


# ---------------------------------------------------------
#   selected_chats
# ---------------------------------------------------------

def db_save_selected_chat(owner_id: int, data: dict[str, Any]) -> int:
    stamp = now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO selected_chats
                (owner_user_id, chat_id, chat_type, title, username, is_forum, member_count,
                 bot_status, ownership_code, ownership_label, request_kind, access_level,
                 selected_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_user_id, chat_id) DO UPDATE SET
                chat_type       = excluded.chat_type,
                title           = excluded.title,
                username        = excluded.username,
                is_forum        = excluded.is_forum,
                member_count    = excluded.member_count,
                bot_status      = excluded.bot_status,
                ownership_code  = excluded.ownership_code,
                ownership_label = excluded.ownership_label,
                request_kind    = excluded.request_kind,
                access_level    = excluded.access_level,
                last_checked_at = excluded.last_checked_at
            """,
            (
                int(owner_id),
                int(data["chat_id"]),
                data.get("chat_type"),
                data.get("title"),
                data.get("username"),
                None if data.get("is_forum") is None else int(bool(data.get("is_forum"))),
                data.get("member_count"),
                data.get("bot_status"),
                data.get("ownership_code"),
                data.get("ownership_label"),
                data.get("request_kind"),
                data.get("access_level"),
                stamp,
                stamp,
            ),
        )
        row = conn.execute(
            "SELECT id FROM selected_chats WHERE owner_user_id = ? AND chat_id = ?",
            (int(owner_id), int(data["chat_id"])),
        ).fetchone()
    return int(row["id"])


def db_list_selected_chats(owner_id: int, limit: int, offset: int) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM selected_chats WHERE owner_user_id = ?
            ORDER BY last_checked_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            (int(owner_id), int(limit), int(offset)),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def db_count_selected_chats(owner_id: int) -> int:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM selected_chats WHERE owner_user_id = ?", (int(owner_id),)
        ).fetchone()
    return int(row["c"])


def db_get_selected_chat(owner_id: int, row_id: int) -> Optional[dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM selected_chats WHERE owner_user_id = ? AND id = ?",
            (int(owner_id), int(row_id)),
        ).fetchone()
    return row_to_dict(row)


def db_delete_selected_chat(owner_id: int, row_id: int) -> int:
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM selected_chats WHERE owner_user_id = ? AND id = ?",
            (int(owner_id), int(row_id)),
        )
        return cur.rowcount


def db_clear_selected_chats(owner_id: int) -> int:
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM selected_chats WHERE owner_user_id = ?", (int(owner_id),))
        return cur.rowcount


# ---------------------------------------------------------
#   inspection_history
# ---------------------------------------------------------

def db_add_history(
    user_id: int,
    chat_id: Optional[int],
    kind: str,
    subject_id: Optional[int],
    subject_name: Optional[str],
    summary: Optional[str],
) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO inspection_history
                (user_id, chat_id, kind, subject_id, subject_name, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                chat_id,
                kind,
                subject_id,
                trunc(subject_name, 120) if subject_name else None,
                trunc(summary, 240) if summary else None,
                now_iso(),
            ),
        )
        # نگه‌داری محدود: فقط آخرین N رکورد و رکوردهای تازه‌تر از X روز.
        conn.execute(
            """
            DELETE FROM inspection_history WHERE user_id = ? AND id NOT IN (
                SELECT id FROM inspection_history WHERE user_id = ? ORDER BY id DESC LIMIT ?
            )
            """,
            (int(user_id), int(user_id), MAX_HISTORY_PER_USER),
        )
        cutoff = (now_utc() - timedelta(days=HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "DELETE FROM inspection_history WHERE user_id = ? AND created_at < ?",
            (int(user_id), cutoff),
        )


def db_list_history(user_id: int, limit: int, offset: int) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inspection_history WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (int(user_id), int(limit), int(offset)),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def db_count_history(user_id: int) -> int:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM inspection_history WHERE user_id = ?", (int(user_id),)
        ).fetchone()
    return int(row["c"])


def db_get_history(user_id: int, row_id: int) -> Optional[dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM inspection_history WHERE user_id = ? AND id = ?",
            (int(user_id), int(row_id)),
        ).fetchone()
    return row_to_dict(row)


def db_clear_history(user_id: int) -> int:
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM inspection_history WHERE user_id = ?", (int(user_id),))
        return cur.rowcount


# ---------------------------------------------------------
#   known_chats & stats
# ---------------------------------------------------------

def db_upsert_known_chat(
    chat: Any, status: Optional[str] = None, active: bool = True, added_by: Optional[int] = None
) -> None:
    if chat is None or getattr(chat, "id", None) is None:
        return
    if getattr(chat, "type", None) == "private":
        return
    stamp = now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO known_chats
                (chat_id, chat_type, title, username, bot_status, is_active, added_by, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type  = excluded.chat_type,
                title      = excluded.title,
                username   = excluded.username,
                bot_status = COALESCE(excluded.bot_status, known_chats.bot_status),
                is_active  = excluded.is_active,
                added_by   = COALESCE(excluded.added_by, known_chats.added_by),
                last_seen  = excluded.last_seen
            """,
            (
                int(chat.id),
                getattr(chat, "type", None),
                getattr(chat, "title", None),
                getattr(chat, "username", None),
                status,
                1 if active else 0,
                added_by,
                stamp,
                stamp,
            ),
        )


def db_bump_stat(key: str, amount: int = 1) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO bot_stats(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = bot_stats.value + excluded.value
            """,
            (key, amount),
        )


def db_collect_stats() -> dict[str, Any]:
    with db_conn() as conn:
        def scalar(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        data = {
            "users": scalar("SELECT COUNT(*) FROM users_cache WHERE is_bot = 0"),
            "started": scalar("SELECT COUNT(*) FROM users_cache WHERE started = 1"),
            "blocked": scalar("SELECT COUNT(*) FROM users_cache WHERE is_blocked = 1"),
            "bots_seen": scalar("SELECT COUNT(*) FROM users_cache WHERE is_bot = 1"),
            "selected": scalar("SELECT COUNT(*) FROM selected_chats"),
            "history": scalar("SELECT COUNT(*) FROM inspection_history"),
            "known_chats": scalar("SELECT COUNT(*) FROM known_chats WHERE is_active = 1"),
            "left_chats": scalar("SELECT COUNT(*) FROM known_chats WHERE is_active = 0"),
        }
        counters = {row["key"]: int(row["value"]) for row in conn.execute("SELECT key, value FROM bot_stats")}
    data["counters"] = counters
    try:
        data["db_size"] = os.path.getsize(DB_PATH)
    except OSError:
        data["db_size"] = None
    return data


def db_list_known_chats(limit: int, offset: int) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM known_chats ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (int(limit), int(offset)),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def db_vacuum() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


# =========================================================
#                  07 — USER INFORMATION ENGINE
# =========================================================

# (attribute, Persian label, emoji, omitted-when-false)
USER_FIELD_SPECS: list[tuple[str, str, str, bool]] = [
    ("id", "آیدی عددی", "🆔", False),
    ("is_bot", "ربات بودن", "🤖", False),
    ("first_name", "نام", "👤", False),
    ("last_name", "نام خانوادگی", "👥", False),
    ("username", "یوزرنیم", "🔗", False),
    ("language_code", "کد زبان", "🌍", False),
    ("is_premium", "تلگرام پریمیوم", "⭐", True),
    ("added_to_attachment_menu", "افزوده‌شده به منوی پیوست", "📎", True),
    ("can_join_groups", "امکان افزوده‌شدن به گروه‌ها", "➕", False),
    ("can_read_all_group_messages", "خواندن همه‌ی پیام‌های گروه (Privacy Off)", "👁", False),
    ("supports_inline_queries", "پشتیبانی از حالت Inline", "⌨️", False),
    ("can_connect_to_business", "اتصال به حساب Business", "💼", False),
    ("has_main_web_app", "دارای Main Web App", "🕸", False),
    ("has_topics_enabled", "فعال‌بودن تاپیک در چت خصوصی", "🧵", False),
    ("allows_users_to_create_topics", "اجازه‌ی ساخت تاپیک به کاربران", "🧵", False),
]

KNOWN_USER_KEYS = {spec[0] for spec in USER_FIELD_SPECS}


def get_user_information(user: User) -> dict[str, Any]:
    """
    Extract every field of the received Telegram User object.

    state:
      "true"/"false" -> boolean value actually delivered by Telegram
      "present"      -> non-boolean value delivered
      "missing"      -> field not delivered (never invented)
    """
    fields: dict[str, dict[str, Any]] = {}
    for attr, label, emoji, omit_false in USER_FIELD_SPECS:
        value = getattr(user, attr, None)
        if isinstance(value, bool):
            state = "true" if value else "false"
        elif value is None:
            state = "missing"
        else:
            state = "present"
        fields[attr] = {
            "label": label,
            "emoji": emoji,
            "value": value,
            "state": state,
            "omitted_when_false": omit_false,
        }
    user_id = int(user.id)
    username = getattr(user, "username", None)
    if user_id in WELL_KNOWN_IDS:
        kind = "special"
    elif getattr(user, "is_bot", False):
        kind = "bot"
    else:
        kind = "user"
    extra = {
        key: value
        for key, value in safe_to_dict(user).items()
        if key not in KNOWN_USER_KEYS
    }
    full_name = " ".join(
        part for part in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if part
    ).strip()
    return {
        "id": user_id,
        "kind": kind,
        "full_name": full_name or None,
        "username": username,
        "username_url": public_url(username),
        "direct_link": f"tg://user?id={user_id}",
        "special_note": WELL_KNOWN_IDS.get(user_id),
        "fields": fields,
        "extra_fields": extra,
    }


def user_kind_label(info: dict[str, Any]) -> str:
    if info["kind"] == "special":
        return "حساب سیستمی/شناخته‌شده‌ی تلگرام"
    if info["kind"] == "bot":
        return "ربات 🤖"
    return "کاربر عادی"


@dataclass
class UserBundle:
    """Everything the bot could legitimately collect about one user."""

    user_id: int
    user: Optional[User] = None
    full: Any = None                       # ChatFullInfo returned by getChat(user_id)
    full_error: Optional[BaseException] = None
    photos_total: Optional[int] = None
    photos_error: Optional[BaseException] = None
    member: Any = None                     # ChatMember inside the current chat
    member_error: Optional[BaseException] = None
    member_chat: Any = None
    cached: Optional[dict[str, Any]] = None


async def fetch_user_bundle(
    bot: Any,
    user: Optional[User],
    *,
    user_id: Optional[int] = None,
    context_chat: Any = None,
    deep: bool = True,
) -> UserBundle:
    """Collect user data via getChat / getUserProfilePhotos / getChatMember."""
    uid = int(user.id) if user is not None else int(user_id or 0)
    bundle = UserBundle(user_id=uid, user=user)
    bundle.cached = await dbx(db_get_cached_user, uid, _default=None)
    if uid <= 0:
        return bundle
    if deep:
        full, err = await safe_call(bot.get_chat, uid)
        bundle.full, bundle.full_error = full, err
        photos, perr = await safe_call(bot.get_user_profile_photos, uid, limit=1)
        if photos is not None:
            bundle.photos_total = photos.total_count
        bundle.photos_error = perr
        if context_chat is not None and is_chat_like(getattr(context_chat, "type", None)):
            member, merr = await safe_call(bot.get_chat_member, context_chat.id, uid)
            bundle.member, bundle.member_error, bundle.member_chat = member, merr, context_chat
    return bundle


def rights_lines(obj: Any, spec: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    granted: list[str] = []
    denied: list[str] = []
    for attr, label in spec:
        value = getattr(obj, attr, None)
        if value is None:
            continue
        (granted if value else denied).append(label)
    return granted, denied


def add_rights_rows(sec: Section, obj: Any, spec: list[tuple[str, str]], title: str, opts: Options) -> None:
    granted, denied = rights_lines(obj, spec)
    if granted:
        sec.add("✅", f"{title} — مجاز", "، ".join(granted))
    if denied and not opts.compact:
        sec.add("❌", f"{title} — غیرمجاز", "، ".join(denied))


def add_member_rows(sec: Section, member: Any, opts: Options, prefix: str = "") -> None:
    """Render a ChatMember (owner / admin / member / restricted / left / banned)."""
    if member is None:
        return
    status = getattr(member, "status", None)
    sec.add("📌", f"{prefix}وضعیت عضویت", MEMBER_STATUS_LABELS.get(str(status), status), inline=True)
    sec.add_opt("🏷", "عنوان سفارشی (Custom Title)", getattr(member, "custom_title", None))
    sec.add_present_bool("🕶", "حالت ناشناس (Anonymous)", getattr(member, "is_anonymous", None))
    until = getattr(member, "until_date", None)
    if until:
        sec.add_dt("⏱", "تاریخ پایان وضعیت", until, opts)
    if status == "administrator":
        add_rights_rows(sec, member, ADMIN_RIGHTS_LABELS, "دسترسی‌های ادمین", opts)
        sec.add_present_bool("✏️", "ربات می‌تواند این ادمین را ویرایش کند", getattr(member, "can_be_edited", None))
    elif status == "restricted":
        sec.add_present_bool("👥", "هنوز عضو چت است", getattr(member, "is_member", None))
        add_rights_rows(sec, member, PERMISSION_LABELS, "مجوزها", opts)


def describe_birthdate(birthdate: Any) -> Optional[str]:
    if birthdate is None:
        return None
    day = getattr(birthdate, "day", None)
    month = getattr(birthdate, "month", None)
    year = getattr(birthdate, "year", None)
    if day is None or month is None:
        return None
    return f"{year}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d} (سال نامشخص)"


def build_user_sections(bundle: UserBundle, opts: Options, heading: str = "اطلاعات کاربر") -> list[Section]:
    """Create the report sections describing one user."""
    sections: list[Section] = []
    user = bundle.user
    full = bundle.full
    info = get_user_information(user) if user is not None else None

    main = Section(heading, "👤")
    main.add("🆔", "آیدی عددی", bundle.user_id, as_code=True)

    first = getattr(user, "first_name", None) if user is not None else getattr(full, "first_name", None)
    last = getattr(user, "last_name", None) if user is not None else getattr(full, "last_name", None)
    full_name = " ".join(p for p in (first, last) if p).strip()
    main.add("👤", "نام", full_name or UNAVAILABLE)
    if not opts.compact:
        if first:
            main.add("▫️", "نام کوچک", first, inline=True)
        if last:
            main.add("▫️", "نام خانوادگی", last, inline=True)
        elif user is not None:
            main.add("▫️", "نام خانوادگی", "ثبت نشده (کاربر نام خانوادگی ندارد)", inline=True)

    username = getattr(user, "username", None) if user is not None else getattr(full, "username", None)
    if username:
        main.add("🔗", "یوزرنیم", "@" + username, as_code=True)
        main.add("🌐", "لینک", public_url(username), as_code=True)
    elif user is not None or full is not None:
        main.add("🔗", "یوزرنیم", "❌ ندارد (یوزرنیم عمومی ثبت نشده است)")
    else:
        main.add_missing("🔗", "یوزرنیم")
    active = getattr(full, "active_usernames", None) if full is not None else None
    if active and len(active) > 1:
        main.add("🔠", "یوزرنیم‌های فعال", "، ".join("@" + u for u in active))

    if bundle.user_id > 0:
        main.add("🪪", "لینک مستقیم پروفایل", f"tg://user?id={bundle.user_id}", as_code=True)
        main.add_note("لینک tg:// فقط در برنامه‌ی تلگرام و برای کاربرانی که مشاهده‌ی آن‌ها ممکن است کار می‌کند.")

    if info is not None:
        main.add("🤖", "نوع حساب", user_kind_label(info), inline=True)
        main.add("⭐", "پریمیوم", fmt_bool(getattr(user, "is_premium", None), omit_false=True), inline=True)
        lang = getattr(user, "language_code", None)
        main.add(
            "🌍",
            "زبان",
            code(lang) if lang else esc("ارسال نشده (تلگرام زبان را برای این کاربر نفرستاده است)"),
            raw=True,
        )
        if info["special_note"]:
            main.add("🏷", "حساب شناخته‌شده", info["special_note"])
    else:
        main.add("🤖", "نوع حساب", "از getChat مشخص نمی‌شود؛ نوع حساب فقط از شیء User پیام قابل‌دریافت است.", inline=False)
    sections.append(main)

    if info is not None and (info["kind"] == "bot" or not opts.compact):
        bot_sec = Section("ویژگی‌های اعلام‌شده‌ی ربات", "🤖")
        for attr in (
            "can_join_groups",
            "can_read_all_group_messages",
            "supports_inline_queries",
            "can_connect_to_business",
            "has_main_web_app",
            "added_to_attachment_menu",
            "has_topics_enabled",
            "allows_users_to_create_topics",
        ):
            entry = info["fields"][attr]
            if entry["state"] in ("true", "false"):
                bot_sec.add_bool(entry["emoji"], entry["label"], entry["value"])
        if not bot_sec.empty:
            sections.append(bot_sec)
        elif info["kind"] == "bot":
            bot_sec.add_note(
                "این ویژگی‌ها فقط برای خود ربات (متد getMe) ارسال می‌شوند؛ برای سایر ربات‌ها در دسترس نیستند."
            )
            sections.append(bot_sec)

    sections.append(build_full_info_section(bundle, opts))

    if bundle.member is not None:
        member_sec = Section(f"وضعیت در چت «{trunc(chat_display(bundle.member_chat), 40)}»", "🏷")
        add_member_rows(member_sec, bundle.member, opts)
        sections.append(member_sec)

    photo_sec = Section("تصاویر پروفایل", "📷")
    if bundle.photos_total is not None:
        photo_sec.add("🖼", "تعداد عکس‌های قابل‌دسترسی", bundle.photos_total, inline=True)
        if bundle.photos_total == 0:
            photo_sec.add_note("کاربر عکس ندارد یا تنظیمات حریم خصوصی او اجازه‌ی دسترسی نمی‌دهد.")
    elif bundle.photos_error is not None:
        photo_sec.add("🖼", "تعداد عکس‌ها", "⚪ " + explain_error(bundle.photos_error))
    if not photo_sec.empty:
        sections.append(photo_sec)

    cache_sec = Section("سابقه در پایگاه‌داده‌ی ربات", "🗂")
    cached = bundle.cached
    if cached:
        first_seen = parse_iso(cached.get("first_seen"))
        last_seen = parse_iso(cached.get("last_seen"))
        cache_sec.add_dt("🕰", "اولین مشاهده توسط ربات", first_seen, opts)
        cache_sec.add_dt("🕑", "آخرین مشاهده توسط ربات", last_seen, opts)
        cache_sec.add("🔁", "تعداد تعامل ثبت‌شده", cached.get("interactions"), inline=True)
        cache_sec.add_note("این تاریخ‌ها مربوط به زمان مشاهده‌ی کاربر توسط همین ربات است، نه ساخت حساب تلگرام.")
        sections.append(cache_sec)

    if info is not None and info["extra_fields"]:
        extra_sec = Section("فیلدهای اضافی نسخه‌ی نصب‌شده‌ی Bot API", "🧪")
        for key, value in list(info["extra_fields"].items())[:15]:
            extra_sec.add("▫️", key, one_line(value, 200), as_code=True)
        sections.append(extra_sec)

    if not opts.compact:
        limits = Section("محدودیت‌های دریافت اطلاعات", "🚧")
        limits.add_note(API_LIMITS_TEXT)
        sections.append(limits)
    return [sec for sec in sections if not sec.empty]


def build_full_info_section(bundle: UserBundle, opts: Options) -> Section:
    """Section built from getChat(user_id) (ChatFullInfo)."""
    sec = Section("اطلاعات تکمیلی (getChat)", "🧩")
    full = bundle.full
    if full is None:
        if bundle.full_error is not None:
            sec.add(
                "⚪",
                "اطلاعات تکمیلی",
                "دریافت نشد: " + explain_error(bundle.full_error)
                + " (معمولاً به‌دلیل اینکه کاربر هنوز با ربات تعامل نداشته است)",
            )
        return sec
    sec.add_opt("📝", "بیو (Bio)", getattr(full, "bio", None))
    birth = describe_birthdate(getattr(full, "birthdate", None))
    sec.add_opt("🎂", "تاریخ تولد (اگر عمومی باشد)", birth, as_code=True)
    personal = getattr(full, "personal_chat", None)
    if personal is not None:
        label = f"{chat_display(personal)} ({personal.id})"
        sec.add("📣", "کانال شخصی پروفایل", label, as_code=True)
    intro = getattr(full, "business_intro", None)
    if intro is not None:
        sec.add_opt("💼", "معرفی کسب‌وکار — عنوان", getattr(intro, "title", None))
        sec.add_opt("💼", "معرفی کسب‌وکار — پیام", getattr(intro, "message", None))
    b_loc = getattr(full, "business_location", None)
    if b_loc is not None:
        sec.add_opt("🏬", "آدرس کسب‌وکار", getattr(b_loc, "address", None))
    hours = getattr(full, "business_opening_hours", None)
    if hours is not None:
        count = len(getattr(hours, "opening_hours", []) or [])
        sec.add("🕘", "ساعات کاری", f"{getattr(hours, 'time_zone_name', '؟')} — {count} بازه", inline=True)
    sec.add_present_bool("🕶", "فوروارد خصوصی (پنهان‌کردن لینک پروفایل)", getattr(full, "has_private_forwards", None))
    sec.add_present_bool(
        "🔇", "محدودیت دریافت ویس/ویدیو پیام", getattr(full, "has_restricted_voice_and_video_messages", None)
    )
    sec.add_opt("⏳", "حذف خودکار پیام‌ها (ثانیه)", getattr(full, "message_auto_delete_time", None), inline=True)
    sec.add_opt("🎨", "رنگ Accent", getattr(full, "accent_color_id", None), inline=True)
    sec.add_opt("🎨", "رنگ Accent پروفایل", getattr(full, "profile_accent_color_id", None), inline=True)
    sec.add_opt("😎", "ایموجی وضعیت", getattr(full, "emoji_status_custom_emoji_id", None), as_code=True)
    sec.add_dt("⌛", "انقضای ایموجی وضعیت", getattr(full, "emoji_status_expiration_date", None), opts)
    photo = getattr(full, "photo", None)
    if photo is not None and not opts.compact:
        sec.add("🖼", "عکس پروفایل (ChatPhoto)", "دارد", inline=True)
        sec.add_opt("🔑", "Big File Unique ID", getattr(photo, "big_file_unique_id", None), as_code=True)
    if sec.empty:
        sec.add_note("getChat انجام شد اما فیلد تکمیلی عمومی‌ای برای این کاربر ارسال نشد.")
    return sec


# =========================================================
#                  08 — CHAT INFORMATION ENGINE
# =========================================================

CHAT_FEATURE_SPECS: list[tuple[str, str, str, str]] = [
    ("is_forum", "تاپیک‌دار (Forum)", "🧵", "bool"),
    ("is_direct_messages", "کانال پیام مستقیم", "📬", "bool"),
    ("slow_mode_delay", "حالت آهسته (Slow Mode)", "🐢", "seconds"),
    ("message_auto_delete_time", "حذف خودکار پیام‌ها", "⏳", "seconds"),
    ("has_protected_content", "محتوای محافظت‌شده (ممنوعیت فوروارد/ذخیره)", "🛡", "bool"),
    ("join_to_send_messages", "عضویت لازم برای ارسال پیام", "✍️", "bool"),
    ("join_by_request", "عضویت با تأیید ادمین", "📝", "bool"),
    ("has_hidden_members", "اعضای پنهان", "🙈", "bool"),
    ("has_aggressive_anti_spam_enabled", "ضداسپم تهاجمی", "🧯", "bool"),
    ("has_visible_history", "تاریخچه برای اعضای جدید قابل‌مشاهده", "📜", "bool"),
    ("can_set_sticker_set", "امکان تنظیم مجموعه‌ی استیکر", "🧩", "bool"),
    ("sticker_set_name", "مجموعه‌ی استیکر گروه", "🧩", "code"),
    ("custom_emoji_sticker_set_name", "مجموعه‌ی ایموجی سفارشی", "😀", "code"),
    ("unrestrict_boost_count", "بوست لازم برای رفع محدودیت", "🚀", "text"),
    ("max_reaction_count", "حداکثر ریاکشن هر پیام", "❤️", "text"),
    ("accent_color_id", "شناسه‌ی رنگ Accent", "🎨", "text"),
    ("profile_accent_color_id", "رنگ Accent پروفایل", "🎨", "text"),
    ("background_custom_emoji_id", "ایموجی پس‌زمینه", "🖼", "code"),
    ("emoji_status_custom_emoji_id", "ایموجی وضعیت", "😎", "code"),
    ("emoji_status_expiration_date", "انقضای ایموجی وضعیت", "⌛", "dt"),
    ("can_send_paid_media", "امکان ارسال رسانه‌ی پولی", "⭐", "bool"),
    ("linked_chat_id", "آیدی چت پیوندشده (کانال/گروه گفتگو)", "🔗", "code"),
]


def render_specs(sec: Section, obj: Any, specs: list[tuple[str, str, str, str]], opts: Options) -> None:
    unsent: list[str] = []
    for attr, label, emoji, kind in specs:
        value = getattr(obj, attr, None)
        if value is None:
            if kind == "bool":
                unsent.append(label)
            continue
        if kind == "bool":
            sec.add_bool(emoji, label, bool(value))
        elif kind == "seconds":
            sec.add(emoji, label, fmt_duration(value), inline=True)
        elif kind == "dt":
            sec.add_dt(emoji, label, value, opts)
        elif kind == "code":
            sec.add(emoji, label, value, as_code=True)
        else:
            sec.add(emoji, label, value, inline=True)
    if unsent and not opts.compact:
        sec.add("⚪", "ارسال‌نشده (معمولاً یعنی غیرفعال)", "، ".join(unsent))


@dataclass
class ChatBundle:
    """Everything collected about a chat; any piece may be missing."""

    ref: Any
    chat: Any = None
    via: str = "id"
    error: Optional[str] = None
    error_exc: Optional[BaseException] = None
    member_count: Optional[int] = None
    member_count_error: Optional[BaseException] = None
    bot_member: Any = None
    bot_member_error: Optional[BaseException] = None
    requester_member: Any = None
    requester_error: Optional[BaseException] = None
    requester_id: Optional[int] = None
    admins: Optional[list] = None
    admins_error: Optional[BaseException] = None
    linked_chat: Any = None
    shared_title: Optional[str] = None
    shared_username: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.chat is not None

    @property
    def chat_id(self) -> Optional[int]:
        if self.chat is not None:
            return int(self.chat.id)
        if isinstance(self.ref, int):
            return self.ref
        return None

    @property
    def access(self) -> str:
        """admin | member | public | none"""
        if self.chat is None:
            return "none"
        status = getattr(self.bot_member, "status", None)
        if status in ("creator", "administrator"):
            return "admin"
        if status == "member" or (status == "restricted" and getattr(self.bot_member, "is_member", False)):
            return "member"
        return "public"

    @property
    def owner(self) -> Optional[User]:
        for admin in self.admins or []:
            if getattr(admin, "status", None) == "creator":
                return admin.user
        return None


BOT_ACCESS_LABELS = {
    "admin": "✅ ربات ادمین این چت است",
    "member": "✅ ربات عضو این چت است (دسترسی محدودتر از ادمین)",
    "public": "⚠️ ربات عضو نیست؛ فقط اطلاعات عمومی چت قابل‌دریافت است",
    "none": "❌ ربات به این چت دسترسی ندارد",
}


async def fetch_chat_bundle(
    bot: Any,
    ref: Any,
    *,
    requester_id: Optional[int] = None,
    want_admins: bool = False,
    username_hint: Optional[str] = None,
    shared_title: Optional[str] = None,
) -> ChatBundle:
    """Fetch chat info using getChat and related methods; never raises."""
    bundle = ChatBundle(ref=ref, requester_id=requester_id, shared_title=shared_title)
    bundle.shared_username = username_hint
    chat, err = await safe_call(bot.get_chat, ref)
    if chat is None and isinstance(ref, int) and username_hint:
        chat2, err2 = await safe_call(bot.get_chat, "@" + username_hint.lstrip("@"))
        if chat2 is not None:
            chat, err = chat2, None
            bundle.via = "username"
    if chat is None:
        bundle.error_exc = err
        bundle.error = explain_error(err) or "خطای نامشخص"
        return bundle
    bundle.chat = chat
    chat_type = getattr(chat, "type", None)
    if not is_chat_like(chat_type):
        return bundle

    count, cerr = await safe_call(bot.get_chat_member_count, chat.id)
    bundle.member_count, bundle.member_count_error = count, cerr

    bot_member, berr = await safe_call(bot.get_chat_member, chat.id, bot.id)
    bundle.bot_member, bundle.bot_member_error = bot_member, berr

    if requester_id:
        member, rerr = await safe_call(bot.get_chat_member, chat.id, requester_id)
        bundle.requester_member, bundle.requester_error = member, rerr

    if want_admins:
        admins, aerr = await safe_call(bot.get_chat_administrators, chat.id)
        bundle.admins = list(admins) if admins is not None else None
        bundle.admins_error = aerr

    linked_id = getattr(chat, "linked_chat_id", None)
    if linked_id:
        linked, _ = await safe_call(bot.get_chat, linked_id)
        bundle.linked_chat = linked
    return bundle


@dataclass
class Ownership:
    code: str
    label: str
    explanation: str
    verified: bool = False


def evaluate_ownership(bundle: ChatBundle, requested_created: bool) -> Ownership:
    """
    Decide the ownership verification result.

    Three independent sources are considered:
      1) getChatMember(chat, user)  -> status creator / administrator / ...
      2) getChatAdministrators      -> owner entry equals the user
      3) the selector flag chat_is_created (client-side filter, not verifiable by the bot)
    """
    uid = bundle.requester_id
    member = bundle.requester_member
    status = getattr(member, "status", None)
    if status == "creator":
        return Ownership("owner", "✅ مالک (Creator) تأیید شد", "getChatMember وضعیت creator را برای شما برگرداند.", True)
    owner = bundle.owner
    if uid and owner is not None and int(owner.id) == int(uid):
        return Ownership("owner", "✅ مالک (Creator) تأیید شد", "در فهرست ادمین‌ها، مالک چت همین حساب است.", True)
    if status == "administrator":
        return Ownership(
            "admin",
            "🛡 ادمین هستید، اما مالک نیستید",
            "شما در این چت ادمین‌اید ولی مالک (Creator) نیستید. «ساخته‌شده توسط شما» با «ادمین بودن» یکی نیست.",
            True,
        )
    if status in ("member", "restricted"):
        return Ownership("member", "👤 عضو چت هستید، نه مالک", "وضعیت شما در چت: عضو.", True)
    if status in ("left", "kicked"):
        return Ownership("none", "❌ عضو این چت نیستید", "وضعیت شما در این چت left/kicked است.", True)
    if owner is not None and uid and int(owner.id) != int(uid):
        return Ownership("not_owner", "❌ مالک چت شما نیستید", "مالک چت کاربر دیگری است.", True)
    if requested_created:
        return Ownership(
            "selected_created",
            "🟡 از فهرست «ساخته‌شده توسط شما» تلگرام انتخاب شده؛ تأیید مستقل ربات ممکن نیست",
            "ربات عضو چت نیست یا اجازه‌ی خواندن وضعیت اعضا را ندارد، پس نمی‌تواند مالکیت را مستقلاً "
            "تأیید کند. برای تأیید قطعی، ربات را به چت اضافه (ترجیحاً ادمین) کنید و دوباره بررسی کنید.",
            False,
        )
    return Ownership(
        "unverified",
        "⚪ وضعیت شما در این چت قابل تأیید نیست",
        "ربات دسترسی کافی برای بررسی وضعیت اعضا ندارد.",
        False,
    )


def describe_reactions(reactions: Any) -> Optional[str]:
    if not reactions:
        return None
    parts = []
    for reaction in reactions:
        emoji = getattr(reaction, "emoji", None)
        if emoji:
            parts.append(emoji)
        elif getattr(reaction, "custom_emoji_id", None):
            parts.append("[custom]")
        else:
            parts.append("⭐")
    return " ".join(parts[:40])


def admin_line(admin: Any) -> str:
    user = admin.user
    status = getattr(admin, "status", None)
    icon = "👑" if status == "creator" else ("🤖" if getattr(user, "is_bot", False) else "🛡")
    pieces = [f"{icon} {user_mention(user)}", f"🆔 {code(user.id)}"]
    if getattr(user, "username", None):
        pieces.append("@" + esc(user.username))
    title = getattr(admin, "custom_title", None)
    if title:
        pieces.append(f"«{esc(trunc(title, 30))}»")
    if getattr(admin, "is_anonymous", None):
        pieces.append("🕶 ناشناس")
    return " │ ".join(pieces)


def build_chat_report(
    bundle: ChatBundle,
    opts: Options,
    *,
    title: str = "اطلاعات چت",
    requested_created: bool = False,
    show_ownership: bool = False,
    request_label: Optional[str] = None,
) -> Report:
    """Build the full professional report for a chat."""
    report = Report(title, "🏛")
    chat = bundle.chat
    if chat is None:
        sec = report.section("دسترسی به چت", "⛔")
        ref = bundle.ref
        sec.add("🆔", "ارجاع درخواست‌شده", ref, as_code=True)
        if isinstance(ref, int):
            forms = chat_id_forms(ref)
            sec.add("🧭", "نوع آیدی", forms["kind"], inline=True)
        sec.add("❌", "نتیجه", bundle.error or "خطای نامشخص")
        if bundle.shared_title:
            sec.add("🏷", "عنوان ارسال‌شده توسط تلگرام (ChatShared)", bundle.shared_title)
        if bundle.shared_username:
            sec.add("🔗", "یوزرنیم ارسال‌شده توسط تلگرام", "@" + bundle.shared_username, as_code=True)
        sec.add_note("ربات نمی‌تواند چتی را که به آن دسترسی ندارد بررسی کند. ربات را عضو چت کنید تا گزارش کامل‌تر شود.")
        if show_ownership:
            own = evaluate_ownership(bundle, requested_created)
            osec = report.section("تأیید مالکیت", "🔐")
            osec.add("📊", "نتیجه", own.label)
            osec.add_note(own.explanation)
        return report.with_status_footer()

    chat_type = getattr(chat, "type", None)
    main = report.section("اطلاعات پایه", "🪪")
    main.add("🆔", "آیدی عددی چت", chat.id, as_code=True)
    forms = chat_id_forms(int(chat.id))
    main.add("🧭", "نوع آیدی", forms["kind"], inline=True)
    if forms["short"] and not opts.compact:
        main.add("🔢", "آیدی کوتاه (فرمت MTProto/لینک t.me/c)", forms["short"], as_code=True)
    main.add("🏷", "نوع چت", type_label(chat_type), inline=True)
    if getattr(chat, "title", None):
        main.add("📛", "عنوان", chat.title)
    else:
        name = " ".join(p for p in (getattr(chat, "first_name", None), getattr(chat, "last_name", None)) if p)
        main.add_opt("👤", "نام", name)
    username = getattr(chat, "username", None)
    if username:
        main.add("🔗", "یوزرنیم", "@" + username, as_code=True)
        main.add("🌐", "لینک عمومی", public_url(username), as_code=True)
    else:
        main.add("🔗", "یوزرنیم", "❌ ندارد (چت خصوصی/بدون یوزرنیم)")
    active = getattr(chat, "active_usernames", None)
    if active and len(active) > 1:
        main.add("🔠", "یوزرنیم‌های فعال", "، ".join("@" + u for u in active))
    main.add_quote("📝", "توضیحات (Description)", getattr(chat, "description", None) or "") if getattr(chat, "description", None) else None
    main.add_opt("👤", "بیو (Bio)", getattr(chat, "bio", None))
    invite = getattr(chat, "invite_link", None)
    if invite:
        main.add("🎟", "لینک دعوت", invite, as_code=True)
    elif is_chat_like(chat_type):
        main.add(
            "🎟",
            "لینک دعوت",
            "⚪ ارسال نشد (فقط وقتی ربات ادمین با دسترسی دعوت باشد، یا لینک ساخته شده باشد، برمی‌گردد)",
        )
    if bundle.via == "username":
        main.add_note("اطلاعات از طریق یوزرنیم عمومی چت دریافت شد (نه با آیدی عددی).")

    if is_chat_like(chat_type):
        if bundle.member_count is not None:
            main.add("👥", "تعداد اعضا", bundle.member_count, inline=True)
        elif bundle.member_count_error is not None:
            main.add("👥", "تعداد اعضا", "⚪ " + explain_error(bundle.member_count_error))
    if bundle.linked_chat is not None:
        main.add(
            "🔗",
            "چت پیوندشده",
            f"{chat_display(bundle.linked_chat)} ({bundle.linked_chat.id})",
            as_code=True,
        )

    features = Section("ویژگی‌ها و تنظیمات", "⚙️")
    render_specs(features, chat, CHAT_FEATURE_SPECS, opts)
    reactions = describe_reactions(getattr(chat, "available_reactions", None))
    if reactions:
        features.add("😍", "ریاکشن‌های مجاز", reactions)
    report.extend([features])

    permissions = getattr(chat, "permissions", None)
    if permissions is not None:
        psec = report.section("مجوزهای پیش‌فرض اعضا", "🔐")
        granted, denied = rights_lines(permissions, PERMISSION_LABELS)
        if granted:
            psec.add("✅", "مجاز", "، ".join(granted))
        if denied:
            psec.add("❌", "غیرمجاز", "، ".join(denied))
        if not granted and not denied:
            psec.add_note("فیلد مجوزی ارسال نشد.")

    pinned = getattr(chat, "pinned_message", None)
    if pinned is not None:
        pin_sec = report.section("پیام پین‌شده", "📌")
        pin_sec.add("🔢", "آیدی پیام", pinned.message_id, as_code=True)
        ptype = primary_type(pinned)
        pin_sec.add("📦", "نوع", MESSAGE_TYPE_LABELS.get(ptype, ("", ptype))[1], inline=True)
        preview = getattr(pinned, "text", None) or getattr(pinned, "caption", None)
        if preview:
            pin_sec.add_quote("💬", "متن", preview, 400)
        pin_sec.add_opt("🔗", "لینک پیام", message_link(chat, pinned.message_id), as_code=True)

    location = getattr(chat, "location", None)
    if location is not None:
        loc_sec = report.section("موقعیت مکانی چت", "📍")
        loc_sec.add_opt("🏠", "آدرس", getattr(location, "address", None))
        geo = getattr(location, "location", None)
        if geo is not None:
            loc_sec.add("🧭", "مختصات", f"{geo.latitude}, {geo.longitude}", as_code=True)
            loc_sec.add("🗺", "نقشه", f"https://www.google.com/maps?q={geo.latitude},{geo.longitude}", as_code=True)

    photo = getattr(chat, "photo", None)
    if photo is not None:
        photo_sec = report.section("عکس چت", "🖼")
        photo_sec.add("✅", "عکس دارد", "بله", inline=True)
        photo_sec.add_opt("🔑", "Big File Unique ID", getattr(photo, "big_file_unique_id", None), as_code=True)
        photo_sec.add_opt("🔑", "Small File Unique ID", getattr(photo, "small_file_unique_id", None), as_code=True)

    # --- وضعیت ربات ---
    if is_chat_like(chat_type):
        access = report.section("وضعیت دسترسی ربات", "🤖")
        access.add("📊", "دسترسی", BOT_ACCESS_LABELS[bundle.access])
        if bundle.bot_member is not None:
            add_member_rows(access, bundle.bot_member, opts, prefix="ربات — ")
        elif bundle.bot_member_error is not None:
            access.add("⚪", "وضعیت ربات", explain_error(bundle.bot_member_error))

    # --- ادمین‌ها ---
    if bundle.admins is not None:
        adm = report.section("مالک و ادمین‌ها", "👮")
        owner = bundle.owner
        if owner is not None:
            adm.add("👑", "مالک (Owner)", admin_line(next(a for a in bundle.admins if a.status == "creator")), raw=True)
        else:
            adm.add("👑", "مالک (Owner)", "⚪ در فهرست برگردانده‌شده نبود")
        adm.add("📊", "تعداد ادمین‌ها", len(bundle.admins), inline=True)
        adm.add_lines("🛡", "فهرست", [admin_line(a) for a in bundle.admins], limit=MAX_ADMINS_SHOWN)
        if not opts.compact:
            detailed = [a for a in bundle.admins if getattr(a, "status", None) == "administrator"][:8]
            for admin in detailed:
                granted, _ = rights_lines(admin, ADMIN_RIGHTS_LABELS)
                if granted:
                    adm.add_raw_row(
                        f"🔑 <b>دسترسی‌های {esc(trunc(user_display(admin.user), 25))}:</b>\n{esc('، '.join(granted))}"
                    )
    elif bundle.admins_error is not None:
        adm = report.section("مالک و ادمین‌ها", "👮")
        adm.add("⚪", "فهرست ادمین‌ها", explain_error(bundle.admins_error))

    # --- مالکیت ---
    if show_ownership:
        own = evaluate_ownership(bundle, requested_created)
        osec = report.section("تأیید مالکیت", "🔐")
        if request_label:
            osec.add("🧲", "روش انتخاب", request_label)
        osec.add("📊", "نتیجه", own.label)
        osec.add("🧾", "توضیح", own.explanation)
        osec.add_note("«ساخته‌شده توسط شما» (Creator) با «دسترسی ادمین» تفاوت دارد.")
    elif bundle.requester_member is not None:
        rsec = report.section("وضعیت شما در این چت", "🙋")
        add_member_rows(rsec, bundle.requester_member, opts)

    if bundle.chat is not None and not opts.compact:
        extra = Section("فیلدهای اضافی نسخه‌ی نصب‌شده‌ی Bot API", "🧪")
        known = {
            "id", "type", "title", "username", "first_name", "last_name", "is_forum", "photo", "description",
            "invite_link", "pinned_message", "permissions", "slow_mode_delay", "linked_chat_id", "location",
            "bio", "active_usernames", "available_reactions", "message_auto_delete_time",
        }
        known |= {spec[0] for spec in CHAT_FEATURE_SPECS}
        known |= {
            "birthdate", "business_intro", "business_location", "business_opening_hours", "personal_chat",
            "has_private_forwards", "has_restricted_voice_and_video_messages", "can_set_sticker_set",
            "accent_color_id", "max_reaction_count", "rating", "unique_gift_colors", "paid_message_star_count",
            "parent_chat", "first_profile_audio", "accepted_gift_types",
        }
        for key, value in safe_to_dict(chat).items():
            if key not in known:
                extra.add("▫️", key, one_line(value, 200), as_code=True)
        if not extra.empty:
            report.extend([extra])
    return report.with_status_footer()


def build_chat_brief_section(bundle: ChatBundle, heading: str = "چت") -> Section:
    """Compact chat block used inside message reports."""
    sec = Section(heading, "🏛")
    chat = bundle.chat
    if chat is None:
        sec.add("🆔", "آیدی چت", bundle.chat_id, as_code=True)
        sec.add("⚪", "اطلاعات چت", bundle.error or UNAVAILABLE)
        return sec
    sec.add("🆔", "آیدی چت", chat.id, as_code=True)
    sec.add("🏷", "نوع", type_label(chat.type), inline=True)
    sec.add_opt("📛", "عنوان", getattr(chat, "title", None))
    if getattr(chat, "username", None):
        sec.add("🔗", "یوزرنیم", "@" + chat.username, as_code=True)
    if bundle.member_count is not None:
        sec.add("👥", "تعداد اعضا", bundle.member_count, inline=True)
    sec.add("🤖", "دسترسی ربات", BOT_ACCESS_LABELS[bundle.access])
    return sec


def build_chat_from_message(chat: Any) -> Section:
    """Minimal chat section built from the Chat object attached to a message (no API call)."""
    sec = Section("چت پیام", "🏛")
    sec.add("🆔", "آیدی چت", chat.id, as_code=True)
    sec.add("🏷", "نوع", type_label(getattr(chat, "type", None)), inline=True)
    sec.add_opt("📛", "عنوان", getattr(chat, "title", None))
    if getattr(chat, "username", None):
        sec.add("🔗", "یوزرنیم", "@" + chat.username, as_code=True)
    sec.add_present_bool("🧵", "تاپیک‌دار", getattr(chat, "is_forum", None))
    return sec


# =========================================================
#                  09 — FORWARD INTELLIGENCE ENGINE
# =========================================================

FORWARD_KIND_LABELS = {
    "user": "👤 کاربر (MessageOriginUser)",
    "hidden_user": "🕶 کاربر مخفی (MessageOriginHiddenUser)",
    "chat": "💬 چت/گروه به‌نام خودش (MessageOriginChat)",
    "channel": "📢 کانال (MessageOriginChannel)",
    "legacy": "🕰 فوروارد قدیمی (فیلدهای Legacy)",
}


@dataclass
class ForwardInfo:
    """Normalised description of Message.forward_origin."""

    present: bool = False
    kind: str = "none"
    origin_type: Optional[str] = None
    date: Optional[datetime] = None
    user: Optional[User] = None
    hidden_name: Optional[str] = None
    chat: Any = None
    message_id: Optional[int] = None
    signature: Optional[str] = None
    auto_forward: bool = False
    legacy: bool = False
    notes: list[str] = field(default_factory=list)


def inspect_forward(message: Message) -> ForwardInfo:
    """Inspect the modern forward_origin; fall back to legacy attributes if needed."""
    info = ForwardInfo()
    info.auto_forward = bool(getattr(message, "is_automatic_forward", False))
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        info.present = True
        info.origin_type = str(getattr(origin, "type", "") or type(origin).__name__)
        info.date = getattr(origin, "date", None)
        sender_user = getattr(origin, "sender_user", None)
        hidden_name = getattr(origin, "sender_user_name", None)
        sender_chat = getattr(origin, "sender_chat", None)
        channel_chat = getattr(origin, "chat", None)
        if sender_user is not None:
            info.kind = "user"
            info.user = sender_user
        elif hidden_name is not None:
            info.kind = "hidden_user"
            info.hidden_name = hidden_name
            info.notes.append(
                "فرستنده‌ی اصلی در تنظیمات حریم خصوصی خود «فوروارد پیام» را مخفی کرده است؛ "
                "آیدی عددی و یوزرنیم او هرگز از طریق Bot API قابل‌دریافت نیست."
            )
        elif sender_chat is not None:
            info.kind = "chat"
            info.chat = sender_chat
            info.signature = getattr(origin, "author_signature", None)
        elif channel_chat is not None:
            info.kind = "channel"
            info.chat = channel_chat
            info.message_id = getattr(origin, "message_id", None)
            info.signature = getattr(origin, "author_signature", None)
        else:
            info.kind = "legacy"
            info.notes.append("نوع forward_origin ناشناخته است (نسخه‌ی جدیدتر Bot API).")
        return info

    # --- Legacy attributes (only used when forward_origin is absent) ---
    legacy_user = getattr(message, "forward_from", None)
    legacy_chat = getattr(message, "forward_from_chat", None)
    legacy_name = getattr(message, "forward_sender_name", None)
    legacy_date = getattr(message, "forward_date", None)
    api_extra = getattr(message, "api_kwargs", None) or {}
    legacy_user = legacy_user or None
    if legacy_date is None and "forward_date" in api_extra:
        legacy_date = api_extra.get("forward_date")
    if legacy_user is not None or legacy_chat is not None or legacy_name or legacy_date:
        info.present = True
        info.legacy = True
        info.kind = "legacy"
        info.origin_type = "legacy"
        info.date = legacy_date if isinstance(legacy_date, datetime) else None
        info.user = legacy_user
        info.chat = legacy_chat
        info.hidden_name = legacy_name
        info.message_id = getattr(message, "forward_from_message_id", None)
        info.signature = getattr(message, "forward_signature", None)
        info.notes.append("این پیام از فیلدهای قدیمی forward_* استفاده می‌کند.")
        if legacy_name and legacy_user is None:
            info.notes.append("فرستنده‌ی اصلی هویت خود را مخفی کرده است؛ شناسایی ممکن نیست.")
    return info


def forward_info_dict(info: ForwardInfo) -> dict[str, Any]:
    if not info.present:
        return {"is_forwarded": False}
    data: dict[str, Any] = {
        "is_forwarded": True,
        "kind": info.kind,
        "origin_type": info.origin_type,
        "date": info.date.isoformat() if isinstance(info.date, datetime) else None,
        "is_automatic_forward": info.auto_forward,
        "legacy": info.legacy,
        "notes": info.notes,
    }
    if info.user is not None:
        data["user"] = get_user_information(info.user)
    if info.hidden_name is not None:
        data["hidden_sender_name"] = info.hidden_name
        data["user_id_available"] = False
    if info.chat is not None:
        data["chat"] = {
            "id": info.chat.id,
            "type": getattr(info.chat, "type", None),
            "title": getattr(info.chat, "title", None),
            "username": getattr(info.chat, "username", None),
        }
    if info.message_id is not None:
        data["original_message_id"] = info.message_id
    if info.signature:
        data["author_signature"] = info.signature
    return data


def add_identity_rows(sec: Section, user: Any, *, prefix: str = "") -> None:
    """Short user identity block reused in many places."""
    if user is None:
        sec.add_missing("👤", f"{prefix}کاربر")
        return
    sec.add("🆔", f"{prefix}آیدی عددی", user.id, as_code=True)
    sec.add("👤", f"{prefix}نام", user_display(user))
    if getattr(user, "username", None):
        sec.add("🔗", f"{prefix}یوزرنیم", "@" + user.username, as_code=True)
    else:
        sec.add("🔗", f"{prefix}یوزرنیم", "❌ ندارد")
    sec.add("🤖", f"{prefix}نوع حساب", "ربات 🤖" if getattr(user, "is_bot", False) else "کاربر عادی", inline=True)
    if user.id in WELL_KNOWN_IDS:
        sec.add("🏷", f"{prefix}حساب شناخته‌شده", WELL_KNOWN_IDS[user.id])


def build_forward_sections(
    info: ForwardInfo,
    opts: Options,
    *,
    origin_user_bundle: Optional[UserBundle] = None,
    origin_chat_bundle: Optional[ChatBundle] = None,
) -> list[Section]:
    """Sections that describe where a forwarded message originally came from."""
    if not info.present:
        return []
    sections: list[Section] = []
    head = Section("اطلاعات فوروارد", "↪️")
    head.add("🧭", "نوع منبع", FORWARD_KIND_LABELS.get(info.kind, info.kind))
    if info.origin_type:
        head.add("🧬", "origin.type", info.origin_type, as_code=True, inline=True)
    head.add_dt("🕰", "زمان ارسال پیام اصلی", info.date, opts)
    if info.date is None:
        head.add("🕰", "زمان ارسال پیام اصلی", "⚪ ارسال نشده")
    if info.auto_forward:
        head.add("🔁", "فوروارد خودکار", "✅ بله — پست کانال که خودکار به گروه گفتگو منتقل شده", inline=False)

    if info.kind in ("user", "legacy") and info.user is not None:
        head.add("📌", "نتیجه", "هویت فرستنده‌ی اصلی در دسترس است ✅")
        sections.append(head)
        bundle = origin_user_bundle or UserBundle(user_id=int(info.user.id), user=info.user)
        sections.extend(build_user_sections(bundle, opts, heading="منبع اصلی — کاربر"))
    elif info.kind == "hidden_user" or (info.kind == "legacy" and info.hidden_name and info.user is None):
        head.add("🕶", "نام نمایشی فرستنده", info.hidden_name, inline=False)
        head.add("🔒", "وضعیت حریم خصوصی", "مخفی — فرستنده فوروارد را پنهان کرده است")
        head.add("🆔", "آیدی عددی", "❌ غیرقابل دریافت (به‌دلیل حریم خصوصی)")
        head.add("🔗", "یوزرنیم", "❌ غیرقابل دریافت (به‌دلیل حریم خصوصی)")
        head.add_warning(
            "ربات هرگز هویت فرستنده‌ی مخفی را شناسایی یا حدس نمی‌زند. نام نمایشی فقط متنی است که "
            "خود فرستنده/تلگرام اعلام کرده و ممکن است با نام واقعی متفاوت باشد."
        )
        sections.append(head)
    elif info.kind in ("chat", "channel", "legacy") and info.chat is not None:
        chat = info.chat
        head.add("🆔", "آیدی چت مبدأ", chat.id, as_code=True)
        head.add("📛", "عنوان", getattr(chat, "title", None) or chat_display(chat))
        head.add("🏷", "نوع چت", type_label(getattr(chat, "type", None)), inline=True)
        if getattr(chat, "username", None):
            head.add("🔗", "یوزرنیم", "@" + chat.username, as_code=True)
            head.add("🌐", "لینک", public_url(chat.username), as_code=True)
        if info.message_id is not None:
            head.add("🔢", "آیدی پیام اصلی در مبدأ", info.message_id, as_code=True)
            link = message_link(chat, info.message_id)
            if link:
                head.add("🔗", "لینک پیام اصلی", link, as_code=True)
        head.add_opt("✍️", "امضای نویسنده (Author Signature)", info.signature)
        if info.kind == "chat":
            head.add_note("پیام توسط یک ادمین ناشناس/چت به‌نام خود چت ارسال شده است؛ آیدی کاربر نویسنده در دسترس نیست.")
        sections.append(head)
        if origin_chat_bundle is not None and origin_chat_bundle.chat is not None:
            sections.append(build_chat_brief_section(origin_chat_bundle, "منبع اصلی — اطلاعات چت"))
        elif origin_chat_bundle is not None and origin_chat_bundle.error:
            note = Section("منبع اصلی — دسترسی به چت", "🏛")
            note.add("⚪", "نتیجه", origin_chat_bundle.error)
            sections.append(note)
    else:
        head.add("⚪", "منبع اصلی", UNAVAILABLE)
        sections.append(head)

    for note in info.notes:
        if sections:
            sections[0].add_note(note)
    return sections


# =========================================================
#                  10 — MESSAGE TYPE PARSERS
# =========================================================

def detect_message_types(message: Message) -> list[str]:
    """Return all content / service keys present on the message (ordered)."""
    found: list[str] = []
    for key in MESSAGE_TYPE_LABELS:
        value = getattr(message, key, None)
        if value is None or value is False:
            continue
        if isinstance(value, (tuple, list)) and not value:
            continue
        if isinstance(value, str) and not value:
            continue
        found.append(key)
    if "animation" in found and "document" in found:
        found.remove("document")          # تلگرام برای گیف هر دو را می‌فرستد
    if "venue" in found and "location" in found:
        found.remove("location")          # برای Venue فیلد location هم پر می‌شود
    return found


def primary_type(message: Message) -> str:
    types = detect_message_types(message)
    return types[0] if types else "unknown"


def type_title(key: str) -> str:
    emoji, label = MESSAGE_TYPE_LABELS.get(key, ("📦", key))
    return f"{emoji} {label}"


def thumb_of(obj: Any) -> Any:
    return getattr(obj, "thumbnail", None) or getattr(obj, "thumb", None)


def add_file_rows(sec: Section, obj: Any, opts: Options, *, label: str = "") -> None:
    """Common file fields: file_id, file_unique_id, file_size."""
    if obj is None:
        return
    prefix = f"{label} — " if label else ""
    sec.add("🔑", f"{prefix}File ID", getattr(obj, "file_id", None), as_code=True)
    sec.add("🧬", f"{prefix}File Unique ID", getattr(obj, "file_unique_id", None), as_code=True)
    size = getattr(obj, "file_size", None)
    if size is not None:
        sec.add("💾", f"{prefix}حجم فایل", f"{fmt_size(size)} ({size} بایت)", inline=True)
        if size > 20 * 1024 * 1024:
            sec.add_note("حجم فایل بیش از ۲۰ مگابایت است و ربات‌ها نمی‌توانند آن را دانلود کنند (ارسال مجدد با File ID ممکن است).")
    else:
        sec.add("💾", f"{prefix}حجم فایل", "⚪ ارسال نشده", inline=True)


def add_thumb_rows(sec: Section, thumb: Any, label: str = "بندانگشتی (Thumbnail)") -> None:
    if thumb is None:
        return
    size = getattr(thumb, "file_size", None)
    dims = f"{getattr(thumb, 'width', '؟')}×{getattr(thumb, 'height', '؟')}"
    text = f"{dims}" + (f" — {fmt_size(size)}" if size else "")
    sec.add("🖼", label, text, inline=True)
    sec.add("🧬", f"{label} — Unique ID", getattr(thumb, "file_unique_id", None), as_code=True)


def add_media_flags(sec: Section, message: Message) -> None:
    sec.add_present_bool("🙈", "پوشش اسپویلر (Spoiler)", getattr(message, "has_media_spoiler", None))
    sec.add_present_bool("⬆️", "کپشن بالای رسانه", getattr(message, "show_caption_above_media", None))
    sec.add_opt("🧷", "شناسه‌ی آلبوم (media_group_id)", getattr(message, "media_group_id", None), as_code=True)


def parse_text(message: Message, opts: Options) -> list[Section]:
    text = message.text or ""
    sec = Section(type_title("text"), "💬")
    sec.add("🔤", "تعداد نویسه", len(text), inline=True)
    sec.add("📏", "تعداد خط", text.count("\n") + 1, inline=True)
    sec.add("🔢", "تعداد کلمه", len(text.split()), inline=True)
    sec.add_quote("📝", "متن پیام", text, 1500)
    options = getattr(message, "link_preview_options", None)
    if options is not None and not opts.compact:
        sec.add_present_bool("🔗", "پیش‌نمایش لینک غیرفعال", getattr(options, "is_disabled", None))
        sec.add_opt("🔗", "آدرس پیش‌نمایش", getattr(options, "url", None), as_code=True)
    return [sec]


def parse_photo(message: Message, opts: Options) -> list[Section]:
    sizes = list(message.photo or [])
    sec = Section(type_title("photo"), "🖼")
    sec.add("🗂", "تعداد اندازه‌های موجود", len(sizes), inline=True)
    if sizes:
        largest = sizes[-1]
        sec.add("📐", "بزرگ‌ترین اندازه", f"{largest.width}×{largest.height}", inline=True)
        add_file_rows(sec, largest, opts, label="بزرگ‌ترین")
        lines = []
        for index, size in enumerate(sizes, start=1):
            fsize = f" — {fmt_size(size.file_size)}" if getattr(size, "file_size", None) else ""
            lines.append(f"▫️ {index}) {size.width}×{size.height}{esc(fsize)} │ {code(short_file_id(size.file_unique_id, 8))}")
        sec.add_lines("🧮", "همه‌ی اندازه‌ها", lines, limit=12)
        if not opts.compact:
            for index, size in enumerate(sizes[:-1], start=1):
                sec.add("🔑", f"File ID اندازه‌ی {index}", size.file_id, as_code=True)
    add_media_flags(sec, message)
    return [sec]


def parse_video(message: Message, opts: Options) -> list[Section]:
    video = message.video
    sec = Section(type_title("video"), "🎬")
    add_file_rows(sec, video, opts)
    sec.add("⏱", "مدت", fmt_duration(getattr(video, "duration", None)), inline=True)
    sec.add("📐", "ابعاد", f"{video.width}×{video.height}", inline=True)
    sec.add_opt("🎞", "MIME Type", getattr(video, "mime_type", None), as_code=True)
    sec.add_opt("📄", "نام فایل", getattr(video, "file_name", None))
    add_thumb_rows(sec, thumb_of(video))
    cover = getattr(video, "cover", None)
    if cover:
        sec.add("🖼", "تعداد تصاویر Cover", len(cover), inline=True)
    sec.add_opt("⏯", "زمان شروع پیش‌فرض (ثانیه)", getattr(video, "start_timestamp", None), inline=True)
    qualities = getattr(video, "qualities", None)
    if qualities:
        sec.add("🎚", "تعداد کیفیت‌های موجود", len(qualities), inline=True)
    add_media_flags(sec, message)
    return [sec]


def parse_animation(message: Message, opts: Options) -> list[Section]:
    anim = message.animation
    sec = Section(type_title("animation"), "🎞")
    add_file_rows(sec, anim, opts)
    sec.add("⏱", "مدت", fmt_duration(getattr(anim, "duration", None)), inline=True)
    sec.add("📐", "ابعاد", f"{anim.width}×{anim.height}", inline=True)
    sec.add_opt("🎞", "MIME Type", getattr(anim, "mime_type", None), as_code=True)
    sec.add_opt("📄", "نام فایل", getattr(anim, "file_name", None))
    add_thumb_rows(sec, thumb_of(anim))
    add_media_flags(sec, message)
    return [sec]


def parse_document(message: Message, opts: Options) -> list[Section]:
    doc = message.document
    sec = Section(type_title("document"), "📄")
    add_file_rows(sec, doc, opts)
    name = getattr(doc, "file_name", None)
    sec.add_opt("📄", "نام فایل", name)
    mime = getattr(doc, "mime_type", None)
    sec.add("🧪", "MIME Type", mime or "⚪ ارسال نشده", as_code=bool(mime), inline=not mime)
    if name:
        ext = Path(name).suffix
        if ext:
            sec.add("🏷", "پسوند", ext, as_code=True, inline=True)
        guess = guess_mime_from_name(name)
        if guess and guess != mime:
            sec.add("🔍", "MIME حدسی از روی پسوند", guess, as_code=True, inline=True)
    add_thumb_rows(sec, thumb_of(doc))
    add_media_flags(sec, message)
    return [sec]


def parse_audio(message: Message, opts: Options) -> list[Section]:
    audio = message.audio
    sec = Section(type_title("audio"), "🎵")
    add_file_rows(sec, audio, opts)
    sec.add("⏱", "مدت", fmt_duration(getattr(audio, "duration", None)), inline=True)
    sec.add_opt("🎤", "خواننده (Performer)", getattr(audio, "performer", None))
    sec.add_opt("🎼", "عنوان (Title)", getattr(audio, "title", None))
    sec.add_opt("📄", "نام فایل", getattr(audio, "file_name", None))
    sec.add_opt("🧪", "MIME Type", getattr(audio, "mime_type", None), as_code=True)
    add_thumb_rows(sec, thumb_of(audio), "کاور آهنگ")
    return [sec]


def parse_voice(message: Message, opts: Options) -> list[Section]:
    voice = message.voice
    sec = Section(type_title("voice"), "🎙")
    add_file_rows(sec, voice, opts)
    sec.add("⏱", "مدت", fmt_duration(getattr(voice, "duration", None)), inline=True)
    sec.add_opt("🧪", "MIME Type", getattr(voice, "mime_type", None), as_code=True)
    waveform = getattr(voice, "waveform", None)
    if waveform:
        preview = ", ".join(str(v) for v in list(waveform)[:24])
        sec.add("📈", "شکل موج (Waveform)", f"{len(waveform)} نمونه — {preview}…", as_code=True)
    else:
        sec.add("📈", "شکل موج (Waveform)", "⚪ Bot API این مقدار را برای ربات‌ها ارسال نمی‌کند")
    return [sec]


def parse_video_note(message: Message, opts: Options) -> list[Section]:
    note = message.video_note
    sec = Section(type_title("video_note"), "⭕")
    add_file_rows(sec, note, opts)
    sec.add("⏱", "مدت", fmt_duration(getattr(note, "duration", None)), inline=True)
    sec.add("📐", "قطر (Length)", f"{note.length}×{note.length}", inline=True)
    add_thumb_rows(sec, thumb_of(note))
    return [sec]


def parse_sticker(message: Message, opts: Options) -> list[Section]:
    sticker = message.sticker
    sec = Section(type_title("sticker"), "🧩")
    sec.add("🆔", "Sticker ID (File Unique ID)", sticker.file_unique_id, as_code=True)
    add_file_rows(sec, sticker, opts)
    sec.add_opt("😀", "ایموجی مرتبط", getattr(sticker, "emoji", None), inline=True)
    sec.add_opt("📚", "نام مجموعه (Set Name)", getattr(sticker, "set_name", None), as_code=True)
    if getattr(sticker, "set_name", None):
        sec.add("🔗", "لینک مجموعه", f"https://t.me/addstickers/{sticker.set_name}", as_code=True)
    sec.add("📐", "ابعاد", f"{sticker.width}×{sticker.height}", inline=True)
    sec.add("🏷", "نوع استیکر", {"regular": "معمولی", "mask": "ماسک", "custom_emoji": "ایموجی سفارشی"}.get(str(sticker.type), sticker.type), inline=True)
    sec.add_bool("🎞", "متحرک (Animated / TGS)", bool(getattr(sticker, "is_animated", False)))
    sec.add_bool("🎬", "ویدیویی (WEBM)", bool(getattr(sticker, "is_video", False)))
    custom_id = getattr(sticker, "custom_emoji_id", None)
    sec.add_bool("😎", "ایموجی سفارشی (Custom Emoji)", bool(custom_id))
    sec.add_opt("🆔", "Custom Emoji ID", custom_id, as_code=True)
    premium = getattr(sticker, "premium_animation", None)
    sec.add_bool("⭐", "دارای انیمیشن پریمیوم", premium is not None)
    if premium is not None:
        sec.add_opt("🔑", "Premium Animation File ID", getattr(premium, "file_id", None), as_code=True)
    sec.add_present_bool("🎨", "نیاز به رنگ‌آمیزی مجدد (Needs Repainting)", getattr(sticker, "needs_repainting", None))
    mask = getattr(sticker, "mask_position", None)
    if mask is not None:
        sec.add("🎭", "موقعیت ماسک", f"{mask.point} (x={mask.x_shift}, y={mask.y_shift}, scale={mask.scale})", as_code=True)
    add_thumb_rows(sec, thumb_of(sticker))
    return [sec]


def map_links(latitude: float, longitude: float) -> list[str]:
    return [
        f"https://www.google.com/maps?q={latitude},{longitude}",
        f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=16/{latitude}/{longitude}",
    ]


def add_location_rows(sec: Section, location: Any) -> None:
    sec.add("🧭", "عرض جغرافیایی (Latitude)", location.latitude, as_code=True)
    sec.add("🧭", "طول جغرافیایی (Longitude)", location.longitude, as_code=True)
    sec.add_opt("🎯", "دقت افقی (متر)", getattr(location, "horizontal_accuracy", None), inline=True)
    live = getattr(location, "live_period", None)
    sec.add("📡", "لوکیشن زنده", "✅ بله" if live else "❌ خیر (لوکیشن ثابت)", inline=True)
    sec.add_opt("⏳", "مدت لوکیشن زنده (ثانیه)", live, inline=True)
    sec.add_opt("🧭", "جهت حرکت (درجه)", getattr(location, "heading", None), inline=True)
    sec.add_opt("📡", "شعاع هشدار مجاورت (متر)", getattr(location, "proximity_alert_radius", None), inline=True)
    for url in map_links(location.latitude, location.longitude):
        sec.add("🗺", "نقشه", url, as_code=True)


def parse_location(message: Message, opts: Options) -> list[Section]:
    sec = Section(type_title("location"), "📍")
    add_location_rows(sec, message.location)
    return [sec]


def parse_venue(message: Message, opts: Options) -> list[Section]:
    venue = message.venue
    sec = Section(type_title("venue"), "🏢")
    sec.add("📛", "عنوان", venue.title)
    sec.add("🏠", "آدرس", venue.address)
    sec.add_opt("🆔", "Foursquare ID", getattr(venue, "foursquare_id", None), as_code=True)
    sec.add_opt("🏷", "Foursquare Type", getattr(venue, "foursquare_type", None), as_code=True)
    sec.add_opt("🆔", "Google Place ID", getattr(venue, "google_place_id", None), as_code=True)
    sec.add_opt("🏷", "Google Place Type", getattr(venue, "google_place_type", None), as_code=True)
    if venue.location is not None:
        add_location_rows(sec, venue.location)
    return [sec]


def parse_contact(message: Message, opts: Options) -> list[Section]:
    contact = message.contact
    sec = Section(type_title("contact"), "📇")
    sec.add("👤", "نام", contact.first_name)
    sec.add_opt("👥", "نام خانوادگی", getattr(contact, "last_name", None))
    sec.add("📞", "شماره تلفن (آنچه در پیام به اشتراک گذاشته شده)", contact.phone_number, as_code=True)
    user_id = getattr(contact, "user_id", None)
    if user_id:
        sec.add("🆔", "آیدی کاربر تلگرام مخاطب", user_id, as_code=True)
        sender = getattr(message, "from_user", None)
        if sender is not None and sender.id == user_id:
            sec.add("✅", "مالکیت", "مخاطب، حساب خودِ فرستنده است (اشتراک شماره‌ی خود)", inline=False)
        else:
            sec.add("ℹ️", "مالکیت", "مخاطب متعلق به شخص دیگری است و صرفاً توسط فرستنده ارسال شده", inline=False)
    else:
        sec.add("🆔", "آیدی کاربر تلگرام مخاطب", "⚪ ارسال نشده (مخاطب حساب تلگرام ندارد یا آیدی‌اش منتشر نشده)")
    vcard = getattr(contact, "vcard", None)
    if vcard:
        sec.add("🪪", "vCard", trunc(vcard, 600), as_code=True)
    sec.add_note("ربات فقط اطلاعاتی را نمایش می‌دهد که خود فرستنده در همین پیام به اشتراک گذاشته است.")
    return [sec]


def describe_poll_option(option: Any, index: int, total: int) -> str:
    votes = getattr(option, "voter_count", 0) or 0
    percent = f" ({votes * 100 // total}%)" if total else ""
    return f"▫️ {index}) {esc(trunc(getattr(option, 'text', ''), 80))} — {votes} رأی{percent}"


def parse_poll(message: Message, opts: Options) -> list[Section]:
    poll = message.poll
    sec = Section(type_title("poll"), "📊")
    sec.add("🆔", "Poll ID", poll.id, as_code=True)
    sec.add("❓", "سؤال", poll.question)
    sec.add("🏷", "نوع", {"regular": "عادی", "quiz": "آزمون (Quiz)"}.get(str(poll.type), poll.type), inline=True)
    sec.add_bool("🕶", "ناشناس (Anonymous)", poll.is_anonymous)
    sec.add_bool("☑️", "چندجوابی", poll.allows_multiple_answers)
    sec.add_bool("🔒", "بسته‌شده", poll.is_closed)
    total = getattr(poll, "total_voter_count", 0) or 0
    sec.add("👥", "مجموع آرا", total, inline=True)
    options = list(poll.options or [])
    sec.add_lines("🗳", "گزینه‌ها", [describe_poll_option(o, i, total) for i, o in enumerate(options, 1)], limit=12)
    correct = getattr(poll, "correct_option_id", None)
    if correct is None:
        ids = getattr(poll, "correct_option_ids", None)
        if ids:
            correct = ", ".join(str(i) for i in ids)
    sec.add_opt("✅", "گزینه‌ی درست (شمارش از ۰)", correct, as_code=True)
    sec.add_opt("💡", "توضیح پاسخ", getattr(poll, "explanation", None))
    sec.add_opt("⏳", "مدت باز بودن (ثانیه)", getattr(poll, "open_period", None), inline=True)
    sec.add_dt("⏱", "زمان بسته‌شدن", getattr(poll, "close_date", None), opts)
    return [sec]


def decode_slot(value: int) -> str:
    v = value - 1
    reels = [v % 4, (v // 4) % 4, v // 16]
    names = [SLOT_SYMBOLS[r] for r in reels]
    jackpot = len(set(reels)) == 1
    return " | ".join(names) + ("  🎉 جکپات!" if jackpot else "")


def parse_dice(message: Message, opts: Options) -> list[Section]:
    dice = message.dice
    sec = Section(type_title("dice"), "🎲")
    sec.add("🎯", "ایموجی", dice.emoji, inline=True)
    sec.add("🔢", "مقدار", dice.value, as_code=True, inline=True)
    rule = DICE_RULES.get(dice.emoji)
    if rule:
        sec.add("📘", "نوع بازی", rule[2], inline=True)
        sec.add("📏", "بازه‌ی مقدار", f"{rule[0]} تا {rule[1]}", inline=True)
    if dice.emoji == "🎰" and 1 <= dice.value <= 64:
        sec.add("🎰", "نتیجه‌ی چرخ‌ها", decode_slot(dice.value))
    sec.add_note("مقدار تاس توسط سرور تلگرام تعیین می‌شود و قابل جعل توسط کاربر نیست.")
    return [sec]


def parse_game(message: Message, opts: Options) -> list[Section]:
    game = message.game
    sec = Section(type_title("game"), "🎮")
    sec.add("📛", "عنوان", game.title)
    sec.add("📝", "توضیحات", game.description)
    sec.add_opt("💬", "متن", getattr(game, "text", None))
    sec.add("🖼", "تعداد تصاویر", len(game.photo or ()), inline=True)
    sec.add_bool("🎞", "دارای انیمیشن", getattr(game, "animation", None) is not None)
    return [sec]


def parse_web_app_data(message: Message, opts: Options) -> list[Section]:
    data = message.web_app_data
    sec = Section(type_title("web_app_data"), "🕸")
    sec.add_opt("🔘", "متن دکمه", getattr(data, "button_text", None))
    sec.add("📦", "داده‌ی ارسالی", trunc(getattr(data, "data", ""), 800), as_code=True)
    return [sec]


def parse_users_shared(message: Message, opts: Options) -> list[Section]:
    shared = message.users_shared
    sec = Section(type_title("users_shared"), "👥")
    sec.add("🔢", "Request ID", shared.request_id, as_code=True, inline=True)
    users = list(getattr(shared, "users", None) or [])
    sec.add("👥", "تعداد کاربران انتخاب‌شده", len(users), inline=True)
    for item in users[:10]:
        sec.add("🆔", "آیدی کاربر", item.user_id, as_code=True)
        name = " ".join(p for p in (getattr(item, "first_name", None), getattr(item, "last_name", None)) if p)
        sec.add_opt("👤", "نام", name)
        if getattr(item, "username", None):
            sec.add("🔗", "یوزرنیم", "@" + item.username, as_code=True)
    return [sec]


def parse_user_shared(message: Message, opts: Options) -> list[Section]:
    item = message.user_shared
    sec = Section(type_title("user_shared"), "👤")
    sec.add("🔢", "Request ID", getattr(item, "request_id", None), as_code=True, inline=True)
    sec.add("🆔", "آیدی کاربر", getattr(item, "user_id", None), as_code=True)
    return [sec]


def parse_chat_shared(message: Message, opts: Options) -> list[Section]:
    shared = message.chat_shared
    sec = Section(type_title("chat_shared"), "🏛")
    sec.add("🔢", "Request ID", shared.request_id, as_code=True, inline=True)
    sec.add("🆔", "آیدی چت", shared.chat_id, as_code=True)
    sec.add_opt("📛", "عنوان", getattr(shared, "title", None))
    if getattr(shared, "username", None):
        sec.add("🔗", "یوزرنیم", "@" + shared.username, as_code=True)
    photo = getattr(shared, "photo", None)
    if photo:
        sec.add("🖼", "تعداد اندازه‌های عکس", len(photo), inline=True)
    return [sec]


def parse_invoice(message: Message, opts: Options) -> list[Section]:
    invoice = message.invoice
    sec = Section(type_title("invoice"), "🧾")
    sec.add("📛", "عنوان", invoice.title)
    sec.add("📝", "توضیحات", invoice.description)
    sec.add("🧷", "Start Parameter", getattr(invoice, "start_parameter", None) or "⚪ ندارد", as_code=True)
    sec.add("💱", "واحد پول", invoice.currency, as_code=True, inline=True)
    sec.add("💰", "مبلغ کل (کوچک‌ترین واحد پول)", invoice.total_amount, as_code=True, inline=True)
    sec.add_note("برای اکثر ارزها مبلغ بر اساس کوچک‌ترین واحد (مثلاً سنت) است؛ برای XTR (Stars) همان تعداد ستاره است.")
    return [sec]


def parse_successful_payment(message: Message, opts: Options) -> list[Section]:
    pay = message.successful_payment
    sec = Section(type_title("successful_payment"), "💳")
    sec.add("💱", "واحد پول", pay.currency, as_code=True, inline=True)
    sec.add("💰", "مبلغ (کوچک‌ترین واحد)", pay.total_amount, as_code=True, inline=True)
    sec.add("📦", "Invoice Payload", trunc(pay.invoice_payload, 200), as_code=True)
    sec.add_opt("🚚", "Shipping Option ID", getattr(pay, "shipping_option_id", None), as_code=True)
    sec.add("🧾", "Telegram Charge ID", pay.telegram_payment_charge_id, as_code=True)
    sec.add_opt("🏦", "Provider Charge ID", getattr(pay, "provider_payment_charge_id", None), as_code=True)
    sec.add_present_bool("🔁", "پرداخت اشتراکی (Recurring)", getattr(pay, "is_recurring", None))
    sec.add_present_bool("1️⃣", "اولین پرداخت اشتراک", getattr(pay, "is_first_recurring", None))
    sec.add_dt("⌛", "انقضای اشتراک", getattr(pay, "subscription_expiration_date", None), opts)
    order = getattr(pay, "order_info", None)
    if order is not None:
        present = [name for name in ("name", "phone_number", "email", "shipping_address") if getattr(order, name, None)]
        sec.add("📬", "فیلدهای ثبت‌شده‌ی Order Info", "، ".join(present) or "خالی")
        sec.add_note("برای حفظ حریم خصوصی، مقدار اطلاعات تماس سفارش نمایش داده نمی‌شود.")
    return [sec]


def parse_refunded_payment(message: Message, opts: Options) -> list[Section]:
    refund = message.refunded_payment
    sec = Section(type_title("refunded_payment"), "↩️")
    sec.add("💱", "واحد پول", getattr(refund, "currency", None), as_code=True, inline=True)
    sec.add("💰", "مبلغ", getattr(refund, "total_amount", None), as_code=True, inline=True)
    sec.add("🧾", "Telegram Charge ID", getattr(refund, "telegram_payment_charge_id", None), as_code=True)
    return [sec]


def parse_passport_data(message: Message, opts: Options) -> list[Section]:
    passport = message.passport_data
    sec = Section(type_title("passport_data"), "🛂")
    elements = list(getattr(passport, "data", None) or [])
    sec.add("🗂", "تعداد المان‌های ارسال‌شده", len(elements), inline=True)
    types = sorted({str(getattr(el, "type", "?")) for el in elements})
    sec.add("📑", "نوع مدارک", "، ".join(types) or "—")
    sec.add_note("محتوای Passport رمزنگاری‌شده است و فقط ربات صاحب کلید خصوصی می‌تواند آن را رمزگشایی کند؛ این ابزار آن را نمایش نمی‌دهد.")
    return [sec]


def user_list_lines(users: Iterable[Any]) -> list[str]:
    lines = []
    for user in users:
        extra = " 🤖" if getattr(user, "is_bot", False) else ""
        uname = f" │ @{esc(user.username)}" if getattr(user, "username", None) else ""
        lines.append(f"▫️ {user_mention(user)}{extra} │ 🆔 {code(user.id)}{uname}")
    return lines


def parse_service(message: Message, key: str, opts: Options) -> list[Section]:
    """Service messages (join / leave / title / photo / pin / topics ...)."""
    sec = Section(type_title(key), "🛎")
    value = getattr(message, key, None)
    if key == "new_chat_members":
        members = list(value or [])
        sec.add("👥", "تعداد", len(members), inline=True)
        sec.add_lines("➕", "اعضای جدید", user_list_lines(members), limit=15)
        adder = getattr(message, "from_user", None)
        if adder is not None and members and all(adder.id != m.id for m in members):
            sec.add("🙋", "اضافه‌کننده", f"{user_mention(adder)} │ {code(adder.id)}", raw=True)
        elif adder is not None and members:
            sec.add("🔗", "روش ورود", "عضویت مستقیم (لینک/جستجو)", inline=True)
    elif key == "left_chat_member":
        sec.add_lines("➖", "عضو خارج‌شده", user_list_lines([value]))
        remover = getattr(message, "from_user", None)
        if remover is not None and remover.id != value.id:
            sec.add("🚫", "حذف‌کننده", f"{user_mention(remover)} │ {code(remover.id)}", raw=True)
    elif key == "new_chat_title":
        sec.add("✏️", "عنوان جدید", value)
    elif key == "new_chat_photo":
        sizes = list(value or [])
        sec.add("🗂", "تعداد اندازه‌ها", len(sizes), inline=True)
        if sizes:
            sec.add("📐", "بزرگ‌ترین", f"{sizes[-1].width}×{sizes[-1].height}", inline=True)
            add_file_rows(sec, sizes[-1], opts)
    elif key == "message_auto_delete_timer_changed":
        seconds = getattr(value, "message_auto_delete_time", 0)
        sec.add("⏳", "تایمر جدید", "خاموش شد" if not seconds else fmt_duration(seconds), inline=True)
    elif key == "migrate_to_chat_id":
        sec.add("🆔", "آیدی سوپرگروه جدید", value, as_code=True)
    elif key == "migrate_from_chat_id":
        sec.add("🆔", "آیدی گروه قدیمی", value, as_code=True)
    elif key == "pinned_message":
        sec.add("🔢", "آیدی پیام پین‌شده", getattr(value, "message_id", None), as_code=True)
        if isinstance(value, Message):
            ptype = primary_type(value)
            sec.add("📦", "نوع پیام پین‌شده", type_title(ptype), inline=True)
            preview = getattr(value, "text", None) or getattr(value, "caption", None)
            if preview:
                sec.add_quote("💬", "متن", preview, 400)
            sec.add_opt("🔗", "لینک", message_link(message.chat, value.message_id), as_code=True)
        else:
            sec.add_note("پیام پین‌شده برای ربات در دسترس نیست (InaccessibleMessage).")
    elif key == "forum_topic_created":
        sec.add("📛", "نام تاپیک", value.name)
        sec.add_opt("🎨", "رنگ آیکون", getattr(value, "icon_color", None), as_code=True)
        sec.add_opt("😀", "Custom Emoji ID آیکون", getattr(value, "icon_custom_emoji_id", None), as_code=True)
    elif key == "forum_topic_edited":
        sec.add_opt("📛", "نام جدید", getattr(value, "name", None))
        sec.add_opt("😀", "Custom Emoji ID جدید", getattr(value, "icon_custom_emoji_id", None), as_code=True)
    elif key == "write_access_allowed":
        sec.add_opt("🕸", "نام وب‌اپ", getattr(value, "web_app_name", None))
        sec.add_present_bool("📎", "از منوی پیوست", getattr(value, "from_attachment_menu", None))
        sec.add_present_bool("🔘", "از درخواست دکمه", getattr(value, "from_request", None))
    elif key == "proximity_alert_triggered":
        sec.add("🚶", "مسافر", f"{user_mention(value.traveler)} │ {code(value.traveler.id)}", raw=True)
        sec.add("👁", "ناظر", f"{user_mention(value.watcher)} │ {code(value.watcher.id)}", raw=True)
        sec.add("📏", "فاصله (متر)", value.distance, inline=True)
    elif key in ("video_chat_started", "video_chat_ended"):
        duration = getattr(value, "duration", None)
        if duration is not None:
            sec.add("⏱", "مدت", fmt_duration(duration), inline=True)
    elif key == "video_chat_scheduled":
        sec.add_dt("🗓", "زمان شروع", getattr(value, "start_date", None), opts)
    elif key == "video_chat_participants_invited":
        sec.add_lines("📨", "دعوت‌شدگان", user_list_lines(getattr(value, "users", []) or []), limit=15)
    elif key == "boost_added":
        sec.add("🚀", "تعداد بوست", getattr(value, "boost_count", None), inline=True)
    elif key in ("group_chat_created", "supergroup_chat_created", "channel_chat_created"):
        creator = getattr(message, "from_user", None)
        sec.add("✅", "رویداد", "چت ساخته شد", inline=True)
        if creator is not None:
            sec.add("👑", "سازنده", f"{user_mention(creator)} │ {code(creator.id)}", raw=True)
    elif key in ("delete_chat_photo", "forum_topic_closed", "forum_topic_reopened",
                 "general_forum_topic_hidden", "general_forum_topic_unhidden"):
        sec.add("✅", "رویداد", "ثبت شد", inline=True)
    else:
        return parse_generic(message, key, opts)
    return [sec]


def parse_generic(message: Message, key: str, opts: Options) -> list[Section]:
    """Fallback parser: dump any other supported field generically (no invented data)."""
    value = getattr(message, key, None)
    sec = Section(type_title(key), "📦")
    data = safe_to_dict(value) if hasattr(value, "to_dict") else value
    pairs = flatten_dict(data, max_depth=2)
    for name, text in pairs[:25]:
        sec.add("▫️", name or key, text, as_code=True)
    if len(pairs) > 25:
        sec.add_note(f"{len(pairs) - 25} فیلد دیگر در خروجی JSON قابل مشاهده است.")
    if sec.empty:
        sec.add("✅", "وضعیت", "فیلد وجود دارد", inline=True)
    return [sec]


PARSER_MAP: dict[str, Callable[[Message, Options], list[Section]]] = {
    "text": parse_text,
    "photo": parse_photo,
    "video": parse_video,
    "animation": parse_animation,
    "document": parse_document,
    "audio": parse_audio,
    "voice": parse_voice,
    "video_note": parse_video_note,
    "sticker": parse_sticker,
    "location": parse_location,
    "venue": parse_venue,
    "contact": parse_contact,
    "poll": parse_poll,
    "dice": parse_dice,
    "game": parse_game,
    "web_app_data": parse_web_app_data,
    "users_shared": parse_users_shared,
    "user_shared": parse_user_shared,
    "chat_shared": parse_chat_shared,
    "invoice": parse_invoice,
    "successful_payment": parse_successful_payment,
    "refunded_payment": parse_refunded_payment,
    "passport_data": parse_passport_data,
}


def parse_message_content(message: Message, opts: Options) -> list[Section]:
    """Run the matching parser for every content/service type present."""
    sections: list[Section] = []
    for key in detect_message_types(message):
        try:
            parser = PARSER_MAP.get(key)
            if parser is not None:
                sections.extend(parser(message, opts))
            elif key in SERVICE_TYPES:
                sections.extend(parse_service(message, key, opts))
            else:
                sections.extend(parse_generic(message, key, opts))
        except Exception as exc:       # یک پیام معیوب هرگز ربات را از کار نمی‌اندازد
            log.warning("Parser failure for %s: %s", key, type(exc).__name__)
            sec = Section(type_title(key), "⚠️")
            sec.add_warning("تحلیل این بخش با خطا مواجه شد؛ جزئیات در خروجی JSON موجود است.")
            sections.append(sec)
    return sections


# ---------------------------------------------------------
#   Entities
# ---------------------------------------------------------

ENTITY_LABELS = {
    "mention": "منشن (@username)",
    "hashtag": "هشتگ",
    "cashtag": "کشتگ ($)",
    "bot_command": "دستور ربات",
    "url": "لینک",
    "email": "ایمیل",
    "phone_number": "شماره تلفن",
    "bold": "درشت",
    "italic": "کج",
    "underline": "زیرخط",
    "strikethrough": "خط‌خورده",
    "spoiler": "اسپویلر",
    "blockquote": "نقل‌قول",
    "expandable_blockquote": "نقل‌قول بازشونده",
    "code": "کد درون‌خطی",
    "pre": "بلوک کد",
    "text_link": "لینک متنی",
    "text_mention": "منشن متنی (با آیدی)",
    "custom_emoji": "ایموجی سفارشی",
}


def build_entities_section(message: Message, opts: Options) -> Optional[Section]:
    if not opts.entities:
        return None
    entities = list(getattr(message, "entities", None) or [])
    source = "متن"
    parsed: dict = {}
    if entities:
        try:
            parsed = message.parse_entities()
        except Exception:
            parsed = {}
    else:
        entities = list(getattr(message, "caption_entities", None) or [])
        source = "کپشن"
        if entities:
            try:
                parsed = message.parse_caption_entities()
            except Exception:
                parsed = {}
    if not entities:
        return None
    sec = Section(f"Entityهای {source}", "🔗")
    counts: dict[str, int] = {}
    for ent in entities:
        counts[str(ent.type)] = counts.get(str(ent.type), 0) + 1
    summary = "، ".join(f"{ENTITY_LABELS.get(k, k)}: {v}" for k, v in counts.items())
    sec.add("📊", "خلاصه", summary)
    lines = []
    for ent in entities[:MAX_ENTITIES_SHOWN]:
        piece = parsed.get(ent, "")
        line = f"▫️ <b>{esc(ENTITY_LABELS.get(str(ent.type), ent.type))}</b> [{ent.offset}:{ent.length}]"
        if piece and str(ent.type) not in ("bold", "italic", "underline", "strikethrough"):
            line += f" {code(trunc(piece, 60))}"
        if getattr(ent, "url", None):
            line += f"\n   ↳ {code(trunc(ent.url, 120))}"
        if getattr(ent, "user", None) is not None:
            line += f"\n   ↳ 🆔 {code(ent.user.id)} {esc(user_display(ent.user))}"
        if getattr(ent, "language", None):
            line += f" ({esc(ent.language)})"
        if getattr(ent, "custom_emoji_id", None):
            line += f"\n   ↳ {code(ent.custom_emoji_id)}"
        lines.append(line)
    sec.add_lines("🧾", "جزئیات", lines, limit=MAX_ENTITIES_SHOWN)
    return sec


# =========================================================
#       11 — MESSAGE / REPLY REPORT BUILDERS & JSON ENGINE
# =========================================================

HANDLED_MESSAGE_KEYS: set[str] = {
    "message_id", "message_thread_id", "direct_messages_topic", "from", "sender_chat",
    "sender_boost_count", "sender_business_bot", "business_connection_id", "date", "chat",
    "forward_origin", "is_topic_message", "is_automatic_forward", "reply_to_message",
    "external_reply", "quote", "reply_to_story", "reply_to_checklist_task_id", "via_bot",
    "edit_date", "has_protected_content", "is_from_offline", "media_group_id",
    "author_signature", "text", "entities", "link_preview_options", "caption",
    "caption_entities", "show_caption_above_media", "has_media_spoiler", "reply_markup",
    "effect_id", "paid_star_count", "is_paid_post", "suggested_post_info", "forward_from",
    "forward_from_chat", "forward_from_message_id", "forward_signature",
    "forward_sender_name", "forward_date", "has_media_spoiler", "story",
} | set(MESSAGE_TYPE_LABELS.keys())


def prefix_titles(sections: Iterable[Section], prefix: str) -> list[Section]:
    result = []
    for sec in sections:
        if sec is None or sec.empty:
            continue
        sec.title = f"{prefix}{sec.title}"
        result.append(sec)
    return result


def summarize_reply_markup(markup: Any) -> Optional[Section]:
    rows = getattr(markup, "inline_keyboard", None)
    if not rows:
        return None
    sec = Section("کیبورد شیشه‌ای پیام (Inline Keyboard)", "⌨️")
    total = sum(len(row) for row in rows)
    sec.add("📊", "ردیف / دکمه", f"{len(rows)} ردیف — {total} دکمه", inline=True)
    lines = []
    for row in rows[:8]:
        for button in row[:4]:
            kind = "callback"
            detail = ""
            if getattr(button, "url", None):
                kind, detail = "لینک", f" → {code(trunc(button.url, 70))}"
            elif getattr(button, "web_app", None):
                kind, detail = "وب‌اپ", f" → {code(trunc(button.web_app.url, 70))}"
            elif getattr(button, "copy_text", None):
                kind = "کپی متن"
            elif getattr(button, "switch_inline_query", None) is not None or \
                    getattr(button, "switch_inline_query_current_chat", None) is not None:
                kind = "Inline"
            elif getattr(button, "pay", None):
                kind = "پرداخت"
            else:
                kind = "Callback"
            lines.append(f"▫️ {esc(trunc(button.text, 30))} <i>({esc(kind)})</i>{detail}")
    sec.add_lines("🔘", "دکمه‌ها", lines, limit=16)
    return sec


def build_sender_section(
    message: Message, opts: Options, forwarded: bool
) -> tuple[Section, list[str]]:
    """Describe who sent the message (user, bot, anonymous admin, channel ...)."""
    sec = Section("فرستنده‌ی پیام در این چت", "🙋")
    notes: list[str] = []
    user = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)
    chat = message.chat
    if forwarded:
        sec.add_note("این بخش مربوط به کسی است که پیام را در این چت فوروارد/ارسال کرده؛ منبع اصلی در بخش «اطلاعات فوروارد» است.")
    if user is not None and user.id == 1087968824 and sender_chat is not None:
        sec.add("🕶", "نوع فرستنده", "ادمین ناشناس گروه (GroupAnonymousBot)")
        sec.add("🆔", "آیدی چتِ فرستنده", sender_chat.id, as_code=True)
        sec.add("📛", "عنوان", chat_display(sender_chat))
        sec.add_note("هویت ادمینِ ناشناس هرگز در Bot API فاش نمی‌شود؛ فقط خود گروه مشخص است.")
        notes.append("anonymous")
    elif sender_chat is not None and (user is None or user.id in (136817688, 777000)):
        sec.add("📢", "نوع فرستنده", "چت/کانال (sender_chat)")
        sec.add("🆔", "آیدی چت فرستنده", sender_chat.id, as_code=True)
        sec.add("🏷", "نوع چت", type_label(getattr(sender_chat, "type", None)), inline=True)
        sec.add("📛", "عنوان", chat_display(sender_chat))
        if getattr(sender_chat, "username", None):
            sec.add("🔗", "یوزرنیم", "@" + sender_chat.username, as_code=True)
        if user is not None:
            add_identity_rows(sec, user, prefix="حساب سیستمی — ")
    elif user is not None:
        add_identity_rows(sec, user)
        if getattr(user, "is_bot", False):
            sec.add("🤖", "هشدار", "نویسنده‌ی این پیام یک ربات است.")
            notes.append("bot")
        if sender_chat is not None:
            sec.add("📢", "ارسال از طرف چت", f"{chat_display(sender_chat)} ({sender_chat.id})", as_code=True)
    else:
        if getattr(chat, "type", None) == "channel":
            reason = "پیام کانال است؛ برای پست‌های کانال، کاربر نویسنده ارسال نمی‌شود (در صورت وجود فقط author_signature)."
        else:
            reason = "فرستنده برای ربات ارسال نشده است (پیام سرویس، ناشناس یا محدودیت Bot API)."
        sec.add("⚪", "فرستنده", reason)
    sec.add_opt("✍️", "امضای نویسنده", getattr(message, "author_signature", None))
    boosts = getattr(message, "sender_boost_count", None)
    sec.add_opt("🚀", "تعداد بوست‌های فرستنده برای این گروه", boosts, inline=True)
    via = getattr(message, "via_bot", None)
    if via is not None:
        sec.add("🤖", "ارسال با ربات (via)", f"@{via.username} │ {via.id}" if via.username else str(via.id), as_code=True)
    return sec, notes


def build_message_info_section(message: Message, opts: Options, types: list[str], notes: list[str]) -> Section:
    sec = Section("اطلاعات پیام", "✉️")
    sec.add("🔢", "آیدی پیام (Message ID)", message.message_id, as_code=True)
    sec.add("📦", "نوع پیام", "، ".join(type_title(t) for t in types) if types else "نامشخص / بدون محتوای قابل‌تشخیص")
    sec.add("🆔", "آیدی چتِ پیام (Chat ID)", message.chat.id, as_code=True)
    sec.add("🏷", "نوع چت", type_label(getattr(message.chat, "type", None)), inline=True)
    sec.add_dt("🕰", "زمان ارسال", getattr(message, "date", None), opts)
    sec.add_dt("✏️", "زمان آخرین ویرایش", getattr(message, "edit_date", None), opts)
    thread = getattr(message, "message_thread_id", None)
    if thread is not None:
        sec.add("🧵", "آیدی تاپیک (Thread ID)", thread, as_code=True)
        sec.add_present_bool("🧵", "پیام داخل تاپیک", getattr(message, "is_topic_message", None))
    sec.add_opt("🔗", "لینک پیام", message_link(message.chat, message.message_id), as_code=True)
    sec.add_present_bool("🛡", "محتوای محافظت‌شده", getattr(message, "has_protected_content", None))
    sec.add_present_bool("🌙", "ارسال آفلاین (Offline)", getattr(message, "is_from_offline", None))
    sec.add_present_bool("🔁", "فوروارد خودکار کانال", getattr(message, "is_automatic_forward", None))
    sec.add_opt("🔗", "Business Connection ID", getattr(message, "business_connection_id", None), as_code=True)
    sec.add_opt("✨", "Effect ID", getattr(message, "effect_id", None), as_code=True)
    sec.add_opt("⭐", "ستاره‌ی پرداختی", getattr(message, "paid_star_count", None), inline=True)
    if "bot" in notes:
        sec.add("🤖", "تشخیص", "پیام توسط ربات نوشته شده است.")
    if getattr(message, "sender_business_bot", None) is not None:
        sec.add("💼", "ربات Business", user_display(message.sender_business_bot), inline=True)

    reply = getattr(message, "reply_to_message", None)
    if reply is not None:
        sec.add("↩️", "ریپلای به پیام شماره‌ی", reply.message_id, as_code=True, inline=True)
        who = getattr(reply, "from_user", None)
        if who is not None:
            sec.add("↩️", "نویسنده‌ی پیام ریپلای‌شده", f"{user_display(who)} ({who.id})", as_code=True)
    quote = getattr(message, "quote", None)
    if quote is not None:
        sec.add_quote("❝", "نقل‌قول (Quote)", getattr(quote, "text", ""), 400)
        sec.add_present_bool("✍️", "نقل‌قول دستی", getattr(quote, "is_manual", None))
    if getattr(message, "reply_to_story", None) is not None:
        story = message.reply_to_story
        sec.add("📖", "ریپلای به استوری", f"{getattr(story.chat, 'id', '؟')} / {getattr(story, 'id', '؟')}", as_code=True)
    return sec


def build_external_reply_section(message: Message, opts: Options) -> Optional[Section]:
    ext = getattr(message, "external_reply", None)
    if ext is None:
        return None
    sec = Section("ریپلای خارجی (به پیامی در چت دیگر)", "🌐")
    sec.add_opt("🔢", "آیدی پیام مقصد", getattr(ext, "message_id", None), as_code=True)
    chat = getattr(ext, "chat", None)
    if chat is not None:
        sec.add("🆔", "آیدی چت مقصد", chat.id, as_code=True)
        sec.add("📛", "عنوان", chat_display(chat))
    origin = getattr(ext, "origin", None)
    if origin is not None:
        sec.add("🧭", "نوع منبع", str(getattr(origin, "type", "?")), inline=True)
        u = getattr(origin, "sender_user", None)
        if u is not None:
            sec.add("🆔", "آیدی نویسنده", u.id, as_code=True)
            sec.add("👤", "نام نویسنده", user_display(u))
    return sec


def unknown_fields_section(message: Message, opts: Options) -> Optional[Section]:
    try:
        keys = set(message.to_dict().keys())
    except Exception:
        return None
    extra = sorted(keys - HANDLED_MESSAGE_KEYS)
    if not extra:
        return None
    sec = Section("فیلدهای اضافی (نسخه‌ی جدیدتر Bot API)", "🧪")
    data = message.to_dict()
    for key in extra[:12]:
        sec.add("▫️", key, one_line(json.dumps(data[key], ensure_ascii=False, default=json_default), 200), as_code=True)
    return sec


def build_message_sections(
    message: Message,
    opts: Options,
    *,
    sender_bundle: Optional[UserBundle] = None,
    origin_user_bundle: Optional[UserBundle] = None,
    origin_chat_bundle: Optional[ChatBundle] = None,
    include_chat: bool = True,
) -> list[Section]:
    """Full structural inspection of one message (sync, no network calls)."""
    types = detect_message_types(message)
    forward = inspect_forward(message)
    sender_sec, notes = build_sender_section(message, opts, forwarded=forward.present)
    sections: list[Section] = [build_message_info_section(message, opts, types, notes)]

    if forward.present:
        sections.extend(build_forward_sections(
            forward, opts, origin_user_bundle=origin_user_bundle, origin_chat_bundle=origin_chat_bundle
        ))

    user = getattr(message, "from_user", None)
    if sender_bundle is not None and user is not None and "anonymous" not in notes:
        heading = "فرستنده‌ی پیام در این چت" + (" (فوروارد‌کننده)" if forward.present else "")
        sections.extend(build_user_sections(sender_bundle, opts, heading=heading))
        if getattr(user, "is_bot", False):
            sections[-1].add("🤖", "تشخیص", "این پیام توسط یک ربات نوشته شده است.")
    else:
        sections.append(sender_sec)

    sections.extend(parse_message_content(message, opts))

    caption = getattr(message, "caption", None)
    if caption:
        cap = Section("کپشن", "📝")
        cap.add("🔤", "تعداد نویسه", len(caption), inline=True)
        cap.add_quote("💬", "متن کپشن", caption, 1500)
        sections.append(cap)

    ent = build_entities_section(message, opts)
    if ent is not None:
        sections.append(ent)

    ext = build_external_reply_section(message, opts)
    if ext is not None:
        sections.append(ext)

    markup = summarize_reply_markup(getattr(message, "reply_markup", None))
    if markup is not None and not opts.compact:
        sections.append(markup)

    if include_chat:
        sections.append(build_chat_from_message(message.chat))

    unknown = unknown_fields_section(message, opts)
    if unknown is not None and not opts.compact:
        sections.append(unknown)
    return [s for s in sections if not s.empty]


async def gather_message_context(
    bot: Any, message: Message, *, deep: bool
) -> dict[str, Any]:
    """Collect async enrichment data for a message (sender / forward origin)."""
    context: dict[str, Any] = {}
    user = getattr(message, "from_user", None)
    if user is not None and deep and user.id != 1087968824 and message.chat.type != "private":
        context["sender_bundle"] = await fetch_user_bundle(bot, user, context_chat=message.chat, deep=True)
    forward = inspect_forward(message)
    if forward.present:
        if forward.user is not None:
            context["origin_user_bundle"] = await fetch_user_bundle(bot, forward.user, deep=deep)
        if forward.chat is not None and deep and forward.kind in ("chat", "channel", "legacy"):
            context["origin_chat_bundle"] = await fetch_chat_bundle(
                bot, forward.chat.id, username_hint=getattr(forward.chat, "username", None)
            )
    return context


async def build_message_report(
    bot: Any,
    message: Message,
    opts: Options,
    *,
    title: str = "گزارش کامل پیام",
    deep: bool = False,
    prefix: str = "",
) -> Report:
    ctx = await gather_message_context(bot, message, deep=deep)
    report = Report(title, "🔎")
    sections = build_message_sections(message, opts, **ctx)
    if prefix:
        sections = prefix_titles(sections, prefix)
    report.extend(sections)
    return report.with_status_footer()


def summarize_message(message: Message) -> str:
    types = detect_message_types(message)
    labels = "، ".join(MESSAGE_TYPE_LABELS.get(t, ("", t))[1] for t in types[:3]) or "نامشخص"
    forward = inspect_forward(message)
    extra = " | فوروارد" if forward.present else ""
    return f"{labels}{extra} | پیام {message.message_id}"


def media_file_ids(message: Message) -> list[tuple[str, str]]:
    """List of (label, file_id) pairs that can be copied or re-sent."""
    pairs: list[tuple[str, str]] = []
    if getattr(message, "photo", None):
        pairs.append(("عکس", message.photo[-1].file_id))
    for key, label in (
        ("video", "ویدیو"), ("animation", "گیف"), ("document", "فایل"), ("audio", "آهنگ"),
        ("voice", "ویس"), ("video_note", "ویدیو پیام"), ("sticker", "استیکر"),
    ):
        obj = getattr(message, key, None)
        if obj is not None and getattr(obj, "file_id", None):
            if key == "document" and getattr(message, "animation", None) is not None:
                continue
            pairs.append((label, obj.file_id))
    return pairs


def media_unique_ids(message: Message) -> list[str]:
    result = []
    if getattr(message, "photo", None):
        result.append(message.photo[-1].file_unique_id)
    for key in ("video", "animation", "document", "audio", "voice", "video_note", "sticker"):
        obj = getattr(message, key, None)
        if obj is not None and getattr(obj, "file_unique_id", None):
            result.append(obj.file_unique_id)
    return result


# ---------------------------------------------------------
#   JSON engine
# ---------------------------------------------------------

def json_meta(kind: str) -> dict[str, Any]:
    return {
        "generated_at": now_utc().isoformat(),
        "bot": {"name": BOT_NAME, "version": BOT_VERSION},
        "kind": kind,
        "source": "Telegram Bot API (فقط داده‌های قابل‌دریافت؛ هیچ فیلدی ساخته نشده است)",
        "unavailable_note": UNAVAILABLE,
    }


def user_info_json(bundle: UserBundle) -> dict[str, Any]:
    data: dict[str, Any] = {"meta": json_meta("user"), "user_id": bundle.user_id}
    if bundle.user is not None:
        data["user"] = get_user_information(bundle.user)
    if bundle.full is not None:
        data["get_chat"] = safe_to_dict(bundle.full)
    elif bundle.full_error is not None:
        data["get_chat_error"] = explain_error(bundle.full_error)
    if bundle.photos_total is not None:
        data["profile_photos_total"] = bundle.photos_total
    if bundle.member is not None:
        data["chat_member"] = safe_to_dict(bundle.member)
    return data


def chat_info_json(bundle: ChatBundle) -> dict[str, Any]:
    data: dict[str, Any] = {"meta": json_meta("chat"), "ref": bundle.ref}
    if bundle.chat is not None:
        data["chat"] = safe_to_dict(bundle.chat)
        data["id_forms"] = chat_id_forms(int(bundle.chat.id))
    else:
        data["error"] = bundle.error
    data["bot_access"] = bundle.access
    data["member_count"] = bundle.member_count
    if bundle.bot_member is not None:
        data["bot_member"] = safe_to_dict(bundle.bot_member)
    if bundle.admins is not None:
        data["administrators"] = [safe_to_dict(a) for a in bundle.admins]
    if bundle.requester_member is not None:
        data["requester_member"] = safe_to_dict(bundle.requester_member)
    return data


def message_info_json(message: Message, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    forward = inspect_forward(message)
    sender = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)
    data: dict[str, Any] = {
        "meta": json_meta("message"),
        "ids": {
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "sender_user_id": sender.id if sender else None,
            "sender_chat_id": sender_chat.id if sender_chat else None,
            "forwarded_sender_id": forward.user.id if forward.user else None,
            "forwarded_source_chat_id": forward.chat.id if forward.chat else None,
            "thread_id": getattr(message, "message_thread_id", None),
        },
        "types": detect_message_types(message),
        "date": message.date.isoformat() if getattr(message, "date", None) else None,
        "sender": get_user_information(sender) if sender else None,
        "forward": forward_info_dict(forward),
        "file_ids": [{"label": l, "file_id": f} for l, f in media_file_ids(message)],
        "raw_message": safe_to_dict(message),
    }
    link = message_link(message.chat, message.message_id)
    if link:
        data["link"] = link
    if extra:
        data.update(extra)
    return data


def json_file(data: Any, filename: str) -> io.BytesIO:
    buffer = io.BytesIO(dumps_json(data).encode("utf-8"))
    buffer.name = filename
    return buffer


# =========================================================
#                  12 — EXTRA TOOLS
# =========================================================

def rle_decode(data: bytes) -> bytes:
    """Run-length decoding used by Telegram file identifiers."""
    result = bytearray()
    pending_zero = False
    for byte in data:
        if pending_zero:
            result.extend(b"\x00" * byte)
            pending_zero = False
        elif byte == 0:
            pending_zero = True
        else:
            result.append(byte)
    return bytes(result)


def decode_file_id(file_id: str) -> Optional[dict[str, Any]]:
    """Best-effort local decoding of a Bot API file_id (type & data-center only)."""
    value = file_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-=]{20,512}", value):
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = rle_decode(raw)
        if len(decoded) < 8:
            return None
        major = decoded[-1]
        minor = decoded[-2] if major >= 4 else 0
        type_raw, dc_id = struct.unpack("<iB", decoded[:5])
        type_id = type_raw & 0x00FFFFFF
        return {
            "type_id": type_id,
            "type_name": FILE_ID_TYPES.get(type_id, f"ناشناخته ({type_id})"),
            "dc_id": dc_id,
            "has_file_reference": bool(type_raw & (1 << 25)),
            "is_web_location": bool(type_raw & (1 << 24)),
            "version": f"{major}.{minor}",
            "decoded_bytes": len(decoded),
            "length": len(value),
            "sha256_prefix": hashlib.sha256(value.encode()).hexdigest()[:16],
        }
    except Exception:
        return None


LINK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private_message", re.compile(r"(?:https?://)?t\.me/c/(\d+)/(?:\d+/)?(\d+)", re.I)),
    ("invite_plus", re.compile(r"(?:https?://)?t\.me/\+([A-Za-z0-9_-]{8,})", re.I)),
    ("invite_joinchat", re.compile(r"(?:https?://)?t\.me/joinchat/([A-Za-z0-9_-]{8,})", re.I)),
    ("sticker_set", re.compile(r"(?:https?://)?t\.me/addstickers/([A-Za-z0-9_]+)", re.I)),
    ("emoji_set", re.compile(r"(?:https?://)?t\.me/addemoji/([A-Za-z0-9_]+)", re.I)),
    ("public_message", re.compile(r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})/(\d+)", re.I)),
    ("tg_user", re.compile(r"tg://user\?id=(\d+)", re.I)),
    ("tg_resolve", re.compile(r"tg://resolve\?domain=([A-Za-z0-9_]+)", re.I)),
    ("username_link", re.compile(r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})(?:\?start=([^\s&]+))?", re.I)),
    ("at_username", re.compile(r"^@([A-Za-z][A-Za-z0-9_]{3,31})$")),
]


def parse_telegram_link(text: str) -> Optional[dict[str, Any]]:
    value = text.strip()
    for kind, pattern in LINK_PATTERNS:
        match = pattern.search(value) if kind != "at_username" else pattern.match(value)
        if not match:
            continue
        groups = match.groups()
        result: dict[str, Any] = {"kind": kind}
        if kind == "private_message":
            result.update(chat_id=int("-100" + groups[0]), short_id=groups[0], message_id=int(groups[1]))
        elif kind in ("invite_plus", "invite_joinchat"):
            result.update(invite_hash=groups[0])
        elif kind in ("sticker_set", "emoji_set"):
            result.update(set_name=groups[0])
        elif kind == "public_message":
            result.update(username=groups[0], message_id=int(groups[1]))
        elif kind == "tg_user":
            result.update(user_id=int(groups[0]))
        elif kind in ("tg_resolve", "at_username"):
            result.update(username=groups[0])
        elif kind == "username_link":
            result.update(username=groups[0], start_param=groups[1] if len(groups) > 1 else None)
        return result
    return None


LINK_KIND_LABELS = {
    "private_message": "پیام در چت خصوصی/بدون یوزرنیم (t.me/c)",
    "invite_plus": "لینک دعوت (t.me/+)",
    "invite_joinchat": "لینک دعوت قدیمی (joinchat)",
    "sticker_set": "مجموعه استیکر",
    "emoji_set": "مجموعه ایموجی",
    "public_message": "پیام در چت عمومی",
    "tg_user": "لینک مستقیم کاربر (tg://user)",
    "tg_resolve": "لینک tg://resolve",
    "username_link": "لینک یوزرنیم",
    "at_username": "یوزرنیم",
}


def convert_chat_id(value: int) -> dict[str, Any]:
    """Explain the forms of a numeric Telegram identifier."""
    text = str(value)
    result: dict[str, Any] = {"input": value}
    if value > 0:
        result["interpretation"] = "آیدی کاربر/ربات یا آیدی کوتاه کانال/سوپرگروه"
        result["as_user_id"] = value
        result["as_channel_bot_api"] = int(f"-100{value}")
        result["as_link_prefix"] = f"https://t.me/c/{value}/<message_id>"
    elif text.startswith("-100"):
        result["interpretation"] = "سوپرگروه یا کانال (فرمت Bot API)"
        result["bot_api"] = value
        result["short_id"] = text[4:]
        result["as_link_prefix"] = f"https://t.me/c/{text[4:]}/<message_id>"
    else:
        result["interpretation"] = "گروه معمولی (فرمت Bot API)"
        result["bot_api"] = value
        result["abs_id"] = abs(value)
        result["note"] = "با ارتقای گروه به سوپرگروه، آیدی عوض می‌شود و آیدی جدید با -100 شروع می‌شود."
    return result


def build_clock_section(opts: Options) -> Section:
    now = now_utc()
    sec = Section("ساعت و تاریخ", "🕒")
    sec.add("🌍", "میلادی (UTC)", to_gregorian_text(now), as_code=True)
    sec.add("🇮🇷", "شمسی (تهران)", to_jalali_text(now), as_code=True)
    sec.add("🔢", "Unix Timestamp", int(now.timestamp()), as_code=True)
    return sec


# =========================================================
#           13 — KEYBOARDS & MESSAGE SENDING HELPERS
# =========================================================

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def btn(text: str, data: str) -> InlineKeyboardButton:
    """Callback button with strict callback_data validation (<= 64 bytes)."""
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data too long: {data[:20]}…")
    return InlineKeyboardButton(text, callback_data=data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=url)


def copy_btn(text: str, value: Any) -> Optional[InlineKeyboardButton]:
    """Native 'copy to clipboard' button (needs python-telegram-bot >= 21.7)."""
    value = str(value)
    if CopyTextButton is None or not (1 <= len(value) <= 256):
        return None
    return InlineKeyboardButton(text, copy_text=CopyTextButton(text=value))


def clean_rows(rows: Iterable[Iterable[Optional[InlineKeyboardButton]]]) -> list[list[InlineKeyboardButton]]:
    cleaned: list[list[InlineKeyboardButton]] = []
    for row in rows:
        items = [b for b in row if b is not None]
        if items:
            cleaned.append(items)
    return cleaned


def kb(rows: Iterable[Iterable[Optional[InlineKeyboardButton]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(clean_rows(rows))


def back_row(target: str = "m:main", text: str = "🔙 منوی اصلی") -> list[InlineKeyboardButton]:
    if target == "x":          # در گروه‌ها «بازگشت» یعنی بستن پیام
        return [btn("✖️ بستن", "x")]
    return [btn(text, target)]


def close_row() -> list[InlineKeyboardButton]:
    return [btn("✖️ بستن", "x")]


def is_owner(user_id: Optional[int]) -> bool:
    return user_id is not None and int(user_id) == int(OWNER_ID)


def kb_main(user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = [
        [btn("👤 اطلاعات حساب من", "m:me"), btn("🔎 بررسی پیام", "m:inspect")],
        [btn("🏛 گروه‌ها و کانال‌های من", "m:chats"), btn("📷 تصاویر پروفایل", "m:photos")],
        [btn("🔍 جستجوی آیدی/یوزرنیم", "t:lookup"), btn("🧰 ابزارها", "m:tools")],
        [btn("📜 تاریخچه", "h:l:0"), btn("⚙️ تنظیمات", "m:settings")],
        [btn("📚 راهنما", "m:help"), btn("ℹ️ درباره", "m:about")],
    ]
    if is_owner(user_id):
        rows.append([btn("👑 پنل مالک ربات", "a:home")])
    return kb(rows)


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MAIN_BUTTONS["me"]), KeyboardButton(MAIN_BUTTONS["inspect"])],
            [KeyboardButton(MAIN_BUTTONS["chats"]), KeyboardButton(MAIN_BUTTONS["photos"])],
            [KeyboardButton(MAIN_BUTTONS["help"]), KeyboardButton(MAIN_BUTTONS["settings"])],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="پیام، فایل یا فوروارد بفرست…",
    )


def kb_help_menu() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    keys = list(HELP_TOPICS.keys())
    for index in range(0, len(keys), 2):
        rows.append([btn(HELP_TOPICS[k][0], f"hp:{k}") for k in keys[index:index + 2]])
    rows.append(back_row())
    return kb(rows)


def kb_help_topic() -> InlineKeyboardMarkup:
    return kb([[btn("📚 فهرست راهنما", "m:help")], back_row()])


def kb_tools() -> InlineKeyboardMarkup:
    return kb([
        [btn("🔍 جستجوی کاربر/چت", "t:lookup"), btn("🔢 تبدیل آیدی چت", "t:convert")],
        [btn("🔗 تحلیل لینک t.me", "t:link"), btn("🧬 رمزگشایی File ID", "t:fid")],
        [btn("🕒 ساعت و تاریخ", "t:clock"), btn("🆔 آیدی‌های من", "t:myids")],
        [btn("👤 انتخاب کاربر/ربات با انتخابگر", "t:pickuser")],
        back_row(),
    ])


def kb_cancel() -> InlineKeyboardMarkup:
    return kb([[btn("✖️ انصراف", "t:cancel")], back_row()])


def kb_inspect_menu() -> InlineKeyboardMarkup:
    return kb([
        [btn("📖 راهنمای بررسی فوروارد", "hp:forward"), btn("🧭 راهنمای /get", "hp:get")],
        [btn("⚠️ چه چیزی قابل دریافت نیست؟", "hp:limits")],
        back_row(),
    ])


def kb_chats_menu(saved_count: int = 0) -> InlineKeyboardMarkup:
    return kb([
        [btn("🧲 باز کردن انتخابگر چت‌ها", "sel:open")],
        [btn(f"📂 چت‌های ذخیره‌شده ({saved_count})", "sc:l:0")],
        [btn("🔍 بررسی چت با آیدی/یوزرنیم", "t:lookup")],
        [btn("ℹ️ توضیح عملکرد", "hp:chats")],
        back_row(),
    ])


def kb_settings(values: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, spec in SETTINGS_SPEC.items():
        current = values.get(key, spec["default"])
        if spec["type"] == "toggle":
            mark = "✅" if current == "1" else "❌"
            text = f"{spec['emoji']} {spec['label']}: {mark}"
        else:
            labels = dict(spec["choices"])
            text = f"{spec['emoji']} {spec['label']}: {labels.get(current, current)}"
        rows.append([btn(text, f"s:t:{key}")])
    rows.append([btn("♻️ بازنشانی تنظیمات", "s:r"), btn("🗑 پاک‌کردن اطلاعات من", "s:w")])
    rows.append(back_row())
    return kb(rows)


def kb_user_actions(
    user_id: int,
    username: Optional[str] = None,
    opts: Optional[Options] = None,
    back: str = "m:main",
    refresh: Optional[str] = None,
) -> list[list[Optional[InlineKeyboardButton]]]:
    opts = opts or DEFAULT_OPTIONS
    rows: list[list[Optional[InlineKeyboardButton]]] = [
        [copy_btn(f"📋 کپی آیدی {user_id}", user_id)],
        [btn("📷 تصاویر پروفایل", f"u:p:{user_id}:0")],
    ]
    if opts.show_json:
        rows[-1].append(btn("🧾 JSON", f"u:j:{user_id}"))
    if username:
        rows.append([url_btn("🌐 باز کردن پروفایل", public_url(username) or "https://t.me")])
    if refresh:
        rows.append([btn("🔄 بروزرسانی", refresh)])
    rows.append(back_row(back))
    return rows


def kb_chat_actions(
    chat_id: int,
    *,
    username: Optional[str] = None,
    invite_link: Optional[str] = None,
    has_photo: bool = False,
    chat_like: bool = True,
    opts: Optional[Options] = None,
    extra_rows: Optional[list[list[Optional[InlineKeyboardButton]]]] = None,
    back: str = "m:main",
) -> list[list[Optional[InlineKeyboardButton]]]:
    opts = opts or DEFAULT_OPTIONS
    rows: list[list[Optional[InlineKeyboardButton]]] = [[copy_btn(f"📋 کپی آیدی چت {chat_id}", chat_id)]]
    if chat_like:
        rows.append([btn("👮 مالک و ادمین‌ها", f"c:a:{chat_id}"), btn("🔄 بروزرسانی", f"c:r:{chat_id}")])
    if has_photo:
        rows.append([btn("🖼 عکس چت", f"c:ph:{chat_id}")])
    if opts.show_json:
        rows.append([btn("🧾 JSON", f"c:j:{chat_id}")])
    if username:
        rows.append([url_btn("🌐 باز کردن چت", public_url(username) or "https://t.me")])
    elif invite_link and invite_link.startswith("https://"):
        rows.append([url_btn("🎟 لینک دعوت", invite_link)])
    if extra_rows:
        rows.extend(extra_rows)
    rows.append(back_row(back))
    return rows


def kb_message_actions(
    message: Message, mkey: str, opts: Options
) -> list[list[Optional[InlineKeyboardButton]]]:
    rows: list[list[Optional[InlineKeyboardButton]]] = []
    for label, file_id in media_file_ids(message)[:2]:
        rows.append([copy_btn(f"📋 کپی File ID ({label})", file_id)])
    uniques = media_unique_ids(message)
    if uniques:
        rows.append([copy_btn("📋 کپی File Unique ID", uniques[0])])
    rows.append([copy_btn(f"📋 کپی آیدی پیام {message.message_id}", message.message_id),
                 copy_btn(f"📋 کپی آیدی چت", message.chat.id)])
    action_row: list[Optional[InlineKeyboardButton]] = []
    if opts.show_json:
        action_row.append(btn("🧾 JSON", f"mj:{mkey}"))
    if media_file_ids(message):
        action_row.append(btn("📥 ارسال مجدد فایل", f"f:{mkey}:s"))
        action_row.append(btn("🧬 رمزگشایی File ID", f"f:{mkey}:d"))
    rows.append(action_row)
    sender = getattr(message, "from_user", None)
    forward = inspect_forward(message)
    people: list[Optional[InlineKeyboardButton]] = []
    if sender is not None and sender.id != 1087968824 and message.chat.type != "private":
        people.append(btn("👤 فرستنده", f"u:v:{sender.id}"))
    if forward.user is not None:
        people.append(btn("↪️ منبع اصلی (کاربر)", f"u:v:{forward.user.id}"))
    if forward.chat is not None:
        people.append(btn("↪️ منبع اصلی (چت)", f"c:v:{forward.chat.id}"))
    rows.append(people)
    if message.chat.type != "private":
        rows.append([btn("🏛 اطلاعات چت", f"c:v:{message.chat.id}")])
    return rows


def kb_history_back() -> list[list[InlineKeyboardButton]]:
    return [[btn("📜 تاریخچه", "h:l:0")], back_row()]


def page_markup(
    key: str, index: int, pages: list[str], rows: Optional[list[list[Optional[InlineKeyboardButton]]]]
) -> InlineKeyboardMarkup:
    nav: list[InlineKeyboardButton] = []
    total = len(pages)
    if total > 1:
        if index > 0:
            nav.append(btn("◀️ قبلی", f"pg:{key}:{index - 1}"))
        nav.append(btn(f"📄 {index + 1}/{total}", f"pg:{key}:0"))
        if index < total - 1:
            nav.append(btn("بعدی ▶️", f"pg:{key}:{index + 1}"))
    all_rows: list[list[Optional[InlineKeyboardButton]]] = []
    if nav:
        all_rows.append(nav)
    all_rows.extend(rows or [])
    return kb(all_rows)


# ---------------------------------------------------------
#   KeyboardButtonRequestChat builders (native chat picker)
# ---------------------------------------------------------

def minimal_admin_rights(**overrides: bool) -> Optional[ChatAdministratorRights]:
    base = dict(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=False,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
    )
    base.update(overrides)
    try:
        return ChatAdministratorRights(**base)
    except TypeError:
        return None


def make_request_chat(
    request_id: int,
    *,
    channel: bool,
    created: Optional[bool] = None,
    forum: Optional[bool] = None,
    has_username: Optional[bool] = None,
    bot_member: Optional[bool] = None,
    user_rights: Optional[ChatAdministratorRights] = None,
    bot_rights: Optional[ChatAdministratorRights] = None,
) -> KeyboardButtonRequestChat:
    """Create a KeyboardButtonRequestChat, degrading gracefully on older library versions."""
    kwargs: dict[str, Any] = {"request_id": request_id, "chat_is_channel": channel}
    if created is not None:
        kwargs["chat_is_created"] = created
    if forum is not None:
        kwargs["chat_is_forum"] = forum
    if has_username is not None:
        kwargs["chat_has_username"] = has_username
    if bot_member is not None:
        kwargs["bot_is_member"] = bot_member
    if user_rights is not None:
        kwargs["user_administrator_rights"] = user_rights
    if bot_rights is not None:
        kwargs["bot_administrator_rights"] = bot_rights
    detailed = dict(kwargs, request_title=True, request_username=True, request_photo=True)
    try:
        return KeyboardButtonRequestChat(**detailed)
    except TypeError:
        return KeyboardButtonRequestChat(**kwargs)


def selector_keyboard(full: bool = True) -> ReplyKeyboardMarkup:
    """The reply keyboard that exposes Telegram's native 'choose chat' pickers."""
    channel_btn = KeyboardButton(
        "📢 کانال‌های ساخته‌شده توسط من",
        request_chat=make_request_chat(RQ_CH_CREATED, channel=True, created=True),
    )
    group_btn = KeyboardButton(
        "👥 گروه‌های ساخته‌شده توسط من",
        request_chat=make_request_chat(RQ_GR_CREATED, channel=False, created=True),
    )
    forum_btn = KeyboardButton(
        "🧵 گروه‌های تاپیک‌دار من",
        request_chat=make_request_chat(RQ_FORUM_CREATED, channel=False, created=True, forum=True),
    )
    public_btn = KeyboardButton(
        "🌐 گروه‌های عمومی ساخته‌شده",
        request_chat=make_request_chat(RQ_GR_PUBLIC_CREATED, channel=False, created=True, has_username=True),
    )
    rights = minimal_admin_rights()
    admin_ch = KeyboardButton(
        "🛡 کانال‌هایی که ادمینم",
        request_chat=make_request_chat(RQ_CH_ADMIN, channel=True, user_rights=rights),
    )
    admin_gr = KeyboardButton(
        "🛡 گروه‌هایی که ادمینم",
        request_chat=make_request_chat(RQ_GR_ADMIN, channel=False, user_rights=rights),
    )
    member_ch = KeyboardButton(
        "🤖 کانال‌های دارای ربات",
        request_chat=make_request_chat(RQ_CH_BOT_MEMBER, channel=True, bot_member=True),
    )
    member_gr = KeyboardButton(
        "🤖 گروه‌های دارای ربات",
        request_chat=make_request_chat(RQ_GR_BOT_MEMBER, channel=False, bot_member=True),
    )
    bot_rights = minimal_admin_rights(can_invite_users=True)
    add_ch = KeyboardButton(
        "📢➕ کانال من + افزودن ربات",
        request_chat=make_request_chat(RQ_CH_ADD_BOT, channel=True, created=True, bot_rights=bot_rights),
    )
    add_gr = KeyboardButton(
        "👥➕ گروه من + افزودن ربات",
        request_chat=make_request_chat(RQ_GR_ADD_BOT, channel=False, created=True, bot_rights=bot_rights),
    )
    rows = [[channel_btn, group_btn]]
    if full:
        rows.append([forum_btn, public_btn])
        if rights is not None:                      # فیلتر ادمین فقط با حقوق معتبر معنا دارد
            rows.append([admin_ch, admin_gr])
        rows.append([member_ch, member_gr])
        if bot_rights is not None:                  # افزودن ربات به‌عنوان ادمین
            rows.append([add_ch, add_gr])
    extra: list[KeyboardButton] = []
    if KeyboardButtonRequestUsers is not None:
        try:
            extra.append(KeyboardButton("👤 انتخاب کاربر", request_users=KeyboardButtonRequestUsers(
                request_id=RQ_USER_ANY, user_is_bot=False, request_name=True, request_username=True)))
            extra.append(KeyboardButton("🤖 انتخاب ربات", request_users=KeyboardButtonRequestUsers(
                request_id=RQ_USER_BOT, user_is_bot=True, request_name=True, request_username=True)))
        except TypeError:
            extra = []
    if extra:
        rows.append(extra)
    rows.append([KeyboardButton("📂 چت‌های ذخیره‌شده"), KeyboardButton(BACK_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="یک چت را از فهرست تلگرام انتخاب کن…",
    )


def user_picker_keyboard() -> Optional[ReplyKeyboardMarkup]:
    if KeyboardButtonRequestUsers is None:
        return None
    try:
        return ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton("👤 انتخاب کاربر", request_users=KeyboardButtonRequestUsers(
                        request_id=RQ_USER_ANY, user_is_bot=False, request_name=True, request_username=True)),
                    KeyboardButton("🤖 انتخاب ربات", request_users=KeyboardButtonRequestUsers(
                        request_id=RQ_USER_BOT, user_is_bot=True, request_name=True, request_username=True)),
                ],
                [
                    KeyboardButton("⭐ انتخاب کاربر پریمیوم", request_users=KeyboardButtonRequestUsers(
                        request_id=RQ_USER_PREMIUM, user_is_bot=False, user_is_premium=True,
                        request_name=True, request_username=True)),
                ],
                [KeyboardButton(BACK_BUTTON_TEXT)],
            ],
            resize_keyboard=True,
            input_field_placeholder="کاربر را از فهرست تلگرام انتخاب کن…",
        )
    except TypeError:
        return None


# ---------------------------------------------------------
#   Sending / editing helpers
# ---------------------------------------------------------

def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def send_html(
    bot: Any,
    chat_id: int,
    text: str,
    markup: Any = None,
    *,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    parse_mode: Optional[str] = ParseMode.HTML,
) -> Optional[Message]:
    """Send a message; on HTML parse failure fall back to plain text."""
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:TG_TEXT_LIMIT],
        "parse_mode": parse_mode,
        "reply_markup": markup,
        "link_preview_options": NO_PREVIEW,
    }
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    if reply_to_id and ReplyParameters is not None:
        kwargs["reply_parameters"] = ReplyParameters(message_id=reply_to_id, allow_sending_without_reply=True)
    message, err = await safe_call(bot.send_message, **kwargs)
    if message is not None:
        return message
    text_err = str(getattr(err, "message", err)).lower()
    if "parse entities" in text_err or "can't parse" in text_err:
        kwargs["text"] = strip_html(text)[:TG_TEXT_LIMIT]
        kwargs["parse_mode"] = None
        message, err = await safe_call(bot.send_message, **kwargs)
        if message is not None:
            return message
    if err is not None and "thread not found" in text_err:
        kwargs.pop("message_thread_id", None)
        message, err = await safe_call(bot.send_message, **kwargs)
        if message is not None:
            return message
    if err is not None:
        log.warning("send_message failed (%s): %s", chat_id, type(err).__name__)
    return None


async def answer_cb(query: Any, text: Optional[str] = None, alert: bool = False) -> None:
    try:
        await query.answer(text=text, show_alert=alert)
    except TelegramError:
        pass


async def edit_or_send(
    bot: Any,
    query: Any,
    text: str,
    markup: Any = None,
) -> Optional[Message]:
    """Edit the callback's message in place; fall back to sending a new message."""
    msg = getattr(query, "message", None)
    if isinstance(msg, Message) and msg.text is not None:
        result, err = await safe_call(
            bot.edit_message_text,
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=text[:TG_TEXT_LIMIT],
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            link_preview_options=NO_PREVIEW,
        )
        if result is not None and isinstance(result, Message):
            return result
        if err is not None and "not modified" in str(err).lower():
            return msg
        if err is not None:
            log.info("edit failed, sending new message: %s", type(err).__name__)
    chat_id = msg.chat.id if msg is not None else query.from_user.id
    thread = getattr(msg, "message_thread_id", None) if isinstance(msg, Message) else None
    return await send_html(bot, chat_id, text, markup, thread_id=thread)


def register_owner(message: Optional[Message], owner_id: Optional[int]) -> None:
    if message is None or owner_id is None:
        return
    if message.chat.type != "private":
        MSG_OWNERS.put(owner_id, key=f"{message.chat.id}:{message.message_id}")


def can_press(query: Any) -> bool:
    """In groups, only the invoking user (or the bot owner) may page/close a report."""
    msg = getattr(query, "message", None)
    if msg is None or msg.chat.type == "private":
        return True
    owner = MSG_OWNERS.get(f"{msg.chat.id}:{msg.message_id}")
    if owner is None:
        return True
    return query.from_user.id in (owner, OWNER_ID)


async def send_report(
    bot: Any,
    chat_id: int,
    report: Any,
    rows: Optional[list[list[Optional[InlineKeyboardButton]]]] = None,
    *,
    reply_to_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    edit_query: Any = None,
    thread_id: Optional[int] = None,
) -> Optional[Message]:
    """Paginate a report and send/edit the first page with glass buttons."""
    pages = report.paginate() if isinstance(report, Report) else list(report)
    key = PAGES.put({"pages": pages, "rows": rows or [], "owner": owner_id})
    markup = page_markup(key, 0, pages, rows)
    if edit_query is not None:
        message = await edit_or_send(bot, edit_query, pages[0], markup)
        if message is not None and owner_id is None and edit_query.from_user:
            owner_id = edit_query.from_user.id
    else:
        message = await send_html(bot, chat_id, pages[0], markup, reply_to_id=reply_to_id, thread_id=thread_id)
    register_owner(message, owner_id)
    return message


async def send_json_payload(
    bot: Any,
    chat_id: int,
    data: Any,
    filename: str,
    *,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
) -> bool:
    """Send JSON inline when short, otherwise as a document."""
    text = dumps_json(data)
    safe_text = html.escape(text, quote=False)
    if len(safe_text) <= 3300:
        sent = await send_html(
            bot,
            chat_id,
            f"🧾 <b>خروجی JSON</b>\n{SEP}\n<pre><code class=\"language-json\">{safe_text}</code></pre>",
            kb([close_row()]),
            reply_to_id=reply_to_id,
            thread_id=thread_id,
        )
        return sent is not None
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "document": json_file(data, filename),
        "caption": f"🧾 خروجی JSON ({fmt_size(len(text.encode('utf-8')))})",
        "reply_markup": kb([close_row()]),
    }
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    if reply_to_id and ReplyParameters is not None:
        kwargs["reply_parameters"] = ReplyParameters(message_id=reply_to_id, allow_sending_without_reply=True)
    result, err = await safe_call(bot.send_document, **kwargs)
    if err is not None:
        log.warning("send_document failed: %s", type(err).__name__)
    return result is not None


def history_text(item: dict[str, Any], opts: Options) -> str:
    created = parse_iso(item.get("created_at"))
    return (
        f"📜 <b>جزئیات رکورد #{item['id']}</b>\n{SEP}\n\n"
        f"🏷 <b>نوع:</b> {esc(HISTORY_KIND_LABELS.get(item.get('kind'), item.get('kind')))}\n\n"
        f"🆔 <b>شناسه‌ی موضوع:</b> {code(item.get('subject_id'))}\n\n"
        f"📛 <b>نام:</b> {esc(item.get('subject_name') or '—')}\n\n"
        f"📝 <b>خلاصه:</b> {esc(item.get('summary') or '—')}\n\n"
        f"🕰 <b>زمان:</b>\n{code(fmt_dt(created, opts))}"
    )


HISTORY_KIND_LABELS = {
    "message": "🔎 بررسی پیام",
    "user": "👤 بررسی کاربر",
    "chat": "🏛 بررسی چت",
    "forward": "↪️ بررسی فوروارد",
    "photo": "📷 تصاویر پروفایل",
    "selected_chat": "🧲 چت انتخابی",
    "id": "🆔 دریافت آیدی",
    "json": "🧾 خروجی JSON",
    "tool": "🧰 ابزار",
}


async def record_history(
    user_id: Optional[int],
    chat_id: Optional[int],
    kind: str,
    subject_id: Optional[int],
    subject_name: Optional[str],
    summary: Optional[str],
    opts: Optional[Options] = None,
) -> None:
    if user_id is None:
        return
    if opts is not None and not opts.save_history:
        return
    await dbx(db_add_history, user_id, chat_id, kind, subject_id, subject_name, summary)
    await dbx(db_bump_stat, f"inspect_{kind}")


# =========================================================
#       14 — PROFILE PHOTO ENGINE + TARGET RESOLUTION
# =========================================================

USERS = LRUStore(800)          # آخرین شیء User دیده‌شده برای هر آیدی


def remember_user(user: Any) -> None:
    if user is not None and getattr(user, "id", None) is not None:
        USERS.put(user, key=str(user.id))


def thread_of(message: Optional[Message]) -> Optional[int]:
    if message is None:
        return None
    if getattr(message, "is_topic_message", False):
        return getattr(message, "message_thread_id", None)
    return None


def effective_reply(message: Optional[Message]) -> Optional[Message]:
    """The replied message, ignoring the implicit 'topic root' reply in forums."""
    if message is None:
        return None
    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return None
    if getattr(reply, "forum_topic_created", None) is not None:
        if reply.message_id == getattr(message, "message_thread_id", None):
            return None
    return reply


def parse_ref(text: str) -> Optional[Any]:
    """Parse a numeric ID, @username or t.me link into int | '@username'."""
    value = (text or "").strip()
    if not value:
        return None
    if re.fullmatch(r"-?\d{1,20}", value):
        return int(value)
    link = parse_telegram_link(value)
    if link:
        if "user_id" in link:
            return int(link["user_id"])
        if link.get("chat_id"):
            return int(link["chat_id"])
        if link.get("username"):
            return "@" + link["username"]
        return None
    match = re.fullmatch(r"@?([A-Za-z][A-Za-z0-9_]{3,31})", value)
    if match:
        return "@" + match.group(1)
    return None


@dataclass
class TempFile:
    path: Path
    size: int
    sha256: str
    mime: Optional[str]
    file_path: Optional[str]


@contextlib.asynccontextmanager
async def temp_download(bot: Any, file_id: str, max_bytes: int = TEMP_MAX_BYTES):
    """Download a Telegram file to a temporary location and always clean it up."""
    file_obj, err = await safe_call(bot.get_file, file_id)
    if file_obj is None:
        raise ValueError(explain_error(err) or "دریافت اطلاعات فایل ممکن نیست")
    declared = getattr(file_obj, "file_size", None)
    if declared is not None and declared > max_bytes:
        raise ValueError(f"حجم فایل ({fmt_size(declared)}) از سقف مجاز موقت ({fmt_size(max_bytes)}) بیشتر است")
    tmp_dir = Path(tempfile.mkdtemp(prefix="tgintel_"))
    suffix = Path(file_obj.file_path or "").suffix or ".bin"
    target = tmp_dir / f"download{suffix}"
    try:
        try:
            await file_obj.download_to_drive(custom_path=target)
        except TelegramError as exc:
            raise ValueError(explain_error(exc)) from exc
        size = target.stat().st_size
        if size > max_bytes:
            raise ValueError("حجم فایل دانلودشده از سقف مجاز بیشتر است")
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        yield TempFile(
            path=target,
            size=size,
            sha256=digest.hexdigest(),
            mime=mimetypes.guess_type(target.name)[0],
            file_path=file_obj.file_path,
        )
    finally:
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            tmp_dir.rmdir()


def photo_nav_rows(user_id: int, index: int, total: int, file_id: str) -> list[list[Optional[InlineKeyboardButton]]]:
    nav: list[InlineKeyboardButton] = []
    if index > 0:
        nav.append(btn("◀️ قبلی", f"ph:n:{user_id}:{index - 1}"))
    nav.append(btn(f"🖼 {index + 1}/{total}", f"ph:n:{user_id}:0"))
    if index < total - 1:
        nav.append(btn("بعدی ▶️", f"ph:n:{user_id}:{index + 1}"))
    return [
        nav,
        [btn("📥 فایل اصلی + هش", f"ph:d:{user_id}:{index}"), btn("🗂 همه‌ی اندازه‌ها", f"ph:i:{user_id}:{index}")],
        [btn("🎞 آلبوم (تا ۱۰ عکس)", f"ph:a:{user_id}"), copy_btn("📋 کپی File ID", file_id)],
        [btn("👤 اطلاعات کاربر", f"u:v:{user_id}")],
        back_row("m:photos", "🔙 بازگشت"),
    ]


def photo_caption(user_id: int, index: int, total: int, sizes: Sequence[Any]) -> str:
    best = sizes[-1]
    lines = [
        f"📷 <b>تصویر پروفایل {index + 1} از {total}</b>",
        SEP,
        f"🆔 <b>آیدی کاربر:</b> {code(user_id)}",
        f"📐 <b>بزرگ‌ترین اندازه:</b> {best.width}×{best.height}",
    ]
    if getattr(best, "file_size", None):
        lines.append(f"💾 <b>حجم:</b> {esc(fmt_size(best.file_size))}")
    lines.append(f"🗂 <b>تعداد اندازه‌ها:</b> {len(sizes)}")
    lines.append(f"🧬 <b>Unique ID:</b> {code(best.file_unique_id)}")
    return "\n".join(lines)[:CAPTION_LIMIT]


async def show_profile_photo(
    bot: Any,
    chat_id: int,
    user_id: int,
    index: int,
    opts: Options,
    *,
    query: Any = None,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    requester_id: Optional[int] = None,
) -> None:
    """Show one profile photo using Telegram's own file system (no external hosting)."""
    index = max(index, 0)
    photos, err = await safe_call(bot.get_user_profile_photos, user_id, offset=index, limit=1)
    if photos is None:
        text = f"📷 <b>تصاویر پروفایل</b>\n{SEP}\n\n⚠️ {esc(explain_error(err))}"
        await send_or_edit_text(bot, chat_id, text, kb([back_row("m:photos", "🔙 بازگشت")]), query, reply_to_id, thread_id)
        return
    total = int(photos.total_count or 0)
    if total == 0:
        text = (
            f"📷 <b>تصاویر پروفایل</b>\n{SEP}\n\n🆔 <b>کاربر:</b> {code(user_id)}\n\n"
            "⚪ هیچ تصویر قابل‌دسترسی‌ای یافت نشد.\n\n"
            "<i>کاربر عکس ندارد یا تنظیمات حریم خصوصی او اجازه‌ی نمایش به ربات‌ها را نمی‌دهد.</i>"
        )
        await send_or_edit_text(bot, chat_id, text, kb([back_row("m:photos", "🔙 بازگشت")]), query, reply_to_id, thread_id)
        return
    if index >= total:
        index = total - 1
        photos, err = await safe_call(bot.get_user_profile_photos, user_id, offset=index, limit=1)
        if photos is None or not photos.photos:
            return
    sizes = photos.photos[0]
    best = sizes[-1]
    caption = photo_caption(user_id, index, total, sizes)
    rows = photo_nav_rows(user_id, index, total, best.file_id)
    markup = kb(rows)
    message = getattr(query, "message", None) if query is not None else None

    if isinstance(message, Message) and message.photo:
        _, merr = await safe_call(
            bot.edit_message_media,
            chat_id=message.chat.id,
            message_id=message.message_id,
            media=InputMediaPhoto(media=best.file_id, caption=caption, parse_mode=ParseMode.HTML),
            reply_markup=markup,
        )
        if merr is None or "not modified" in str(merr).lower():
            return
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": best.file_id,
        "caption": caption,
        "parse_mode": ParseMode.HTML,
        "reply_markup": markup,
    }
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    if reply_to_id and ReplyParameters is not None:
        kwargs["reply_parameters"] = ReplyParameters(message_id=reply_to_id, allow_sending_without_reply=True)
    sent, serr = await safe_call(bot.send_photo, **kwargs)
    if sent is None:
        # fallback: download and upload (Telegram's own storage only)
        try:
            async with temp_download(bot, best.file_id) as tf:
                with tf.path.open("rb") as handle:
                    kwargs["photo"] = handle
                    sent, serr = await safe_call(bot.send_photo, **kwargs)
        except ValueError as exc:
            serr = exc
    if sent is None:
        await send_html(bot, chat_id, f"⚠️ ارسال عکس ممکن نشد: {esc(explain_error(serr) if not isinstance(serr, ValueError) else serr)}",
                        kb([back_row("m:photos", "🔙 بازگشت")]), thread_id=thread_id)
        return
    register_owner(sent, requester_id)
    if query is not None and isinstance(message, Message) and message.text is not None:
        with contextlib.suppress(TelegramError):
            await message.delete()


async def send_or_edit_text(
    bot: Any,
    chat_id: int,
    text: str,
    markup: Any,
    query: Any,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
) -> Optional[Message]:
    if query is not None:
        return await edit_or_send(bot, query, text, markup)
    return await send_html(bot, chat_id, text, markup, reply_to_id=reply_to_id, thread_id=thread_id)


async def photo_sizes_report(bot: Any, chat_id: int, user_id: int, index: int, opts: Options, query: Any) -> None:
    photos, err = await safe_call(bot.get_user_profile_photos, user_id, offset=index, limit=1)
    if photos is None or not photos.photos:
        await send_html(bot, chat_id, f"⚠️ {esc(explain_error(err) or 'تصویری یافت نشد')}", kb([close_row()]))
        return
    sizes = photos.photos[0]
    report = Report("همه‌ی اندازه‌های تصویر پروفایل", "🗂")
    sec = report.section(f"تصویر {index + 1} از {photos.total_count}", "📷")
    for number, size in enumerate(sizes, start=1):
        sec.add("📐", f"اندازه‌ی {number}", f"{size.width}×{size.height}" + (f" — {fmt_size(size.file_size)}" if size.file_size else ""), inline=True)
        sec.add("🔑", f"File ID {number}", size.file_id, as_code=True)
        sec.add("🧬", f"Unique ID {number}", size.file_unique_id, as_code=True)
    await send_report(bot, chat_id, report, [close_row()], owner_id=query.from_user.id if query else None)


async def send_profile_album(bot: Any, chat_id: int, user_id: int, thread_id: Optional[int] = None) -> bool:
    photos, err = await safe_call(bot.get_user_profile_photos, user_id, limit=10)
    if photos is None or not photos.photos:
        await send_html(bot, chat_id, f"⚪ {esc(explain_error(err) or 'تصویری برای ارسال وجود ندارد')}", kb([close_row()]), thread_id=thread_id)
        return False
    media: list[InputMediaPhoto] = []
    for number, sizes in enumerate(photos.photos[:10], start=1):
        caption = f"📷 تصاویر پروفایل — کاربر {user_id} (کل: {photos.total_count})" if number == 1 else None
        media.append(InputMediaPhoto(media=sizes[-1].file_id, caption=caption))
    kwargs: dict[str, Any] = {"chat_id": chat_id, "media": media}
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    result, serr = await safe_call(bot.send_media_group, **kwargs)
    if result is None:
        await send_html(bot, chat_id, f"⚠️ ارسال آلبوم ممکن نشد: {esc(explain_error(serr))}", kb([close_row()]), thread_id=thread_id)
        return False
    return True


async def send_original_photo_file(
    bot: Any, chat_id: int, user_id: int, index: int, thread_id: Optional[int] = None
) -> None:
    """Download a profile photo temporarily, send it as a document with its SHA-256, then clean up."""
    photos, err = await safe_call(bot.get_user_profile_photos, user_id, offset=index, limit=1)
    if photos is None or not photos.photos:
        await send_html(bot, chat_id, f"⚪ {esc(explain_error(err) or 'تصویر یافت نشد')}", kb([close_row()]), thread_id=thread_id)
        return
    best = photos.photos[0][-1]
    try:
        async with temp_download(bot, best.file_id) as tf:
            caption = (
                f"📥 فایل اصلی تصویر پروفایل\n"
                f"👤 کاربر: {user_id}\n"
                f"📐 {best.width}×{best.height} | 💾 {fmt_size(tf.size)}\n"
                f"🧪 {tf.mime or 'نامشخص'}\n"
                f"🔐 SHA-256:\n{tf.sha256}"
            )
            with tf.path.open("rb") as handle:
                kwargs: dict[str, Any] = {
                    "chat_id": chat_id,
                    "document": handle,
                    "filename": f"profile_{user_id}_{index + 1}{tf.path.suffix}",
                    "caption": caption[:CAPTION_LIMIT],
                    "reply_markup": kb([close_row()]),
                }
                if thread_id:
                    kwargs["message_thread_id"] = thread_id
                _, serr = await safe_call(bot.send_document, **kwargs)
        if serr is not None:
            await send_html(bot, chat_id, f"⚠️ {esc(explain_error(serr))}", kb([close_row()]), thread_id=thread_id)
    except ValueError as exc:
        await send_html(bot, chat_id, f"⚠️ {esc(exc)}", kb([close_row()]), thread_id=thread_id)


# =========================================================
#       15 — HANDLERS: PRESENTERS (user / chat / message)
# =========================================================

async def notify(update: Update, text: str, markup: Any = None) -> Optional[Message]:
    chat = update.effective_chat
    msg = update.effective_message
    if chat is None:
        return None
    reply_to = msg.message_id if (msg is not None and chat.type != "private") else None
    return await send_html(
        update.get_bot(), chat.id, text, markup, reply_to_id=reply_to, thread_id=thread_of(msg)
    )


async def throttle(update: Update, bucket: str, limit: int = 8, window: float = 30.0) -> bool:
    user = update.effective_user
    if user is None:
        return True
    wait = RATE.check(user.id, bucket, limit, window)
    if wait <= 0:
        return True
    await notify(update, f"⏳ درخواست‌های زیادی ارسال کردی؛ لطفاً <b>{int(wait) + 1}</b> ثانیه صبر کن.")
    return False


async def present_user(
    bot: Any,
    *,
    chat_id: int,
    requester_id: Optional[int],
    user: Optional[User],
    user_id: Optional[int],
    opts: Options,
    query: Any = None,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    heading: str = "اطلاعات کاربر",
    back: str = "m:main",
    context_chat: Any = None,
) -> None:
    if user is None and user_id is not None:
        user = USERS.get(str(user_id))
    bundle = await fetch_user_bundle(bot, user, user_id=user_id, context_chat=context_chat, deep=True)
    report = Report(heading, "👤")
    report.extend(build_user_sections(bundle, opts, heading="اطلاعات کاربر"))
    report.with_status_footer()
    username = getattr(bundle.user, "username", None) or getattr(bundle.full, "username", None)
    rows = kb_user_actions(bundle.user_id, username, opts, back, refresh=f"u:v:{bundle.user_id}")
    await send_report(
        bot, chat_id, report, rows,
        reply_to_id=reply_to_id, owner_id=requester_id, edit_query=query, thread_id=thread_id,
    )
    name = user_display(bundle.user) if bundle.user is not None else chat_display(bundle.full)
    await record_history(requester_id, chat_id, "user", bundle.user_id, name, "بررسی کاربر", opts)


async def present_chat(
    bot: Any,
    *,
    chat_id: int,
    requester_id: Optional[int],
    ref: Any,
    opts: Options,
    query: Any = None,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    want_admins: bool = False,
    only_admins: bool = False,
    username_hint: Optional[str] = None,
    heading: str = "اطلاعات چت",
    back: str = "m:main",
    extra_rows: Optional[list[list[Optional[InlineKeyboardButton]]]] = None,
) -> ChatBundle:
    bundle = await fetch_chat_bundle(
        bot, ref, requester_id=requester_id, want_admins=want_admins, username_hint=username_hint
    )
    report = build_chat_report(bundle, opts, title=heading)
    if only_admins:
        keep = {"وضعیت دسترسی ربات", "مالک و ادمین‌ها"}
        report.sections = [s for s in report.sections if s.title in keep] or report.sections
        report.title = "مالک و ادمین‌های چت"
    chat = bundle.chat
    if chat is not None:
        rows = kb_chat_actions(
            int(chat.id),
            username=getattr(chat, "username", None),
            invite_link=getattr(chat, "invite_link", None),
            has_photo=getattr(chat, "photo", None) is not None,
            chat_like=is_chat_like(getattr(chat, "type", None)),
            opts=opts,
            extra_rows=extra_rows,
            back=back,
        )
    else:
        rows = [[btn("🔍 جستجوی دیگر", "t:lookup")], back_row(back)]
    await send_report(
        bot, chat_id, report, rows,
        reply_to_id=reply_to_id, owner_id=requester_id, edit_query=query, thread_id=thread_id,
    )
    if chat is not None:
        await record_history(requester_id, chat_id, "chat", int(chat.id), chat_display(chat), type_label(chat.type), opts)
    return bundle


async def assemble_message_report(
    bot: Any,
    message: Message,
    opts: Options,
    *,
    title: str,
    deep: bool,
    chat_brief: bool = False,
) -> Report:
    ctx = await gather_message_context(bot, message, deep=deep)
    sections = build_message_sections(message, opts, include_chat=not chat_brief, **ctx)
    if chat_brief:
        bundle = await fetch_chat_bundle(bot, message.chat.id)
        sections.append(build_chat_brief_section(bundle, "چت پیام"))
    report = Report(title, "🔎")
    report.extend(sections)
    return report.with_status_footer()


async def present_message(
    bot: Any,
    message: Message,
    *,
    chat_id: int,
    requester_id: Optional[int],
    opts: Options,
    title: str,
    deep: bool,
    query: Any = None,
    reply_to_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    kind: str = "message",
    back: str = "m:main",
) -> None:
    group_like = message.chat.type != "private"
    report = await assemble_message_report(bot, message, opts, title=title, deep=deep, chat_brief=group_like and deep)
    mkey = MSGS.put(message)
    rows = kb_message_actions(message, mkey, opts)
    rows.append(back_row(back) if message.chat.type == "private" else close_row())
    await send_report(
        bot, chat_id, report, rows,
        reply_to_id=reply_to_id, owner_id=requester_id, edit_query=query, thread_id=thread_id,
    )
    sender = getattr(message, "from_user", None)
    await record_history(
        requester_id, message.chat.id, kind,
        sender.id if sender else None,
        user_display(sender) if sender else chat_display(message.chat),
        summarize_message(message), opts,
    )


def build_ids_section(
    message: Optional[Message], chat: Any, user: Optional[User], reply: Optional[Message]
) -> Section:
    """The /id card: always separates User ID, Chat ID and Message ID."""
    sec = Section("آیدی‌های عددی", "🆔")
    if user is not None:
        sec.add("👤", "آیدی کاربر (User ID)", user.id, as_code=True)
    else:
        sec.add("👤", "آیدی کاربر (User ID)", "برای این نوع پیام (مثلاً پست کانال) توسط تلگرام ارسال نمی‌شود")
    chat_type = getattr(chat, "type", None)
    label = {
        "private": "آیدی گفتگوی خصوصی (Chat ID)",
        "group": "آیدی گروه (Chat ID)",
        "supergroup": "آیدی سوپرگروه (Chat ID)",
        "channel": "آیدی کانال (Chat ID)",
    }.get(str(chat_type), "آیدی چت (Chat ID)")
    sec.add("🏛", label, chat.id, as_code=True)
    forms = chat_id_forms(int(chat.id))
    sec.add("🧭", "نوع آیدی", forms["kind"], inline=True)
    if forms["short"] and chat_type != "private":
        sec.add("🔢", "آیدی کوتاه (برای لینک t.me/c)", forms["short"], as_code=True)
    if getattr(chat, "title", None):
        sec.add("📛", "نام چت", chat.title)
    if getattr(chat, "username", None):
        sec.add("🔗", "یوزرنیم چت", "@" + chat.username, as_code=True)
    if message is not None:
        sec.add("🔢", "آیدی همین پیام (Message ID)", message.message_id, as_code=True)
        if getattr(message, "sender_chat", None) is not None:
            sec.add("🕶", "آیدی چتِ فرستنده (ادمین ناشناس/کانال)", message.sender_chat.id, as_code=True)
        thread = thread_of(message)
        if thread:
            sec.add("🧵", "آیدی تاپیک (Thread ID)", thread, as_code=True)
    if reply is not None:
        sec.add_raw_row("↩️ <b>— پیام ریپلای‌شده —</b>")
        sec.add("🔢", "آیدی پیام ریپلای‌شده (Message ID)", reply.message_id, as_code=True)
        author = getattr(reply, "from_user", None)
        if author is not None:
            sec.add("👤", "آیدی نویسنده‌ی پیام", author.id, as_code=True)
            sec.add("🏷", "نویسنده", user_display(author) + (" 🤖" if author.is_bot else ""), inline=True)
        if getattr(reply, "sender_chat", None) is not None:
            sec.add("📢", "آیدی چتِ نویسنده (sender_chat)", reply.sender_chat.id, as_code=True)
        forward = inspect_forward(reply)
        if forward.present:
            sec.add_raw_row("↪️ <b>— منبع فوروارد —</b>")
            if forward.user is not None:
                sec.add("👤", "آیدی فرستنده‌ی اصلی فوروارد", forward.user.id, as_code=True)
            elif forward.kind == "hidden_user" or (forward.hidden_name and forward.user is None):
                sec.add("🕶", "فرستنده‌ی اصلی", f"مخفی — نام نمایشی: {forward.hidden_name} (آیدی غیرقابل دریافت)")
            if forward.chat is not None:
                sec.add("🏛", "آیدی چت مبدأ فوروارد", forward.chat.id, as_code=True)
            if forward.message_id is not None:
                sec.add("🔢", "آیدی پیام اصلی در مبدأ", forward.message_id, as_code=True)
    sec.add_note("آیدی کاربر، آیدی چت و آیدی پیام سه مقدار کاملاً متفاوت‌اند و با هم اشتباه گرفته نمی‌شوند.")
    return sec


# =========================================================
#       15b — COMMAND HANDLERS
# =========================================================

def ctx_basics(update: Update) -> tuple[Optional[Message], Any, Optional[User]]:
    return update.effective_message, update.effective_chat, update.effective_user


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if chat is None:
        return
    context.user_data.clear()
    bot = context.bot
    if chat.type == "private":
        if user is not None:
            await dbx(db_upsert_user, user, True)
        await send_html(bot, chat.id, esc(WELCOME_TEXT), main_reply_keyboard())
        await send_html(
            bot, chat.id, f"🧭 <b>منوی اصلی</b>\n{SEP}\n\nیکی از گزینه‌های شیشه‌ای زیر را انتخاب کن:",
            kb_main(user.id if user else None),
        )
        if context.args and context.args[0] == "chats":
            await send_html(bot, chat.id, SELECTOR_INTRO, selector_keyboard())
        return
    username = bot.username
    rows = [
        [btn("🆔 آیدی‌های این چت", f"c:v:{chat.id}")],
        [url_btn("🤖 باز کردن ربات در خصوصی", f"https://t.me/{username}?start=start")] if username else [],
        close_row(),
    ]
    text = (
        f"👋 <b>{esc(BOT_NAME)}</b>\n{SEP}\n\n"
        "در این چت با دستورهای زیر کار می‌کنم:\n"
        "• <code>/id</code> آیدی عددی گروه و اطلاعات کامل آن\n"
        "• <code>/get</code> روی یک پیام (ریپلای) تحلیل کامل پیام\n"
        "• <code>/user</code> یا <code>/info</code> اطلاعات کاربر\n"
        "• <code>/chat</code> اطلاعات چت"
    )
    await send_html(bot, chat.id, text, kb(rows), reply_to_id=msg.message_id if msg else None, thread_id=thread_of(msg))


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if chat is None:
        return
    await send_html(
        context.bot, chat.id, f"🧭 <b>منوی اصلی</b>\n{SEP}\n\nیکی از گزینه‌های شیشه‌ای زیر را انتخاب کن:",
        kb_main(user.id if user else None),
        reply_to_id=msg.message_id if (msg and chat.type != "private") else None,
        thread_id=thread_of(msg),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if chat is None:
        return
    await send_html(
        context.bot, chat.id, f"📚 <b>راهنمای {esc(BOT_NAME)}</b>\n{SEP}\n\nیک موضوع را انتخاب کن:",
        kb_help_menu(),
        reply_to_id=msg.message_id if (msg and chat.type != "private") else None,
        thread_id=thread_of(msg),
    )


def about_text() -> str:
    return ABOUT_TEXT.format(
        name=esc(BOT_NAME),
        version=esc(BOT_VERSION),
        date=esc(VERSION_DATE),
        python=esc(sys.version.split()[0]),
        ptb=esc(getattr(telegram, "__version__", "?")),
        uptime=esc(fmt_uptime(time.time() - START_TIME)),
    )


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if chat is None:
        return
    await send_html(
        context.bot, chat.id, about_text(), kb([back_row("m:main"), close_row()]) if chat.type == "private" else kb([close_row()]),
        reply_to_id=msg.message_id if (msg and chat.type != "private") else None,
        thread_id=thread_of(msg),
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "id", 10, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    reply = effective_reply(msg)
    report = Report("آیدی‌های عددی", "🆔")
    report.sections.append(build_ids_section(msg, chat, user, reply))
    extra: list[list[Optional[InlineKeyboardButton]]] = []
    if user is not None:
        extra.append([copy_btn(f"📋 کپی آیدی من {user.id}", user.id)])
    if reply is not None:
        mkey = MSGS.put(reply)
        extra.append([btn("🔎 بررسی کامل پیام ریپلای‌شده", f"mi:{mkey}")])
        if getattr(reply, "message_id", None):
            extra.append([copy_btn(f"📋 کپی آیدی پیام {reply.message_id}", reply.message_id)])

    if chat.type == "private":
        rows = [[copy_btn(f"📋 کپی آیدی چت {chat.id}", chat.id)]] + extra
        if user is not None:
            rows.append([btn("👤 اطلاعات کامل من", f"u:v:{user.id}")])
        rows.append(back_row())
    else:
        bundle = await fetch_chat_bundle(bot, chat.id, requester_id=user.id if user else None)
        chat_report = build_chat_report(bundle, opts, title="اطلاعات گروه")
        report.sections.extend(chat_report.sections)
        rows = kb_chat_actions(
            int(chat.id),
            username=getattr(bundle.chat or chat, "username", None),
            invite_link=getattr(bundle.chat, "invite_link", None) if bundle.chat else None,
            has_photo=bool(bundle.chat is not None and getattr(bundle.chat, "photo", None)),
            chat_like=is_chat_like(chat.type),
            opts=opts,
            extra_rows=extra,
            back="x",
        )
        rows = [r for r in rows if not (len(r) == 1 and r[0] is not None and r[0].callback_data == "x")]
        rows.append(close_row())
    report.with_status_footer()
    await send_report(
        bot, chat.id, report, rows,
        reply_to_id=msg.message_id if chat.type != "private" else None,
        owner_id=user.id if user else None, thread_id=thread_of(msg),
    )
    await record_history(user.id if user else None, chat.id, "id", chat.id, chat_display(chat), "دریافت آیدی", opts)


async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The main command — behaves according to the 8 rules of the specification."""
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "get", 8, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    reply = effective_reply(msg)
    thread = thread_of(msg)
    reply_to = msg.message_id if chat.type != "private" else None

    if reply is not None:
        await present_message(
            bot, reply, chat_id=chat.id, requester_id=user.id if user else None, opts=opts,
            title="نتیجه‌ی /get — بررسی پیام ریپلای‌شده", deep=True,
            reply_to_id=reply_to, thread_id=thread, kind="forward" if inspect_forward(reply).present else "message",
        )
        return

    if chat.type == "private":
        if user is None:
            await notify(update, "⚠️ کاربر شناسایی نشد.")
            return
        await present_user(
            bot, chat_id=chat.id, requester_id=user.id, user=user, user_id=user.id, opts=opts,
            heading="اطلاعات حساب شما",
        )
        return

    # group / supergroup / channel without reply: chat report (+ requester section)
    extra = []
    if user is not None:
        extra.append([btn("👤 اطلاعات من", f"u:v:{user.id}")])
    extra.append(close_row())
    bundle = await present_chat(
        bot, chat_id=chat.id, requester_id=user.id if user else None, ref=chat.id, opts=opts,
        reply_to_id=reply_to, thread_id=thread, heading="نتیجه‌ی /get — اطلاعات چت",
        username_hint=getattr(chat, "username", None), extra_rows=extra, back="x",
    )


async def resolve_user_arg(
    bot: Any, update: Update, args: Sequence[str]
) -> tuple[Optional[User], Optional[int], Optional[str]]:
    msg, chat, user = ctx_basics(update)
    if args:
        ref = parse_ref(" ".join(args))
        if ref is None:
            return None, None, "فرمت ورودی نامعتبر است. آیدی عددی یا @username بفرست."
        if isinstance(ref, int):
            if ref <= 0:
                return None, None, "آیدی کاربر باید عددی مثبت باشد. برای گروه/کانال از /chat استفاده کن."
            known = user if (user is not None and user.id == ref) else USERS.get(str(ref))
            return known, ref, None
        cached = await dbx(db_find_cached_username, ref, _default=None)
        if cached:
            return USERS.get(str(cached["user_id"])), int(cached["user_id"]), None
        found, err = await safe_call(bot.get_chat, ref)
        if found is None:
            return None, None, explain_error(err)
        if found.type != "private":
            return None, None, "این یوزرنیم متعلق به یک گروه/کانال است؛ از /chat استفاده کن."
        return None, int(found.id), None
    reply = effective_reply(msg)
    if reply is not None:
        author = getattr(reply, "from_user", None)
        if author is not None and author.id != 1087968824:
            return author, author.id, None
        return None, None, "نویسنده‌ی کاربر برای این پیام در دسترس نیست (پست کانال یا ادمین ناشناس)."
    if user is not None:
        return user, user.id, None
    return None, None, "کاربر شناسایی نشد."


async def cmd_user_like(update: Update, context: ContextTypes.DEFAULT_TYPE, heading: str, force_full: bool = False) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "user", 8, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    if force_full:
        opts = Options(**{**opts.__dict__, "detail": "full"})
    target, target_id, error = await resolve_user_arg(bot, update, context.args or [])
    if error or target_id is None:
        await notify(update, f"⚠️ {esc(error or 'کاربر پیدا نشد')}")
        return
    await present_user(
        bot, chat_id=chat.id, requester_id=user.id if user else None, user=target, user_id=target_id,
        opts=opts, reply_to_id=msg.message_id if chat.type != "private" else None, thread_id=thread_of(msg),
        heading=heading, context_chat=chat if chat.type != "private" else None,
        back="m:main" if chat.type == "private" else "x",
    )


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_user_like(update, context, "اطلاعات کاربر")


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_user_like(update, context, "گزارش کامل کاربر", force_full=True)


async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "chat", 8, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    hint: Optional[str] = None
    ref: Any = None
    if context.args:
        ref = parse_ref(" ".join(context.args))
        if ref is None:
            await notify(update, "⚠️ فرمت نامعتبر است. آیدی عددی (مثل <code>-100123…</code>) یا @username بفرست.")
            return
    else:
        reply = effective_reply(msg)
        if reply is not None:
            forward = inspect_forward(reply)
            if forward.chat is not None:
                ref, hint = forward.chat.id, getattr(forward.chat, "username", None)
            elif getattr(reply, "sender_chat", None) is not None:
                ref, hint = reply.sender_chat.id, getattr(reply.sender_chat, "username", None)
            else:
                ref, hint = reply.chat.id, getattr(reply.chat, "username", None)
        elif chat.type == "private":
            await notify(
                update,
                "ℹ️ در گفتگوی خصوصی آیدی یا یوزرنیم چت را بعد از دستور بنویس، مثلاً:\n"
                "<code>/chat @channelname</code>\nیا از منوی «🏛 گروه‌ها و کانال‌های من» استفاده کن.",
                kb([[btn("🏛 گروه‌ها و کانال‌های من", "m:chats")], back_row()]),
            )
            return
        else:
            ref, hint = chat.id, getattr(chat, "username", None)
    if isinstance(ref, str):
        found, err = await safe_call(bot.get_chat, ref)
        if found is None:
            await notify(update, f"⚠️ {esc(explain_error(err))}")
            return
        ref = int(found.id)
        hint = getattr(found, "username", None)
        if found.type == "private":
            await present_user(
                bot, chat_id=chat.id, requester_id=user.id if user else None, user=None, user_id=ref, opts=opts,
                reply_to_id=msg.message_id if chat.type != "private" else None, thread_id=thread_of(msg),
            )
            return
    await present_chat(
        bot, chat_id=chat.id, requester_id=user.id if user else None, ref=ref, opts=opts,
        reply_to_id=msg.message_id if chat.type != "private" else None, thread_id=thread_of(msg),
        username_hint=hint, back="m:main" if chat.type == "private" else "x",
    )


async def cmd_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "forward", 8, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    target = effective_reply(msg)
    if target is None:
        await notify(
            update,
            "↪️ برای تحلیل فوروارد، روی یک <b>پیام فوروارد‌شده</b> ریپلای کن و <code>/forward</code> بزن.\n"
            "در خصوصی ربات هم می‌توانی خود پیام را مستقیم فوروارد کنی.",
            kb([[btn("📖 راهنمای فوروارد", "hp:forward")], back_row()]),
        )
        return
    info = inspect_forward(target)
    if not info.present:
        await notify(
            update,
            "⚪ پیام ریپلای‌شده فوروارد نیست (فیلد <code>forward_origin</code> در آن وجود ندارد).",
            kb([[btn("🔎 بررسی کامل همین پیام", f"mi:{MSGS.put(target)}")], close_row()]),
        )
        return
    origin_user = await fetch_user_bundle(bot, info.user, deep=True) if info.user is not None else None
    origin_chat = None
    if info.chat is not None:
        origin_chat = await fetch_chat_bundle(bot, info.chat.id, username_hint=getattr(info.chat, "username", None))
    report = Report("تحلیل پیام فوروارد‌شده", "↪️")
    report.extend(build_forward_sections(info, opts, origin_user_bundle=origin_user, origin_chat_bundle=origin_chat))
    forwarder = getattr(target, "from_user", None)
    if forwarder is not None:
        sec = Section("کسی که پیام را در این چت فوروارد کرده", "🙋")
        add_identity_rows(sec, forwarder)
        report.extend([sec])
    brief = Section("پیام", "✉️")
    brief.add("🔢", "آیدی پیام (Message ID)", target.message_id, as_code=True)
    brief.add("📦", "نوع", type_title(primary_type(target)), inline=True)
    brief.add_dt("🕰", "زمان فوروارد در این چت", getattr(target, "date", None), opts)
    report.extend([brief])
    report.with_status_footer()
    mkey = MSGS.put(target)
    rows: list[list[Optional[InlineKeyboardButton]]] = []
    if info.user is not None:
        rows.append([btn("👤 گزارش کامل منبع اصلی", f"u:v:{info.user.id}")])
    if info.chat is not None:
        rows.append([btn("🏛 گزارش کامل چت مبدأ", f"c:v:{info.chat.id}")])
    rows.append([btn("🔎 بررسی کامل پیام", f"mi:{mkey}")])
    if opts.show_json:
        rows.append([btn("🧾 JSON", f"mj:{mkey}")])
    rows.append(back_row() if chat.type == "private" else close_row())
    await send_report(
        bot, chat.id, report, rows, reply_to_id=msg.message_id if chat.type != "private" else None,
        owner_id=user.id if user else None, thread_id=thread_of(msg),
    )
    await record_history(user.id if user else None, chat.id, "forward", info.user.id if info.user else None,
                         user_display(info.user) if info.user else (info.hidden_name or chat_display(info.chat)),
                         FORWARD_KIND_LABELS.get(info.kind, info.kind), opts)


async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "reply", 8, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    target = effective_reply(msg)
    if target is None:
        await notify(
            update,
            "↩️ روی پیام یک کاربر یا ربات ریپلای کن و <code>/reply</code> بزن تا نویسنده‌ی آن تحلیل شود.",
            kb([[btn("🧭 راهنمای /get", "hp:get")], back_row()]),
        )
        return
    author = getattr(target, "from_user", None)
    sender_chat = getattr(target, "sender_chat", None)
    if author is not None and author.id != 1087968824:
        await present_user(
            bot, chat_id=chat.id, requester_id=user.id if user else None, user=author, user_id=author.id,
            opts=opts, reply_to_id=msg.message_id if chat.type != "private" else None, thread_id=thread_of(msg),
            heading="نویسنده‌ی پیام ریپلای‌شده" + (" (ربات 🤖)" if author.is_bot else ""),
            context_chat=chat if chat.type != "private" else None, back="m:main" if chat.type == "private" else "x",
        )
        return
    if sender_chat is not None:
        await present_chat(
            bot, chat_id=chat.id, requester_id=user.id if user else None, ref=sender_chat.id, opts=opts,
            reply_to_id=msg.message_id if chat.type != "private" else None, thread_id=thread_of(msg),
            username_hint=getattr(sender_chat, "username", None), heading="نویسنده‌ی پیام (چت/کانال)",
            back="m:main" if chat.type == "private" else "x",
        )
        return
    await notify(update, "⚪ نویسنده‌ی این پیام برای ربات در دسترس نیست (پیام سرویس یا ناشناس).")


async def cmd_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "photo", 6, 30):
        return
    bot = context.bot
    opts = await load_options(user.id if user else None)
    target, target_id, error = await resolve_user_arg(bot, update, context.args or [])
    if error or target_id is None:
        await notify(update, f"⚠️ {esc(error or 'کاربر پیدا نشد')}")
        return
    await show_profile_photo(
        bot, chat.id, target_id, 0, opts,
        reply_to_id=msg.message_id if chat.type != "private" else None, thread_id=thread_of(msg),
        requester_id=user.id if user else None,
    )
    await record_history(user.id if user else None, chat.id, "photo", target_id, user_display(target) if target else None, "مشاهده‌ی تصاویر پروفایل", opts)


async def cmd_json(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None:
        return
    if not await throttle(update, "json", 6, 30):
        return
    bot = context.bot
    thread = thread_of(msg)
    reply_to = msg.message_id if chat.type != "private" else None
    reply = effective_reply(msg)
    if reply is not None:
        data = message_info_json(reply)
        author = getattr(reply, "from_user", None)
        if author is not None and author.id != 1087968824:
            bundle = await fetch_user_bundle(bot, author, context_chat=chat if chat.type != "private" else None, deep=True)
            data["sender_bundle"] = user_info_json(bundle)
        name = f"message_{reply.message_id}.json"
    elif context.args:
        ref = parse_ref(" ".join(context.args))
        if ref is None:
            await notify(update, "⚠️ ورودی نامعتبر است.")
            return
        if isinstance(ref, int) and ref > 0:
            bundle = await fetch_user_bundle(bot, USERS.get(str(ref)), user_id=ref, deep=True)
            data, name = user_info_json(bundle), f"user_{ref}.json"
        else:
            cb = await fetch_chat_bundle(bot, ref, requester_id=user.id if user else None, want_admins=True)
            data, name = chat_info_json(cb), f"chat_{ref}.json".replace("@", "")
    elif chat.type == "private" and user is not None:
        bundle = await fetch_user_bundle(bot, user, deep=True)
        data, name = user_info_json(bundle), f"user_{user.id}.json"
    else:
        cb = await fetch_chat_bundle(bot, chat.id, requester_id=user.id if user else None, want_admins=True)
        data, name = chat_info_json(cb), f"chat_{chat.id}.json"
    await send_json_payload(bot, chat.id, data, name, reply_to_id=reply_to, thread_id=thread)
    opts = await load_options(user.id if user else None)
    await record_history(user.id if user else None, chat.id, "json", None, name, "خروجی JSON", opts)


# =========================================================
#       16 — CALLBACK HANDLERS (glass-button interface)
# =========================================================

CALLBACK_DATA_RE = re.compile(r"[A-Za-z0-9_:\-@.]{1,64}")

PROMPTS: dict[str, str] = {
    "lookup": (
        "🔍 <b>جستجوی کاربر یا چت</b>\n" + SEP + "\n\n"
        "یکی از موارد زیر را بفرست:\n"
        "• آیدی عددی کاربر (مثلاً <code>123456789</code>)\n"
        "• آیدی عددی گروه/کانال (مثلاً <code>-1001234567890</code>)\n"
        "• یوزرنیم (<code>@name</code>) یا لینک t.me\n"
        "• یا یک پیام را فوروارد کن تا منبع اصلی آن بررسی شود\n\n"
        "ℹ️ ربات فقط چتی را می‌بیند که عضو آن است یا یوزرنیم عمومی دارد."
    ),
    "photo": (
        "📷 <b>تصاویر پروفایل کاربر دیگر</b>\n" + SEP + "\n\n"
        "آیدی عددی یا @username کاربر را بفرست (یا یک پیام او را فوروارد کن)."
    ),
    "convert": (
        "🔢 <b>تبدیل آیدی چت</b>\n" + SEP + "\n\n"
        "یک آیدی عددی بفرست (مثلاً <code>-1001234567890</code>) تا فرمت‌های مختلف آن را ببینی."
    ),
    "link": (
        "🔗 <b>تحلیل لینک تلگرام</b>\n" + SEP + "\n\n"
        "یک لینک <code>t.me</code> یا <code>tg://</code> بفرست تا نوع و اجزای آن را استخراج کنم."
    ),
    "fid": (
        "🧬 <b>رمزگشایی File ID</b>\n" + SEP + "\n\n"
        "File ID را بفرست، یا مستقیماً یک فایل/عکس/استیکر بفرست تا نوع و دیتاسنتر آن تحلیل شود."
    ),
    "broadcast": (
        "📣 <b>پیام همگانی</b>\n" + SEP + "\n\n"
        "متن پیام همگانی را بفرست. قبل از ارسال، تأییدیه گرفته می‌شود."
    ),
}


def msg_chat_id(query: Any) -> int:
    message = getattr(query, "message", None)
    return message.chat.id if message is not None else query.from_user.id


def msg_thread_id(query: Any) -> Optional[int]:
    message = getattr(query, "message", None)
    return thread_of(message) if isinstance(message, Message) else None


def is_private_query(query: Any) -> bool:
    message = getattr(query, "message", None)
    return message is None or message.chat.type == "private"


def query_back(query: Any) -> str:
    return "m:main" if is_private_query(query) else "x"


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Central dispatcher for every inline button press."""
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    data = query.data or ""
    if not CALLBACK_DATA_RE.fullmatch(data):
        await answer_cb(query, "داده‌ی دکمه نامعتبر است.", True)
        return
    parts = data.split(":")
    route = CALLBACK_ROUTES.get(parts[0])
    if route is None:
        await answer_cb(query, "این دکمه دیگر معتبر نیست؛ منو را دوباره باز کن.", True)
        return
    wait = RATE.check(query.from_user.id, "cb", 30, 10)
    if wait > 0:
        await answer_cb(query, f"⏳ کمی آرام‌تر؛ {int(wait) + 1} ثانیه صبر کن.", True)
        return
    if parts[0] in ("pg", "x") and not can_press(query):
        await answer_cb(query, "این گزارش را فقط کسی که دستور را فرستاده می‌تواند مدیریت کند.", True)
        return
    await answer_cb(query)
    opts = await load_options(query.from_user.id)
    try:
        await route(update, context, query, parts, opts)
    except ApplicationHandlerStop:
        raise
    except (ValueError, IndexError):
        log.info("Invalid callback payload: %s", data[:40])
        await send_html(context.bot, msg_chat_id(query), "⚠️ داده‌ی این دکمه نامعتبر یا قدیمی است.", kb([close_row()]))
    except Exception as exc:
        log.exception("Callback failure (%s): %s", parts[0], type(exc).__name__)
        await send_html(context.bot, msg_chat_id(query), "⚠️ خطای غیرمنتظره رخ داد؛ دوباره تلاش کن.", kb([close_row()]))


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    name = parts[1]
    user = query.from_user
    chat_id = msg_chat_id(query)
    if name == "main":
        context.user_data.pop("mode", None)
        await edit_or_send(bot, query, f"🧭 <b>منوی اصلی</b>\n{SEP}\n\nیکی از گزینه‌های شیشه‌ای زیر را انتخاب کن:", kb_main(user.id))
    elif name == "me":
        await present_user(
            bot, chat_id=chat_id, requester_id=user.id, user=user, user_id=user.id, opts=opts,
            query=query, heading="اطلاعات حساب شما",
            context_chat=query.message.chat if (query.message and query.message.chat.type != "private") else None,
            back=query_back(query),
        )
    elif name == "inspect":
        context.user_data["inspect_once"] = True
        text = (
            f"🔎 <b>بررسی پیام</b>\n{SEP}\n\n"
            "هر پیامی را همین‌جا بفرست یا فوروارد کن؛ گزارش کامل آن ساخته می‌شود:\n\n"
            "• متن، عکس، ویدیو، گیف، فایل، آهنگ، ویس، ویدیو پیام\n"
            "• استیکر، لوکیشن، مکان، مخاطب، نظرسنجی، تاس\n"
            "• پیام‌های فوروارد‌شده (منبع اصلی)\n\n"
            "💡 در گروه‌ها روی پیام ریپلای کن و <code>/get</code> بزن."
        )
        await edit_or_send(bot, query, text, kb_inspect_menu())
    elif name == "chats":
        count = await dbx(db_count_selected_chats, user.id, _default=0) or 0
        await edit_or_send(bot, query, SELECTOR_INTRO, kb_chats_menu(count))
    elif name == "photos":
        text = f"📷 <b>تصاویر پروفایل</b>\n{SEP}\n\nتصاویر کدام کاربر را ببینم؟"
        rows = [
            [btn("📷 تصاویر من", f"ph:n:{user.id}:0")],
            [btn("🔍 تصاویر کاربر دیگر", "t:photo")],
            [btn("ℹ️ توضیح", "hp:photos")],
            back_row(),
        ]
        await edit_or_send(bot, query, text, kb(rows))
    elif name == "help":
        await edit_or_send(bot, query, f"📚 <b>راهنمای {esc(BOT_NAME)}</b>\n{SEP}\n\nیک موضوع را انتخاب کن:", kb_help_menu())
    elif name == "settings":
        values = await dbx(db_get_settings, user.id, _default={k: v["default"] for k, v in SETTINGS_SPEC.items()})
        await edit_or_send(bot, query, settings_text(values), kb_settings(values))
    elif name == "about":
        await edit_or_send(bot, query, about_text(), kb([[btn("🔄 بروزرسانی", "m:about")], back_row()]))
    elif name == "tools":
        await edit_or_send(bot, query, f"🧰 <b>ابزارها</b>\n{SEP}\n\nیک ابزار را انتخاب کن:", kb_tools())
    else:
        raise ValueError("unknown menu")


async def cb_help(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    topic = HELP_TOPICS.get(parts[1])
    if topic is None:
        raise ValueError("unknown topic")
    await edit_or_send(context.bot, query, topic[1], kb_help_topic())


def settings_text(values: dict[str, str]) -> str:
    blocks = [f"⚙️ <b>تنظیمات</b>\n{SEP}"]
    for key, spec in SETTINGS_SPEC.items():
        current = values.get(key, spec["default"])
        if spec["type"] == "toggle":
            state = "✅ روشن" if current == "1" else "❌ خاموش"
        else:
            state = dict(spec["choices"]).get(current, current)
        blocks.append(f"{spec['emoji']} <b>{esc(spec['label'])}:</b> {esc(state)}\n<i>{esc(spec['help'])}</i>")
    blocks.append("برای تغییر هر مورد روی دکمه‌ی آن بزن 👇")
    return "\n\n".join(blocks)


async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    uid = query.from_user.id
    action = parts[1]
    if action == "t":
        key = parts[2]
        spec = SETTINGS_SPEC.get(key)
        if spec is None:
            raise ValueError("unknown setting")
        values = await dbx(db_get_settings, uid, _default={k: v["default"] for k, v in SETTINGS_SPEC.items()})
        current = values.get(key, spec["default"])
        if spec["type"] == "toggle":
            new_value = "0" if current == "1" else "1"
        else:
            choices = [c[0] for c in spec["choices"]]
            new_value = choices[(choices.index(current) + 1) % len(choices)] if current in choices else choices[0]
        await dbx(db_set_setting, uid, key, new_value)
        values[key] = new_value
        await edit_or_send(bot, query, settings_text(values), kb_settings(values))
    elif action == "r":
        await dbx(db_reset_settings, uid)
        values = {k: v["default"] for k, v in SETTINGS_SPEC.items()}
        await edit_or_send(bot, query, settings_text(values), kb_settings(values))
    elif action == "w":
        text = (
            f"🗑 <b>پاک‌کردن اطلاعات من</b>\n{SEP}\n\n"
            "این کار تاریخچه‌ی بررسی‌ها، چت‌های ذخیره‌شده و تنظیمات تو را برای همیشه حذف می‌کند.\n\nمطمئنی؟"
        )
        await edit_or_send(bot, query, text, kb([[btn("✅ بله، پاک کن", "s:wy")], [btn("❌ انصراف", "m:settings")]]))
    elif action == "wy":
        a = await dbx(db_clear_history, uid, _default=0)
        b = await dbx(db_clear_selected_chats, uid, _default=0)
        await dbx(db_reset_settings, uid)
        await edit_or_send(
            bot, query,
            f"✅ پاک شد.\n\n📜 رکورد تاریخچه: {a or 0}\n🏛 چت ذخیره‌شده: {b or 0}\n⚙️ تنظیمات: بازنشانی شد",
            kb([back_row()]),
        )
    else:
        raise ValueError("unknown settings action")


async def cb_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    name = parts[1]
    user = query.from_user
    chat_id = msg_chat_id(query)
    if name in PROMPTS and name != "broadcast":
        context.user_data["mode"] = name
        await edit_or_send(bot, query, PROMPTS[name], kb_cancel())
    elif name == "cancel":
        context.user_data.pop("mode", None)
        context.user_data.pop("inspect_once", None)
        context.user_data.pop("broadcast_text", None)
        await edit_or_send(bot, query, f"✅ لغو شد.\n\n🧭 <b>منوی اصلی</b>\n{SEP}", kb_main(user.id))
    elif name == "clock":
        report = Report("ساعت و تاریخ", "🕒")
        report.extend([build_clock_section(opts)])
        await send_report(bot, chat_id, report, [[btn("🔄 بروزرسانی", "t:clock")], back_row()], edit_query=query, owner_id=user.id)
    elif name == "myids":
        report = Report("آیدی‌های من", "🆔")
        sec = report.section("آیدی‌ها", "🆔")
        sec.add("👤", "آیدی کاربر (User ID)", user.id, as_code=True)
        sec.add("🏛", "آیدی این چت (Chat ID)", chat_id, as_code=True)
        if isinstance(query.message, Message):
            sec.add("🔢", "آیدی این پیام (Message ID)", query.message.message_id, as_code=True)
        sec.add("🌍", "زبان", user.language_code or "ارسال نشده", as_code=True, inline=True)
        sec.add_note("هر سه آیدی با هم متفاوت‌اند.")
        await send_report(
            bot, chat_id, report,
            [[copy_btn(f"📋 کپی آیدی من {user.id}", user.id)], back_row("m:tools", "🔙 ابزارها")],
            edit_query=query, owner_id=user.id,
        )
    elif name == "pickuser":
        keyboard = user_picker_keyboard()
        if keyboard is None:
            await send_html(bot, chat_id, "⚠️ نسخه‌ی کتابخانه از انتخاب کاربر پشتیبانی نمی‌کند.", kb([close_row()]))
            return
        if not is_private_query(query):
            await send_html(bot, chat_id, "ℹ️ انتخابگر کاربر فقط در گفتگوی خصوصی ربات کار می‌کند.", kb([close_row()]))
            return
        await send_html(
            bot, chat_id,
            f"👤 <b>انتخاب کاربر یا ربات</b>\n{SEP}\n\nیکی از دکمه‌های پایین صفحه را بزن و از فهرست تلگرام انتخاب کن.\n"
            "<i>تلگرام فقط همان آیدی (و در صورت اجازه نام/یوزرنیم) را برای ربات می‌فرستد.</i>",
            keyboard,
        )
    else:
        raise ValueError("unknown tool")


async def cb_user(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    action = parts[1]
    uid = to_int(parts[2])
    requester = query.from_user
    chat_id = msg_chat_id(query)
    thread = msg_thread_id(query)
    wait = RATE.check(requester.id, f"u_{action}", 10, 30)
    if wait > 0:
        await send_html(bot, chat_id, f"⏳ لطفاً {int(wait) + 1} ثانیه صبر کن.", kb([close_row()]), thread_id=thread)
        return
    if action == "v":
        message = query.message
        context_chat = message.chat if (isinstance(message, Message) and message.chat.type != "private") else None
        await present_user(
            bot, chat_id=chat_id, requester_id=requester.id, user=USERS.get(str(uid)), user_id=uid, opts=opts,
            query=query, context_chat=context_chat, back=query_back(query),
        )
    elif action == "p":
        index = to_int(parts[3]) if len(parts) > 3 else 0
        await show_profile_photo(bot, chat_id, uid, index, opts, query=query, thread_id=thread, requester_id=requester.id)
        await record_history(requester.id, chat_id, "photo", uid, None, "مشاهده‌ی تصاویر پروفایل", opts)
    elif action == "j":
        bundle = await fetch_user_bundle(bot, USERS.get(str(uid)), user_id=uid, deep=True)
        await send_json_payload(bot, chat_id, user_info_json(bundle), f"user_{uid}.json", thread_id=thread)
        await record_history(requester.id, chat_id, "json", uid, None, "JSON کاربر", opts)
    else:
        raise ValueError("unknown user action")


async def send_chat_photo(bot: Any, chat_id: int, target_chat_id: int, thread_id: Optional[int]) -> None:
    chat, err = await safe_call(bot.get_chat, target_chat_id)
    photo = getattr(chat, "photo", None) if chat is not None else None
    if chat is None or photo is None:
        reason = explain_error(err) if err else "این چت عکسی ندارد یا برای ربات در دسترس نیست."
        await send_html(bot, chat_id, f"⚪ {esc(reason)}", kb([close_row()]), thread_id=thread_id)
        return
    try:
        async with temp_download(bot, photo.big_file_id) as tf:
            caption = (
                f"🖼 <b>عکس چت</b>\n🏛 {esc(chat_display(chat))}\n🆔 {code(chat.id)}\n"
                f"💾 {esc(fmt_size(tf.size))}\n🔐 SHA-256:\n{code(tf.sha256)}"
            )
            with tf.path.open("rb") as handle:
                kwargs: dict[str, Any] = {
                    "chat_id": chat_id, "photo": handle, "caption": caption[:CAPTION_LIMIT],
                    "parse_mode": ParseMode.HTML, "reply_markup": kb([close_row()]),
                }
                if thread_id:
                    kwargs["message_thread_id"] = thread_id
                _, serr = await safe_call(bot.send_photo, **kwargs)
        if serr is not None:
            await send_html(bot, chat_id, f"⚠️ {esc(explain_error(serr))}", kb([close_row()]), thread_id=thread_id)
    except ValueError as exc:
        await send_html(bot, chat_id, f"⚠️ {esc(exc)}", kb([close_row()]), thread_id=thread_id)


async def cb_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    action = parts[1]
    cid = to_int(parts[2])
    requester = query.from_user
    chat_id = msg_chat_id(query)
    thread = msg_thread_id(query)
    wait = RATE.check(requester.id, f"c_{action}", 10, 30)
    if wait > 0:
        await send_html(bot, chat_id, f"⏳ لطفاً {int(wait) + 1} ثانیه صبر کن.", kb([close_row()]), thread_id=thread)
        return
    hint = None
    message = query.message
    if isinstance(message, Message) and message.chat.id == cid:
        hint = getattr(message.chat, "username", None)
    if action in ("v", "r"):
        await present_chat(
            bot, chat_id=chat_id, requester_id=requester.id, ref=cid, opts=opts, query=query,
            username_hint=hint, back=query_back(query),
        )
    elif action == "a":
        await present_chat(
            bot, chat_id=chat_id, requester_id=requester.id, ref=cid, opts=opts, query=query,
            want_admins=True, only_admins=True, username_hint=hint, back=f"c:v:{cid}",
        )
    elif action == "ph":
        await send_chat_photo(bot, chat_id, cid, thread)
    elif action == "j":
        bundle = await fetch_chat_bundle(bot, cid, requester_id=requester.id, want_admins=True, username_hint=hint)
        await send_json_payload(bot, chat_id, chat_info_json(bundle), f"chat_{cid}.json", thread_id=thread)
        await record_history(requester.id, chat_id, "json", cid, None, "JSON چت", opts)
    else:
        raise ValueError("unknown chat action")


async def cb_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    action = parts[1]
    uid = to_int(parts[2])
    requester = query.from_user
    chat_id = msg_chat_id(query)
    thread = msg_thread_id(query)
    wait = RATE.check(requester.id, f"ph_{action}", 12, 30)
    if wait > 0:
        await send_html(bot, chat_id, f"⏳ لطفاً {int(wait) + 1} ثانیه صبر کن.", kb([close_row()]), thread_id=thread)
        return
    if action == "n":
        index = to_int(parts[3])
        await show_profile_photo(bot, chat_id, uid, index, opts, query=query, thread_id=thread, requester_id=requester.id)
    elif action == "d":
        await send_original_photo_file(bot, chat_id, uid, to_int(parts[3]), thread)
    elif action == "i":
        await photo_sizes_report(bot, chat_id, uid, to_int(parts[3]), opts, query)
    elif action == "a":
        await send_profile_album(bot, chat_id, uid, thread)
    else:
        raise ValueError("unknown photo action")


async def cb_page(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    key = parts[1]
    index = to_int(parts[2])
    entry = PAGES.get(key)
    if not entry:
        await edit_or_send(context.bot, query, "⌛ این گزارش منقضی شده است؛ دوباره آن را درخواست کن.", kb([back_row()]))
        return
    pages = entry["pages"]
    index = max(0, min(index, len(pages) - 1))
    await edit_or_send(context.bot, query, pages[index], page_markup(key, index, pages, entry["rows"]))


async def cb_close(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    message = query.message
    if message is None:
        return
    try:
        await context.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except TelegramError:
        await edit_or_send(context.bot, query, "✖️ بسته شد.", None)


async def cb_msg_json(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    message = MSGS.get(parts[1])
    chat_id = msg_chat_id(query)
    if message is None:
        await send_html(context.bot, chat_id, "⌛ این پیام از حافظه‌ی موقت حذف شده؛ دوباره آن را بفرست.", kb([close_row()]))
        return
    await send_json_payload(context.bot, chat_id, message_info_json(message), f"message_{message.message_id}.json", thread_id=msg_thread_id(query))
    await record_history(query.from_user.id, chat_id, "json", message.message_id, None, "JSON پیام", opts)


async def cb_msg_inspect(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    message = MSGS.get(parts[1])
    chat_id = msg_chat_id(query)
    if message is None:
        await send_html(context.bot, chat_id, "⌛ این پیام از حافظه‌ی موقت حذف شده؛ دوباره آن را بفرست.", kb([close_row()]))
        return
    if not await throttle(update, "inspect", 12, 30):
        return
    await present_message(
        context.bot, message, chat_id=chat_id, requester_id=query.from_user.id, opts=opts,
        title="گزارش کامل پیام", deep=True, thread_id=msg_thread_id(query),
        kind="forward" if inspect_forward(message).present else "message",
    )


async def resend_media(bot: Any, chat_id: int, message: Message, thread_id: Optional[int]) -> Optional[str]:
    """Re-send media using Telegram's own file_id (no download, no external service)."""
    method = None
    key = ""
    file_id = None
    if message.photo:
        method, key, file_id = bot.send_photo, "photo", message.photo[-1].file_id
    elif message.video:
        method, key, file_id = bot.send_video, "video", message.video.file_id
    elif message.animation:
        method, key, file_id = bot.send_animation, "animation", message.animation.file_id
    elif message.document:
        method, key, file_id = bot.send_document, "document", message.document.file_id
    elif message.audio:
        method, key, file_id = bot.send_audio, "audio", message.audio.file_id
    elif message.voice:
        method, key, file_id = bot.send_voice, "voice", message.voice.file_id
    elif message.video_note:
        method, key, file_id = bot.send_video_note, "video_note", message.video_note.file_id
    elif message.sticker:
        method, key, file_id = bot.send_sticker, "sticker", message.sticker.file_id
    if method is None:
        return "این پیام فایل قابل ارسال مجدد ندارد."
    kwargs: dict[str, Any] = {"chat_id": chat_id, key: file_id, "reply_markup": kb([close_row()])}
    if message.caption and key in ("photo", "video", "animation", "document", "audio", "voice"):
        kwargs["caption"] = message.caption[:CAPTION_LIMIT]
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    _, err = await safe_call(method, **kwargs)
    return explain_error(err) if err is not None else None


async def cb_file(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    message = MSGS.get(parts[1])
    action = parts[2]
    chat_id = msg_chat_id(query)
    thread = msg_thread_id(query)
    bot = context.bot
    if message is None:
        await send_html(bot, chat_id, "⌛ این پیام از حافظه‌ی موقت حذف شده؛ دوباره آن را بفرست.", kb([close_row()]))
        return
    if action == "s":
        error = await resend_media(bot, chat_id, message, thread)
        if error:
            await send_html(bot, chat_id, f"⚠️ {esc(error)}", kb([close_row()]), thread_id=thread)
    elif action == "d":
        report = Report("رمزگشایی File ID", "🧬")
        for label, file_id in media_file_ids(message)[:3]:
            report.extend([file_id_section(label, file_id)])
        await send_report(bot, chat_id, report, [close_row()], owner_id=query.from_user.id, thread_id=thread)
    else:
        raise ValueError("unknown file action")


def file_id_section(label: str, file_id: str) -> Section:
    sec = Section(f"File ID — {label}", "🧬")
    sec.add("🔑", "File ID", file_id, as_code=True)
    info = decode_file_id(file_id)
    if info is None:
        sec.add("⚪", "نتیجه", "File ID قابل رمزگشایی محلی نبود (قالب نامعتبر یا نسخه‌ی جدید).")
        return sec
    sec.add("🏷", "نوع فایل", info["type_name"], inline=True)
    sec.add("🌐", "دیتاسنتر (DC)", info["dc_id"], as_code=True, inline=True)
    sec.add("🔖", "نسخه‌ی قالب", info["version"], as_code=True, inline=True)
    sec.add_bool("🧷", "دارای File Reference", info["has_file_reference"])
    sec.add_bool("🌍", "Web Location", info["is_web_location"])
    sec.add("📏", "طول File ID", f"{info['length']} نویسه ({info['decoded_bytes']} بایت پس از رمزگشایی)", inline=True)
    sec.add_note("این تحلیل محلی و Best-Effort است؛ File ID فقط برای خود همین ربات معتبر است و شامل هیچ اطلاعات خصوصی دیگری نیست.")
    return sec


async def cb_history(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    uid = query.from_user.id
    action = parts[1]
    if action == "l":
        page = max(to_int(parts[2]), 0)
        total = await dbx(db_count_history, uid, _default=0) or 0
        pages = max((total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE, 1)
        page = min(page, pages - 1)
        items = await dbx(db_list_history, uid, HISTORY_PAGE_SIZE, page * HISTORY_PAGE_SIZE, _default=[]) or []
        lines = [f"📜 <b>تاریخچه‌ی بررسی‌ها</b>\n{SEP}\n"]
        if not items:
            lines.append("⚪ هنوز چیزی ثبت نشده است. هر پیام یا کاربری که بررسی کنی اینجا ذخیره می‌شود.")
        rows: list[list[Optional[InlineKeyboardButton]]] = []
        for item in items:
            kind_label = HISTORY_KIND_LABELS.get(item["kind"], item["kind"])
            when = fmt_ago(parse_iso(item["created_at"]))
            name = item.get("subject_name") or (str(item.get("subject_id")) if item.get("subject_id") else "—")
            lines.append(f"{kind_label} │ {esc(trunc(name, 28))} │ <i>{esc(when)}</i>")
            rows.append([btn(f"{kind_label} · {trunc(name, 22)} · #{item['id']}", f"h:v:{item['id']}")])
        lines.append(f"\n📄 صفحه {page + 1} از {pages} — مجموع: {total}")
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(btn("◀️ قبلی", f"h:l:{page - 1}"))
        if page < pages - 1:
            nav.append(btn("بعدی ▶️", f"h:l:{page + 1}"))
        if nav:
            rows.append(nav)
        if total:
            rows.append([btn("🗑 پاک‌کردن تاریخچه", "h:c")])
        rows.append(back_row())
        await edit_or_send(bot, query, "\n".join(lines), kb(rows))
    elif action == "v":
        item = await dbx(db_get_history, uid, to_int(parts[2]), _default=None)
        if not item:
            await edit_or_send(bot, query, "⚪ این رکورد پیدا نشد.", kb([[btn("📜 تاریخچه", "h:l:0")]]))
            return
        rows = []
        if item.get("kind") in ("user", "photo") and item.get("subject_id"):
            rows.append([btn("👤 بررسی دوباره‌ی کاربر", f"u:v:{item['subject_id']}")])
        if item.get("kind") == "chat" and item.get("subject_id"):
            rows.append([btn("🏛 بررسی دوباره‌ی چت", f"c:v:{item['subject_id']}")])
        rows.append([btn("📜 تاریخچه", "h:l:0")])
        rows.append(back_row())
        await edit_or_send(bot, query, history_text(item, opts), kb(rows))
    elif action == "c":
        await edit_or_send(
            bot, query, "🗑 همه‌ی رکوردهای تاریخچه‌ی تو حذف شود؟",
            kb([[btn("✅ بله", "h:cy")], [btn("❌ خیر", "h:l:0")]]),
        )
    elif action == "cy":
        removed = await dbx(db_clear_history, uid, _default=0)
        await edit_or_send(bot, query, f"✅ {removed or 0} رکورد حذف شد.", kb([back_row()]))
    else:
        raise ValueError("unknown history action")


# =========================================================
#       16b — PRIVATE MESSAGES, INPUT MODES, KEYBOARD TEXTS
# =========================================================

async def lookup_ref(
    bot: Any,
    *,
    chat_id: int,
    requester_id: int,
    ref: Any,
    opts: Options,
    thread_id: Optional[int] = None,
    query: Any = None,
) -> None:
    """Resolve an ID / @username and present the matching user or chat report."""
    if isinstance(ref, int):
        if ref > 0:
            await present_user(bot, chat_id=chat_id, requester_id=requester_id, user=USERS.get(str(ref)), user_id=ref,
                               opts=opts, thread_id=thread_id, query=query, back="m:main")
        else:
            await present_chat(bot, chat_id=chat_id, requester_id=requester_id, ref=ref, opts=opts,
                               thread_id=thread_id, query=query, back="m:main")
        return
    cached = await dbx(db_find_cached_username, ref, _default=None)
    if cached:
        await present_user(bot, chat_id=chat_id, requester_id=requester_id, user=USERS.get(str(cached["user_id"])),
                           user_id=int(cached["user_id"]), opts=opts, thread_id=thread_id, query=query, back="m:main")
        return
    found, err = await safe_call(bot.get_chat, ref)
    if found is None:
        await send_html(
            bot, chat_id,
            f"⚠️ <b>{esc(ref)}</b>\n{esc(explain_error(err))}",
            kb([[btn("🔍 جستجوی دیگر", "t:lookup")], back_row()]), thread_id=thread_id,
        )
        return
    if found.type == "private":
        await present_user(bot, chat_id=chat_id, requester_id=requester_id, user=None, user_id=int(found.id),
                           opts=opts, thread_id=thread_id, query=query, back="m:main")
    else:
        await present_chat(bot, chat_id=chat_id, requester_id=requester_id, ref=int(found.id), opts=opts,
                           thread_id=thread_id, query=query, username_hint=getattr(found, "username", None), back="m:main")


async def resolve_photo_target(bot: Any, ref: Any) -> tuple[Optional[int], Optional[str]]:
    if isinstance(ref, int):
        if ref <= 0:
            return None, "آیدی کاربر باید مثبت باشد."
        return ref, None
    cached = await dbx(db_find_cached_username, ref, _default=None)
    if cached:
        return int(cached["user_id"]), None
    found, err = await safe_call(bot.get_chat, ref)
    if found is None:
        return None, explain_error(err)
    if found.type != "private":
        return None, "این یوزرنیم متعلق به گروه/کانال است، نه کاربر."
    return int(found.id), None


async def handle_mode_input(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, opts: Options) -> bool:
    """Process the user's reply to one of the interactive prompts. Returns True if handled."""
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None or user is None:
        return False
    bot = context.bot
    text = (msg.text or "").strip()
    cancel_rows = kb_cancel()

    # فوروارد در حالت جستجو: منبع اصلی را بررسی کن
    forward = inspect_forward(msg)
    if forward.present and mode in ("lookup", "photo"):
        context.user_data.pop("mode", None)
        if forward.user is not None:
            if mode == "photo":
                await show_profile_photo(bot, chat.id, forward.user.id, 0, opts, requester_id=user.id)
            else:
                await present_user(bot, chat_id=chat.id, requester_id=user.id, user=forward.user,
                                   user_id=forward.user.id, opts=opts, heading="منبع اصلی پیام فوروارد‌شده")
        elif forward.chat is not None:
            await present_chat(bot, chat_id=chat.id, requester_id=user.id, ref=forward.chat.id, opts=opts,
                               username_hint=getattr(forward.chat, "username", None), heading="منبع اصلی پیام فوروارد‌شده")
        else:
            await send_html(
                bot, chat.id,
                "🕶 فرستنده‌ی اصلی هویت خود را مخفی کرده است؛ آیدی/یوزرنیم او هرگز قابل دریافت نیست.\n"
                f"نام نمایشی: <b>{esc(forward.hidden_name)}</b>",
                kb([back_row()]),
            )
        return True

    if mode == "fid":
        found_ids = media_file_ids(msg)
        report = Report("رمزگشایی File ID", "🧬")
        if found_ids:
            for label, file_id in found_ids[:3]:
                report.extend([file_id_section(label, file_id)])
        elif text:
            report.extend([file_id_section("ورودی شما", text)])
        else:
            await send_html(bot, chat.id, "⚠️ File ID یا یک فایل بفرست.", cancel_rows)
            return True
        context.user_data.pop("mode", None)
        await send_report(bot, chat.id, report, [[btn("🧬 رمزگشایی دیگر", "t:fid")], back_row("m:tools", "🔙 ابزارها")], owner_id=user.id)
        await record_history(user.id, chat.id, "tool", None, "File ID", "رمزگشایی File ID", opts)
        return True

    if not text:
        await send_html(bot, chat.id, "⚠️ این بخش ورودی متنی می‌خواهد. دوباره تلاش کن یا انصراف بده.", cancel_rows)
        return True

    if mode == "lookup":
        ref = parse_ref(text)
        if ref is None:
            await send_html(bot, chat.id, "⚠️ فرمت نامعتبر است. آیدی عددی، @username یا لینک t.me بفرست.", cancel_rows)
            return True
        if not await throttle(update, "lookup", 8, 30):
            return True
        context.user_data.pop("mode", None)
        await lookup_ref(bot, chat_id=chat.id, requester_id=user.id, ref=ref, opts=opts)
        return True

    if mode == "photo":
        ref = parse_ref(text)
        if ref is None:
            await send_html(bot, chat.id, "⚠️ فرمت نامعتبر است. آیدی عددی یا @username بفرست.", cancel_rows)
            return True
        target_id, error = await resolve_photo_target(bot, ref)
        if target_id is None:
            await send_html(bot, chat.id, f"⚠️ {esc(error)}", cancel_rows)
            return True
        context.user_data.pop("mode", None)
        await show_profile_photo(bot, chat.id, target_id, 0, opts, requester_id=user.id)
        await record_history(user.id, chat.id, "photo", target_id, None, "مشاهده‌ی تصاویر پروفایل", opts)
        return True

    if mode == "convert":
        try:
            number = to_int(text)
        except ValueError:
            await send_html(bot, chat.id, "⚠️ فقط یک عدد صحیح بفرست.", cancel_rows)
            return True
        info = convert_chat_id(number)
        report = Report("تبدیل آیدی چت", "🔢")
        sec = report.section("نتیجه", "🔢")
        sec.add("🔢", "ورودی", number, as_code=True)
        sec.add("🧭", "تفسیر", info["interpretation"])
        for key, label in (
            ("as_user_id", "اگر آیدی کاربر باشد"),
            ("as_channel_bot_api", "اگر آیدی کوتاه کانال/سوپرگروه باشد (فرمت Bot API)"),
            ("bot_api", "آیدی فرمت Bot API"),
            ("short_id", "آیدی کوتاه (MTProto)"),
            ("abs_id", "قدر مطلق آیدی گروه"),
            ("as_link_prefix", "پیشوند لینک پیام"),
        ):
            if key in info:
                sec.add("▫️", label, info[key], as_code=True)
        if "note" in info:
            sec.add_note(info["note"])
        context.user_data.pop("mode", None)
        await send_report(bot, chat.id, report, [[btn("🔢 تبدیل دیگر", "t:convert")], back_row("m:tools", "🔙 ابزارها")], owner_id=user.id)
        return True

    if mode == "link":
        link = parse_telegram_link(text)
        if link is None:
            await send_html(bot, chat.id, "⚠️ لینک تلگرام معتبری پیدا نشد. مثال: <code>https://t.me/name/12</code>", cancel_rows)
            return True
        report = Report("تحلیل لینک تلگرام", "🔗")
        sec = report.section("اجزای لینک", "🔗")
        sec.add("🏷", "نوع", LINK_KIND_LABELS.get(link["kind"], link["kind"]))
        rows: list[list[Optional[InlineKeyboardButton]]] = []
        if link.get("username"):
            sec.add("🔗", "یوزرنیم", "@" + link["username"], as_code=True)
            rows.append([btn("🔍 بررسی این یوزرنیم", "t:lookup")])
        if link.get("message_id") is not None:
            sec.add("🔢", "آیدی پیام (Message ID)", link["message_id"], as_code=True)
        if link.get("chat_id") is not None:
            sec.add("🆔", "آیدی چت (فرمت Bot API)", link["chat_id"], as_code=True)
            sec.add("🔢", "آیدی کوتاه", link["short_id"], as_code=True)
            rows.append([btn("🏛 بررسی این چت", f"c:v:{link['chat_id']}")])
        if link.get("user_id") is not None:
            sec.add("🆔", "آیدی کاربر", link["user_id"], as_code=True)
            rows.append([btn("👤 بررسی این کاربر", f"u:v:{link['user_id']}")])
        if link.get("invite_hash"):
            sec.add("🎟", "Hash دعوت", link["invite_hash"], as_code=True)
            sec.add_note("لینک دعوت مستقیماً قابل بررسی نیست؛ ربات برای دریافت اطلاعات باید عضو آن چت باشد.")
        if link.get("set_name"):
            sec.add("🧩", "نام مجموعه", link["set_name"], as_code=True)
        if link.get("start_param"):
            sec.add("🧷", "پارامتر Start", link["start_param"], as_code=True)
        context.user_data.pop("mode", None)
        rows.append([btn("🔗 تحلیل لینک دیگر", "t:link")])
        rows.append(back_row("m:tools", "🔙 ابزارها"))
        await send_report(bot, chat.id, report, rows, owner_id=user.id)
        return True

    if mode == "broadcast":
        if not is_owner(user.id):
            context.user_data.pop("mode", None)
            return True
        context.user_data["broadcast_text"] = text[:3500]
        context.user_data.pop("mode", None)
        targets = await dbx(db_broadcast_targets, _default=[]) or []
        await send_html(
            bot, chat.id,
            f"📣 <b>پیش‌نمایش پیام همگانی</b>\n{SEP}\n\n{esc(text[:3500])}\n\n{SEP}\n👥 گیرندگان: <b>{len(targets)}</b>",
            kb([[btn("✅ ارسال برای همه", "a:bcy")], [btn("❌ انصراف", "t:cancel")]]),
        )
        return True
    return False


async def on_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all for private chats: input modes or automatic message inspection."""
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None or user is None:
        return
    bot = context.bot
    opts = await load_options(user.id)
    mode = context.user_data.get("mode")
    if mode:
        if await handle_mode_input(update, context, mode, opts):
            return
    once = bool(context.user_data.pop("inspect_once", False))
    if not opts.auto_inspect and not once:
        mkey = MSGS.put(msg)
        await send_html(
            bot, chat.id,
            "ℹ️ بررسی خودکار خاموش است.",
            kb([[btn("🔎 بررسی همین پیام", f"mi:{mkey}")], [btn("⚙️ تنظیمات", "m:settings")]]),
            reply_to_id=msg.message_id,
        )
        return
    if not await throttle(update, "inspect", 12, 30):
        return
    forward = inspect_forward(msg)
    await present_message(
        bot, msg, chat_id=chat.id, requester_id=user.id, opts=opts,
        title="گزارش پیام فوروارد‌شده" if forward.present else "گزارش کامل پیام",
        deep=forward.present, kind="forward" if forward.present else "message",
        reply_to_id=msg.message_id,
    )


async def on_keyboard_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route the persistent reply-keyboard buttons to the same screens as the inline menu."""
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None or user is None or not msg.text:
        return
    bot = context.bot
    opts = await load_options(user.id)
    text = msg.text.strip()
    context.user_data.pop("mode", None)
    if text == MAIN_BUTTONS["me"]:
        await present_user(bot, chat_id=chat.id, requester_id=user.id, user=user, user_id=user.id, opts=opts,
                           heading="اطلاعات حساب شما")
    elif text == MAIN_BUTTONS["inspect"]:
        context.user_data["inspect_once"] = True
        await send_html(
            bot, chat.id,
            f"🔎 <b>بررسی پیام</b>\n{SEP}\n\nهر پیام، فایل، استیکر، لوکیشن، مخاطب یا فورواردی را بفرست؛ همین‌جا تحلیل می‌شود.\n"
            "در گروه‌ها روی پیام ریپلای کن و <code>/get</code> بزن.",
            kb_inspect_menu(),
        )
    elif text == MAIN_BUTTONS["chats"]:
        count = await dbx(db_count_selected_chats, user.id, _default=0) or 0
        await send_html(bot, chat.id, SELECTOR_INTRO, selector_keyboard())
        await send_html(bot, chat.id, f"🏛 <b>مدیریت چت‌ها</b>\n{SEP}", kb_chats_menu(count))
    elif text == MAIN_BUTTONS["photos"]:
        await send_html(
            bot, chat.id, f"📷 <b>تصاویر پروفایل</b>\n{SEP}\n\nتصاویر کدام کاربر را ببینم؟",
            kb([[btn("📷 تصاویر من", f"ph:n:{user.id}:0")], [btn("🔍 تصاویر کاربر دیگر", "t:photo")], back_row()]),
        )
    elif text == MAIN_BUTTONS["help"]:
        await send_html(bot, chat.id, f"📚 <b>راهنمای {esc(BOT_NAME)}</b>\n{SEP}\n\nیک موضوع را انتخاب کن:", kb_help_menu())
    elif text == MAIN_BUTTONS["settings"]:
        values = await dbx(db_get_settings, user.id, _default={k: v["default"] for k, v in SETTINGS_SPEC.items()})
        await send_html(bot, chat.id, settings_text(values), kb_settings(values))
    elif text == BACK_BUTTON_TEXT:
        await send_html(bot, chat.id, "🧭 بازگشت به منوی اصلی ✅", main_reply_keyboard())
        await send_html(bot, chat.id, f"🧭 <b>منوی اصلی</b>\n{SEP}", kb_main(user.id))
    elif text == "📂 چت‌های ذخیره‌شده":
        await show_saved_chats(bot, chat.id, user.id, 0, None)


# =========================================================
#       17 — CHAT SELECTOR FLOW (KeyboardButtonRequestChat)
# =========================================================

CREATED_KINDS = {value[0] for value in CHAT_REQUESTS.values() if value[2]}
KIND_LABELS = {value[0]: value[1] for value in CHAT_REQUESTS.values()}


def chat_icon(chat_type: Optional[str]) -> str:
    return {"channel": "📢", "supergroup": "👥", "group": "👥"}.get(str(chat_type), "🏛")


def ownership_short(code_value: Optional[str]) -> str:
    return {
        "owner": "👑 مالک تأییدشده",
        "admin": "🛡 ادمین",
        "member": "👤 عضو",
        "none": "🚪 عضو نیست",
        "not_owner": "❌ مالک نیستی",
        "selected_created": "🟡 ساخته‌شده (تأیید نشده)",
        "unverified": "⚪ تأیید نشده",
    }.get(str(code_value), "⚪ نامشخص")


async def inspect_selected_chat(
    bot: Any,
    *,
    chat_id: int,
    user_id: int,
    target_chat_id: int,
    request_kind: str,
    opts: Options,
    shared_title: Optional[str] = None,
    shared_username: Optional[str] = None,
    query: Any = None,
    thread_id: Optional[int] = None,
    persist: bool = True,
) -> Optional[int]:
    """Inspect a chat the user selected, verify ownership, store it and show the report."""
    created = request_kind in CREATED_KINDS
    bundle = await fetch_chat_bundle(
        bot, target_chat_id, requester_id=user_id, want_admins=True,
        username_hint=shared_username, shared_title=shared_title,
    )
    ownership = evaluate_ownership(bundle, created)
    report = build_chat_report(
        bundle, opts, title="گزارش چت انتخاب‌شده", requested_created=created,
        show_ownership=True, request_label=KIND_LABELS.get(request_kind, "انتخاب دستی"),
    )
    chat = bundle.chat
    row_id: Optional[int] = None
    if persist:
        status = getattr(bundle.bot_member, "status", None)
        record = {
            "chat_id": int(chat.id) if chat is not None else int(target_chat_id),
            "chat_type": getattr(chat, "type", None),
            "title": getattr(chat, "title", None) or shared_title or (chat_display(chat) if chat is not None else None),
            "username": getattr(chat, "username", None) or shared_username,
            "is_forum": getattr(chat, "is_forum", None) if chat is not None else None,
            "member_count": bundle.member_count,
            "bot_status": status,
            "ownership_code": ownership.code,
            "ownership_label": ownership.label,
            "request_kind": request_kind,
            "access_level": bundle.access,
        }
        row_id = await dbx(db_save_selected_chat, user_id, record, _default=None)
        sec = report.section("ذخیره‌سازی", "💾")
        if row_id:
            sec.add("✅", "وضعیت", f"در پایگاه‌داده‌ی محلی ذخیره شد (رکورد #{row_id})", inline=False)
            sec.add_note("فقط اطلاعات لازم (آیدی، عنوان، یوزرنیم، نوع، وضعیت‌ها) ذخیره می‌شود؛ از «چت‌های ذخیره‌شده» قابل مشاهده و حذف است.")
        else:
            sec.add_warning("ذخیره در پایگاه‌داده انجام نشد (خطای پایگاه‌داده).")
    extra: list[list[Optional[InlineKeyboardButton]]] = []
    if row_id:
        extra.append([btn("🔄 بررسی دوباره", f"sc:v:{row_id}"), btn("🗑 حذف از فهرست", f"sc:d:{row_id}")])
    extra.append([btn("📂 چت‌های ذخیره‌شده", "sc:l:0"), btn("🧲 انتخاب چت دیگر", "sel:open")])
    if chat is not None:
        rows = kb_chat_actions(
            int(chat.id), username=getattr(chat, "username", None),
            invite_link=getattr(chat, "invite_link", None),
            has_photo=getattr(chat, "photo", None) is not None,
            chat_like=is_chat_like(getattr(chat, "type", None)), opts=opts, extra_rows=extra, back="m:chats",
        )
    else:
        rows = extra + [back_row("m:chats", "🔙 بازگشت")]
    await send_report(bot, chat_id, report, rows, owner_id=user_id, edit_query=query, thread_id=thread_id)
    await record_history(
        user_id, chat_id, "selected_chat", int(target_chat_id),
        (chat_display(chat) if chat is not None else shared_title), ownership_short(ownership.code), opts,
    )
    return row_id


async def on_chat_shared(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ChatShared service message produced by KeyboardButtonRequestChat."""
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None or user is None:
        return
    shared = getattr(msg, "chat_shared", None)
    if shared is None:
        return
    request = CHAT_REQUESTS.get(shared.request_id)
    if request is None:
        await notify(update, "⚠️ این انتخاب مربوط به درخواست ناشناخته‌ای بود و نادیده گرفته شد.")
        return
    if not await throttle(update, "chatshared", 6, 30):
        return
    kind = request[0]
    opts = await load_options(user.id)
    await send_html(context.bot, chat.id, "⏳ در حال بررسی چت انتخاب‌شده…", None, reply_to_id=msg.message_id)
    await inspect_selected_chat(
        context.bot, chat_id=chat.id, user_id=user.id, target_chat_id=int(shared.chat_id), request_kind=kind,
        opts=opts, shared_title=getattr(shared, "title", None), shared_username=getattr(shared, "username", None),
    )


async def on_users_shared(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None or user is None:
        return
    shared = getattr(msg, "users_shared", None)
    items = list(getattr(shared, "users", None) or []) if shared is not None else []
    legacy = getattr(msg, "user_shared", None)
    ids: list[int] = [int(item.user_id) for item in items]
    if legacy is not None and getattr(legacy, "user_id", None):
        ids.append(int(legacy.user_id))
    if not ids:
        return
    if not await throttle(update, "usershared", 6, 30):
        return
    opts = await load_options(user.id)
    for target in ids[:3]:
        await present_user(
            context.bot, chat_id=chat.id, requester_id=user.id, user=USERS.get(str(target)), user_id=target,
            opts=opts, heading="کاربر انتخاب‌شده", back="m:tools",
        )


async def show_saved_chats(bot: Any, chat_id: int, user_id: int, page: int, query: Any) -> None:
    total = await dbx(db_count_selected_chats, user_id, _default=0) or 0
    pages = max((total + CHATS_PAGE_SIZE - 1) // CHATS_PAGE_SIZE, 1)
    page = max(0, min(page, pages - 1))
    items = await dbx(db_list_selected_chats, user_id, CHATS_PAGE_SIZE, page * CHATS_PAGE_SIZE, _default=[]) or []
    lines = [f"📂 <b>چت‌های ذخیره‌شده</b>\n{SEP}\n"]
    rows: list[list[Optional[InlineKeyboardButton]]] = []
    if not items:
        lines.append("⚪ هنوز چتی انتخاب نکرده‌ای. از «🧲 انتخابگر چت‌ها» استفاده کن.")
    for item in items:
        title = item.get("title") or item.get("username") or str(item["chat_id"])
        icon = chat_icon(item.get("chat_type"))
        lines.append(
            f"{icon} <b>{esc(trunc(title, 34))}</b>\n"
            f"   🆔 {code(item['chat_id'])} │ {esc(ownership_short(item.get('ownership_code')))}"
        )
        rows.append([btn(f"{icon} {trunc(title, 24)} · {ownership_short(item.get('ownership_code'))}", f"sc:v:{item['id']}")])
    lines.append(f"\n📄 صفحه {page + 1} از {pages} — مجموع: {total}")
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(btn("◀️ قبلی", f"sc:l:{page - 1}"))
    if page < pages - 1:
        nav.append(btn("بعدی ▶️", f"sc:l:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([btn("🧲 انتخابگر چت‌ها", "sel:open")])
    if total:
        rows.append([btn("🗑 حذف همه", "sc:ca")])
    rows.append(back_row("m:chats", "🔙 بازگشت"))
    text = "\n".join(lines)
    if query is not None:
        await edit_or_send(bot, query, text, kb(rows))
    else:
        await send_html(bot, chat_id, text, kb(rows))


async def cb_saved(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    user = query.from_user
    chat_id = msg_chat_id(query)
    action = parts[1]
    if action == "l":
        await show_saved_chats(bot, chat_id, user.id, to_int(parts[2]), query)
    elif action == "v":
        item = await dbx(db_get_selected_chat, user.id, to_int(parts[2]), _default=None)
        if not item:
            await edit_or_send(bot, query, "⚪ این رکورد پیدا نشد (شاید حذف شده).", kb([[btn("📂 فهرست", "sc:l:0")]]))
            return
        wait = RATE.check(user.id, "sc_view", 8, 30)
        if wait > 0:
            await send_html(bot, chat_id, f"⏳ لطفاً {int(wait) + 1} ثانیه صبر کن.", kb([close_row()]))
            return
        await inspect_selected_chat(
            bot, chat_id=chat_id, user_id=user.id, target_chat_id=int(item["chat_id"]),
            request_kind=item.get("request_kind") or "manual", opts=opts,
            shared_title=item.get("title"), shared_username=item.get("username"), query=query,
        )
    elif action == "d":
        row_id = to_int(parts[2])
        await edit_or_send(
            bot, query, "🗑 این چت از فهرست ذخیره‌شده‌ها حذف شود؟\n<i>خود چت در تلگرام هیچ تغییری نمی‌کند.</i>",
            kb([[btn("✅ بله، حذف کن", f"sc:dy:{row_id}")], [btn("❌ انصراف", "sc:l:0")]]),
        )
    elif action == "dy":
        removed = await dbx(db_delete_selected_chat, user.id, to_int(parts[2]), _default=0)
        await edit_or_send(bot, query, "✅ حذف شد." if removed else "⚪ رکوردی حذف نشد.", kb([[btn("📂 فهرست", "sc:l:0")]]))
    elif action == "ca":
        await edit_or_send(
            bot, query, "🗑 همه‌ی چت‌های ذخیره‌شده‌ی تو حذف شود؟",
            kb([[btn("✅ بله، همه را حذف کن", "sc:cy")], [btn("❌ انصراف", "sc:l:0")]]),
        )
    elif action == "cy":
        removed = await dbx(db_clear_selected_chats, user.id, _default=0)
        await edit_or_send(bot, query, f"✅ {removed or 0} چت از فهرست حذف شد.", kb([back_row("m:chats", "🔙 بازگشت")]))
    else:
        raise ValueError("unknown saved-chat action")


async def cb_selector(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    chat_id = msg_chat_id(query)
    if parts[1] != "open":
        raise ValueError("unknown selector action")
    if not is_private_query(query):
        await send_html(
            bot, chat_id,
            "ℹ️ انتخابگر چت‌ها فقط در گفتگوی خصوصی با ربات کار می‌کند.",
            kb([[url_btn("🤖 باز کردن ربات", f"https://t.me/{bot.username}?start=chats")]] if bot.username else [close_row()]),
        )
        return
    try:
        keyboard = selector_keyboard()
    except Exception as exc:
        log.warning("Full selector keyboard failed (%s); falling back", type(exc).__name__)
        keyboard = selector_keyboard(full=False)
    sent = await send_html(bot, chat_id, SELECTOR_INTRO, keyboard)
    if sent is None:
        sent = await send_html(bot, chat_id, SELECTOR_INTRO, selector_keyboard(full=False))
    if sent is None:
        await send_html(bot, chat_id, "⚠️ ساخت انتخابگر ممکن نشد؛ نسخه‌ی تلگرام یا کتابخانه را بررسی کن.", kb([back_row("m:chats")]))


# =========================================================
#       18 — OWNER PANEL, TRACKING, CHAT-MEMBER EVENTS
# =========================================================

def kb_admin() -> InlineKeyboardMarkup:
    return kb([
        [btn("📊 آمار ربات", "a:stats"), btn("💬 چت‌های شناخته‌شده", "a:chats:0")],
        [btn("📣 پیام همگانی", "a:bc"), btn("🧹 بهینه‌سازی پایگاه‌داده", "a:vac")],
        [btn("📄 دریافت لاگ", "a:log"), btn("🩺 سلامت ربات", "a:health")],
        back_row(),
    ])


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = ctx_basics(update)
    if msg is None or chat is None or user is None:
        return
    if not is_owner(user.id) or chat.type != "private":
        return
    await send_html(context.bot, chat.id, f"👑 <b>پنل مالک ربات</b>\n{SEP}", kb_admin())


def build_stats_report(stats: dict[str, Any]) -> Report:
    report = Report("آمار ربات", "📊")
    sec = report.section("کاربران و چت‌ها", "👥")
    sec.add("👤", "کاربران ثبت‌شده", stats["users"], inline=True)
    sec.add("✅", "کاربرانی که ربات را Start کرده‌اند", stats["started"], inline=True)
    sec.add("🚫", "کاربران مسدودکننده", stats["blocked"], inline=True)
    sec.add("🤖", "ربات‌های دیده‌شده", stats["bots_seen"], inline=True)
    sec.add("🏛", "چت‌های فعال", stats["known_chats"], inline=True)
    sec.add("🚪", "چت‌هایی که ربات از آن‌ها خارج شده", stats["left_chats"], inline=True)
    data = report.section("داده‌ها", "💾")
    data.add("🧲", "چت‌های انتخاب‌شده", stats["selected"], inline=True)
    data.add("📜", "رکوردهای تاریخچه", stats["history"], inline=True)
    if stats.get("db_size") is not None:
        data.add("🗄", "حجم پایگاه‌داده", fmt_size(stats["db_size"]), inline=True)
    counters = stats.get("counters") or {}
    if counters:
        usage = report.section("آمار استفاده", "📈")
        for key, value in sorted(counters.items()):
            usage.add("▫️", key, value, as_code=True, inline=True)
    runtime = report.section("زمان اجرا", "⏱")
    runtime.add("⏱", "زمان فعالیت", fmt_uptime(time.time() - START_TIME), inline=True)
    runtime.add("🧠", "گزارش‌های در حافظه", len(PAGES), inline=True)
    runtime.add("✉️", "پیام‌های در حافظه", len(MSGS), inline=True)
    runtime.add("👤", "کاربران در حافظه", len(USERS), inline=True)
    return report


async def broadcast_worker(bot: Any, owner_chat: int, text: str, targets: list[int]) -> None:
    sent = failed = blocked = 0
    for target in targets:
        _, err = await safe_call(bot.send_message, chat_id=target, text=text)
        if err is None:
            sent += 1
        elif isinstance(err, Forbidden):
            blocked += 1
            await dbx(db_mark_user_blocked, target, True)
        else:
            failed += 1
        await asyncio.sleep(0.06)
    await send_html(
        bot, owner_chat,
        f"📣 <b>گزارش پیام همگانی</b>\n{SEP}\n\n✅ ارسال‌شده: {sent}\n🚫 مسدودکننده: {blocked}\n⚠️ ناموفق: {failed}",
        kb([[btn("👑 پنل مالک", "a:home")]]),
    )


async def cb_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, parts: list[str], opts: Options) -> None:
    bot = context.bot
    user = query.from_user
    chat_id = msg_chat_id(query)
    if not is_owner(user.id):
        await answer_cb(query, "این بخش فقط برای مالک ربات است.", True)
        return
    action = parts[1]
    if action == "home":
        context.user_data.pop("mode", None)
        await edit_or_send(bot, query, f"👑 <b>پنل مالک ربات</b>\n{SEP}", kb_admin())
    elif action == "stats":
        stats = await dbx(db_collect_stats, _default=None)
        if not stats:
            await edit_or_send(bot, query, "⚠️ خواندن آمار ممکن نشد.", kb([[btn("👑 پنل", "a:home")]]))
            return
        await send_report(bot, chat_id, build_stats_report(stats), [[btn("🔄 بروزرسانی", "a:stats")], [btn("👑 پنل", "a:home")]],
                          edit_query=query, owner_id=user.id)
    elif action == "chats":
        page = max(to_int(parts[2]), 0)
        items = await dbx(db_list_known_chats, 8, page * 8, _default=[]) or []
        lines = [f"💬 <b>چت‌های شناخته‌شده</b>\n{SEP}\n"]
        rows: list[list[Optional[InlineKeyboardButton]]] = []
        for item in items:
            state = "🟢" if item["is_active"] else "🔴"
            lines.append(f"{state} {chat_icon(item['chat_type'])} <b>{esc(trunc(item['title'] or item['username'] or '—', 30))}</b> │ {code(item['chat_id'])}")
            rows.append([btn(f"{state} {trunc(item['title'] or str(item['chat_id']), 28)}", f"c:v:{item['chat_id']}")])
        if not items:
            lines.append("⚪ موردی نیست.")
        nav = []
        if page > 0:
            nav.append(btn("◀️ قبلی", f"a:chats:{page - 1}"))
        if len(items) == 8:
            nav.append(btn("بعدی ▶️", f"a:chats:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([btn("👑 پنل", "a:home")])
        await edit_or_send(bot, query, "\n".join(lines), kb(rows))
    elif action == "bc":
        context.user_data["mode"] = "broadcast"
        await edit_or_send(bot, query, PROMPTS["broadcast"], kb_cancel())
    elif action == "bcy":
        text = context.user_data.pop("broadcast_text", None)
        if not text:
            await edit_or_send(bot, query, "⚪ متنی برای ارسال وجود ندارد.", kb([[btn("👑 پنل", "a:home")]]))
            return
        targets = await dbx(db_broadcast_targets, _default=[]) or []
        await edit_or_send(bot, query, f"📣 ارسال برای {len(targets)} کاربر آغاز شد؛ پس از پایان گزارش می‌دهم.", kb([[btn("👑 پنل", "a:home")]]))
        context.application.create_task(broadcast_worker(bot, chat_id, text, targets))
    elif action == "vac":
        await dbx(db_vacuum)
        await edit_or_send(bot, query, "✅ پایگاه‌داده بهینه‌سازی شد.", kb([[btn("👑 پنل", "a:home")]]))
    elif action == "log":
        try:
            lines = Path(LOG_PATH).read_text(encoding="utf-8", errors="ignore").splitlines()[-120:]
        except OSError:
            lines = []
        content = TOKEN_PATTERN.sub("<TOKEN-REDACTED>", "\n".join(lines)) or "(لاگ خالی است)"
        buffer = io.BytesIO(content.encode("utf-8"))
        buffer.name = "telegram_intelligence_tail.log"
        await safe_call(bot.send_document, chat_id=chat_id, document=buffer, caption="📄 آخرین خطوط لاگ (توکن حذف شده است)",
                        reply_markup=kb([close_row()]))
    elif action == "health":
        me, err = await safe_call(bot.get_me)
        info, werr = await safe_call(bot.get_webhook_info)
        report = Report("سلامت ربات", "🩺")
        sec = report.section("اتصال", "🌐")
        if me is not None:
            sec.add("🤖", "یوزرنیم ربات", "@" + (me.username or "?"), as_code=True)
            sec.add("🆔", "آیدی ربات", me.id, as_code=True)
            sec.add_bool("➕", "امکان افزوده‌شدن به گروه", getattr(me, "can_join_groups", None))
            sec.add_bool("👁", "خواندن همه‌ی پیام‌های گروه", getattr(me, "can_read_all_group_messages", None))
            sec.add_bool("⌨️", "حالت Inline", getattr(me, "supports_inline_queries", None))
        else:
            sec.add("⚠️", "getMe", explain_error(err))
        if info is not None:
            sec.add("🕸", "Webhook", info.url or "تنظیم نشده (Long Polling ✅)", as_code=True)
            sec.add("📬", "به‌روزرسانی‌های در انتظار", info.pending_update_count, inline=True)
            if getattr(info, "last_error_message", None):
                sec.add("⚠️", "آخرین خطای Webhook", info.last_error_message)
        sys_sec = report.section("سیستم", "🖥")
        sys_sec.add("🐍", "Python", sys.version.split()[0], as_code=True, inline=True)
        sys_sec.add("📦", "python-telegram-bot", getattr(telegram, "__version__", "?"), as_code=True, inline=True)
        sys_sec.add("🗄", "مسیر پایگاه‌داده", DB_PATH, as_code=True)
        await send_report(bot, chat_id, report, [[btn("🔄 بروزرسانی", "a:health")], [btn("👑 پنل", "a:home")]],
                          edit_query=query, owner_id=user.id)
    else:
        raise ValueError("unknown admin action")


async def track_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lightweight bookkeeping for every update (never blocks other handlers)."""
    try:
        user = update.effective_user
        chat = update.effective_chat
        message = update.effective_message
        if user is not None:
            remember_user(user)
            await dbx(db_upsert_user, user, bool(chat is not None and chat.type == "private"))
        if message is not None:
            reply = getattr(message, "reply_to_message", None)
            if reply is not None and getattr(reply, "from_user", None) is not None:
                remember_user(reply.from_user)
            origin = getattr(message, "forward_origin", None)
            origin_user = getattr(origin, "sender_user", None) if origin is not None else None
            if origin_user is not None:
                remember_user(origin_user)
            for member in getattr(message, "new_chat_members", None) or []:
                remember_user(member)
        if chat is not None and chat.type in ("group", "supergroup", "channel"):
            await dbx(db_upsert_known_chat, chat, None, True, None)
        if update.message is not None:
            await dbx(db_bump_stat, "messages_seen")
        elif update.callback_query is not None:
            await dbx(db_bump_stat, "button_presses")
    except Exception as exc:        # pragma: no cover — tracking must never break the bot
        log.debug("track_update failed: %s", type(exc).__name__)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """React when the bot is added to / removed from / promoted in a chat."""
    event = update.my_chat_member
    if event is None:
        return
    bot = context.bot
    chat = event.chat
    actor = event.from_user
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    if chat.type == "private":
        if new_status == ChatMemberStatus.BANNED:
            await dbx(db_mark_user_blocked, chat.id, True)
        elif new_status == ChatMemberStatus.MEMBER:
            await dbx(db_mark_user_blocked, chat.id, False)
        return
    is_member_now = new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) or (
        new_status == ChatMemberStatus.RESTRICTED and getattr(event.new_chat_member, "is_member", False)
    )
    was_member = old_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    await dbx(db_upsert_known_chat, chat, str(new_status), is_member_now, actor.id if actor else None)
    log.info("my_chat_member: chat=%s type=%s %s -> %s", chat.id, chat.type, old_status, new_status)
    opts = await load_options(actor.id if actor else None)

    if is_member_now and not was_member:
        if chat.type in ("group", "supergroup"):
            await send_html(
                bot, chat.id,
                f"👋 سلام! من <b>{esc(BOT_NAME)}</b> هستم.\n{SEP}\n\n"
                "• <code>/id</code> → آیدی عددی این گروه + اطلاعات کامل\n"
                "• <code>/get</code> روی پیام (ریپلای) → تحلیل کامل پیام\n"
                "• برای گزارش کامل‌تر (ادمین‌ها، مجوزها) مرا ادمین کن.",
                kb([[btn("🆔 آیدی و اطلاعات گروه", f"c:v:{chat.id}")], close_row()]),
            )
        if actor is not None and opts.notify_chat_added:
            await send_html(
                bot, actor.id,
                f"✅ <b>ربات به چت اضافه شد</b>\n{SEP}\n\n🏛 {esc(chat_display(chat))}\n🆔 {code(chat.id)}\n"
                f"🏷 {esc(type_label(chat.type))}",
                kb([[btn("🏛 گزارش کامل چت", f"c:v:{chat.id}")], [btn("👮 مالک و ادمین‌ها", f"c:a:{chat.id}")]]),
            )
    elif new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and was_member:
        if actor is not None and opts.notify_chat_added:
            await send_html(
                bot, actor.id,
                f"🚪 ربات از چت «{esc(chat_display(chat))}» ({code(chat.id)}) خارج یا حذف شد.", None,
            )
    elif new_status == ChatMemberStatus.ADMINISTRATOR and old_status != ChatMemberStatus.ADMINISTRATOR:
        if actor is not None and opts.notify_chat_added:
            await send_html(
                bot, actor.id,
                f"🛡 ربات در «{esc(chat_display(chat))}» ادمین شد؛ اکنون گزارش کامل‌تر (ادمین‌ها و لینک دعوت) در دسترس است.",
                kb([[btn("🏛 گزارش کامل چت", f"c:v:{chat.id}")]]),
            )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler: log technically, tell the user gently, never crash."""
    error = context.error
    if isinstance(error, RetryAfter):
        log.warning("Flood control hit (RetryAfter)")
        return
    if isinstance(error, (TimedOut, NetworkError)) and not isinstance(error, BadRequest):
        log.warning("Network problem: %s", type(error).__name__)
        return
    if isinstance(error, InvalidToken):
        log.critical("Telegram rejected the bot token (InvalidToken).")
        return
    if isinstance(error, Forbidden):
        log.info("Forbidden: %s", getattr(error, "message", "")[:120])
        return
    log.error("Unhandled exception while processing an update", exc_info=error)
    if isinstance(update, Update) and update.effective_chat is not None:
        with contextlib.suppress(Exception):
            await send_html(context.bot, update.effective_chat.id, "⚠️ خطای داخلی رخ داد؛ لطفاً دوباره تلاش کن.", None)
    if RATE.check(OWNER_ID, "errnotify", 1, 120) == 0:
        with contextlib.suppress(Exception):
            await send_html(context.bot, OWNER_ID, f"⚠️ خطای مدیریت‌نشده: <code>{esc(type(error).__name__)}</code> (جزئیات در لاگ)", None)


# =========================================================
#       19 — REGISTRATION, MAIN, SELF-TEST
# =========================================================

CALLBACK_ROUTES: dict[str, Callable[..., Awaitable[None]]] = {
    "m": cb_menu,
    "hp": cb_help,
    "s": cb_settings,
    "t": cb_tool,
    "u": cb_user,
    "c": cb_chat,
    "ph": cb_photo,
    "pg": cb_page,
    "x": cb_close,
    "mj": cb_msg_json,
    "mi": cb_msg_inspect,
    "f": cb_file,
    "h": cb_history,
    "sc": cb_saved,
    "sel": cb_selector,
    "a": cb_admin,
}

COMMAND_HANDLERS: list[tuple[str, Callable[..., Awaitable[None]]]] = [
    ("start", cmd_start),
    ("help", cmd_help),
    ("get", cmd_get),
    ("id", cmd_id),
    ("info", cmd_info),
    ("user", cmd_user),
    ("chat", cmd_chat),
    ("forward", cmd_forward),
    ("reply", cmd_reply),
    ("photo", cmd_photo),
    ("json", cmd_json),
    ("version", cmd_version),
    ("menu", cmd_menu),
    ("admin", cmd_admin),
]

KEYBOARD_TEXTS = list(MAIN_BUTTONS.values()) + [BACK_BUTTON_TEXT, "📂 چت‌های ذخیره‌شده"]


def token_is_valid(token: Optional[str]) -> bool:
    """Return True only for a token-shaped value; never embeds a real token."""
    return bool(token) and bool(re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", str(token).strip()))


def register_handlers(app: Application) -> None:
    """Register every handler in one organised place (no duplicates)."""
    # گروه -10: ثبت اطلاعات هر آپدیت (مانع اجرای بقیه‌ی هندلرها نمی‌شود)
    app.add_handler(TypeHandler(Update, track_update), group=-10)

    # دستورها (پیام‌های گروه/خصوصی و پست‌های کانال)
    command_filter = filters.UpdateType.MESSAGE | filters.UpdateType.CHANNEL_POST
    for name, callback in COMMAND_HANDLERS:
        app.add_handler(CommandHandler(name, callback, filters=command_filter))

    # دکمه‌های شیشه‌ای
    app.add_handler(CallbackQueryHandler(on_callback))

    # انتخابگرهای بومی تلگرام (ChatShared / UsersShared)
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, on_chat_shared))
    users_shared_filter = getattr(filters.StatusUpdate, "USERS_SHARED", None)
    if users_shared_filter is not None:
        app.add_handler(MessageHandler(users_shared_filter, on_users_shared))

    # دکمه‌های کیبورد پایین صفحه
    pattern = "^(?:" + "|".join(re.escape(text) for text in KEYBOARD_TEXTS) + ")$"
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(pattern), on_keyboard_text))

    # هر پیام دیگر در خصوصی: حالت‌های ورودی یا بررسی خودکار
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.StatusUpdate.ALL, on_private_message
    ))

    # افزوده‌شدن / حذف ربات از چت‌ها
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_error_handler(on_error)


async def post_init(app: Application) -> None:
    """Runs once after the application is initialised: publish commands."""
    commands = [BotCommand(name, description) for name, description in BOT_COMMANDS]
    _, err = await safe_call(app.bot.set_my_commands, commands)
    if err is not None:
        log.warning("set_my_commands failed: %s", type(err).__name__)
    await safe_call(
        app.bot.set_my_short_description,
        "ابزار پیشرفته‌ی بررسی اطلاعات کاربر، گروه، کانال، پیام و فایل در تلگرام",
    )
    me = app.bot
    log.info("Bot started as @%s (id=%s) — %s v%s", me.username, me.id, BOT_NAME, BOT_VERSION)


def main() -> None:
    if not token_is_valid(TOKEN):
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing or invalid. "
            "Set it in your environment before starting the bot."
        )

    init_db()

    app = Application.builder().token(TOKEN).build()
    app.post_init = post_init

    register_handlers(app)

    try:
        app.run_polling(
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES
        )
    except InvalidToken:
        log.critical("The Telegram bot token was rejected by Telegram. Check TOKEN in the configuration section.")
        raise SystemExit(1)


# ---------------------------------------------------------
#   Self-test with synthetic Telegram objects (no network)
# ---------------------------------------------------------

def run_selftest() -> int:
    """Run offline checks: python telegram_intelligence_bot.py --selftest"""
    global DB_PATH
    from telegram import (
        Chat as TChat, Contact, Dice, Document, Location, MessageOriginChannel, MessageOriginChat,
        MessageOriginHiddenUser, MessageOriginUser, PhotoSize, Poll, PollOption, Sticker, Video, Voice,
    )

    results: list[tuple[str, bool, str]] = []

    def check(name: str, func: Callable[[], Any]) -> None:
        try:
            outcome = func()
            results.append((name, outcome is not False, ""))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    stamp = datetime.now(timezone.utc)
    user = User(id=123456789, first_name="Example", last_name="User", is_bot=False,
                username="example", language_code="fa", is_premium=True)
    bot_user = User(id=42, first_name="HelperBot", is_bot=True, username="helper_bot")
    group = TChat(id=-1001234567890, type="supergroup", title="Test <Group> & Co")
    private = TChat(id=123456789, type="private", first_name="Example")

    def make(**kwargs: Any) -> Message:
        base = dict(message_id=10, date=stamp, chat=private, from_user=user)
        base.update(kwargs)
        return Message(**base)

    def t_token() -> bool:
        return (not token_is_valid("")) and (not token_is_valid("placeholder")) \
            and (not token_is_valid("nocolon")) and token_is_valid("123456:" + "A" * 35)

    def t_db() -> bool:
        global DB_PATH
        original = DB_PATH
        with tempfile.TemporaryDirectory() as tmp:
            DB_PATH = os.path.join(tmp, "test.db")
            init_db()
            db_upsert_user(user, True)
            assert db_get_cached_user(user.id)["username"] == "example"
            db_set_setting(user.id, "date_mode", "jalali")
            assert db_get_settings(user.id)["date_mode"] == "jalali"
            row = db_save_selected_chat(user.id, {"chat_id": group.id, "chat_type": "supergroup", "title": "T"})
            assert db_get_selected_chat(user.id, row)["chat_id"] == group.id
            db_add_history(user.id, group.id, "chat", group.id, "T", "x")
            assert db_count_history(user.id) == 1
            db_upsert_known_chat(group, "member", True, user.id)
            db_bump_stat("x")
            assert db_collect_stats()["selected"] == 1
            try:
                db_set_setting(user.id, "evil'; DROP TABLE settings;--", "1")
                raise AssertionError("unknown setting accepted")
            except ValueError:
                pass
        DB_PATH = original
        return True

    def t_html_escape() -> bool:
        sec = Section("t", "x")
        sec.add("a", "label", "<script>alert(1)</script> & more")
        return "&lt;script&gt;" in sec.rows[0] and "<script>" not in sec.rows[0]

    def t_pagination() -> bool:
        report = Report("big", "x")
        sec = report.section("rows", "x")
        for i in range(300):
            sec.add("a", f"label {i}", "v" * 100)
        pages = report.with_status_footer().paginate()
        return len(pages) > 1 and all(len(p) <= TG_TEXT_LIMIT for p in pages)

    def t_jalali() -> bool:
        return gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1) and gregorian_to_jalali(2025, 3, 21) == (1404, 1, 1)

    def t_user_engine() -> bool:
        info = get_user_information(user)
        assert info["fields"]["is_premium"]["state"] == "true"
        assert info["fields"]["last_name"]["state"] == "present"
        assert info["fields"]["can_join_groups"]["state"] == "missing"
        assert info["username_url"] == "https://t.me/example"
        bundle = UserBundle(user_id=user.id, user=user, photos_total=2)
        sections = build_user_sections(bundle, Options())
        return any("اطلاعات کاربر" in s.title for s in sections)

    def t_forward() -> bool:
        origin_user = make(forward_origin=MessageOriginUser(date=stamp, sender_user=bot_user))
        assert inspect_forward(origin_user).kind == "user"
        hidden = make(forward_origin=MessageOriginHiddenUser(date=stamp, sender_user_name="Hidden Person"))
        info = inspect_forward(hidden)
        assert info.kind == "hidden_user" and info.user is None
        text = "\n".join(r for s in build_forward_sections(info, Options()) for r in s.rows)
        assert "Hidden Person" in text and "غیرقابل دریافت" in text
        chat_origin = make(forward_origin=MessageOriginChat(date=stamp, sender_chat=group, author_signature="sig"))
        assert inspect_forward(chat_origin).kind == "chat"
        channel = make(forward_origin=MessageOriginChannel(date=stamp, chat=TChat(id=-1009, type="channel", title="Ch"), message_id=77))
        finfo = inspect_forward(channel)
        assert finfo.kind == "channel" and finfo.message_id == 77
        assert forward_info_dict(finfo)["original_message_id"] == 77
        return not inspect_forward(make(text="x")).present

    def t_parsers() -> bool:
        photo = (PhotoSize("fid1", "uid1", 90, 90, 100), PhotoSize("fid2", "uid2", 800, 600, 5000))
        samples = {
            "text": make(text="hello world"),
            "photo": make(photo=photo, caption="cap"),
            "video": make(video=Video("v", "vu", 640, 480, 12, mime_type="video/mp4", file_size=1000)),
            "document": make(document=Document("d", "du", file_name="a.pdf", mime_type="application/pdf", file_size=9)),
            "voice": make(voice=Voice("vo", "vou", 5, mime_type="audio/ogg")),
            "sticker": make(sticker=Sticker("s", "su", 512, 512, False, False, "regular", emoji="😀", set_name="pack")),
            "location": make(location=Location(35.7, 51.4, live_period=60)),
            "contact": make(contact=Contact("+989000000000", "Ali", user_id=user.id)),
            "dice": make(dice=Dice(64, "🎰")),
            "poll": make(poll=Poll("1", "Q?", (PollOption("a", 1), PollOption("b", 2)), 3, False, True, "regular", False)),
        }
        for key, message in samples.items():
            assert key in detect_message_types(message), key
            sections = build_message_sections(message, Options())
            assert sections, key
            body = "\n".join(r for s in sections for r in s.rows)
            assert "<script" not in body
        slot = "\n".join(r for s in build_message_sections(samples["dice"], Options()) for r in s.rows)
        assert "جکپات" in slot
        return True

    def t_service() -> bool:
        message = Message(message_id=5, date=stamp, chat=group, from_user=user,
                          new_chat_members=(bot_user,), new_chat_title=None)
        sections = build_message_sections(message, Options())
        return any("ورود عضو" in s.title for s in sections)

    def t_chat_report() -> bool:
        bundle = ChatBundle(ref=group.id, chat=group, member_count=10)
        report = build_chat_report(bundle, Options(), show_ownership=True, requested_created=True)
        text = "\n".join(report.paginate())
        assert "&lt;Group&gt;" in text and "-1001234567890" in text and "1234567890" in text
        failed = build_chat_report(ChatBundle(ref=-1005, error="چت پیدا نشد"), Options())
        return "چت پیدا نشد" in "\n".join(failed.paginate())

    def t_ownership() -> bool:
        bundle = ChatBundle(ref=1, chat=group, requester_id=user.id)
        assert evaluate_ownership(bundle, True).code == "selected_created"
        assert evaluate_ownership(bundle, False).code == "unverified"
        return True

    def t_json() -> bool:
        message = make(text="hi", forward_origin=MessageOriginHiddenUser(date=stamp, sender_user_name="H"))
        data = message_info_json(message)
        parsed = json.loads(dumps_json(data))
        return parsed["ids"]["message_id"] == 10 and parsed["forward"]["user_id_available"] is False

    def t_fileid() -> bool:
        payload = struct.pack("<iB", 2, 4) + bytes(range(1, 11)) + bytes([30, 4])
        token = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        info = decode_file_id(token)
        return info is not None and info["dc_id"] == 4 and info["type_id"] == 2

    def t_links() -> bool:
        assert parse_telegram_link("https://t.me/c/1234567890/55")["chat_id"] == -1001234567890
        assert parse_telegram_link("https://t.me/example_chan/9")["message_id"] == 9
        assert parse_telegram_link("https://t.me/+AbCdEfGhIjK")["kind"] == "invite_plus"
        assert convert_chat_id(-1001234567890)["short_id"] == "1234567890"
        assert parse_ref("@example") == "@example" and parse_ref("-100123") == -100123 and parse_ref("bad id!") is None
        return True

    def t_callbacks() -> bool:
        markups = [kb_main(OWNER_ID), kb_help_menu(), kb_tools(), kb_chats_menu(3), kb_admin(),
                   kb_settings({k: v["default"] for k, v in SETTINGS_SPEC.items()}),
                   kb(kb_user_actions(1, "x", Options())), kb(kb_chat_actions(-100123, username="x", has_photo=True)),
                   kb(photo_nav_rows(1, 2, 5, "fid"))]
        for markup in markups:
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data is not None:
                        assert len(button.callback_data.encode()) <= 64, button.callback_data
                        assert CALLBACK_DATA_RE.fullmatch(button.callback_data), button.callback_data
                        assert button.callback_data.split(":")[0] in CALLBACK_ROUTES, button.callback_data
        return True

    def t_selector() -> bool:
        keyboard = selector_keyboard()
        requests = [b.request_chat for row in keyboard.keyboard for b in row if getattr(b, "request_chat", None)]
        created = [r for r in requests if getattr(r, "chat_is_created", None)]
        ids = {r.request_id for r in requests}
        return bool(created) and ids >= {RQ_CH_CREATED, RQ_GR_CREATED}

    def t_register() -> bool:
        app = Application.builder().token("123456789:" + "A" * 35).build()
        register_handlers(app)
        names = [name for name, _ in COMMAND_HANDLERS]
        assert len(names) == len(set(names))
        required = {"start", "help", "get", "id", "info", "user", "chat", "forward", "reply", "photo", "json", "version"}
        assert required <= set(names)
        total = sum(len(h) for h in app.handlers.values())
        return total >= len(COMMAND_HANDLERS) + 5

    def t_redaction() -> bool:
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "token 123456789:" + "A" * 35 + " leaked", None, None)
        return "AAAA" not in RedactingFormatter("%(message)s").format(record)

    for name, func in [
        ("اعتبارسنجی توکن", t_token), ("پایگاه‌داده و SQL پارامتری", t_db), ("Escape کردن HTML", t_html_escape),
        ("صفحه‌بندی گزارش", t_pagination), ("تبدیل تاریخ شمسی", t_jalali), ("موتور اطلاعات کاربر", t_user_engine),
        ("فوروارد (user/hidden/chat/channel)", t_forward), ("پارسرهای انواع پیام", t_parsers),
        ("پیام‌های سرویس", t_service), ("گزارش چت", t_chat_report), ("بررسی مالکیت", t_ownership),
        ("خروجی JSON", t_json), ("رمزگشایی File ID", t_fileid), ("لینک و تبدیل آیدی", t_links),
        ("اعتبار callback_data و مسیرها", t_callbacks), ("انتخابگر KeyboardButtonRequestChat", t_selector),
        ("ثبت هندلرها", t_register), ("حذف توکن از لاگ", t_redaction),
    ]:
        check(name, func)

    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_intelligence.db")
    failed = 0
    for name, ok, detail in results:
        print(("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail else ""))
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} تست موفق")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    main()

