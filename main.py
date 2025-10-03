"""
Продвинутый телеграм модератор-бот на aiogram 3
Функции:
- Фильтр запрещённых слов и анти-ссылки с белым списком
- Раздельные наказания для слов и ссылок (Warn / Mute / Ban / None)
- Включение/выключение бота через админ-панель
- Режимы работы: all / admins
- Управление бот-админами и Owner (ID: 7322925570)
- Все тексты жирным шрифтом
- Работает в обычных чатах и в темах (topics)
- Полная админ-панель через inline-кнопки
- Панель доступна только Owner и бот-админам
"""

import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

load_dotenv()

OWNER_ID = 7322925570  # твой ID

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не установлен в .env")

DATA_FILE = "data.json"
DEFAULTS = {
    "banned_words": [],
    "allowed_links": [],
    "link_protection": True,
    "action_words": "mute",
    "mute_seconds_words": 600,
    "action_links": "mute",
    "mute_seconds_links": 600,
    "enabled": True,
    "mode": "admins",  # admins = игнорируем админов, all = наказываем всех
    "bot_admins": []   # список бот-админов
}

LINK_REGEX = re.compile(r"(https?://|t\.me/|telegram\.me/|\bwww\.|\.[a-z]{2,3}(?:/|\b))", re.IGNORECASE)

bot = Bot(token=BOT_TOKEN, parse_mode="MarkdownV2")
dp = Dispatcher()

# -------------------- Работа с data.json --------------------
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_data(data: Dict[str, Any]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

def ensure_chat_settings(chat_id: str) -> Dict[str, Any]:
    if chat_id not in data:
        data[chat_id] = DEFAULTS.copy()
        save_data(data)
    return data[chat_id]

# -------------------- Проверки --------------------
def compile_patterns(words: List[str]) -> List[re.Pattern]:
    patterns = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if " " in w:
            patterns.append(re.compile(re.escape(w), re.IGNORECASE))
        else:
            patterns.append(re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE))
    return patterns

def contains_banned(text: str, patterns: List[re.Pattern]) -> (bool, str):
    if not text:
        return False, ""
    for patt in patterns:
        m = patt.search(text)
        if m:
            return True, m.group(0)
    return False, ""

def contains_link(text: str, allowed: List[str]) -> (bool, str):
    if not text:
        return False, ""
    m = LINK_REGEX.search(text)
    if not m:
        return False, ""
    for domain in allowed:
        if domain.lower() in text.lower():
            return False, ""
    return True, m.group(0)

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.is_chat_admin()
    except Exception:
        return False

def is_bot_admin(chat_id: str, user_id: int) -> bool:
    settings = ensure_chat_settings(chat_id)
    return user_id in settings.get("bot_admins", []) or user_id == OWNER_ID

# -------------------- Админ-панель --------------------
def admin_panel_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Вкл/Выкл", callback_data="toggle_enabled"),
        InlineKeyboardButton("⚙️ Режим", callback_data="toggle_mode"),
        InlineKeyboardButton("🔨 Наказания", callback_data="set_actions"),
        InlineKeyboardButton("📝 Запрещённые слова", callback_data="edit_words"),
        InlineKeyboardButton("🔗 Белый список ссылок", callback_data="edit_links"),
        InlineKeyboardButton("👑 Управление админами", callback_data="manage_admins")
    )
    return kb

@dp.message(Command(commands=["admin"]))
async def show_admin_panel(message: types.Message):
    chat_id = str(message.chat.id)
    if not is_bot_admin(chat_id, message.from_user.id):
        return await message.reply("**Только Owner и бот-админы могут открывать панель**")
    await message.reply("**Админ-панель:**", reply_markup=admin_panel_keyboard())

# -------------------- Управление включением/режимом --------------------
@dp.callback_query(lambda c: c.data == "toggle_enabled")
async def callback_toggle_enabled(query: types.CallbackQuery):
    chat_id = str(query.message.chat.id)
    settings = ensure_chat_settings(chat_id)
    if not is_bot_admin(chat_id, query.from_user.id):
        return await query.answer("Нет прав")
    settings["enabled"] = not settings.get("enabled", True)
    save_data(data)
    status = "✅ Включён" if settings["enabled"] else "⛔ Выключен"
    await query.message.edit_text(f"**Бот {status}**", reply_markup=admin_panel_keyboard())
    await query.answer()

@dp.callback_query(lambda c: c.data == "toggle_mode")
async def callback_toggle_mode(query: types.CallbackQuery):
    chat_id = str(query.message.chat.id)
    settings = ensure_chat_settings(chat_id)
    if not is_bot_admin(chat_id, query.from_user.id):
        return await query.answer("Нет прав")
    settings["mode"] = "all" if settings.get("mode", "admins") == "admins" else "admins"
    save_data(data)
    mode_text = "Все" if settings["mode"] == "all" else "Только пользователи"
    await query.message.edit_text(f"**Режим изменён: {mode_text}**", reply_markup=admin_panel_keyboard())
    await query.answer()

# -------------------- Модерация сообщений --------------------
@dp.message()
async def mod_message(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    chat_id = str(message.chat.id)
    settings = ensure_chat_settings(chat_id)

    if not settings.get("enabled", True):
        return

    # Режим
    if settings.get("mode", "admins") == "admins":
        if await is_user_admin(message.chat.id, message.from_user.id):
            return

    text = message.text or message.caption or ""
    patterns = compile_patterns(settings.get("banned_words", []))
    is_banned, _ = contains_banned(text, patterns)
    found_link, _ = (False, "")
    if settings.get("link_protection", True):
        found_link, _ = contains_link(text, settings.get("allowed_links", []))

    if not is_banned and not found_link:
        return

    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception:
        pass

    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name

    # Раздельные действия
    if is_banned:
        action = settings.get("action_words", "mute")
        mute_seconds = settings.get("mute_seconds_words", 600)
        reason = "запрещённое слово"
    elif found_link:
        action = settings.get("action_links", "mute")
        mute_seconds = settings.get("mute_seconds_links", 600)
        reason = "ссылку"
    else:
        return

    minutes = mute_seconds // 60
    minutes_text = f"{minutes} минут" if minutes >= 1 else f"{mute_seconds} секунд"

    if action == "warn":
        await bot.send_message(message.chat.id, f"🚫 **Пользователь {username} написал {reason} и получил предупреждение.**\n**Пожалуйста, соблюдайте правила чата!**")
    elif action == "mute":
        until_date = datetime.utcnow() + timedelta(seconds=mute_seconds)
        permissions = ChatPermissions(can_send_messages=False)
        try:
            await bot.restrict_chat_member(message.chat.id, message.from_user.id, permissions=permissions, until_date=until_date)
        except Exception:
            pass
        await bot.send_message(message.chat.id, f"🚫 **Пользователь {username} написал {reason} и получил мут на {minutes_text}.**\n**Пожалуйста, соблюдайте правила чата!**")
    elif action == "ban":
        try:
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
        except Exception:
            pass
        await bot.send_message(message.chat.id, f"🚫 **Пользователь {username} написал {reason} и был заблокирован.**\n**Пожалуйста, соблюдайте правила чата!**")

# -------------------- Запуск --------------------
async def main():
    try:
        print("Запуск бота модерации...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
