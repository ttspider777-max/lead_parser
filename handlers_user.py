import html
import re

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import config
import db
import gate

router = Router()


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя и отсекает забаненных."""

    async def __call__(self, handler, event, data):
        tg_user = data.get("event_from_user")
        if tg_user and not tg_user.is_bot:
            user, is_new = await db.upsert_user(tg_user.id, tg_user.username, tg_user.first_name, tg_user.is_premium)
            if user["banned"] and tg_user.id not in config.ADMIN_IDS:
                return
            data["user"], data["is_new"] = user, is_new
        return await handler(event, data)


def button(text, emoji_id="", **kwargs):
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(text=text, **kwargs)


def menu_kb(settings, plain=False):
    def emoji(key):
        return "" if plain else settings[f"btn_{key}_emoji"]

    rows = []
    if config.WEBAPP_URL:
        rows.append([button(settings["btn_app_text"], emoji("app"), web_app=WebAppInfo(url=config.WEBAPP_URL))])
    rows.append([button(settings["btn_prices_text"], emoji("prices"), callback_data="prices"),
                 button(settings["btn_support_text"], emoji("support"), url=config.SUPPORT_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def strip_custom_emoji(text):
    return re.sub(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", r"\1", text)


async def send_menu(message: Message, first_name):
    settings = await db.get_settings()
    text = (settings["greeting"].replace("{name}", html.escape(first_name or "друг"))
            .replace("{trial}", str(config.TRIAL_GENERATIONS)))
    try:
        await message.answer(text, reply_markup=menu_kb(settings))
    except TelegramBadRequest:
        # премиум-эмодзи недоступны боту (у владельца бота нет Premium) — шлём без них
        await message.answer(strip_custom_emoji(text), reply_markup=menu_kb(settings, plain=True))


async def send_gate(message: Message, missing):
    rows = [[InlineKeyboardButton(text=c["title"], url=c["url"])] for c in missing]
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    await message.answer("Чтобы пользоваться ботом, подпишитесь на каналы:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def prices_text(user) -> str:
    s = await db.get_settings()
    q = db.quota(user)
    if q["left"] is None:
        status = "безлимит"
    elif q["kind"] == "daily":
        status = f"{q['left']} из {q['limit']} генераций на сегодня"
    else:
        status = f"пробный доступ, осталось {q['left']} генераций"
    return (f"<b>Тарифы</b>\n\n"
            f"♾ <b>Навсегда</b> — {s['price_forever']} ₽\nБезлимитные генерации каждый день.\n\n"
            f"📅 <b>Лимит в день</b> — от {s['price_daily']} ₽\nФиксированное число генераций в сутки, "
            f"цена зависит от количества.\n\n"
            f"За подпиской пишите @{config.SUPPORT_USERNAME} — пришлём ключ, активируйте его командой "
            f"<code>/key КЛЮЧ</code> или в приложении.\n\nВаш доступ: {status}")


@router.message(CommandStart())
async def start(message: Message, user: dict):
    missing = await gate.missing_channels(user["id"])
    if missing:
        return await send_gate(message, missing)
    await send_menu(message, user["first_name"])


@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, user: dict):
    missing = await gate.missing_channels(user["id"])
    if missing:
        return await call.answer("Вы подписались не на все каналы", show_alert=True)
    await call.message.delete()
    await send_menu(call.message, user["first_name"])
    await call.answer()


@router.callback_query(F.data == "prices")
async def prices(call: CallbackQuery, user: dict):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить подписку", url=config.SUPPORT_URL)],
        [InlineKeyboardButton(text="‹ Назад", callback_data="menu")],
    ])
    await call.message.answer(await prices_text(user), reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "menu")
async def back_to_menu(call: CallbackQuery, user: dict):
    await call.message.delete()
    await send_menu(call.message, user["first_name"])
    await call.answer()


@router.message(Command("key"))
async def key(message: Message, command: CommandObject, user: dict):
    if not command.args:
        return await message.answer("Отправьте ключ так: <code>/key HL-XXXX-XXXX-XXXX</code>")
    k = await db.activate_key(user["id"], command.args)
    if not k:
        return await message.answer("Ключ не найден или уже использован.")
    await message.answer(f"✅ Ключ активирован: <b>{db.key_title(k)}</b>")
