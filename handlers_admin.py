import asyncio
import html
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
import gate
from handlers_user import send_menu
from loader import bot

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

BUTTONS = {"app": "Открыть парсер", "prices": "Тарифы", "support": "Поддержка"}
PAGE = 8


class St(StatesGroup):
    find = State()
    bonus = State()
    daily = State()
    greeting = State()
    button = State()
    channel = State()
    key_daily = State()
    tip = State()
    price = State()
    broadcast = State()


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


BACK = kb([("‹ В админ-панель", "adm:home")])


def fmt_time(ts):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "—"


async def panel():
    now = int(time.time())
    s = await db.one(
        "SELECT (SELECT COUNT(*) FROM users) users, "
        "(SELECT COUNT(*) FROM users WHERE created_at > ?1 - 86400) new_day, "
        "(SELECT COUNT(*) FROM users WHERE plan != '' AND (plan_until = 0 OR plan_until > ?1)) subs, "
        "(SELECT COALESCE(SUM(searches),0) FROM users) searches, "
        "(SELECT COUNT(*) FROM user_leads) leads, "
        "(SELECT COUNT(*) FROM user_leads WHERE status != 'new') written, "
        "(SELECT COUNT(*) FROM keys WHERE used_by IS NULL) keys_free, "
        "(SELECT COUNT(*) FROM leads) base, (SELECT COUNT(*) FROM cache_meta) cached", now)
    total_pairs = len(config.COUNTRIES) * len(config.NICHES)
    text = (f"<b>Админ-панель · {config.APP_NAME}</b>\n\n"
            f"👥 Пользователей: <b>{s['users']}</b> (+{s['new_day']} за сутки)\n"
            f"👑 С подпиской: <b>{s['subs']}</b>\n"
            f"🔎 Поисков: <b>{s['searches']}</b>\n"
            f"🎯 Выдано лидов: <b>{s['leads']}</b>, написали: <b>{s['written']}</b>\n"
            f"🔑 Неиспользованных ключей: <b>{s['keys_free']}</b>\n"
            f"🗺 База лидов: <b>{s['base']}</b> (загружено {s['cached']} из {total_pairs} стран/ниш)")
    markup = kb(
        [("✏️ Приветствие", "adm:greet"), ("🔘 Кнопки меню", "adm:btns")],
        [("📢 Обязательная подписка", "adm:chan")],
        [("👥 Пользователи", "adm:users:0"), ("🔍 Найти", "adm:find")],
        [("🔑 Создать ключ", "adm:keys"), ("📋 Ключи", "adm:keylist")],
        [("💡 Совет в приложении", "adm:tip"), ("💰 Цены", "adm:prices")],
        [("📨 Рассылка всем", "adm:bc"), ("🗺 База лидов", "adm:base")],
    )
    return text, markup


@router.message(Command("admin"))
async def admin(message: Message, state: FSMContext):
    await state.clear()
    text, markup = await panel()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = await panel()
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


# ---------- пользователи ----------

def plan_line(u) -> str:
    q = db.quota(u)
    if q["kind"] == "admin":
        return "админ, безлимит"
    if q["kind"] == "forever":
        return "♾ безлимит навсегда"
    if q["kind"] == "daily":
        until = "навсегда" if not q["until"] else "до " + fmt_time(q["until"])
        return f"📅 {q['limit']}/день ({until}), сегодня осталось {q['left']}"
    return f"пробный, осталось {q['left']} из {config.TRIAL_GENERATIONS}"


async def user_card(user_id):
    u = await db.get_user(user_id)
    if not u:
        return "Пользователь не найден", BACK
    st = await db.user_stats(user_id)
    keys = await db.all("SELECT * FROM keys WHERE used_by=? ORDER BY used_at DESC LIMIT 3", user_id)
    keys_line = "\n".join(f"  • <code>{k['code']}</code> — {db.key_title(k)}, {fmt_time(k['used_at'])}"
                          for k in keys) or "  —"
    scripts_cnt = (await db.one("SELECT COUNT(*) c FROM scripts WHERE user_id=?", user_id))["c"]
    text = (f"<b>{html.escape(u['first_name'] or '—')}</b>\n\n"
            f"ID: <code>{u['id']}</code>\n"
            f"Юзернейм: {'@' + u['username'] if u['username'] else '—'}\n"
            f"Telegram Premium: {'да' if u['is_premium'] else 'нет'}\n"
            f"Регистрация: {fmt_time(u['created_at'])}\n"
            f"Был в боте: {fmt_time(u['last_seen'])}\n\n"
            f"Доступ: {plan_line(u)}\n"
            f"Бонусных генераций: {u['bonus']}\n"
            f"Поисков: {u['searches']}\n"
            f"Лидов найдено: {st['found']}, написал: {st['written']}, "
            f"отказов: {st['refused']}, интерес: {st['interested']}\n"
            f"Своих скриптов: {scripts_cnt}\n"
            f"Ключи:\n{keys_line}\n\n"
            f"Статус: {'🚫 забанен' if u['banned'] else 'активен'}")
    markup = kb(
        [("➕ Генерации", f"adm:bonus:{user_id}"), ("♻️ Сбросить пробный", f"adm:trial:{user_id}")],
        [("♾ Выдать навсегда", f"adm:forever:{user_id}"), ("📅 Выдать N/день", f"adm:daily:{user_id}")],
        [("✖️ Снять подписку", f"adm:unsub:{user_id}"),
         ("✅ Разбанить" if u["banned"] else "🚫 Забанить", f"adm:ban:{user_id}")],
        [("‹ В админ-панель", "adm:home")],
    )
    return text, markup


async def show_card(target, user_id, edit=True):
    text, markup = await user_card(user_id)
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:users:"))
async def users_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(call.data.split(":")[2])
    total = (await db.one("SELECT COUNT(*) c FROM users"))["c"]
    rows = await db.all("SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?", PAGE, page * PAGE)
    buttons = []
    for u in rows:
        mark = "👑" if db.plan_active(u) else ("🚫" if u["banned"] else "•")
        name = f"@{u['username']}" if u["username"] else (u["first_name"] or str(u["id"]))
        buttons.append([(f"{mark} {name[:28]} · {u['searches']} пои.", f"adm:user:{u['id']}")])
    nav = []
    if page > 0:
        nav.append(("‹", f"adm:users:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(("›", f"adm:users:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([("‹ В админ-панель", "adm:home")])
    await call.message.edit_text(f"<b>Пользователи</b> ({total}), сначала недавно активные:",
                                 reply_markup=kb(*buttons))
    await call.answer()


@router.callback_query(F.data.startswith("adm:user:"))
async def user_open(call: CallbackQuery):
    await show_card(call.message, int(call.data.split(":")[2]))
    await call.answer()


@router.callback_query(F.data == "adm:find")
async def find(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.find)
    await call.message.edit_text("Отправьте ID или @юзернейм пользователя.", reply_markup=BACK)
    await call.answer()


@router.message(St.find, F.text)
async def find_input(message: Message, state: FSMContext):
    query = message.text.strip().lstrip("@")
    if query.isdigit():
        user = await db.get_user(int(query))
    else:
        user = await db.one("SELECT * FROM users WHERE username = ? COLLATE NOCASE", query)
    if not user:
        return await message.answer("Не нашёл. Пользователь должен хотя бы раз запустить бота.", reply_markup=BACK)
    await state.clear()
    await show_card(message, user["id"], edit=False)


@router.callback_query(F.data.startswith("adm:ban:"))
async def ban(call: CallbackQuery):
    user_id = int(call.data.split(":")[2])
    user = await db.get_user(user_id)
    await db.run("UPDATE users SET banned=? WHERE id=?", 0 if user["banned"] else 1, user_id)
    await show_card(call.message, user_id)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("adm:trial:"))
async def reset_trial(call: CallbackQuery):
    user_id = int(call.data.split(":")[2])
    await db.run("UPDATE users SET trial_used=0 WHERE id=?", user_id)
    await show_card(call.message, user_id)
    await call.answer("Пробный доступ сброшен")


@router.callback_query(F.data.startswith("adm:forever:"))
async def give_forever(call: CallbackQuery):
    user_id = int(call.data.split(":")[2])
    await db.run("UPDATE users SET plan='forever', daily_limit=0, plan_until=0 WHERE id=?", user_id)
    await show_card(call.message, user_id)
    await notify(user_id, "🎉 Вам выдан безлимитный доступ навсегда!")
    await call.answer("Выдано")


@router.callback_query(F.data.startswith("adm:unsub:"))
async def unsub(call: CallbackQuery):
    user_id = int(call.data.split(":")[2])
    await db.run("UPDATE users SET plan='', daily_limit=0, plan_until=0 WHERE id=?", user_id)
    await show_card(call.message, user_id)
    await call.answer("Подписка снята")


@router.callback_query(F.data.startswith("adm:bonus:"))
async def bonus(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.bonus)
    await state.update_data(user_id=int(call.data.split(":")[2]))
    await call.message.edit_text("Сколько разовых генераций добавить? (отрицательное число — забрать)",
                                 reply_markup=BACK)
    await call.answer()


@router.message(St.bonus, F.text)
async def bonus_input(message: Message, state: FSMContext):
    try:
        value = int(message.text.strip())
    except ValueError:
        return await message.answer("Нужно целое число.")
    data = await state.get_data()
    await state.clear()
    await db.run("UPDATE users SET bonus = MAX(0, bonus + ?) WHERE id=?", value, data["user_id"])
    if value > 0:
        await notify(data["user_id"], f"🎁 Вам начислено генераций: {value}")
    await show_card(message, data["user_id"], edit=False)


@router.callback_query(F.data.startswith("adm:daily:"))
async def daily(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.daily)
    await state.update_data(user_id=int(call.data.split(":")[2]))
    await call.message.edit_text(
        "Отправьте: <code>генераций_в_день дней</code>\nНапример <code>10 30</code> — 10 в день на 30 дней, "
        "<code>10 0</code> — 10 в день навсегда.", reply_markup=BACK)
    await call.answer()


def parse_daily(text):
    parts = text.split()
    if len(parts) == 1:
        parts.append("0")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    limit, days = int(parts[0]), int(parts[1])
    if not 1 <= limit <= 1000 or days > 3650:
        return None
    return limit, days


@router.message(St.daily, F.text)
async def daily_input(message: Message, state: FSMContext):
    parsed = parse_daily(message.text)
    if not parsed:
        return await message.answer("Формат: <code>10 30</code> (1–1000 генераций, 0–3650 дней).")
    limit, days = parsed
    data = await state.get_data()
    await state.clear()
    until = int(time.time()) + days * 86400 if days else 0
    await db.run("UPDATE users SET plan='daily', daily_limit=?, plan_until=? WHERE id=?", limit, until,
                 data["user_id"])
    await notify(data["user_id"], f"🎉 Вам выдан доступ: {limit} генераций в день")
    await show_card(message, data["user_id"], edit=False)


async def notify(user_id, text):
    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass


# ---------- ключи ----------

@router.callback_query(F.data == "adm:keys")
async def keys(call: CallbackQuery, state: FSMContext):
    await state.clear()
    s = await db.get_settings()
    await call.message.edit_text(
        "<b>Создать ключ</b>\n\n"
        f"♾ Навсегда — безлимит генераций ({s['price_forever']} ₽)\n"
        f"📅 Лимит в день — заданное число генераций в сутки (от {s['price_daily']} ₽)\n\n"
        "Ключ одноразовый: пользователь активирует его в приложении или командой /key.",
        reply_markup=kb([("♾ Навсегда", "adm:key_forever")], [("📅 Лимит в день", "adm:key_daily")],
                        [("‹ В админ-панель", "adm:home")]))
    await call.answer()


async def send_key(message: Message, code, title):
    await message.answer(
        f"🔑 Ключ создан: <b>{title}</b>\n\n<code>{code}</code>\n\n"
        f"Пользователю: откройте @{(await bot.me()).username} → приложение → Поиск → «Активировать ключ», "
        f"или отправьте боту <code>/key {code}</code>",
        reply_markup=kb([("🔑 Ещё ключ", "adm:keys")], [("‹ В админ-панель", "adm:home")]))


@router.callback_query(F.data == "adm:key_forever")
async def key_forever(call: CallbackQuery):
    code = await db.create_key("forever", 0, 0, call.from_user.id)
    await send_key(call.message, code, "безлимит навсегда")
    await call.answer()


@router.callback_query(F.data == "adm:key_daily")
async def key_daily(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.key_daily)
    await call.message.edit_text(
        "Отправьте: <code>генераций_в_день дней</code>\n"
        "<code>10</code> или <code>10 0</code> — 10 в день навсегда, <code>20 30</code> — 20 в день на 30 дней.",
        reply_markup=BACK)
    await call.answer()


@router.message(St.key_daily, F.text)
async def key_daily_input(message: Message, state: FSMContext):
    parsed = parse_daily(message.text)
    if not parsed:
        return await message.answer("Формат: <code>10 30</code> (1–1000 генераций, 0–3650 дней).")
    await state.clear()
    limit, days = parsed
    code = await db.create_key("daily", limit, days, message.from_user.id)
    await send_key(message, code, db.key_title({"kind": "daily", "daily_limit": limit, "days": days}))


@router.callback_query(F.data == "adm:keylist")
async def keylist(call: CallbackQuery):
    free = await db.all("SELECT * FROM keys WHERE used_by IS NULL ORDER BY created_at DESC LIMIT 15")
    used = await db.all("SELECT * FROM keys WHERE used_by IS NOT NULL ORDER BY used_at DESC LIMIT 10")
    lines = ["<b>Свободные ключи</b>"] + [f"<code>{k['code']}</code> — {db.key_title(k)}" for k in free] \
        or ["—"]
    if not free:
        lines.append("—")
    lines += ["", "<b>Последние активации</b>"]
    lines += [f"<code>{k['code']}</code> — {db.key_title(k)} → <code>{k['used_by']}</code>" for k in used] or ["—"]
    rows = [[(f"🗑 {k['code']}", f"adm:keydel:{k['code']}")] for k in free[:8]]
    rows.append([("‹ В админ-панель", "adm:home")])
    await call.message.edit_text("\n".join(lines), reply_markup=kb(*rows))
    await call.answer()


@router.callback_query(F.data.startswith("adm:keydel:"))
async def keydel(call: CallbackQuery):
    await db.run("DELETE FROM keys WHERE code=? AND used_by IS NULL", call.data.split(":", 2)[2])
    await call.answer("Ключ удалён")
    await keylist(call)


# ---------- обязательная подписка ----------

async def channels_view():
    channels = await db.all("SELECT * FROM channels")
    lines = [f"• {html.escape(c['title'])}" for c in channels] or ["Каналов нет — проверка выключена."]
    rows = [[(f"🗑 {c['title'][:30]}", f"adm:chan_del:{c['chat_id']}")] for c in channels]
    rows += [[("➕ Добавить канал", "adm:chan_add")], [("‹ В админ-панель", "adm:home")]]
    return "<b>Обязательная подписка</b>\n\n" + "\n".join(lines), kb(*rows)


@router.callback_query(F.data == "adm:chan")
async def chan(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = await channels_view()
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "adm:chan_add")
async def chan_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.channel)
    await call.message.edit_text(
        "Сначала добавьте бота администратором в канал, затем отправьте сюда @юзернейм канала "
        "или перешлите из него любой пост.", reply_markup=BACK)
    await call.answer()


@router.message(St.channel)
async def chan_input(message: Message, state: FSMContext):
    if message.forward_from_chat:
        ref = message.forward_from_chat.id
    elif message.text:
        ref = message.text.strip()
        ref = int(ref) if ref.lstrip("-").isdigit() else "@" + ref.split("/")[-1].lstrip("@")
    else:
        return await message.answer("Отправьте @юзернейм или перешлите пост из канала.")
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status != "administrator":
            raise ValueError
        url = f"https://t.me/{chat.username}" if chat.username else \
            (chat.invite_link or (await bot.create_chat_invite_link(chat.id)).invite_link)
    except Exception:
        return await message.answer("Не получилось: бот должен быть администратором этого канала "
                                    "с правом приглашать пользователей.", reply_markup=BACK)
    await db.run("INSERT OR REPLACE INTO channels(chat_id, title, url) VALUES(?,?,?)", chat.id, chat.title, url)
    gate.reset_cache()
    await state.clear()
    text, markup = await channels_view()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:chan_del:"))
async def chan_del(call: CallbackQuery, state: FSMContext):
    await db.run("DELETE FROM channels WHERE chat_id=?", int(call.data.split(":")[2]))
    gate.reset_cache()
    await chan(call, state)


# ---------- приветствие ----------

@router.callback_query(F.data == "adm:greet")
async def greet(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.greeting)
    await call.message.edit_text(
        "Отправьте новый текст приветствия. Жирный, курсив, ссылки и <b>премиум-эмодзи</b> сохранятся.\n\n"
        "<code>{name}</code> — имя пользователя, <code>{trial}</code> — число пробных генераций.\n\n"
        "Премиум-эмодзи бот покажет, только если у владельца бота (аккаунта, создавшего его в @BotFather) "
        "есть Telegram Premium — иначе они заменятся обычными.",
        reply_markup=kb([("↺ Сбросить на стандартное", "adm:greet_reset")], [("‹ В админ-панель", "adm:home")]))
    await call.answer()


@router.callback_query(F.data == "adm:greet_reset")
async def greet_reset(call: CallbackQuery, state: FSMContext):
    await db.reset_setting("greeting")
    await home(call, state)


@router.message(St.greeting, F.text)
async def greet_input(message: Message, state: FSMContext):
    await db.set_setting("greeting", message.html_text)
    await state.clear()
    await message.answer("Сохранено. Так это увидят пользователи:")
    await send_menu(message, message.from_user.first_name)


# ---------- кнопки ----------

@router.callback_query(F.data == "adm:btns")
async def btns(call: CallbackQuery, state: FSMContext):
    await state.clear()
    settings = await db.get_settings()
    rows = [[(f"{'✨ ' if settings[f'btn_{k}_emoji'] else ''}{settings[f'btn_{k}_text']}", f"adm:btn:{k}")]
            for k in BUTTONS]
    await call.message.edit_text("Какую кнопку главного меню изменить?",
                                 reply_markup=kb(*rows, [("‹ В админ-панель", "adm:home")]))
    await call.answer()


@router.callback_query(F.data.startswith("adm:btn:"))
async def btn(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[2]
    await state.set_state(St.button)
    await state.update_data(key=key)
    await call.message.edit_text(
        f"Кнопка «{BUTTONS[key]}».\n\nОтправьте новый текст. Премиум-эмодзи в самом начале станет иконкой кнопки.",
        reply_markup=kb([("↺ Сбросить", f"adm:btn_reset:{key}")], [("‹ Назад", "adm:btns")]))
    await call.answer()


@router.callback_query(F.data.startswith("adm:btn_reset:"))
async def btn_reset(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[2]
    await db.reset_setting(f"btn_{key}_text")
    await db.reset_setting(f"btn_{key}_emoji")
    await btns(call, state)


@router.message(St.button, F.text)
async def btn_input(message: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    text, emoji_id = message.text, ""
    lead = next((e for e in message.entities or [] if e.type == "custom_emoji" and e.offset == 0), None)
    if lead:
        emoji_id = lead.custom_emoji_id
        text = text[len(lead.extract_from(text)):]
    text = text.strip()
    if not text or len(text) > 60:
        return await message.answer("Текст кнопки должен быть от 1 до 60 символов.")
    await db.set_setting(f"btn_{key}_text", text)
    await db.set_setting(f"btn_{key}_emoji", emoji_id)
    await state.clear()
    await message.answer("Сохранено. Так это увидят пользователи:")
    await send_menu(message, message.from_user.first_name)


# ---------- совет и цены ----------

@router.callback_query(F.data == "adm:tip")
async def tip(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.tip)
    s = await db.get_settings()
    await call.message.edit_text(
        f"Сейчас в приложении под поиском:\n\n<i>{html.escape(s['tip'])}</i>\n\nОтправьте новый совет "
        "(какие ниши сейчас больше всего нуждаются в сайте/боте).",
        reply_markup=kb([("↺ Сбросить", "adm:tip_reset")], [("‹ В админ-панель", "adm:home")]))
    await call.answer()


@router.callback_query(F.data == "adm:tip_reset")
async def tip_reset(call: CallbackQuery, state: FSMContext):
    await db.reset_setting("tip")
    await home(call, state)


@router.message(St.tip, F.text)
async def tip_input(message: Message, state: FSMContext):
    if len(message.text) > 400:
        return await message.answer("Совет должен быть короче 400 символов.")
    await db.set_setting("tip", message.text.strip())
    await state.clear()
    await message.answer("Совет обновлён.", reply_markup=BACK)


@router.callback_query(F.data == "adm:prices")
async def prices(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.price)
    s = await db.get_settings()
    await call.message.edit_text(
        f"Цены сейчас: навсегда — <b>{s['price_forever']} ₽</b>, лимит в день — от <b>{s['price_daily']} ₽</b>.\n\n"
        "Отправьте две цены через пробел, например <code>750 300</code>.", reply_markup=BACK)
    await call.answer()


@router.message(St.price, F.text)
async def prices_input(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return await message.answer("Формат: <code>750 300</code>")
    await db.set_setting("price_forever", parts[0])
    await db.set_setting("price_daily", parts[1])
    await state.clear()
    await message.answer("Цены обновлены — в приложении и в «Тарифах».", reply_markup=BACK)


# ---------- рассылка ----------

@router.callback_query(F.data == "adm:bc")
async def broadcast(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.broadcast)
    await call.message.edit_text("Отправьте сообщение для рассылки всем пользователям бота "
                                 "(текст, фото, видео — как есть, с премиум-эмодзи).", reply_markup=BACK)
    await call.answer()


@router.message(St.broadcast)
async def broadcast_input(message: Message, state: FSMContext):
    await state.clear()
    users = await db.all("SELECT id FROM users WHERE banned=0")
    status = await message.answer(f"Рассылка запущена: {len(users)} получателей…")
    ok = fail = 0
    for u in users:
        try:
            await message.copy_to(u["id"])
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.copy_to(u["id"])
                ok += 1
            except Exception:
                fail += 1
        except (TelegramForbiddenError, Exception):
            fail += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"Рассылка завершена. Доставлено: {ok}, не доставлено: {fail}.", reply_markup=BACK)


# ---------- база лидов ----------

@router.callback_query(F.data == "adm:base")
async def base(call: CallbackQuery):
    rows = await db.all("SELECT country, SUM(total) total, COUNT(*) niches FROM cache_meta GROUP BY country")
    by = {r["country"]: r for r in rows}
    lines = []
    for code, title in config.COUNTRIES.items():
        r = by.get(code)
        lines.append(f"{title}: {r['total']} лидов ({r['niches']}/{len(config.NICHES)} ниш)" if r
                     else f"{title}: ещё не загружено")
    await call.message.edit_text(
        "<b>База лидов</b> (OpenStreetMap, обновляется раз в неделю фоном)\n\n" + "\n".join(lines),
        reply_markup=BACK)
    await call.answer()
