"""Готовые скрипты первого сообщения лиду.

Плейсхолдеры: {name} — название компании, {niche} — ниша в родительном/описательном виде,
{city} — « в Городе» или пусто. Для лидов без сайта берётся скрипт «site», для лидов с сайтом — «bot».
"""
import config
import db

NICHE_WORDS = {
    "barber": "барбершопа", "beauty": "салона красоты", "auto": "автосервиса", "build": "строительной компании",
    "dental": "стоматологии", "cafe": "кофейни", "restaurant": "ресторана", "spa": "SPA-салона",
    "cosmo": "кабинета косметологии",
}

BUILTIN = [
    {"id": "s1", "need": "site", "title": "Демо-сайт бесплатно", "text":
        "Здравствуйте! Нашёл {name}{city} на карте и заметил, что у вас пока нет своего сайта.\n\n"
        "Я делаю сайты для {niche}: {offer}. Могу бесплатно собрать "
        "демо-версию именно под вас — посмотрите, как это будет выглядеть, и решите. Скинуть?"},
    {"id": "s2", "need": "site", "title": "Коротко и по делу", "text":
        "Добрый день! У {name} нет сайта — клиенты из поиска уходят к конкурентам. "
        "Сделаю современный сайт с онлайн-записью за 5–7 дней. Показать пример?"},
    {"id": "s3", "need": "site", "title": "Через выгоду", "text":
        "Здравствуйте! Подскажите, кто у вас отвечает за рекламу?\n\n"
        "Для {niche} сайт с записью онлайн обычно даёт +20–30% заявок: человек видит цены, отзывы и "
        "записывается сам, без звонка. Могу сделать для {name} демо бесплатно — если понравится, доработаем."},
    {"id": "s4", "need": "site", "title": "С примерами работ", "text":
        "Здравствуйте! Я веб-разработчик, делаю сайты для {niche}. Посмотрел {name}{city} — "
        "у вас отличные отзывы, но своего сайта нет, а это минус для тех, кто ищет вас в Google и Яндексе.\n\n"
        "Могу показать пару своих работ и набросать демо-версию для вас. Интересно?"},
    {"id": "s5", "need": "site", "title": "Мягкий заход", "text":
        "Добрый день! Не отвлеку надолго. Вы рассматривали свой сайт для {name}? "
        "Делаю недорогие и быстрые сайты для {niche}, демо — бесплатно. Если неактуально, просто напишите, "
        "больше не побеспокою."},
    {"id": "s6", "need": "site", "title": "Сайт + запись", "text":
        "Здравствуйте! Сейчас клиенты {name} могут записаться только через звонок или сообщение? "
        "Я могу сделать сайт с онлайн-записью и напоминаниями — меньше пропусков и звонков. "
        "Готов скинуть демо-версию сайта под ваш {niche_short}."},
    {"id": "b1", "need": "bot", "title": "Демо-бот бесплатно", "text":
        "Здравствуйте! Посмотрел сайт {name} — сделан хорошо. А в Telegram клиентам пока приходится "
        "писать вручную.\n\nЯ делаю Telegram-ботов для {niche}: запись, прайс, напоминания и ответы на "
        "частые вопросы 24/7. Могу бесплатно сделать демо-версию бота под вас. Скинуть?"},
    {"id": "b2", "need": "bot", "title": "Коротко", "text":
        "Добрый день! Сделаю для {name} Telegram-бота с онлайн-записью и рассылками за 3–5 дней. "
        "Клиенты записываются сами, администратору меньше работы. Показать демо?"},
    {"id": "b3", "need": "bot", "title": "Через рассылки", "text":
        "Здравствуйте! У вас уже есть сайт, а у Telegram-бота есть одно преимущество — рассылки. "
        "Акции и свободные окошки можно отправлять всем клиентам в один клик, и их читают почти все.\n\n"
        "Могу собрать демо-бота для {name}. Интересно?"},
    {"id": "b4", "need": "bot", "title": "Mini App", "text":
        "Здравствуйте! Делаю для {niche} приложения прямо внутри Telegram: каталог услуг, запись, "
        "бонусы для постоянных клиентов. Скачивать ничего не нужно. Могу показать демо для {name}?"},
    {"id": "b5", "need": "bot", "title": "Мягкий заход", "text":
        "Добрый день! Вы думали о Telegram-боте для {name}? Он принимает заявки, пока вы заняты, "
        "и напоминает клиентам о записи. Демо сделаю бесплатно. Если неактуально — просто дайте знать."},
]

NICHE_SHORT = {
    "barber": "барбершоп", "beauty": "салон", "auto": "автосервис", "build": "бизнес", "dental": "клинику",
    "cafe": "кофейню", "restaurant": "ресторан", "spa": "салон", "cosmo": "кабинет",
}


async def list_for(user_id) -> list[dict]:
    custom = await db.all("SELECT id, need, title, text FROM scripts WHERE user_id=? ORDER BY id", user_id)
    return [dict(s, custom=False) for s in BUILTIN] + \
        [{"id": f"u{s['id']}", "need": s["need"], "title": s["title"], "text": s["text"], "custom": True}
         for s in custom]


async def get(user_id, script_id) -> dict | None:
    if script_id.startswith("u") and script_id[1:].isdigit():
        s = await db.one("SELECT * FROM scripts WHERE id=? AND user_id=?", int(script_id[1:]), user_id)
        return s and {"id": script_id, "need": s["need"], "title": s["title"], "text": s["text"]}
    return next((s for s in BUILTIN if s["id"] == script_id), None)


FOOD = ("cafe", "restaurant")


def render(text, lead) -> str:
    city = f" в г. {lead['city']}" if lead.get("city") else ""
    values = {"name": lead["name"], "city": city, "niche": NICHE_WORDS.get(lead["niche"], "бизнеса"),
              "niche_short": NICHE_SHORT.get(lead["niche"], "бизнес"),
              "offer": "меню, цены, фото и бронирование столиков" if lead["niche"] in FOOD
              else "услуги, цены, фото работ и онлайн-запись"}
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


async def message_for(user, lead) -> str:
    """Текст для конкретного лида: выбранный пользователем скрипт под его потребность."""
    sid = user["script_site"] if lead["need"] == "site" else user["script_bot"]
    script = await get(user["id"], sid) or next(s for s in BUILTIN if s["need"] == lead["need"])
    return render(script["text"], lead)


def niche_title(niche):
    return config.NICHES.get(niche, {}).get("title", niche)
