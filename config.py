import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
# Переменную PORT не используем: на хостингах её часто занимает служебный сервер
PORT = int(os.getenv("WEB_PORT") or 8090)

DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"

APP_NAME = "Heliys Leads"
SUPPORT_USERNAME = "apfov"
SUPPORT_URL = f"https://t.me/{SUPPORT_USERNAME}"

TRIAL_GENERATIONS = 3          # одна генерация = один поиск лидов
LEAD_COUNTS = (5, 10, 15)

PRICE_FOREVER = 750
PRICE_DAILY = 300

COUNTRIES = {
    "RU": "🇷🇺 Россия", "UA": "🇺🇦 Украина", "KZ": "🇰🇿 Казахстан", "UZ": "🇺🇿 Узбекистан",
    "AM": "🇦🇲 Армения", "GE": "🇬🇪 Грузия", "MD": "🇲🇩 Молдова", "DE": "🇩🇪 Германия",
    "PL": "🇵🇱 Польша", "LT": "🇱🇹 Литва", "AE": "🇦🇪 ОАЭ",
}

# Ниша -> название, эмодзи и фильтры OpenStreetMap (каждый фильтр — отдельный запрос в объединении)
NICHES = {
    "barber": {"title": "Барбершопы", "emoji": "💈", "filters": [
        '["shop"="hairdresser"]["hairdresser"~"barber|male",i]',
        '["shop"="hairdresser"]["name"~"barber|барбер",i]']},
    "beauty": {"title": "Салоны красоты", "emoji": "💅", "filters": [
        '["shop"="beauty"]["beauty"!~"cosmetics|skin_care|spa",i]',
        '["shop"="hairdresser"]["hairdresser"!~"barber|male",i]["name"!~"barber|барбер",i]']},
    "auto": {"title": "Автосервисы", "emoji": "🔧", "filters": [
        '["shop"="car_repair"]', '["shop"="tyres"]', '["amenity"="car_wash"]']},
    "build": {"title": "Строительные компании", "emoji": "🏗", "filters": [
        '["office"="construction_company"]', '["craft"="builder"]', '["office"="architect"]']},
    "dental": {"title": "Стоматологии", "emoji": "🦷", "filters": [
        '["amenity"="dentist"]', '["healthcare"="dentist"]']},
    "cafe": {"title": "Кофейни и кафе", "emoji": "☕", "filters": ['["amenity"="cafe"]']},
    "restaurant": {"title": "Рестораны", "emoji": "🍽", "filters": ['["amenity"="restaurant"]']},
    "spa": {"title": "Массаж и SPA", "emoji": "💆", "filters": [
        '["shop"="massage"]', '["leisure"="spa"]', '["amenity"="spa"]', '["beauty"="spa"]']},
    "cosmo": {"title": "Косметология", "emoji": "✨", "filters": [
        '["shop"="beauty"]["beauty"~"cosmetics|skin_care",i]', '["shop"="beauty"]["name"~"космет|cosmet",i]',
        '["healthcare:speciality"~"dermatology|cosmetology",i]']},
}

CACHE_TTL = 7 * 86400          # сколько хранить выгрузку страны/ниши, прежде чем обновлять
