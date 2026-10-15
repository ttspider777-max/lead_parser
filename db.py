import secrets
import time

import aiosqlite

import config

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, is_premium INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0, created_at INTEGER, last_seen INTEGER,
    trial_used INTEGER DEFAULT 0,
    plan TEXT DEFAULT '', daily_limit INTEGER DEFAULT 0, plan_until INTEGER DEFAULT 0,
    day TEXT DEFAULT '', day_used INTEGER DEFAULT 0, bonus INTEGER DEFAULT 0,
    searches INTEGER DEFAULT 0,
    script_site TEXT DEFAULT 's1', script_bot TEXT DEFAULT 'b1');
CREATE TABLE IF NOT EXISTS keys(
    code TEXT PRIMARY KEY, kind TEXT, daily_limit INTEGER DEFAULT 0, days INTEGER DEFAULT 0,
    created_by INTEGER, created_at INTEGER, used_by INTEGER, used_at INTEGER);
CREATE TABLE IF NOT EXISTS channels(chat_id INTEGER PRIMARY KEY, title TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cache_meta(country TEXT, niche TEXT, fetched_at INTEGER, total INTEGER,
    PRIMARY KEY(country, niche));
CREATE TABLE IF NOT EXISTS leads(
    id TEXT, country TEXT, niche TEXT, name TEXT, tg TEXT, need TEXT, city TEXT, address TEXT,
    phone TEXT, website TEXT, PRIMARY KEY(id, niche));
CREATE TABLE IF NOT EXISTS user_leads(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, lead_id TEXT, country TEXT, niche TEXT,
    name TEXT, tg TEXT, need TEXT, city TEXT, address TEXT, phone TEXT, website TEXT,
    status TEXT DEFAULT 'new', created_at INTEGER, updated_at INTEGER, UNIQUE(user_id, lead_id));
CREATE TABLE IF NOT EXISTS scripts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, need TEXT, title TEXT, text TEXT, created_at INTEGER);
"""

DEFAULT_SETTINGS = {
    "greeting": (
        "<b>Heliys Leads</b>\n\n"
        "Привет, {name}! Я нахожу компании, которым нужен сайт или Telegram-бот, "
        "и помогаю быстро им написать.\n\n"
        "Открывай приложение и запускай первый поиск — {trial} генерации бесплатно."
    ),
    "btn_app_text": "Открыть парсер",
    "btn_app_emoji": "",
    "btn_support_text": "Поддержка",
    "btn_support_emoji": "",
    "btn_prices_text": "Тарифы",
    "btn_prices_emoji": "",
    "tip": (
        "Сейчас лучше всего заходят барбершопы, стоматологии и автосервисы: у многих есть только "
        "Instagram или 2ГИС, а онлайн-запись через сайт или бота заметно поднимает число клиентов."
    ),
    "price_forever": str(config.PRICE_FOREVER),
    "price_daily": str(config.PRICE_DAILY),
}


async def init():
    global _db
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()


async def one(sql, *args):
    cur = await _db.execute(sql, args)
    row = await cur.fetchone()
    return dict(row) if row else None


async def all(sql, *args):
    cur = await _db.execute(sql, args)
    return [dict(r) for r in await cur.fetchall()]


async def run(sql, *args):
    cur = await _db.execute(sql, args)
    await _db.commit()
    return cur


async def run_many(sql, rows):
    await _db.executemany(sql, rows)
    await _db.commit()


# ---------- settings ----------

async def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    for row in await all("SELECT key, value FROM settings"):
        s[row["key"]] = row["value"]
    return s


async def set_setting(key, value):
    await run("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              key, value)


async def reset_setting(key):
    await run("DELETE FROM settings WHERE key=?", key)


# ---------- users ----------

async def get_user(user_id):
    return await one("SELECT * FROM users WHERE id=?", user_id)


async def upsert_user(user_id, username, first_name, is_premium):
    """Возвращает (user, is_new)."""
    now = int(time.time())
    user = await get_user(user_id)
    if user:
        await run("UPDATE users SET username=?, first_name=?, is_premium=?, last_seen=? WHERE id=?",
                  username, first_name, int(bool(is_premium)), now, user_id)
        user.update(username=username, first_name=first_name, is_premium=int(bool(is_premium)), last_seen=now)
        return user, False
    await run("INSERT INTO users(id, username, first_name, is_premium, created_at, last_seen) VALUES(?,?,?,?,?,?)",
              user_id, username, first_name, int(bool(is_premium)), now, now)
    return await get_user(user_id), True


def today():
    return time.strftime("%Y-%m-%d")


def plan_active(user) -> bool:
    return bool(user["plan"]) and (user["plan_until"] == 0 or user["plan_until"] > time.time())


def quota(user) -> dict:
    """Сколько генераций доступно. left=None — без ограничений."""
    if user["id"] in config.ADMIN_IDS:
        return {"kind": "admin", "left": None, "limit": None, "until": 0}
    bonus = user["bonus"]
    if plan_active(user):
        if user["plan"] == "forever":
            return {"kind": "forever", "left": None, "limit": None, "until": user["plan_until"]}
        used = user["day_used"] if user["day"] == today() else 0
        return {"kind": "daily", "left": max(0, user["daily_limit"] - used) + bonus,
                "limit": user["daily_limit"], "until": user["plan_until"]}
    return {"kind": "trial", "left": max(0, config.TRIAL_GENERATIONS - user["trial_used"]) + bonus,
            "limit": config.TRIAL_GENERATIONS, "until": 0}


async def spend_generation(user):
    """Списывает одну генерацию. Вызывать только после проверки quota()."""
    q = quota(user)
    if q["left"] is None:
        pass
    elif q["kind"] == "daily" and q["left"] - user["bonus"] > 0:
        if user["day"] == today():
            await run("UPDATE users SET day_used = day_used + 1 WHERE id=?", user["id"])
        else:
            await run("UPDATE users SET day=?, day_used=1 WHERE id=?", today(), user["id"])
    elif q["kind"] == "trial" and q["left"] - user["bonus"] > 0:
        await run("UPDATE users SET trial_used = trial_used + 1 WHERE id=?", user["id"])
    else:
        await run("UPDATE users SET bonus = MAX(0, bonus - 1) WHERE id=?", user["id"])
    await run("UPDATE users SET searches = searches + 1 WHERE id=?", user["id"])


async def user_stats(user_id) -> dict:
    row = await one(
        "SELECT COUNT(*) found, "
        "COALESCE(SUM(status IN ('written','refused','interested')),0) written, "
        "COALESCE(SUM(status='refused'),0) refused, COALESCE(SUM(status='interested'),0) interested "
        "FROM user_leads WHERE user_id=?", user_id)
    return row


# ---------- ключи ----------

def new_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "HL-" + "-".join(parts)


async def create_key(kind, daily_limit, days, admin_id):
    code = new_code()
    await run("INSERT INTO keys(code, kind, daily_limit, days, created_by, created_at) VALUES(?,?,?,?,?,?)",
              code, kind, daily_limit, days, admin_id, int(time.time()))
    return code


def key_title(k) -> str:
    base = "Безлимит навсегда" if k["kind"] == "forever" else f"{k['daily_limit']} генераций в день"
    if k["kind"] == "daily":
        base += ", навсегда" if not k["days"] else f", {k['days']} дн."
    return base


async def activate_key(user_id, code) -> dict | None:
    """Возвращает ключ при успехе, иначе None."""
    code = code.strip().upper()
    key = await one("SELECT * FROM keys WHERE code=? AND used_by IS NULL", code)
    if not key:
        return None
    now = int(time.time())
    cur = await run("UPDATE keys SET used_by=?, used_at=? WHERE code=? AND used_by IS NULL", user_id, now, code)
    if cur.rowcount != 1:
        return None
    until = now + key["days"] * 86400 if key["kind"] == "daily" and key["days"] else 0
    user = await get_user(user_id)
    if key["kind"] == "daily" and user["plan"] == "forever" and plan_active(user):
        return key   # безлимит уже есть — дневной ключ его не понижает
    await run("UPDATE users SET plan=?, daily_limit=?, plan_until=? WHERE id=?",
              key["kind"], key["daily_limit"], until, user_id)
    return key
