import asyncio
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiohttp import web

import api
import config
import db
import handlers_admin
import handlers_user
import leads
from loader import bot

log = logging.getLogger(__name__)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await db.init()

    runner = web.AppRunner(api.build_app())
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
        log.info("Mini App: http://localhost:%s", config.PORT)
    except OSError as e:
        log.error("Mini App не запущен, порт %s занят: %s. Задайте другой порт в WEB_PORT", config.PORT, e)

    if config.WEBAPP_URL:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Парсер", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    else:
        log.warning("WEBAPP_URL не задан — кнопка Mini App скрыта, нужен публичный HTTPS-адрес")
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню"),
                               BotCommand(command="key", description="Активировать ключ")])

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(handlers_user.UserMiddleware())
    dp.include_routers(handlers_admin.router, handlers_user.router)

    warm = asyncio.create_task(leads.warmup())
    try:
        await dp.start_polling(bot)
    finally:
        warm.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
