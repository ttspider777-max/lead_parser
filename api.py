"""HTTP API и раздача Mini App."""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from aiohttp import web

import config
import db
import gate
import leads
import scripts

log = logging.getLogger(__name__)
routes = web.RouteTableDef()
WEBAPP_DIR = config.BASE_DIR / "webapp"
INIT_DATA_TTL = 86400
STATUSES = ("new", "written", "refused", "interested")


class ApiError(Exception):
    pass


def err(message, status=400, **extra):
    return web.json_response({"error": message, **extra}, status=status)


def validate_init_data(init_data: str) -> dict | None:
    """Проверяет подпись Telegram и возвращает данные пользователя."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received = pairs.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return None
        if time.time() - int(pairs["auth_date"]) > INIT_DATA_TTL:
            return None
        return json.loads(pairs["user"])
    except (KeyError, ValueError):
        return None


@web.middleware
async def auth(request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    tg_user = validate_init_data(request.headers.get("X-Init-Data", ""))
    if not tg_user:
        return err("unauthorized", 401)
    user, _ = await db.upsert_user(tg_user["id"], tg_user.get("username"), tg_user.get("first_name"),
                                   tg_user.get("is_premium", False))
    if user["banned"] and user["id"] not in config.ADMIN_IDS:
        return err("banned", 403)
    missing = await gate.missing_channels(user["id"])
    if missing:
        return err("subscribe", 403, channels=[{"title": c["title"], "url": c["url"]} for c in missing])
    request["user"] = user
    try:
        return await handler(request)
    except ApiError as e:
        return err(str(e))
    except leads.LeadError:
        return err("Сервис карт сейчас перегружен. Попробуйте через минуту — генерация не списана.")
    except Exception:
        log.exception("api %s", request.path)
        return err("Внутренняя ошибка", 500)


async def body(request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ApiError("Некорректный запрос")
    return data


async def lead_out(user, row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "tg": row["tg"], "need": row["need"], "city": row["city"],
        "address": row["address"], "phone": row["phone"], "website": row["website"], "status": row["status"],
        "niche": row["niche"], "niche_title": scripts.niche_title(row["niche"]),
        "country": config.COUNTRIES.get(row["country"], row["country"]),
        "message": await scripts.message_for(user, row),
    }


async def me_payload(user) -> dict:
    user = await db.get_user(user["id"])
    settings = await db.get_settings()
    return {
        "user": {"id": user["id"], "first_name": user["first_name"], "username": user["username"],
                 "is_admin": user["id"] in config.ADMIN_IDS},
        "quota": db.quota(user),
        "stats": await db.user_stats(user["id"]),
        "tip": settings["tip"],
        "prices": {"forever": settings["price_forever"], "daily": settings["price_daily"]},
        "trial": config.TRIAL_GENERATIONS,
        "support": config.SUPPORT_USERNAME,
        "countries": [{"code": k, "title": v} for k, v in config.COUNTRIES.items()],
        "niches": [{"code": k, "title": v["title"], "emoji": v["emoji"]} for k, v in config.NICHES.items()],
        "counts": list(config.LEAD_COUNTS),
    }


@routes.get("/api/me")
async def me(request):
    return web.json_response(await me_payload(request["user"]))


@routes.post("/api/search")
async def search(request):
    data = await body(request)
    user = await db.get_user(request["user"]["id"])
    country, niche, count = data.get("country"), data.get("niche"), data.get("count")
    if country not in config.COUNTRIES or niche not in config.NICHES or count not in config.LEAD_COUNTS:
        raise ApiError("Выберите страну, нишу и количество")
    q = db.quota(user)
    if q["left"] is not None and q["left"] <= 0:
        return err("no_quota", 402)
    found = await leads.search(user["id"], country, niche, count)
    if found:   # пустой поиск генерацию не тратит
        await db.spend_generation(user)
    user = await db.get_user(user["id"])
    return web.json_response({
        "leads": [await lead_out(user, r) for r in found],
        "left_in_base": await leads.available(user["id"], country, niche),
        "me": await me_payload(user),
    })


@routes.get("/api/leads")
async def my_leads(request):
    user = await db.get_user(request["user"]["id"])
    rows = await db.all("SELECT * FROM user_leads WHERE user_id=? ORDER BY id DESC LIMIT 300", user["id"])
    return web.json_response({"leads": [await lead_out(user, r) for r in rows]})


@routes.post("/api/leads/status")
async def lead_status(request):
    data = await body(request)
    if data.get("status") not in STATUSES:
        raise ApiError("Неизвестный статус")
    cur = await db.run("UPDATE user_leads SET status=?, updated_at=? WHERE id=? AND user_id=?",
                       data["status"], int(time.time()), data.get("id"), request["user"]["id"])
    if cur.rowcount != 1:
        raise ApiError("Лид не найден")
    return web.json_response({"ok": True, "stats": await db.user_stats(request["user"]["id"])})


@routes.get("/api/scripts")
async def scripts_list(request):
    user = await db.get_user(request["user"]["id"])
    return web.json_response({"scripts": await scripts.list_for(user["id"]),
                              "active": {"site": user["script_site"], "bot": user["script_bot"]}})


@routes.post("/api/scripts/select")
async def scripts_select(request):
    data = await body(request)
    uid = request["user"]["id"]
    script = await scripts.get(uid, str(data.get("id", "")))
    if not script:
        raise ApiError("Скрипт не найден")
    await db.run(f"UPDATE users SET script_{script['need']}=? WHERE id=?", script["id"], uid)
    return await scripts_list(request)


@routes.post("/api/scripts")
async def scripts_create(request):
    data = await body(request)
    uid = request["user"]["id"]
    need, title, text = data.get("need"), str(data.get("title", "")).strip(), str(data.get("text", "")).strip()
    if need not in ("site", "bot"):
        raise ApiError("Выберите, для кого скрипт: сайт или бот")
    if not 1 <= len(title) <= 40 or not 10 <= len(text) <= 1500:
        raise ApiError("Название до 40 символов, текст от 10 до 1500")
    if (await db.one("SELECT COUNT(*) c FROM scripts WHERE user_id=?", uid))["c"] >= 20:
        raise ApiError("Можно сохранить не больше 20 своих скриптов")
    cur = await db.run("INSERT INTO scripts(user_id, need, title, text, created_at) VALUES(?,?,?,?,?)",
                       uid, need, title, text, int(time.time()))
    await db.run(f"UPDATE users SET script_{need}=? WHERE id=?", f"u{cur.lastrowid}", uid)
    return await scripts_list(request)


@routes.post("/api/scripts/delete")
async def scripts_delete(request):
    data = await body(request)
    uid = request["user"]["id"]
    sid = str(data.get("id", ""))
    if not (sid.startswith("u") and sid[1:].isdigit()):
        raise ApiError("Встроенные скрипты удалить нельзя")
    await db.run("DELETE FROM scripts WHERE id=? AND user_id=?", int(sid[1:]), uid)
    await db.run("UPDATE users SET script_site='s1' WHERE id=? AND script_site=?", uid, sid)
    await db.run("UPDATE users SET script_bot='b1' WHERE id=? AND script_bot=?", uid, sid)
    return await scripts_list(request)


@routes.post("/api/key")
async def activate(request):
    data = await body(request)
    key = await db.activate_key(request["user"]["id"], str(data.get("code", "")))
    if not key:
        raise ApiError("Ключ не найден или уже использован")
    return web.json_response({"ok": True, "title": db.key_title(key), "me": await me_payload(request["user"])})


@routes.get("/")
async def index(request):
    return web.FileResponse(WEBAPP_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def build_app():
    app = web.Application(middlewares=[auth])
    app.add_routes(routes)
    app.router.add_static("/", WEBAPP_DIR)
    return app
