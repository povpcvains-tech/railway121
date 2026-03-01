import os
import json
import logging
import sys
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
    Contact, Document, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError
from aiogram.enums import ChatMemberStatus

# ================== КОНФИГУРАЦИЯ ==================
BOT_TOKEN = "8390147683:AAGrG6qpYqesZIMTuJ-YontebMcc29OxXxU"
ADMIN_KEY = "school121_admin_secret_2026"
MODERATOR_KEY = "school121_moderator_secret_2026"
ROOT_USER_ID = 8073934406
ADMINS_FILE = "admins.json"
MODERATORS_FILE = "moderators.json"
BLOCKED_FILE = "blocked_users.json"
LOGS_FILE = "logs.json"
SETTINGS_FILE = "settings.json"
USERS_FILE = "users.json"
TICKETS_FILE = "tickets.json"
GROUPS_FILE = "groups.json"

DEFAULT_SETTINGS = {
    "registration_mode": "ID",
    "notification_interval": 60,
    "last_menu_file_id": None,
    "last_schedule_file_id": None,
    "pending_menu_file_id": None,
    "pending_schedule_file_id": None,
    "current_event": None,
    "event_updated_at": None,
    "flood_threshold": 5,
    "flood_window_ms": 1000,
    "flood_mute_duration": 30,
    "include_author_name": False,
    "include_school_website": False
}

# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)
flood_tracker = {}
muted_users = {}

# ================== ФУНКЦИИ РАБОТЫ С ФАЙЛАМИ ==================
def load_json(file_path: str, default=None):
    if not os.path.exists(file_path):
        save_json(file_path, default if default is not None else [])
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default if default is not None else []

def save_json(file_path: str, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_action(user_id: int, action: str, details: str = ""):
    users = load_json(USERS_FILE, [])
    user = next((u for u in users if u["user_id"] == user_id), None)
    phone = user.get("phone", "неизвестно") if user else "неизвестно"
    logs = load_json(LOGS_FILE, [])
    logs.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
        "phone": phone,
        "action": action,
        "details": details[:500]
    })
    save_json(LOGS_FILE, logs[-1000:])

# ================== ПРОВЕРКА РОЛЕЙ ==================
def is_root(user_id: int) -> bool:
    return user_id == ROOT_USER_ID

def is_admin(user_id: int) -> bool:
    return user_id in load_json(ADMINS_FILE, [])

def is_moderator(user_id: int) -> bool:
    return user_id in load_json(MODERATORS_FILE, [])

def is_staff(user_id: int) -> bool:
    return is_admin(user_id) or is_moderator(user_id) or is_root(user_id)

def is_blocked(user_id: int) -> bool:
    return user_id in load_json(BLOCKED_FILE, [])

def is_muted(user_id: int) -> bool:
    if user_id in muted_users:
        if datetime.now() < muted_users[user_id]["until"]:
            return True
        else:
            del muted_users[user_id]
    return False

def mute_user(user_id: int, duration_sec: int):
    muted_users[user_id] = {
        "until": datetime.now() + timedelta(seconds=duration_sec),
        "duration": duration_sec
    }

# ================== АНТИФЛУД ==================
def check_flood(user_id: int) -> bool:
    settings = get_settings()
    threshold = settings["flood_threshold"]
    window_ms = settings["flood_window_ms"]
    now = datetime.now()
    window_start = now - timedelta(milliseconds=window_ms)
    if user_id not in flood_tracker:
        flood_tracker[user_id] = []
    flood_tracker[user_id] = [ts for ts in flood_tracker[user_id] if ts > window_start]
    flood_tracker[user_id].append(now)
    return len(flood_tracker[user_id]) > threshold

# ================== ПОЛЬЗОВАТЕЛИ ==================
def get_user(user_id: int) -> Optional[Dict]:
    users = load_json(USERS_FILE, [])
    return next((u for u in users if u["user_id"] == user_id), None)

def add_user(user_id: int, phone: str = None, username: str = None, first_name: str = None, last_name: str = None):
    users = load_json(USERS_FILE, [])
    if not any(u["user_id"] == user_id for u in users):
        users.append({
            "user_id": user_id,
            "phone": phone,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        save_json(USERS_FILE, users)
        log_action(user_id, "user_registered", f"Phone: {phone}")

# ================== НАСТРОЙКИ ==================
def save_settings(settings: Dict):
    save_json(SETTINGS_FILE, settings)

def get_settings() -> Dict:
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS.copy())
        return DEFAULT_SETTINGS.copy()
    settings = load_json(SETTINGS_FILE)
    updated = False
    for key, default_value in DEFAULT_SETTINGS.items():
        if key not in settings:
            settings[key] = default_value
            updated = True
    if updated:
        save_settings(settings)
    return settings

# ================== ТИКЕТЫ ==================
def create_ticket(user_id: int, message_text: str, phone: str = None,
                  username: str = None, first_name: str = None,
                  last_name: str = None, registered_at: str = None) -> Dict:
    tickets = load_json(TICKETS_FILE, [])
    ticket_id = len(tickets) + 1
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "message_text": message_text[:1000],
        "phone": phone,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "registered_at": registered_at,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "open",
        "admin_response": None,
        "closed_at": None,
        "closed_by": None
    }
    tickets.append(ticket)
    save_json(TICKETS_FILE, tickets[-500:])
    return ticket

def get_ticket(ticket_id: int) -> Optional[Dict]:
    tickets = load_json(TICKETS_FILE, [])
    return next((t for t in tickets if t["ticket_id"] == ticket_id), None)

def update_ticket_status(ticket_id: int, status: str, admin_id: int = None, response: str = None):
    tickets = load_json(TICKETS_FILE, [])
    for ticket in tickets:
        if ticket["ticket_id"] == ticket_id:
            ticket["status"] = status
            if response:
                ticket["admin_response"] = response
            if status == "closed":
                ticket["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ticket["closed_by"] = admin_id
    save_json(TICKETS_FILE, tickets)
    return True

def get_open_tickets() -> List[Dict]:
    tickets = load_json(TICKETS_FILE, [])
    return [t for t in tickets if t["status"] == "open"]

# ================== КЛАВИАТУРЫ ==================
def get_user_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🍽 Питание")
    builder.button(text="📖 Расписание уроков")
    builder.button(text="🎉 Мероприятия")
    builder.button(text="📝 Поддержка")
    return builder.adjust(2).as_markup(resize_keyboard=True)

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📥 Загрузить питание (файл)")
    builder.button(text="📥 Загрузить расписание (файл)")
    builder.button(text="✏️ Установить мероприятие")
    builder.button(text="📢 Отправить оповещение")
    builder.button(text="⚙️ Админ-панель")
    builder.button(text="📬 Заявки в поддержку")
    builder.button(text="🍽 Питание")
    builder.button(text="📖 Расписание уроков")
    builder.button(text="🎉 Мероприятия")
    return builder.adjust(2, 2, 2, 3).as_markup(resize_keyboard=True)

def get_moderator_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📋 Подтвердить файлы")
    builder.button(text="📬 Заявки в поддержку")
    builder.button(text="📤 Экспорт статистики")
    builder.button(text="🔒 Заблокировать пользователя")
    builder.button(text="🔓 Разблокировать пользователя")
    builder.button(text="🍽 Питание")
    builder.button(text="📖 Расписание уроков")
    builder.button(text="🎉 Мероприятия")
    return builder.adjust(2, 2, 2, 2).as_markup(resize_keyboard=True)

def get_root_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔴 ROOT-ПАНЕЛЬ")
    builder.button(text="📥 Загрузить питание (файл)")
    builder.button(text="📥 Загрузить расписание (файл)")
    builder.button(text="✏️ Установить мероприятие")
    builder.button(text="📢 Отправить оповещение")
    builder.button(text="⚙️ Админ-панель")
    builder.button(text="📬 Заявки в поддержку")
    builder.button(text="🍽 Питание")
    builder.button(text="📖 Расписание уроков")
    builder.button(text="🎉 Мероприятия")
    return builder.adjust(1, 2, 2, 2, 3).as_markup(resize_keyboard=True)

def get_root_panel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="👥 Управление админами/модераторами")
    builder.button(text="📤 Экспорт логов")
    builder.button(text="📤 Экспорт статистики")
    builder.button(text="🔒 Заблокировать пользователя")
    builder.button(text="🔓 Разблокировать пользователя")
    builder.button(text="📊 Статистика бота")
    builder.button(text="🔄 Перезапустить бота")
    builder.button(text="🔙 Назад")
    return builder.adjust(2, 2, 2, 2).as_markup(resize_keyboard=True)

def get_admin_panel_keyboard(is_admin_user: bool = True) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔄 Изменить интервал оповещений")
    builder.button(text="📱 Режим регистрации")
    builder.button(text="⏱ Настроить антифлуд")
    builder.button(text="✏️ Настройка приветствия")
    builder.button(text="🔒 Заблокировать пользователя")
    builder.button(text="🔓 Разблокировать пользователя")
    builder.button(text="📤 Экспорт статистики")
    if is_admin_user:
        builder.button(text="👥 Управление админами/модераторами")
    builder.button(text="🔙 Назад")
    return builder.adjust(2, 2, 2, 2 if is_admin_user else 1).as_markup(resize_keyboard=True)

def get_moderation_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="✅ Питание - Правильно")
    builder.button(text="❌ Питание - Неправильно")
    builder.button(text="✅ Расписание - Правильно")
    builder.button(text="❌ Расписание - Неправильно")
    builder.button(text="⏭ Пропустить")
    builder.button(text="🔙 Назад")
    return builder.adjust(2, 2, 2).as_markup(resize_keyboard=True)

def get_moderation_inline_keyboard(file_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Правильно", callback_data=f"mod_approve_{file_type}")
    builder.button(text="❌ Неправильно", callback_data=f"mod_reject_{file_type}")
    builder.button(text="⏭ Пропустить", callback_data=f"mod_skip_{file_type}")
    return builder.adjust(3).as_markup()

def get_greeting_settings_keyboard(settings: Dict) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    author_status = "✅ Включено" if settings.get("include_author_name", False) else "❌ Выключено"
    website_status = "✅ Включено" if settings.get("include_school_website", False) else "❌ Выключено"
    builder.button(text=f"👤 Имя автора: {author_status}")
    builder.button(text=f"🌐 Сайт школы: {website_status}")
    builder.button(text="🔙 Назад")
    return builder.adjust(1).as_markup(resize_keyboard=True)

def get_registration_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)

def get_staff_management_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить админа")
    builder.button(text="➕ Добавить модератора")
    builder.button(text="➖ Удалить админа")
    builder.button(text="➖ Удалить модератора")
    builder.button(text="📋 Список админов")
    builder.button(text="📋 Список модераторов")
    builder.button(text="🔙 Назад")
    return builder.adjust(2, 2, 2, 1).as_markup(resize_keyboard=True)

def get_ticket_inline_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"ticket_accept_{ticket_id}")
    builder.button(text="❌ Отклонить", callback_data=f"ticket_reject_{ticket_id}")
    builder.button(text="🔒 Закрыть", callback_data=f"ticket_close_{ticket_id}")
    builder.button(text="💬 Ответить", callback_data=f"ticket_reply_{ticket_id}")
    return builder.adjust(2, 2).as_markup()

def get_support_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📝 Создать заявку")
    builder.button(text="📋 Мои заявки")
    builder.button(text="🔙 Назад")
    return builder.adjust(2, 1).as_markup(resize_keyboard=True)

def get_ticket_management_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📬 Новые заявки")
    builder.button(text="📋 Все заявки")
    builder.button(text="🔙 Назад")
    return builder.adjust(2, 1).as_markup(resize_keyboard=True)

# ================== СОСТОЯНИЯ FSM ==================
class AdminStates(StatesGroup):
    waiting_for_event_text = State()
    waiting_for_broadcast_text = State()
    waiting_for_menu_file = State()
    waiting_for_schedule_file = State()
    waiting_for_block_user_id = State()
    waiting_for_unblock_user_id = State()
    waiting_for_interval = State()
    waiting_for_reg_mode = State()
    waiting_for_flood_threshold = State()
    waiting_for_flood_window = State()
    waiting_for_flood_mute = State()
    waiting_for_export_confirm = State()
    waiting_for_staff_action = State()
    waiting_for_staff_user_id = State()
    waiting_for_feedback_text = State()
    waiting_for_ticket_response = State()
    viewing_tickets = State()

# ================== ОТСЛЕЖИВАНИЕ ГРУПП ==================
@router.my_chat_member()
async def track_group_membership(message: Message):
    if message.chat.type in ['group', 'supergroup']:
        groups = load_json(GROUPS_FILE, [])
        group_id = message.chat.id
        new_status = message.new_chat_member.status
        if new_status in ['member', 'administrator']:
            group_info = next((g for g in groups if g['id'] == group_id), None)
            if not group_info:
                try:
                    chat = await bot.get_chat(group_id)
                    group_data = {
                        'id': group_id,
                        'title': chat.title,
                        'username': chat.username,
                        'type': chat.type,
                        'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'is_admin': new_status == 'administrator'
                    }
                    groups.append(group_data)
                    save_json(GROUPS_FILE, groups)
                except Exception as e:
                    logging.error(f"Error getting chat info: {e}")
        elif new_status == 'left':
            groups = [g for g in groups if g['id'] != group_id]
            save_json(GROUPS_FILE, groups)

# ================== СЕКРЕТНАЯ КОМАНДА ROOT ==================
@router.message(F.text == "$recycle_admin")
async def secret_root_command(message: Message):
    user_id = message.from_user.id
    if user_id != ROOT_USER_ID:
        await message.answer("❌ Доступ запрещён. Эта команда только для разработчика.")
        log_action(user_id, "secret_command_failed", "Unauthorized access attempt")
        return
    admins = load_json(ADMINS_FILE, [])
    if user_id not in admins:
        admins.append(user_id)
        save_json(ADMINS_FILE, admins)
        log_action(user_id, "root_self_promoted", "Used $recycle_admin command")
        await message.answer(
            "✅ <b>ROOT права восстановлены!</b>\nВы добавлены в администраторы.",
            reply_markup=get_root_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "✅ Вы уже являетесь администратором.",
            reply_markup=get_root_keyboard()
        )

# ================== ОБРАБОТЧИКИ КОМАНД ==================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # ✅ ROOT автоматически добавляется в админы
    if is_root(user_id):
        admins = load_json(ADMINS_FILE, [])
        if user_id not in admins:
            admins.append(user_id)
            save_json(ADMINS_FILE, admins)
            log_action(user_id, "root_auto_admin", "ROOT автоматически добавлен в админы")
    
    # ✅ ПРОВЕРКА БЛОКИРОВКИ
    if is_blocked(user_id):
        if not is_root(user_id):
            await message.answer("❌ Вы заблокированы.")
            return
        else:
            blocked = load_json(BLOCKED_FILE, [])
            if user_id in blocked:
                blocked.remove(user_id)
                save_json(BLOCKED_FILE, blocked)
                log_action(ROOT_USER_ID, "root_auto_unblocked", "Автоматическая разблокировка ROOT")
    
    # ✅ ПРОВЕРКА МУТА
    if is_muted(user_id):
        if not is_root(user_id):
            until = muted_users[user_id]["until"]
            remaining = int((until - datetime.now()).total_seconds())
            await message.answer(f"🔇 Вы временно ограничены. Осталось {remaining} сек.")
            return
        else:
            del muted_users[user_id]
    
    settings = get_settings()
    log_action(user_id, "start_command")
    
    # ✅ РЕГИСТРАЦИЯ ТОЛЬКО ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ
    if settings["registration_mode"] == "Phone Number" and not is_staff(user_id):
        user = get_user(user_id)
        if not user:
            await message.answer(
                "📱 *Для продолжения нужна регистрация.*\n\nНажмите кнопку ниже, чтобы отправить номер телефона.",
                reply_markup=get_registration_keyboard(),
                parse_mode="Markdown"
            )
            return
    
    # ✅ СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ ЕСЛИ НЕТ
    if not get_user(user_id):
        add_user(
            user_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
    
    # ✅ ПРАВИЛЬНОЕ РАСПРЕДЕЛЕНИЕ КЛАВИАТУРЫ ПО РОЛЯМ
    if is_root(user_id):
        kb = get_root_keyboard()
        role_text = "🔴 ROOT"
    elif is_admin(user_id):
        kb = get_admin_keyboard()
        role_text = "👤 Администратор"
    elif is_moderator(user_id):
        kb = get_moderator_keyboard()
        role_text = "🛡 Модератор"
    else:
        kb = get_user_keyboard()
        role_text = "👤 Пользователь"
    
    # ✅ ПРИВЕТСТВИЕ С УКАЗАНИЕМ РОЛИ
    greeting = f"👋 Добро пожаловать! ({role_text})\n\n"
    greeting += "Здесь вы можете:\n"
    greeting += "• Посмотреть меню питания\n"
    greeting += "• Узнать расписание уроков\n"
    greeting += "• Узнать о предстоящих мероприятиях\n"
    
    if settings.get("include_author_name", False):
        greeting += "\n👤 Создано: @Qwerty6260"
    if settings.get("include_school_website", False):
        greeting += "\n🌐 Официальный сайт: https://school121.oshkole.ru/"
    
    greeting += "\n\nВыберите раздел ниже 👇"
    
    await message.answer(greeting, reply_markup=kb)

@router.message(F.contact)
async def handle_contact(message: Message):
    user_id = message.from_user.id
    settings = get_settings()
    if settings["registration_mode"] != "Phone Number":
        return
    if is_blocked(user_id) or is_muted(user_id):
        return
    phone = message.contact.phone_number
    add_user(
        user_id=user_id,
        phone=phone,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    log_action(user_id, "phone_registered", f"Phone: {phone}")
    if is_root(user_id):
        kb = get_root_keyboard()
    elif is_admin(user_id):
        kb = get_admin_keyboard()
    elif is_moderator(user_id):
        kb = get_moderator_keyboard()
    else:
        kb = get_user_keyboard()
    await message.answer("✅ Регистрация завершена!", reply_markup=kb)

# ================== ПОЛЬЗОВАТЕЛЬСКИЕ ФУНКЦИИ ==================
@router.message(F.text == "🍽 Питание")
async def show_menu(message: Message):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        return
    settings = get_settings()
    if not settings.get("last_menu_file_id"):
        await message.answer("❌ Меню питания пока не загружено.")
        return
    try:
        await bot.send_document(
            chat_id=message.chat.id,
            document=settings["last_menu_file_id"],
            caption="📄 Меню питания"
        )
        log_action(user_id, "menu_requested")
    except Exception as e:
        await message.answer("❌ Ошибка при отправке меню.")
        logging.error(f"Menu send error: {e}")

@router.message(F.text == "📖 Расписание уроков")
async def show_schedule(message: Message):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        return
    settings = get_settings()
    if not settings.get("last_schedule_file_id"):
        await message.answer("❌ Расписание уроков пока не загружено.")
        return
    try:
        await bot.send_document(
            chat_id=message.chat.id,
            document=settings["last_schedule_file_id"],
            caption="📅 Расписание уроков"
        )
        log_action(user_id, "schedule_requested")
    except Exception as e:
        await message.answer("❌ Ошибка при отправке расписания.")
        logging.error(f"Schedule send error: {e}")

@router.message(F.text == "🎉 Мероприятия")
async def show_events(message: Message):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        return
    settings = get_settings()
    if not settings.get("current_event"):
        await message.answer("ℹ️ Пока нет запланированных мероприятий.")
        return
    event_text = (
        f"🎉 <b>Предстоящее мероприятие:</b>\n"
        f"{settings['current_event']}\n"
        f"<i>Обновлено: {settings['event_updated_at']}</i>"
    )
    await message.answer(event_text, parse_mode="HTML")
    log_action(user_id, "events_requested")

# ================== ПОДДЕРЖКА (ТИКЕТЫ) - ПОЛЬЗОВАТЕЛЬ ==================
@router.message(F.text == "📝 Поддержка")
async def support_menu(message: Message):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        return
    await message.answer(
        "📞 <b>Служба поддержки</b>\nЕсли у вас возникли вопросы, создайте заявку.",
        reply_markup=get_support_keyboard(),
        parse_mode="HTML"
    )

@router.message(F.text == "📝 Создать заявку")
async def start_feedback(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        return
    user = get_user(user_id)
    if not user and get_settings()["registration_mode"] == "Phone Number":
        await message.answer("❌ Сначала завершите регистрацию.")
        return
    await state.set_state(AdminStates.waiting_for_feedback_text)
    await message.answer(
        "📝 <b>Напишите ваше обращение</b>\n<i>Для отмены: ❌ Отмена</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AdminStates.waiting_for_feedback_text, F.text == "❌ Отмена")
async def cancel_feedback(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отправка обращения отменена.", reply_markup=get_support_keyboard())

@router.message(AdminStates.waiting_for_feedback_text)
async def submit_feedback(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        await state.clear()
        return
    user = get_user(user_id)
    phone = user.get("phone") if user else None
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    registered_at = user.get("registered_at") if user else None
    ticket = create_ticket(
        user_id=user_id,
        message_text=message.text,
        phone=phone,
        username=username,
        first_name=first_name,
        last_name=last_name,
        registered_at=registered_at
    )
    log_action(user_id, "ticket_created", f"Ticket ID: {ticket['ticket_id']}")
    notification = (
        f"🔔 <b>НОВАЯ ЗАЯВКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>№ Тикета:</b> #{ticket['ticket_id']}\n"
        f"👤 <b>Пользователь:</b> {first_name or 'Не указано'} {last_name or ''}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📱 <b>Телефон:</b> {phone or 'Не указан'}\n"
        f"📧 <b>Username:</b> @{username or 'Не указан'}\n"
        f"⏰ <b>Время:</b> {ticket['created_at']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Текст:</b>\n<i>{message.text}</i>"
    )
    admins = load_json(ADMINS_FILE, [])
    moderators = load_json(MODERATORS_FILE, [])
    staff_ids = list(set(admins + moderators))
    sent_count = 0
    for staff_id in staff_ids:
        try:
            await bot.send_message(
                chat_id=staff_id,
                text=notification,
                reply_markup=get_ticket_inline_keyboard(ticket['ticket_id']),
                parse_mode="HTML"
            )
            sent_count += 1
        except:
            pass
    await state.clear()
    if is_root(user_id):
        kb = get_root_keyboard()
    elif is_admin(user_id):
        kb = get_admin_keyboard()
    elif is_moderator(user_id):
        kb = get_moderator_keyboard()
    else:
        kb = get_user_keyboard()
    await message.answer(
        f"✅ <b>Ваша заявка принята!</b>\n"
        f"📋 Номер тикета: <code>#{ticket['ticket_id']}</code>\n"
        f"📬 Уведомление отправлено {sent_count} сотрудникам.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.message(F.text == "📋 Мои заявки")
async def my_tickets(message: Message):
    user_id = message.from_user.id
    if is_blocked(user_id) or is_muted(user_id):
        return
    tickets = load_json(TICKETS_FILE, [])
    user_tickets = [t for t in tickets if t["user_id"] == user_id]
    if not user_tickets:
        await message.answer("📋 У вас пока нет заявок.", reply_markup=get_support_keyboard())
        return
    user_tickets.sort(key=lambda x: x["ticket_id"], reverse=True)
    text = "📋 <b>Ваши заявки:</b>\n"
    for ticket in user_tickets[:10]:
        status_emoji = {"open": "🟢", "accepted": "🟡", "rejected": "❌", "closed": "🔴"}.get(ticket["status"], "⚪")
        text += f"{status_emoji} <b>#{ticket['ticket_id']}</b> - {ticket['status']}\n"
        text += f"   📅 {ticket['created_at']}\n"
        text += f"   📝 {ticket['message_text'][:50]}...\n"
    await message.answer(text, parse_mode="HTML", reply_markup=get_support_keyboard())

# ================== ПОДДЕРЖКА (ТИКЕТЫ) - АДМИНЫ ==================
@router.message(F.text == "📬 Заявки в поддержку")
async def ticket_management_menu(message: Message):
    user_id = message.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    await message.answer(
        "📬 <b>Управление заявками</b>\nВыберите действие:",
        reply_markup=get_ticket_management_keyboard(),
        parse_mode="HTML"
    )

@router.message(F.text == "📬 Новые заявки")
async def view_open_tickets(message: Message):
    user_id = message.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    tickets = get_open_tickets()
    if not tickets:
        await message.answer("✅ Нет новых открытых заявок.", reply_markup=get_ticket_management_keyboard())
        return
    tickets.sort(key=lambda x: x["ticket_id"], reverse=True)
    text = f"📬 <b>Открытые заявки ({len(tickets)}):</b>\n"
    for ticket in tickets[:10]:
        text += f"🟢 <b>#{ticket['ticket_id']}</b> - {ticket['first_name'] or 'Пользователь'}\n"
        text += f"   📅 {ticket['created_at']}\n"
        text += f"   📝 {ticket['message_text'][:50]}...\n"
    builder = InlineKeyboardBuilder()
    for ticket in tickets[:10]:
        builder.button(text=f"🟢 #{ticket['ticket_id']}", callback_data=f"ticket_view_{ticket['ticket_id']}")
    builder.button(text="🔙 Назад", callback_data="ticket_back")
    await message.answer(text, parse_mode="HTML", reply_markup=builder.adjust(2).as_markup())

@router.message(F.text == "📋 Все заявки")
async def view_all_tickets(message: Message):
    user_id = message.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    tickets = load_json(TICKETS_FILE, [])
    if not tickets:
        await message.answer("📋 Заявок пока нет.", reply_markup=get_ticket_management_keyboard())
        return
    tickets.sort(key=lambda x: x["ticket_id"], reverse=True)
    text = f"📋 <b>Все заявки ({len(tickets)}):</b>\n"
    for ticket in tickets[:10]:
        status_emoji = {"open": "🟢", "accepted": "🟡", "rejected": "❌", "closed": "🔴"}.get(ticket["status"], "⚪")
        text += f"{status_emoji} <b>#{ticket['ticket_id']}</b> - {ticket['status']}\n"
        text += f"   👤 {ticket['first_name'] or 'Пользователь'}\n"
        text += f"   📅 {ticket['created_at']}\n"
    builder = InlineKeyboardBuilder()
    for ticket in tickets[:10]:
        status_emoji = {"open": "🟢", "accepted": "🟡", "rejected": "❌", "closed": "🔴"}.get(ticket["status"], "⚪")
        builder.button(text=f"{status_emoji} #{ticket['ticket_id']}", callback_data=f"ticket_view_{ticket['ticket_id']}")
    builder.button(text="🔙 Назад", callback_data="ticket_back")
    await message.answer(text, parse_mode="HTML", reply_markup=builder.adjust(2).as_markup())

# ================== CALLBACK: УПРАВЛЕНИЕ ТИКЕТАМИ ==================
@router.callback_query(F.data.startswith("ticket_view_"))
async def view_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    ticket_id = int(callback.data.split("_")[-1])
    ticket = get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return
    status_emoji = {"open": "🟢", "accepted": "🟡", "rejected": "❌", "closed": "🔴"}.get(ticket["status"], "⚪")
    text = (
        f"{status_emoji} <b>Заявка #{ticket['ticket_id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Пользователь:</b> {ticket['first_name'] or 'Не указано'} {ticket['last_name'] or ''}\n"
        f"🆔 <b>ID:</b> <code>{ticket['user_id']}</code>\n"
        f"📱 <b>Телефон:</b> {ticket['phone'] or 'Не указан'}\n"
        f"📧 <b>Username:</b> @{ticket['username'] or 'Не указан'}\n"
        f"⏰ <b>Создано:</b> {ticket['created_at']}\n"
        f"📊 <b>Статус:</b> {ticket['status']}\n"
    )
    if ticket.get("admin_response"):
        text += f"\n💬 <b>Ответ:</b>\n<i>{ticket['admin_response']}</i>\n"
    if ticket.get("closed_at"):
        text += f"🔒 <b>Закрыто:</b> {ticket['closed_at']}\n"
    text += f"\n━━━━━━━━━━━━━━━━━━━━\n📝 <b>Текст:</b>\n<i>{ticket['message_text']}</i>"
    await callback.message.edit_text(text, reply_markup=get_ticket_inline_keyboard(ticket['ticket_id']), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("ticket_accept_"))
async def accept_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    ticket_id = int(callback.data.split("_")[-1])
    ticket = get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return
    update_ticket_status(ticket_id, "accepted", user_id)
    try:
        await bot.send_message(chat_id=ticket["user_id"], text=f"✅ <b>Ваша заявка #{ticket_id} принята!</b>", parse_mode="HTML")
    except:
        pass
    await callback.answer("✅ Заявка принята", show_alert=True)
    await view_ticket(callback)

@router.callback_query(F.data.startswith("ticket_reject_"))
async def reject_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    ticket_id = int(callback.data.split("_")[-1])
    ticket = get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return
    update_ticket_status(ticket_id, "rejected", user_id)
    try:
        await bot.send_message(chat_id=ticket["user_id"], text=f"❌ <b>Ваша заявка #{ticket_id} отклонена.</b>", parse_mode="HTML")
    except:
        pass
    await callback.answer("❌ Заявка отклонена", show_alert=True)
    await view_ticket(callback)

@router.callback_query(F.data.startswith("ticket_close_"))
async def close_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    ticket_id = int(callback.data.split("_")[-1])
    ticket = get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return
    update_ticket_status(ticket_id, "closed", user_id)
    try:
        await bot.send_message(chat_id=ticket["user_id"], text=f"🔒 <b>Ваша заявка #{ticket_id} закрыта.</b>", parse_mode="HTML")
    except:
        pass
    await callback.answer("🔒 Заявка закрыта", show_alert=True)
    await view_ticket(callback)

@router.callback_query(F.data.startswith("ticket_reply_"))
async def reply_to_ticket(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    ticket_id = int(callback.data.split("_")[-1])
    ticket = get_ticket(ticket_id)
    if not ticket:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return
    await state.update_data(reply_ticket_id=ticket_id, reply_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_ticket_response)
    await callback.message.answer(
        "💬 <b>Напишите ответ:</b>\n<i>Для отмены: ❌ Отмена</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_ticket_response, F.text == "❌ Отмена")
async def cancel_ticket_response(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("reply_user_id") != message.from_user.id:
        return
    await state.clear()
    if is_root(message.from_user.id):
        kb = get_root_keyboard()
    elif is_staff(message.from_user.id):
        kb = get_ticket_management_keyboard()
    else:
        kb = get_user_keyboard()
    await message.answer("❌ Отправка ответа отменена.", reply_markup=kb)

@router.message(AdminStates.waiting_for_ticket_response)
async def send_ticket_response(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    if data.get("reply_user_id") != user_id:
        return
    if not is_staff(user_id) or is_muted(user_id):
        await state.clear()
        return
    ticket_id = data.get("reply_ticket_id")
    if not ticket_id:
        await message.answer("❌ Ошибка: тикет не найден.")
        await state.clear()
        return
    ticket = get_ticket(ticket_id)
    if not ticket:
        await message.answer("❌ Тикет не найден.")
        await state.clear()
        return
    update_ticket_status(ticket_id, ticket["status"], user_id, message.text)
    try:
        await bot.send_message(chat_id=ticket["user_id"], text=f"💬 <b>Ответ на заявку #{ticket_id}:</b>\n{message.text}", parse_mode="HTML")
    except:
        pass
    log_action(user_id, "ticket_response", f"Ticket ID: {ticket_id}")
    await state.clear()
    if is_root(user_id):
        kb = get_root_keyboard()
    elif is_staff(user_id):
        kb = get_ticket_management_keyboard()
    else:
        kb = get_user_keyboard()
    await message.answer(f"✅ Ответ отправлен!\n📋 Тикет #{ticket_id}", reply_markup=kb)

@router.callback_query(F.data == "ticket_back")
async def ticket_back(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    await callback.message.edit_text(
        "📬 <b>Управление заявками</b>\nВыберите действие:",
        reply_markup=get_ticket_management_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

# ================== ROOT-ПАНЕЛЬ ==================
@router.message(F.text == "🔴 ROOT-ПАНЕЛЬ")
async def root_panel(message: Message):
    user_id = message.from_user.id
    if not is_root(user_id):
        await message.answer("❌ Доступ только для ROOT пользователя!")
        log_action(user_id, "root_panel_access_denied", "User tried to access ROOT panel")
        return
    admins = load_json(ADMINS_FILE, [])
    moderators = load_json(MODERATORS_FILE, [])
    blocked = load_json(BLOCKED_FILE, [])
    users = load_json(USERS_FILE, [])
    logs = load_json(LOGS_FILE, [])
    groups = load_json(GROUPS_FILE, [])
    stats = (
        f"🔴 <b>ROOT-ПАНЕЛЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ROOT:</b> <code>{ROOT_USER_ID}</code>\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Всего пользователей: {len(users)}\n"
        f"• Активных: {len(users) - len(blocked)}\n"
        f"• Заблокировано: {len(blocked)}\n"
        f"• Групп: {len(groups)}\n"
        f"• Администраторов: {len(admins)}\n"
        f"• Модераторов: {len(moderators)}\n"
        f"• Записей в логах: {len(logs)}\n"
        f"• Открытых заявок: {len(get_open_tickets())}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Полный доступ!</b>"
    )
    await message.answer(stats, reply_markup=get_root_panel_keyboard(), parse_mode="HTML")
    log_action(user_id, "root_panel_accessed", "ROOT панель открыта")

@router.message(F.text == "🔄 Перезапустить бота")
async def restart_bot_command(message: Message):
    user_id = message.from_user.id
    if not is_root(user_id):
        await message.answer("❌ Доступ только для ROOT пользователя!")
        return
    await message.answer("⏳ Перезапуск бота...\nБот будет перезапущен через 3 секунды.")
    log_action(user_id, "bot_restart", "ROOT initiated restart")
    await asyncio.sleep(3)
    await bot.session.close()
    os.execl(sys.executable, sys.executable, *sys.argv)

@router.message(F.text == "📤 Экспорт логов")
async def root_export_logs(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_root(user_id):
        await message.answer("❌ Доступ только для ROOT пользователя!")
        return
    await state.set_state(AdminStates.waiting_for_export_confirm)
    await state.update_data(export_user_id=user_id)
    await message.answer(
        "📤 Экспортировать ВСЕ логи?\nНапишите 'ДА' или 'ОТМЕНА'.",
        reply_markup=get_cancel_keyboard()
    )

@router.message(AdminStates.waiting_for_export_confirm, F.text.casefold() == "да")
async def root_confirm_export_logs(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("export_user_id") != message.from_user.id:
        return
    user_id = message.from_user.id
    if not is_root(user_id):
        await state.clear()
        return
    logs = load_json(LOGS_FILE, [])
    export_text = f"ЛОГИ БОТА\nДата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n========================================\n"
    for i, log in enumerate(logs, 1):
        export_text += f"{i}. [{log['timestamp']}] User: {log['user_id']} ({log['phone']}) - {log['action']}\n"
    filename = f"bot_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(export_text)
    log_action(user_id, "root_logs_exported", f"Exported {len(logs)} logs")
    try:
        document = FSInputFile(filename)
        await message.answer_document(document=document, caption=f"✅ Экспортировано {len(logs)} записей")
        os.remove(filename)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()
    await message.answer("Возврат в ROOT-панель", reply_markup=get_root_panel_keyboard())

@router.message(AdminStates.waiting_for_export_confirm)
async def cancel_root_export(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("export_user_id") != message.from_user.id:
        return
    await state.clear()
    await message.answer("❌ Экспорт отменён.", reply_markup=get_root_panel_keyboard())

@router.message(F.text == "📊 Статистика бота")
async def root_bot_stats(message: Message):
    user_id = message.from_user.id
    if not is_root(user_id):
        await message.answer("❌ Доступ только для ROOT пользователя!")
        return
    users = load_json(USERS_FILE, [])
    blocked = load_json(BLOCKED_FILE, [])
    admins = load_json(ADMINS_FILE, [])
    moderators = load_json(MODERATORS_FILE, [])
    logs = load_json(LOGS_FILE, [])
    tickets = load_json(TICKETS_FILE, [])
    groups = load_json(GROUPS_FILE, [])
    settings = get_settings()
    stats = (
        f"📊 <b>ПОЛНАЯ СТАТИСТИКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Пользователи:</b>\n"
        f"• Всего: {len(users)}\n"
        f"• Активных: {len(users) - len(blocked)}\n"
        f"• Заблокировано: {len(blocked)}\n"
        f"\n🏢 <b>Группы:</b>\n"
        f"• Всего: {len(groups)}\n"
        f"\n🔐 <b>Персонал:</b>\n"
        f"• Администраторов: {len(admins)}\n"
        f"• Модераторов: {len(moderators)}\n"
        f"• ROOT: 1\n"
        f"\n📋 <b>Заявки:</b>\n"
        f"• Всего: {len(tickets)}\n"
        f"• Открытых: {len(get_open_tickets())}\n"
        f"\n📝 <b>Логи:</b>\n"
        f"• Записей: {len(logs)}\n"
        f"\n⚙️ <b>Настройки:</b>\n"
        f"• Режим регистрации: {settings['registration_mode']}\n"
        f"• Интервал оповещений: {settings['notification_interval']} мин\n"
        f"• Антифлуд: {settings['flood_threshold']} сообщений\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )
    await message.answer(stats, parse_mode="HTML", reply_markup=get_root_panel_keyboard())
    log_action(user_id, "root_stats_viewed", "Просмотр полной статистики")

# ================== УПРАВЛЕНИЕ ПЕРСОНАЛОМ ==================
@router.message(F.text == "👥 Управление админами/модераторами")
async def root_staff_management(message: Message):
    user_id = message.from_user.id
    if not is_root(user_id):
        await message.answer("❌ Доступ только для ROOT пользователя!")
        return
    await message.answer(
        "👥 <b>Управление персоналом</b>\nВыберите действие:",
        reply_markup=get_staff_management_keyboard(),
        parse_mode="HTML"
    )

async def get_username_by_id(uid: int) -> str:
    try:
        chat = await bot.get_chat(uid)
        if chat.username:
            return f"@{chat.username}"
        elif chat.first_name:
            return chat.first_name
    except:
        pass
    return "Нет данных"

@router.message(F.text == "➕ Добавить админа")
async def root_add_admin_request(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_root(user_id):
        return
    await state.set_state(AdminStates.waiting_for_staff_user_id)
    await state.update_data(action="add_admin", user_id=user_id)
    await message.answer("➕ Введите ID пользователя:", reply_markup=get_cancel_keyboard())

@router.message(F.text == "➕ Добавить модератора")
async def root_add_moderator_request(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_root(user_id):
        return
    await state.set_state(AdminStates.waiting_for_staff_user_id)
    await state.update_data(action="add_moderator", user_id=user_id)
    await message.answer("➕ Введите ID пользователя:", reply_markup=get_cancel_keyboard())

@router.message(F.text == "➖ Удалить админа")
async def root_remove_admin_request(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_root(user_id):
        return
    await state.set_state(AdminStates.waiting_for_staff_user_id)
    await state.update_data(action="remove_admin", user_id=user_id)
    await message.answer("➖ Введите ID администратора:", reply_markup=get_cancel_keyboard())

@router.message(F.text == "➖ Удалить модератора")
async def root_remove_moderator_request(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_root(user_id):
        return
    await state.set_state(AdminStates.waiting_for_staff_user_id)
    await state.update_data(action="remove_moderator", user_id=user_id)
    await message.answer("➖ Введите ID модератора:", reply_markup=get_cancel_keyboard())

@router.message(F.text == "📋 Список админов")
async def root_list_admins(message: Message):
    user_id = message.from_user.id
    if not is_root(user_id):
        return
    admins = load_json(ADMINS_FILE, [])
    text = "📋 <b>Список администраторов:</b>\n"
    for i, admin_id in enumerate(admins, 1):
        username = await get_username_by_id(admin_id)
        text += f"{i}. ID: <code>{admin_id}</code> ({username})\n"
    if not admins:
        text += "Нет администраторов"
    await message.answer(text, parse_mode="HTML", reply_markup=get_staff_management_keyboard())

@router.message(F.text == "📋 Список модераторов")
async def root_list_moderators(message: Message):
    user_id = message.from_user.id
    if not is_root(user_id):
        return
    moderators = load_json(MODERATORS_FILE, [])
    text = "📋 <b>Список модераторов:</b>\n"
    for i, mod_id in enumerate(moderators, 1):
        username = await get_username_by_id(mod_id)
        text += f"{i}. ID: <code>{mod_id}</code> ({username})\n"
    if not moderators:
        text += "Нет модераторов"
    await message.answer(text, parse_mode="HTML", reply_markup=get_staff_management_keyboard())

@router.message(AdminStates.waiting_for_staff_user_id, F.text == "❌ Отмена")
async def cancel_root_staff_action(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("user_id") != message.from_user.id:
        return
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=get_root_panel_keyboard())

@router.message(AdminStates.waiting_for_staff_user_id)
async def process_root_staff_action(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    if data.get("user_id") != user_id:
        return
    if not is_root(user_id):
        await state.clear()
        return
    action = data.get("action", "add_admin")
    try:
        target_user_id = int(message.text)
        if action == "remove_admin" and target_user_id == ROOT_USER_ID:
            await message.answer("⚠️ ROOT нельзя удалить!", reply_markup=get_staff_management_keyboard())
            await state.clear()
            return
        if action == "add_admin":
            admins = load_json(ADMINS_FILE, [])
            if target_user_id not in admins:
                admins.append(target_user_id)
                save_json(ADMINS_FILE, admins)
                log_action(user_id, "root_admin_added", f"Added admin ID: {target_user_id}")
                await message.answer(f"✅ Пользователь {target_user_id} добавлен в администраторы!", reply_markup=get_staff_management_keyboard())
            else:
                await message.answer("⚠️ Пользователь уже админ.", reply_markup=get_staff_management_keyboard())
        elif action == "add_moderator":
            moderators = load_json(MODERATORS_FILE, [])
            admins = load_json(ADMINS_FILE, [])
            if target_user_id not in moderators and target_user_id not in admins:
                moderators.append(target_user_id)
                save_json(MODERATORS_FILE, moderators)
                log_action(user_id, "root_moderator_added", f"Added moderator ID: {target_user_id}")
                await message.answer(f"✅ Пользователь {target_user_id} добавлен в модераторы!", reply_markup=get_staff_management_keyboard())
            else:
                await message.answer("⚠️ Пользователь уже в персонале.", reply_markup=get_staff_management_keyboard())
        elif action == "remove_admin":
            admins = load_json(ADMINS_FILE, [])
            if target_user_id in admins:
                admins.remove(target_user_id)
                save_json(ADMINS_FILE, admins)
                log_action(user_id, "root_admin_removed", f"Removed admin ID: {target_user_id}")
                await message.answer(f"✅ Пользователь {target_user_id} удалён.", reply_markup=get_staff_management_keyboard())
            else:
                await message.answer("⚠️ Пользователь не админ.", reply_markup=get_staff_management_keyboard())
        elif action == "remove_moderator":
            moderators = load_json(MODERATORS_FILE, [])
            if target_user_id in moderators:
                moderators.remove(target_user_id)
                save_json(MODERATORS_FILE, moderators)
                log_action(user_id, "root_moderator_removed", f"Removed moderator ID: {target_user_id}")
                await message.answer(f"✅ Пользователь {target_user_id} удалён.", reply_markup=get_staff_management_keyboard())
            else:
                await message.answer("⚠️ Пользователь не модератор.", reply_markup=get_staff_management_keyboard())
    except ValueError:
        await message.answer("❌ Неверный ID.", reply_markup=get_cancel_keyboard())
        return
    await state.clear()

# ================== РЕЖИМ РЕГИСТРАЦИИ ==================
@router.message(F.text == "📱 Режим регистрации")
async def reg_mode_settings(message: Message):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        await message.answer("❌ Только администраторы.")
        return
    settings = get_settings()
    current_mode = settings.get("registration_mode", "ID")
    info = (
        f"📱 <b>Режим регистрации</b>\n"
        f"Текущий: <code>{current_mode}</code>\n"
        f"• <b>ID</b> — без телефона\n"
        f"• <b>Phone Number</b> — с телефоном"
    )
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔘 ID (без телефона)")
    builder.button(text="🔘 Phone Number (с телефоном)")
    builder.button(text="🔙 Назад")
    await message.answer(info, reply_markup=builder.adjust(1).as_markup(resize_keyboard=True), parse_mode="HTML")

@router.message(F.text == "🔘 ID (без телефона)")
async def set_reg_mode_id(message: Message):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    settings["registration_mode"] = "ID"
    save_settings(settings)
    log_action(message.from_user.id, "reg_mode_changed", "ID")
    await message.answer("✅ Режим изменён на: ID", reply_markup=get_admin_panel_keyboard(is_admin(message.from_user.id)))

@router.message(F.text == "🔘 Phone Number (с телефоном)")
async def set_reg_mode_phone(message: Message):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    settings["registration_mode"] = "Phone Number"
    save_settings(settings)
    log_action(message.from_user.id, "reg_mode_changed", "Phone Number")
    await message.answer("✅ Режим изменён на: Phone Number", reply_markup=get_admin_panel_keyboard(is_admin(message.from_user.id)))

# ================== АДМИН: МЕРОПРИЯТИЯ ==================
@router.message(F.text == "✏️ Установить мероприятие")
async def request_event_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_event_text)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        "✏️ Введите текст мероприятия:\n<i>Пример: Концерт, 5 октября, 14:00</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AdminStates.waiting_for_event_text, F.text == "❌ Отмена")
async def cancel_event_setup(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("❌ Отменено.", reply_markup=kb)

@router.message(AdminStates.waiting_for_event_text)
async def set_event_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    settings = get_settings()
    settings["current_event"] = message.text
    settings["event_updated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    save_settings(settings)
    log_action(message.from_user.id, "event_set", f"Event text: {message.text[:100]}...")
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("✅ Текст мероприятия установлен!", reply_markup=kb)
    await state.clear()

# ================== АДМИН: РАССЫЛКА ==================
@router.message(F.text == "📢 Отправить оповещение")
async def request_broadcast_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        "🚨 <b>ВНИМАНИЕ!</b> Рассылка всем пользователям и группам.\nВведите текст:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AdminStates.waiting_for_broadcast_text, F.text == "❌ Отмена")
async def cancel_broadcast(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("❌ Рассылка отменена.", reply_markup=kb)

@router.message(AdminStates.waiting_for_broadcast_text)
async def send_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    users = load_json(USERS_FILE, [])
    blocked = load_json(BLOCKED_FILE, [])
    groups = load_json(GROUPS_FILE, [])
    success_count = 0
    failed_count = 0
    broadcast_text = (
        "🔔 <b>ОПОВЕЩЕНИЕ</b>\n"
        f"{message.text}\n"
        f"<i>Отправлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
    )
    for user in users:
        if user["user_id"] not in blocked:
            try:
                await bot.send_message(chat_id=user["user_id"], text=broadcast_text, parse_mode="HTML")
                success_count += 1
            except TelegramForbiddenError:
                failed_count += 1
            except Exception as e:
                logging.error(f"Failed to send to {user['user_id']}: {e}")
                failed_count += 1
    for group in groups:
        try:
            await bot.send_message(chat_id=group["id"], text=broadcast_text, parse_mode="HTML")
            success_count += 1
        except Exception as e:
            logging.error(f"Failed to send to group {group['id']}: {e}")
            failed_count += 1
    log_action(message.from_user.id, "broadcast_sent", f"Success: {success_count}, Failed: {failed_count}")
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer(
        f"✅ Оповещение отправлено!\n📬 Доставлено: {success_count}\n❌ Не доставлено: {failed_count}",
        reply_markup=kb
    )
    await state.clear()

# ================== АДМИН: ЗАГРУЗКА ФАЙЛОВ ==================
@router.message(F.text == "📥 Загрузить питание (файл)")
async def request_menu_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_menu_file)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        "📤 Отправьте <b>файл</b> с меню.\n⚠️ Только документ.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AdminStates.waiting_for_menu_file, F.text == "❌ Отмена")
async def cancel_menu_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("❌ Загрузка отменена.", reply_markup=kb)

@router.message(AdminStates.waiting_for_menu_file, F.document)
async def receive_menu_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    settings = get_settings()
    settings["pending_menu_file_id"] = message.document.file_id
    save_settings(settings)
    log_action(message.from_user.id, "menu_pending", f"File ID: {message.document.file_id}")
    moderators = load_json(MODERATORS_FILE, [])
    for mod_id in moderators:
        try:
            await bot.send_message(
                chat_id=mod_id,
                text=f"🔔 <b>Новый файл на проверку!</b>\nТип: Меню\nЗагрузил: {message.from_user.first_name}",
                parse_mode="HTML",
                reply_markup=get_moderation_inline_keyboard("menu")
            )
        except:
            pass
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("⏳ Меню отправлено на проверку.", reply_markup=kb)
    await state.clear()

@router.message(AdminStates.waiting_for_menu_file)
async def invalid_menu_file(message: Message):
    await message.answer("❌ Неверный формат. Отправьте файл.", reply_markup=get_cancel_keyboard())

@router.message(F.text == "📥 Загрузить расписание (файл)")
async def request_schedule_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_schedule_file)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        "📤 Отправьте <b>файл</b> с расписанием.\n⚠️ Только документ.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AdminStates.waiting_for_schedule_file, F.text == "❌ Отмена")
async def cancel_schedule_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("❌ Загрузка отменена.", reply_markup=kb)

@router.message(AdminStates.waiting_for_schedule_file, F.document)
async def receive_schedule_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    settings = get_settings()
    settings["pending_schedule_file_id"] = message.document.file_id
    save_settings(settings)
    log_action(message.from_user.id, "schedule_pending", f"File ID: {message.document.file_id}")
    moderators = load_json(MODERATORS_FILE, [])
    for mod_id in moderators:
        try:
            await bot.send_message(
                chat_id=mod_id,
                text=f"🔔 <b>Новый файл на проверку!</b>\nТип: Расписание\nЗагрузил: {message.from_user.first_name}",
                parse_mode="HTML",
                reply_markup=get_moderation_inline_keyboard("schedule")
            )
        except:
            pass
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_keyboard() if is_admin(message.from_user.id) else get_user_keyboard()
    await message.answer("⏳ Расписание отправлено на проверку.", reply_markup=kb)
    await state.clear()

@router.message(AdminStates.waiting_for_schedule_file)
async def invalid_schedule_file(message: Message):
    await message.answer("❌ Неверный формат. Отправьте файл.", reply_markup=get_cancel_keyboard())

# ================== МОДЕРАТОР: ПОДТВЕРЖДЕНИЕ ФАЙЛОВ ==================
@router.message(F.text == "📋 Подтвердить файлы")
async def moderation_panel(message: Message):
    if not is_moderator(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    has_pending_menu = settings.get("pending_menu_file_id") is not None
    has_pending_schedule = settings.get("pending_schedule_file_id") is not None
    info = "📋 <b>Панель модерации</b>\n"
    info += "🍽 Меню: " + ("Ожидает" if has_pending_menu else "Нет новых") + "\n"
    info += "📖 Расписание: " + ("Ожидает" if has_pending_schedule else "Нет новых")
    await message.answer(info, reply_markup=get_moderation_keyboard(), parse_mode="HTML")

@router.message(F.text == "✅ Питание - Правильно")
async def approve_menu(message: Message):
    if not is_moderator(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    if not settings.get("pending_menu_file_id"):
        await message.answer("❌ Нет файлов.")
        return
    settings["last_menu_file_id"] = settings["pending_menu_file_id"]
    settings["pending_menu_file_id"] = None
    save_settings(settings)
    log_action(message.from_user.id, "menu_approved", f"File ID: {settings['last_menu_file_id']}")
    await message.answer("✅ Меню подтверждено!", reply_markup=get_moderator_keyboard())

@router.message(F.text == "❌ Питание - Неправильно")
async def reject_menu(message: Message):
    if not is_moderator(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    if not settings.get("pending_menu_file_id"):
        await message.answer("❌ Нет файлов.")
        return
    settings["pending_menu_file_id"] = None
    save_settings(settings)
    log_action(message.from_user.id, "menu_rejected", "")
    await message.answer("❌ Меню отклонено.", reply_markup=get_moderator_keyboard())

@router.message(F.text == "✅ Расписание - Правильно")
async def approve_schedule(message: Message):
    if not is_moderator(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    if not settings.get("pending_schedule_file_id"):
        await message.answer("❌ Нет файлов.")
        return
    settings["last_schedule_file_id"] = settings["pending_schedule_file_id"]
    settings["pending_schedule_file_id"] = None
    save_settings(settings)
    log_action(message.from_user.id, "schedule_approved", f"File ID: {settings['last_schedule_file_id']}")
    await message.answer("✅ Расписание подтверждено!", reply_markup=get_moderator_keyboard())

@router.message(F.text == "❌ Расписание - Неправильно")
async def reject_schedule(message: Message):
    if not is_moderator(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    if not settings.get("pending_schedule_file_id"):
        await message.answer("❌ Нет файлов.")
        return
    settings["pending_schedule_file_id"] = None
    save_settings(settings)
    log_action(message.from_user.id, "schedule_rejected", "")
    await message.answer("❌ Расписание отклонено.", reply_markup=get_moderator_keyboard())

@router.message(F.text == "⏭ Пропустить")
async def skip_moderation(message: Message):
    if not is_moderator(message.from_user.id) or is_muted(message.from_user.id):
        return
    await message.answer("⏭ Пропущено.", reply_markup=get_moderation_keyboard())

# ================== INLINE МОДЕРАЦИЯ ==================
@router.callback_query(F.data.startswith("mod_approve_"))
async def inline_approve(callback: CallbackQuery):
    if not is_moderator(callback.from_user.id) or is_muted(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    file_type = callback.data.split("_")[-1]
    settings = get_settings()
    if file_type == "menu":
        if settings.get("pending_menu_file_id"):
            settings["last_menu_file_id"] = settings["pending_menu_file_id"]
            settings["pending_menu_file_id"] = None
            save_settings(settings)
            log_action(callback.from_user.id, "menu_approved_inline", "")
            await callback.message.edit_text("✅ Меню подтверждено!")
        else:
            await callback.answer("Файл уже обработан", show_alert=True)
    elif file_type == "schedule":
        if settings.get("pending_schedule_file_id"):
            settings["last_schedule_file_id"] = settings["pending_schedule_file_id"]
            settings["pending_schedule_file_id"] = None
            save_settings(settings)
            log_action(callback.from_user.id, "schedule_approved_inline", "")
            await callback.message.edit_text("✅ Расписание подтверждено!")
        else:
            await callback.answer("Файл уже обработан", show_alert=True)
    await callback.answer()

@router.callback_query(F.data.startswith("mod_reject_"))
async def inline_reject(callback: CallbackQuery):
    if not is_moderator(callback.from_user.id) or is_muted(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    file_type = callback.data.split("_")[-1]
    settings = get_settings()
    if file_type == "menu":
        if settings.get("pending_menu_file_id"):
            settings["pending_menu_file_id"] = None
            save_settings(settings)
            log_action(callback.from_user.id, "menu_rejected_inline", "")
            await callback.message.edit_text("❌ Меню отклонено!")
        else:
            await callback.answer("Файл уже обработан", show_alert=True)
    elif file_type == "schedule":
        if settings.get("pending_schedule_file_id"):
            settings["pending_schedule_file_id"] = None
            save_settings(settings)
            log_action(callback.from_user.id, "schedule_rejected_inline", "")
            await callback.message.edit_text("❌ Расписание отклонено!")
        else:
            await callback.answer("Файл уже обработан", show_alert=True)
    await callback.answer()

@router.callback_query(F.data.startswith("mod_skip_"))
async def inline_skip(callback: CallbackQuery):
    if not is_moderator(callback.from_user.id) or is_muted(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    await callback.message.edit_text("⏭ Пропущено")
    await callback.answer()

# ================== АДМИН-ПАНЕЛЬ ==================
@router.message(F.text == "⚙️ Админ-панель")
async def admin_panel(message: Message):
    user_id = message.from_user.id
    if not is_staff(user_id) or is_blocked(user_id) or is_muted(user_id):
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    is_admin_user = is_admin(user_id)
    settings = get_settings()
    groups = load_json(GROUPS_FILE, [])
    groups_info = ""
    if groups:
        groups_info = f"\n🏢 <b>Группы ({len(groups)}):</b>\n"
        for i, group in enumerate(groups[:10], 1):
            if group.get('username'):
                link = f"@{group['username']}"
            else:
                link = f"ID: {group['id']}"
            admin_status = "👑" if group.get('is_admin') else "👤"
            groups_info += f"{i}. {admin_status} {group['title']} - {link}\n"
        if len(groups) > 10:
            groups_info += f"... и ещё {len(groups) - 10} групп\n"
    stats = (
        f"🔧 <b>Панель управления</b>\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {len(load_json(USERS_FILE, []))}\n"
        f"• Заблокировано: {len(load_json(BLOCKED_FILE, []))}\n"
        f"• Групп: {len(groups)}\n"
        f"• Администраторов: {len(load_json(ADMINS_FILE, []))}\n"
        f"• Модераторов: {len(load_json(MODERATORS_FILE, []))}\n"
        f"• Открытых заявок: {len(get_open_tickets())}\n"
        f"{groups_info}"
        f"\n⚙️ Настройки:\n"
        f"• Режим регистрации: <code>{settings['registration_mode']}</code>\n"
        f"• Интервал оповещений: <code>{settings['notification_interval']} мин</code>\n"
        f"• Антифлуд: <code>{settings['flood_threshold']} сообщений</code>"
    )
    await message.answer(stats, reply_markup=get_admin_panel_keyboard(is_admin_user), parse_mode="HTML")

# ================== НАСТРОЙКИ ИНТЕРВАЛА ==================
@router.message(F.text == "🔄 Изменить интервал оповещений")
async def request_interval(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        await message.answer("❌ Только администраторы.")
        return
    await state.set_state(AdminStates.waiting_for_interval)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        f"⏱ Текущий интервал: {get_settings()['notification_interval']} мин\nВведите новый (1-1440):",
        reply_markup=get_cancel_keyboard()
    )

@router.message(AdminStates.waiting_for_interval, F.text == "❌ Отмена")
async def cancel_interval_change(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=get_admin_panel_keyboard(True))

@router.message(AdminStates.waiting_for_interval)
async def set_interval(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    try:
        interval = int(message.text)
        if interval < 1 or interval > 1440:
            raise ValueError
        settings = get_settings()
        settings["notification_interval"] = interval
        save_settings(settings)
        log_action(message.from_user.id, "interval_changed", f"{interval} min")
        await message.answer(f"✅ Интервал изменён: {interval} минут", reply_markup=get_admin_panel_keyboard(True))
    except:
        await message.answer("❌ Неверный формат.", reply_markup=get_cancel_keyboard())
        return
    await state.clear()

# ================== АНТИФЛУД ==================
@router.message(F.text == "⏱ Настроить антифлуд")
async def configure_flood(message: Message):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        await message.answer("❌ Только администраторы.")
        return
    settings = get_settings()
    info = (
        "⏱ <b>Настройки антифлуда</b>\n"
        f"• Лимит: <code>{settings['flood_threshold']}</code>\n"
        f"• Окно: <code>{settings['flood_window_ms']} мс</code>\n"
        f"• Мут: <code>{settings['flood_mute_duration']} сек</code>\n"
        "Выберите параметр:"
    )
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔢 Изменить лимит сообщений")
    builder.button(text="⏱ Изменить временное окно")
    builder.button(text="🔇 Изменить длительность мута")
    builder.button(text="🔙 Назад")
    await message.answer(info, reply_markup=builder.adjust(1).as_markup(resize_keyboard=True), parse_mode="HTML")

@router.message(F.text == "🔢 Изменить лимит сообщений")
async def request_flood_threshold(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_flood_threshold)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer("Введите лимит (2-20):", reply_markup=get_cancel_keyboard())

@router.message(AdminStates.waiting_for_flood_threshold)
async def set_flood_threshold(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    try:
        threshold = int(message.text)
        if threshold < 2 or threshold > 20:
            raise ValueError
        settings = get_settings()
        settings["flood_threshold"] = threshold
        save_settings(settings)
        log_action(message.from_user.id, "flood_threshold_changed", f"{threshold}")
        await message.answer(f"✅ Лимит изменён: {threshold}", reply_markup=get_admin_panel_keyboard(True))
    except:
        await message.answer("❌ Неверный формат.", reply_markup=get_cancel_keyboard())
        return
    await state.clear()

@router.message(F.text == "⏱ Изменить временное окно")
async def request_flood_window(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_flood_window)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer("Введите окно (ms500 или s2):", reply_markup=get_cancel_keyboard())

@router.message(AdminStates.waiting_for_flood_window)
async def set_flood_window(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    def parse_window(window_str: str) -> Optional[int]:
        if not window_str or len(window_str) < 3:
            return None
        unit = window_str[:2].lower()
        try:
            value = int(window_str[2:])
        except ValueError:
            return None
        if unit == 'ms':
            return value
        elif unit == 's':
            return value * 1000
        return None
    window_ms = parse_window(message.text)
    if window_ms is None or window_ms < 100 or window_ms > 10000:
        await message.answer("❌ Неверный формат.", reply_markup=get_cancel_keyboard())
        return
    settings = get_settings()
    settings["flood_window_ms"] = window_ms
    save_settings(settings)
    log_action(message.from_user.id, "flood_window_changed", f"{window_ms}ms")
    await message.answer(f"✅ Окно изменено: {window_ms} мс", reply_markup=get_admin_panel_keyboard(True))
    await state.clear()

@router.message(F.text == "🔇 Изменить длительность мута")
async def request_flood_mute(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_flood_mute)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer("Введите длительность (s30, m2, h1):", reply_markup=get_cancel_keyboard())

@router.message(AdminStates.waiting_for_flood_mute)
async def set_flood_mute(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    def parse_duration(duration_str: str) -> Optional[int]:
        if not duration_str or len(duration_str) < 2:
            return None
        unit = duration_str[0].lower()
        try:
            value = int(duration_str[1:])
        except ValueError:
            return None
        if unit == 's':
            return value
        elif unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 3600
        return None
    duration_sec = parse_duration(message.text)
    if duration_sec is None or duration_sec < 5 or duration_sec > 3600:
        await message.answer("❌ Неверный формат.", reply_markup=get_cancel_keyboard())
        return
    settings = get_settings()
    settings["flood_mute_duration"] = duration_sec
    save_settings(settings)
    log_action(message.from_user.id, "flood_mute_changed", f"{duration_sec}s")
    await message.answer(f"✅ Длительность изменена: {duration_sec} сек", reply_markup=get_admin_panel_keyboard(True))
    await state.clear()

# ================== НАСТРОЙКА ПРИВЕТСТВИЯ ==================
@router.message(F.text == "✏️ Настройка приветствия")
async def greeting_settings(message: Message):
    if not is_admin(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        await message.answer("❌ Только администраторы.")
        return
    settings = get_settings()
    info = "✏️ <b>Настройка приветствия</b>\nВыберите параметры:"
    await message.answer(info, reply_markup=get_greeting_settings_keyboard(settings), parse_mode="HTML")

@router.message(F.text.startswith("👤 Имя автора:"))
async def toggle_author_name(message: Message):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    current = settings.get("include_author_name", False)
    new_value = not current
    settings["include_author_name"] = new_value
    save_settings(settings)
    log_action(message.from_user.id, "greeting_author_toggled", f"{'Включено' if new_value else 'Выключено'}")
    status = "✅ Имя автора включено" if new_value else "❌ Имя автора выключено"
    await message.answer(status, reply_markup=get_greeting_settings_keyboard(settings))

@router.message(F.text.startswith("🌐 Сайт школы:"))
async def toggle_school_website(message: Message):
    if not is_admin(message.from_user.id) or is_muted(message.from_user.id):
        return
    settings = get_settings()
    current = settings.get("include_school_website", False)
    new_value = not current
    settings["include_school_website"] = new_value
    save_settings(settings)
    log_action(message.from_user.id, "greeting_website_toggled", f"{'Включено' if new_value else 'Выключено'}")
    status = "✅ Сайт включён" if new_value else "❌ Сайт выключен"
    await message.answer(status, reply_markup=get_greeting_settings_keyboard(settings))

# ================== БЛОКИРОВКА/РАЗБЛОКИРОВКА ==================
@router.message(F.text == "🔒 Заблокировать пользователя")
async def request_block_user(message: Message, state: FSMContext):
    if not is_staff(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_block_user_id)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        "🆔 Введите ID пользователя:\n<i>Подсказка: ID можно найти в логах</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AdminStates.waiting_for_block_user_id, F.text == "❌ Отмена")
async def cancel_block(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_panel_keyboard(is_admin(message.from_user.id))
    await message.answer("❌ Отменено.", reply_markup=kb)

@router.message(AdminStates.waiting_for_block_user_id)
async def block_user(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    if not is_staff(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    try:
        user_id = int(message.text)
        if user_id == ROOT_USER_ID:
            await message.answer("⚠️ ROOT нельзя заблокировать!", reply_markup=get_root_panel_keyboard() if is_root(message.from_user.id) else get_admin_panel_keyboard(is_admin(message.from_user.id)))
            await state.clear()
            return
        blocked = load_json(BLOCKED_FILE, [])
        if user_id in blocked:
            await message.answer("⚠️ Пользователь уже заблокирован.", reply_markup=get_admin_panel_keyboard(is_admin(message.from_user.id)))
            await state.clear()
            return
        blocked.append(user_id)
        save_json(BLOCKED_FILE, blocked)
        try:
            await bot.send_message(chat_id=user_id, text="❌ Вы были заблокированы.")
        except:
            pass
        log_action(message.from_user.id, "user_blocked", f"User ID: {user_id}")
        await message.answer(f"✅ Пользователь {user_id} заблокирован!", reply_markup=get_admin_panel_keyboard(is_admin(message.from_user.id)))
    except:
        await message.answer("❌ Неверный ID.", reply_markup=get_cancel_keyboard())
        return
    await state.clear()

@router.message(F.text == "🔓 Разблокировать пользователя")
async def request_unblock_user(message: Message, state: FSMContext):
    if not is_staff(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_unblock_user_id)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer("🆔 Введите ID пользователя:", reply_markup=get_cancel_keyboard())

@router.message(AdminStates.waiting_for_unblock_user_id, F.text == "❌ Отмена")
async def cancel_unblock(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_panel_keyboard(is_admin(message.from_user.id))
    await message.answer("❌ Отменено.", reply_markup=kb)

@router.message(AdminStates.waiting_for_unblock_user_id)
async def unblock_user(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    if not is_staff(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    try:
        user_id = int(message.text)
        blocked = load_json(BLOCKED_FILE, [])
        if user_id not in blocked:
            await message.answer("⚠️ Пользователь не заблокирован.", reply_markup=get_admin_panel_keyboard(is_admin(message.from_user.id)))
            await state.clear()
            return
        blocked.remove(user_id)
        save_json(BLOCKED_FILE, blocked)
        log_action(message.from_user.id, "user_unblocked", f"User ID: {user_id}")
        await message.answer(f"✅ Пользователь {user_id} разблокирован!", reply_markup=get_admin_panel_keyboard(is_admin(message.from_user.id)))
    except:
        await message.answer("❌ Неверный ID.", reply_markup=get_cancel_keyboard())
        return
    await state.clear()

# ================== ЭКСПОРТ СТАТИСТИКИ ==================
@router.message(F.text == "📤 Экспорт статистики")
async def export_stats(message: Message, state: FSMContext):
    if not is_staff(message.from_user.id) or is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_export_confirm)
    await state.update_data(action_user_id=message.from_user.id)
    await message.answer(
        "📤 Экспортировать статистику?\n'ДА' или 'ОТМЕНА'.",
        reply_markup=get_cancel_keyboard()
    )

@router.message(AdminStates.waiting_for_export_confirm, F.text.casefold() == "да")
async def confirm_export(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    if not is_staff(message.from_user.id) or is_muted(message.from_user.id):
        await state.clear()
        return
    users = load_json(USERS_FILE, [])
    blocked = load_json(BLOCKED_FILE, [])
    total = len(users)
    active = total - len(blocked)
    export_text = f"Статистика пользователей\nДата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n========================================\n"
    export_text += f"Всего: {total}\nАктивных: {active}\nЗаблокированных: {len(blocked)}\n========================================\n"
    for i, user in enumerate(users, 1):
        status = "❌ ЗАБЛОКИРОВАН" if user["user_id"] in blocked else "✅ АКТИВЕН"
        phone = user.get('phone', 'не указан')
        username = f"@{user['username']}" if user.get('username') else "не указан"
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "не указано"
        reg_date = user.get('registered_at', 'неизвестно')
        export_text += f"{i}. ID: {user['user_id']} | Статус: {status} | Имя: {name} | Username: {username} | Телефон: {phone} | Рег: {reg_date}\n"
    filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(export_text)
    log_action(message.from_user.id, "stats_exported", f"Exported {total} users")
    try:
        document = FSInputFile(filename)
        kb = get_root_keyboard() if is_root(message.from_user.id) else get_moderator_keyboard() if is_moderator(message.from_user.id) else get_admin_keyboard()
        await message.answer_document(document=document, caption=f"✅ Экспортировано {total} пользователей")
        os.remove(filename)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()
    await message.answer("Возврат в меню", reply_markup=kb)

@router.message(AdminStates.waiting_for_export_confirm)
async def cancel_export(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("action_user_id") != message.from_user.id:
        return
    await state.clear()
    kb = get_root_keyboard() if is_root(message.from_user.id) else get_admin_panel_keyboard(is_admin(message.from_user.id))
    await message.answer("❌ Экспорт отменён.", reply_markup=kb)

# ================== КОМАНДА ДОБАВЛЕНИЯ АДМИНА ==================
@router.message(Command("addadmin"))
async def add_admin_command(message: Message, command: CommandObject):
    args = command.args
    if not args or len(args.split()) != 2:
        await message.answer(f"ℹ️ Использование: /addadmin [ключ] [user_id]\nПример: /addadmin {ADMIN_KEY} 123456789")
        return
    key, user_id_str = args.split()
    if key != ADMIN_KEY:
        await message.answer("❌ Неверный ключ!")
        log_action(message.from_user.id, "admin_add_failed", f"Invalid key")
        return
    try:
        user_id = int(user_id_str)
        admins = load_json(ADMINS_FILE, [])
        if user_id not in admins:
            admins.append(user_id)
            save_json(ADMINS_FILE, admins)
            log_action(message.from_user.id, "admin_added", f"New admin ID: {user_id}")
            await message.answer(f"✅ Пользователь {user_id} добавлен в администраторы!")
        else:
            await message.answer("⚠️ Пользователь уже админ.")
    except ValueError:
        await message.answer("❌ Неверный формат ID.")

# ================== КОМАНДА ДОБАВЛЕНИЯ МОДЕРАТОРА ==================
@router.message(Command("addmoderator"))
async def add_moderator_command(message: Message, command: CommandObject):
    args = command.args
    if not args or len(args.split()) != 2:
        await message.answer(f"ℹ️ Использование: /addmoderator [ключ] [user_id]\nПример: /addmoderator {MODERATOR_KEY} 123456789")
        return
    key, user_id_str = args.split()
    if key != MODERATOR_KEY and key != ADMIN_KEY:
        await message.answer("❌ Неверный ключ!")
        log_action(message.from_user.id, "moderator_add_failed", f"Invalid key")
        return
    try:
        user_id = int(user_id_str)
        moderators = load_json(MODERATORS_FILE, [])
        admins = load_json(ADMINS_FILE, [])
        if user_id not in moderators and user_id not in admins:
            moderators.append(user_id)
            save_json(MODERATORS_FILE, moderators)
            log_action(message.from_user.id, "moderator_added", f"New moderator ID: {user_id}")
            await message.answer(f"✅ Пользователь {user_id} добавлен в модераторы!")
        else:
            await message.answer("⚠️ Пользователь уже в персонале.")
    except ValueError:
        await message.answer("❌ Неверный формат ID.")

# ================== НАЗАД ==================
@router.message(F.text == "🔙 Назад")
async def back_to_main(message: Message):
    if is_blocked(message.from_user.id) or is_muted(message.from_user.id):
        return
    if is_root(message.from_user.id):
        kb = get_root_keyboard()
    elif is_admin(message.from_user.id):
        kb = get_admin_keyboard()
    elif is_moderator(message.from_user.id):
        kb = get_moderator_keyboard()
    else:
        kb = get_user_keyboard()
    await message.answer("↩️ Возврат в главное меню", reply_markup=kb)

# ================== ГЛОБАЛЬНЫЙ ФИЛЬТР (ОБНОВЛЁН) ==================
@router.message()
async def global_filter(message: Message):
    user_id = message.from_user.id
    chat_type = message.chat.type
    
    # ✅ УДАЛЕНИЕ СООБЩЕНИЙ ЗАБЛОКИРОВАННЫХ В ГРУППАХ
    if chat_type in ['group', 'supergroup']:
        if is_blocked(user_id) and not is_root(user_id):
            try:
                await bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=message.message_id
                )
                log_action(user_id, "message_deleted_blocked", f"Group: {message.chat.id}")
            except Exception as e:
                logging.error(f"Delete failed: {e}")
            return
        
        # Проверка прав админа бота в группе
        try:
            bot_member = await bot.get_chat_member(message.chat.id, bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                return  # Бот не админ - не может удалять
        except:
            pass
    
    # ✅ ПРОВЕРКА БЛОКИРОВКИ
    if is_blocked(user_id):
        if not is_root(user_id):
            await message.answer("❌ Вы заблокированы")
            return
    
    # ✅ ПРОВЕРКА МУТА
    if is_muted(user_id):
        if not is_root(user_id):
            until = muted_users[user_id]["until"]
            remaining = int((until - datetime.now()).total_seconds())
            if remaining > 0:
                await message.answer(f"🔇 Вы временно ограничены. Осталось {remaining} сек.")
            else:
                del muted_users[user_id]
            return
    
    # ✅ АНТИФЛУД ТОЛЬКО В ГРУППАХ
    if chat_type in ['group', 'supergroup']:
        if check_flood(user_id):
            if not is_root(user_id):
                settings = get_settings()
                mute_user(user_id, settings["flood_mute_duration"])
                try:
                    await bot.delete_message(
                        chat_id=message.chat.id,
                        message_id=message.message_id
                    )
                except:
                    pass
                await message.answer(f"🔇 Слишком много сообщений! Мут на {settings['flood_mute_duration']} сек.")
                log_action(user_id, "flood_detected", f"Muted for {settings['flood_mute_duration']}s")
                return
    
    # ✅ РЕГИСТРАЦИЯ ТОЛЬКО ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ В ЛС
    settings = get_settings()
    if chat_type == 'private':
        if settings["registration_mode"] == "Phone Number" and not get_user(user_id) and not is_staff(user_id):
            await message.answer(
                "📱 *Нужна регистрация.*\n\nНажмите кнопку ниже:",
                reply_markup=get_registration_keyboard(),
                parse_mode="Markdown"
            )
            log_action(user_id, "unregistered_message", f"Text: {message.text[:100] if message.text else 'non-text'}")
            return
    
    # Логирование неизвестных команд
    if message.text and not message.text.startswith('/'):
        log_action(user_id, "unknown_message", f"Chat: {chat_type}, Text: {message.text[:100]}")

# ================== ЗАПУСК ==================
async def main():
    for file, default in [
        (ADMINS_FILE, [ROOT_USER_ID]),
        (MODERATORS_FILE, []),
        (BLOCKED_FILE, []),
        (LOGS_FILE, []),
        (USERS_FILE, []),
        (TICKETS_FILE, []),
        (GROUPS_FILE, []),
    ]:
        if not os.path.exists(file):
            save_json(file, default)
    admins = load_json(ADMINS_FILE, [])
    if ROOT_USER_ID not in admins:
        admins.append(ROOT_USER_ID)
        save_json(ADMINS_FILE, admins)
        log_action(ROOT_USER_ID, "root_auto_added", "ROOT автоматически добавлен в админы")
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS.copy())
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("БОТ ЗАПУЩЕН 🟢")
    logging.info(f"ROOT Пользователь: {ROOT_USER_ID}")
    logging.info("Бот работает в личных сообщениях и группах!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    import asyncio  
    asyncio.run(main())
