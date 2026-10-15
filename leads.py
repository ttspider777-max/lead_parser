"""Поиск лидов в OpenStreetMap (Overpass API).

Лид — компания нужной ниши, у которой в карточке указан Telegram. Если у неё нет сайта — ей
предлагаем сайт, если сайт есть, но в Telegram нет бота — предлагаем бота.
Выгрузка страны и ниши тяжёлая (до минуты), поэтому хранится в базе CACHE_TTL.
"""
import asyncio
import logging
import random
import re
import time

import aiohttp

import config
import db

log = logging.getLogger(__name__)

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
TG_KEYS = ("contact:telegram", "telegram")
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
NOT_USERNAMES = {"joinchat", "share", "addstickers", "proxy", "s", "c", "iv"}

_locks: dict[tuple, asyncio.Lock] = {}


class LeadError(Exception):
    pass


def build_query(country, niche) -> str:
    parts = []
    for f in config.NICHES[niche]["filters"]:
        for key in TG_KEYS:
            parts.append(f'nwr{f}["{key}"](area.a);')
    return (f'[out:json][timeout:120];area["ISO3166-1"="{country}"][admin_level=2]->.a;'
            f'({"".join(parts)});out center tags 2000;')


def parse_telegram(raw: str) -> str | None:
    """Достаёт из тега юзернейм или ссылку на номер. Каналы-приглашения и мусор отбрасываем."""
    raw = (raw or "").split(";")[0].strip()
    if not raw:
        return None
    m = re.search(r"(?:t(?:elegram)?\.me|telegram\.dog)/([^/?#\s]+)", raw, re.I)
    value = m.group(1) if m else raw.lstrip("@")
    phone = re.sub(r"[^\d+]", "", value)
    if value.startswith("+") and len(phone) >= 11 and phone[1:].isdigit():
        return phone                                   # t.me/+79991234567 открывает чат по номеру
    if value.lower() in NOT_USERNAMES or not USERNAME_RE.match(value):
        return None
    return "@" + value


def lead_from_element(el, country, niche) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name") or tags.get("name:ru") or tags.get("name:en") or tags.get("brand")
    tg = next((parse_telegram(tags[k]) for k in TG_KEYS if tags.get(k)), None)
    if not name or not tg:
        return None
    website = tags.get("website") or tags.get("contact:website") or ""
    tg_is_bot = tg.lower().endswith("bot")
    if website and tg_is_bot:
        return None                                    # и сайт, и бот уже есть
    city = tags.get("addr:city") or tags.get("addr:place") or ""
    street = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
    return {
        "id": f"{el['type'][0]}{el['id']}", "country": country, "niche": niche, "name": name[:120],
        "tg": tg, "need": "bot" if website else "site", "city": city, "address": street,
        "phone": tags.get("phone") or tags.get("contact:phone") or "", "website": website,
    }


async def fetch_overpass(query: str, rounds=3) -> list[dict]:
    """Бесплатные серверы Overpass часто перегружены (502/429) — перебираем зеркала по кругу с паузами."""
    last = None
    timeout = aiohttp.ClientTimeout(total=150)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "HeliysLeads/1.0"}) as s:
        for attempt in range(rounds):
            for url in MIRRORS[:1] + random.sample(MIRRORS[1:], len(MIRRORS) - 1):
                try:
                    async with s.post(url, data={"data": query}) as r:
                        if r.status == 200:
                            data = await r.json(content_type=None)
                            if "elements" in data:
                                return data["elements"]
                        last = f"{url} HTTP {r.status}"
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    last = f"{url} {type(e).__name__}"
                log.info("Overpass: %s", last)
            await asyncio.sleep(5 + attempt * 10)
    raise LeadError(f"Карты не ответили: {last}")


async def refresh(country, niche, force=False) -> int:
    """Обновляет выгрузку страны/ниши, если она устарела. Возвращает число лидов в базе."""
    lock = _locks.setdefault((country, niche), asyncio.Lock())
    async with lock:
        meta = await db.one("SELECT * FROM cache_meta WHERE country=? AND niche=?", country, niche)
        if meta and not force and time.time() - meta["fetched_at"] < config.CACHE_TTL:
            return meta["total"]
        elements = await fetch_overpass(build_query(country, niche))
        found = {}
        for el in elements:
            lead = lead_from_element(el, country, niche)
            if lead:
                found.setdefault(lead["tg"].lower(), lead)   # одна сеть — один лид
        rows = list(found.values())
        await db.run("DELETE FROM leads WHERE country=? AND niche=?", country, niche)
        await db.run_many(
            "INSERT OR REPLACE INTO leads(id, country, niche, name, tg, need, city, address, phone, website) "
            "VALUES(:id,:country,:niche,:name,:tg,:need,:city,:address,:phone,:website)", rows)
        await db.run("INSERT OR REPLACE INTO cache_meta(country, niche, fetched_at, total) VALUES(?,?,?,?)",
                     country, niche, int(time.time()), len(rows))
        log.info("Лиды %s/%s: %s из %s объектов", country, niche, len(rows), len(elements))
        return len(rows)


async def search(user_id, country, niche, count) -> list[dict]:
    """Выдаёт пользователю новых лидов, которых он ещё не получал. Сайт-лиды идут первыми."""
    await refresh(country, niche)
    rows = await db.all(
        "SELECT * FROM leads l WHERE country=? AND niche=? AND NOT EXISTS ("
        " SELECT 1 FROM user_leads u WHERE u.user_id=? AND u.lead_id=l.id) "
        "ORDER BY need='site' DESC, RANDOM() LIMIT ?", country, niche, user_id, count)
    now = int(time.time())
    for r in rows:
        await db.run(
            "INSERT OR IGNORE INTO user_leads(user_id, lead_id, country, niche, name, tg, need, city, address, "
            "phone, website, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            user_id, r["id"], country, niche, r["name"], r["tg"], r["need"], r["city"], r["address"],
            r["phone"], r["website"], now, now)
    return await db.all(
        "SELECT * FROM user_leads WHERE user_id=? AND lead_id IN (%s)" % ",".join("?" * len(rows)),
        user_id, *[r["id"] for r in rows]) if rows else []


async def available(user_id, country, niche) -> int | None:
    """Сколько новых лидов осталось для пользователя; None — выгрузки ещё нет."""
    meta = await db.one("SELECT 1 FROM cache_meta WHERE country=? AND niche=?", country, niche)
    if not meta:
        return None
    row = await db.one(
        "SELECT COUNT(*) c FROM leads l WHERE country=? AND niche=? AND NOT EXISTS ("
        " SELECT 1 FROM user_leads u WHERE u.user_id=? AND u.lead_id=l.id)", country, niche, user_id)
    return row["c"]


async def warmup():
    """Фоном прогревает кэш по всем странам и нишам, чтобы поиск отвечал сразу. Бережно к Overpass."""
    await asyncio.sleep(10)
    while True:
        for country in config.COUNTRIES:
            for niche in config.NICHES:
                meta = await db.one("SELECT fetched_at FROM cache_meta WHERE country=? AND niche=?", country, niche)
                if meta and time.time() - meta["fetched_at"] < config.CACHE_TTL:
                    continue
                try:
                    await refresh(country, niche)
                except Exception as e:
                    log.warning("Прогрев %s/%s не удался: %s", country, niche, e)
                await asyncio.sleep(20)
        await asyncio.sleep(3600)
