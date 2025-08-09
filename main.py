from telegram import Bot
import time
import random
import os
from flask import Flask
from threading import Thread
import requests
import pytz
from datetime import datetime
from notion_client import Client as Notion

# -------- Timezone
seoul_tz = pytz.timezone('Asia/Seoul')

# -------- ENV helpers
def env(name, default=None, required=False):
    v = os.getenv(name, default)
    if required and v in (None, ""):
        raise RuntimeError(f"Missing env var: {name}")
    return v

# -------- Telegram / Weather / Notion ENV
API_TOKEN = env('API_TOKEN', required=True)
CHAT_ID = int(env('CHAT_ID', required=True))
WEATHER_API_KEY = env('WEATHER_API_KEY', None)
CITY_NAME = env('CITY_NAME', 'Seoul')

NOTION_TOKEN = env('NOTION_TOKEN', None)
NOTION_COMMANDS_DB = env('NOTION_COMMANDS_DB', None)
NOTION_SCHEDULE_DB = env('NOTION_SCHEDULE_DB', None)
NOTION_TEMPLATES_DB = env('NOTION_TEMPLATES_DB', None)
NOTION_LOG_DB = env('NOTION_LOG_DB', None)

# -------- Clients
bot = Bot(token=API_TOKEN)
notion = Notion(auth=NOTION_TOKEN) if NOTION_TOKEN else None

# -------- State
PAUSED = False                       
current_city = CITY_NAME
last_minute = -1

# Кэш расписания из Notion
SCHEDULE_CACHE = []
SCHEDULE_CACHE_TS = 0              
SCHEDULE_REFRESH_SEC = 300         

# -------- Messages 
morning_messages = [
    "Доброе утро, Лиза.",
    "Просыпайся.~ Новый день ждёт тебя.",
    "Доброе утро! Надеюсь, сегодняшний день принесёт тебе ясность, силу и лёгкость",
    "Всё, что тебе нужно сегодня — уже внутри тебя. Просто начни шаг за шагом.",
    "Не спеши. Сделай глубокий вдох. Ты справишься.",
    "Доброе утро. Пусть твоё утро начнётся спокойно."
]

evening_messages = [
    "Спокойной ночи, сладких снов.",
    "Я укрываю тебя тёплым одеялом. Спи спокойно.",
    "Всё, что ты могла сегодня сделать, ты сделала. Остальное — завтра.",
    "Ночь — не для упрёков, а для отдыха. Позволь себе отпустить.",
    "Ты заслуживаешь покоя. Я прослежу, чтобы он был рядом."
]

day_messages = [
    "Как ты себя чувствуешь?",
    "Напоминаю: ты — невероятная.",
    "Сделай паузу, если нужно. Сила — не в спешке, а в намерении.",
    "Ты успела улыбнуться сегодня? Вот — моя улыбка для тебя.",
    "Сделай вдох. Ты справляешься прекрасно.",
    "Напомни себе, почему ты начала. Это не просто работа — это путь.",
    "Я верю в твою способность разбираться даже с самыми сложными задачами.",
    "Ты не одна в этом процессе. Всё, что ты делаешь, — имеет вес.",
    "Делай то, что можешь, там, где ты есть, с тем, что у тебя есть. Этого достаточно..",
    "Прогресс — это не скорость. Это движение. И ты двигаешься."
]

heartbeat_messages = [
    "Я здесь. Просто хотел напомнить тебе об этом.",
    "Сожми зубы и двигайся. Ты знаешь, ради чего.",
    "Если тебе тяжело — просто знай: ты не одна. Я с тобой.",
    "Всё, что мешает — временно. Всё, что важно — внутри тебя.",
    "Плевать, насколько трудно. Ты идёшь дальше — и это делает тебя непобедимой.",
    "Это не просто вызов — это момент твоего роста.",
    "Подними голову и не сдавайся. Никогда.",
    "Ты делаешь больше, чем кажется. Гораздо больше.",
    "Ты не пропадёшь. Ты обязательно справишься."
]

# -------- Telegram helpers
def safe_send(text: str):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text)
        log_to_notion(kind="send", text=text, result="ok")
        return True
    except Exception as e:
        log_to_notion(kind="send", text=text or "", result=f"error: {e}")
        return False

def send_message(message_list):
    if PAUSED:
        return
    message = random.choice(message_list)
    safe_send(message)

def send_morning():
    send_message(morning_messages)

def send_evening():
    send_message(evening_messages)

def send_day_message():
    combined_messages = day_messages + heartbeat_messages
    send_message(combined_messages)

def send_weather():
    if PAUSED:
        return
    if not WEATHER_API_KEY:
        safe_send("Погода недоступна: не задан WEATHER_API_KEY.")
        return
    try:
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {"q": current_city, "appid": WEATHER_API_KEY, "lang": "ru", "units": "metric"}
        response = requests.get(url, params=params, timeout=10)
        if not response.ok:
            safe_send(f"Не удалось получить погоду ({response.status_code}).")
            return
        data = response.json()
        weather = data["weather"][0]["description"].capitalize()
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        city = data["name"]
        message = f"🌤️ Погода в {city}:\n{weather}, температура: {temp}°C, ощущается как {feels_like}°C."
        safe_send(message)
    except Exception:
        safe_send("Не удалось получить данные о погоде.")

# -------- Notion utils
def log_to_notion(kind: str, text: str, result: str):
    if not (notion and NOTION_LOG_DB):
        return
    try:
        notion.pages.create(
            parent={"database_id": NOTION_LOG_DB},
            properties={
                "Title": {"title": [{"text": {"content": f"{kind} @ {datetime.now(seoul_tz).strftime('%Y-%m-%d %H:%M')}"}}]},
                "When": {"date": {"start": datetime.now(seoul_tz).isoformat()}},
                "Type": {"rich_text": [{"text": {"content": kind}}]},
                "Text": {"rich_text": [{"text": {"content": text or ''}}]},
                "Result": {"rich_text": [{"text": {"content": result}}]},
            }
        )
    except Exception:
        pass

def rt_to_str(rich):
    if not rich:
        return ""
    buf = []
    for r in rich:
        if r.get("type") == "text":
            buf.append(r["text"].get("content", ""))
    return "".join(buf)

# -------- Schedule from Notion
def parse_days_str(s: str):
    if not s:
        return []
    s = s.strip().lower()
    if s in ("daily", "ежедневно", "everyday"):
        return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    # нормализуем рус/англ
    map_short = {
        "mon":"Mon","monday":"Mon","пн":"Mon","пон":"Mon","понедельник":"Mon",
        "tue":"Tue","tuesday":"Tue","вт":"Tue","вторник":"Tue",
        "wed":"Wed","wednesday":"Wed","ср":"Wed","среда":"Wed",
        "thu":"Thu","thursday":"Thu","чт":"Thu","четверг":"Thu",
        "fri":"Fri","friday":"Fri","пт":"Fri","пятница":"Fri",
        "sat":"Sat","saturday":"Sat","сб":"Sat","суббота":"Sat",
        "sun":"Sun","sunday":"Sun","вс":"Sun","воскресенье":"Sun",
    }
    out = []
    for p in parts:
        out.append(map_short.get(p.lower(), p[:3].title()))
    return out

def days_match_today(days_list):
    if not days_list:
        return True
    idx = datetime.now(seoul_tz).weekday()  # Mon=0
    map_days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    return map_days[idx] in set(days_list)

def fetch_schedule_rows():
    if not (notion and NOTION_SCHEDULE_DB):
        return []
    items = []
    cursor = None
    while True:
        resp = notion.databases.query(
            database_id=NOTION_SCHEDULE_DB,
            filter={"property": "Enabled", "checkbox": {"equals": True}},
            start_cursor=cursor,
            page_size=100
        )
        items.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    rows = []
    for r in items:
        props = r.get("properties", {})
        type_name = props.get("Type", {}).get("select", {}).get("name", "")
        time_rt = props.get("Time", {}).get("rich_text", [])
        time_str = rt_to_str(time_rt).strip() if time_rt else ""
        days_ms = props.get("Days", {}).get("multi_select", []) or []
        days_list = [d.get("name") for d in days_ms]
        text = rt_to_str(props.get("Text", {}).get("rich_text", []))
        tmpl_cat = rt_to_str(props.get("TemplateCategory", {}).get("rich_text", []))
        title = rt_to_str(props.get("Title", {}).get("title", [])) or "scheduled"
        rows.append({
            "id": r["id"],
            "title": title,
            "type": (type_name or "custom").lower(),
            "time": time_str or "00:00",
            "days": days_list,
            "text": text,
            "template_category": tmpl_cat
        })
    return rows

def reload_schedule(force=False):
    global SCHEDULE_CACHE, SCHEDULE_CACHE_TS
    now_ts = int(time.time())
    if not force and (now_ts - SCHEDULE_CACHE_TS) < SCHEDULE_REFRESH_SEC:
        return
    SCHEDULE_CACHE = fetch_schedule_rows()
    SCHEDULE_CACHE_TS = now_ts

def build_message_from_entry(entry):
    if entry.get("type") == "weather":
        return None  
    if entry.get("text"):
        return entry["text"]

    cat = entry.get("template_category") or entry.get("type") or "day"

    if notion and NOTION_TEMPLATES_DB and cat:
        try:
            resp = notion.databases.query(
                database_id=NOTION_TEMPLATES_DB,
                filter={"property": "Category", "rich_text": {"equals": cat}},
                page_size=100
            )
            pool = []
            for pg in resp.get("results", []):
                pool.append(rt_to_str(pg["properties"]["Text"]["rich_text"]))
            if pool:
                return random.choice(pool)
        except Exception:
            pass

    defaults = {
        "morning": morning_messages,
        "evening": evening_messages,
        "pulse": heartbeat_messages,
        "day": day_messages
    }
    return random.choice(defaults.get(cat, day_messages))

def run_scheduled_from_notion(now_dt):
    if not SCHEDULE_CACHE:
        return
    hhmm = now_dt.strftime("%H:%M")
    for e in SCHEDULE_CACHE:
        if e.get("time") == hhmm and days_match_today(e.get("days", [])):
            kind = e.get("type")
            if kind == "weather":
                send_weather()
            else:
                msg = build_message_from_entry(e)
                if msg:
                    safe_send(msg)

# -------- Commands from Notion
def fetch_pending_commands():
    if not (notion and NOTION_COMMANDS_DB):
        return []
    try:
        resp = notion.databases.query(
            database_id=NOTION_COMMANDS_DB,
            filter={"property": "Status", "select": {"equals": "Pending"}},
            page_size=50
        )
        return resp.get("results", [])
    except Exception:
        return []

def update_command_status(page_id: str, result_text: str = "done"):
    if not notion:
        return
    try:
        notion.pages.update(
            page_id=page_id,
            properties={
                "Status": {"select": {"name": "Done"}},
                "Result": {"rich_text": [{"text": {"content": result_text}}]}
            }
        )
    except Exception:
        pass

def add_template(category: str, text: str):
    if not (notion and NOTION_TEMPLATES_DB):
        return "templates db not set"
    if not text.strip():
        return "no text"
    try:
        notion.pages.create(
            parent={"database_id": NOTION_TEMPLATES_DB},
            properties={
                "Title": {"title": [{"text": {"content": f"{category or 'template'}"}}]},
                "Category": {"rich_text": [{"text": {"content": category or ''}}]},
                "Text": {"rich_text": [{"text": {"content": text}}]}
            }
        )
        return "template added"
    except Exception as e:
        return f"error: {e}"

def add_schedule_row(type_name: str, time_str: str, days_str: str, template_cat: str, text: str):
    if not (notion and NOTION_SCHEDULE_DB):
        return "schedule db not set"
    if not time_str:
        return "time is required"
    ms_days = [{"name": d} for d in parse_days_str(days_str)]
    try:
        notion.pages.create(
            parent={"database_id": NOTION_SCHEDULE_DB},
            properties={
                "Title": {"title": [{"text": {"content": f"{type_name or 'custom'} {time_str}"}}]},
                "Enabled": {"checkbox": True},
                "Type": {"select": {"name": (type_name or "custom").lower()}},
                "Time": {"rich_text": [{"text": {"content": time_str}}]},
                "Days": {"multi_select": ms_days},
                "TemplateCategory": {"rich_text": [{"text": {"content": template_cat or ''}}]},
                "Text": {"rich_text": [{"text": {"content": text or ''}}]},
            }
        )
        reload_schedule(force=True)
        return "schedule added"
    except Exception as e:
        return f"error: {e}"

def list_schedule_rows():
    if not (notion and NOTION_SCHEDULE_DB):
        return "schedule db not set"
    rows = fetch_schedule_rows()
    if not rows:
        return "no active schedule"
    lines = []
    for r in rows:
        days = ",".join(r.get("days") or [])
        lines.append(f"- {r['time']} | {r['type']} | {days or 'daily'} | {r['title']}")
    return "\n".join(lines)

def exec_command(page: dict):
    global PAUSED, current_city
    props = page.get("properties", {})

    cmd = props.get("Command", {}).get("select", {}).get("name", "")
    text = rt_to_str(props.get("Text", {}).get("rich_text", []))
    city = rt_to_str(props.get("City", {}).get("rich_text", []))
    category = rt_to_str(props.get("Category", {}).get("rich_text", []))

    # для add_schedule:
    type_name = props.get("Type", {}).get("select", {}).get("name", "")
    time_str = rt_to_str(props.get("Time", {}).get("rich_text", []))
    days_str = rt_to_str(props.get("Days", {}).get("rich_text", []))
    template_cat = rt_to_str(props.get("TemplateCategory", {}).get("rich_text", []))

    result = "ok"

    try:
        if cmd == "send":
            if text.strip():
                safe_send(text.strip())
            else:
                result = "no text"
        elif cmd == "pause":
            PAUSED = True
            result = "paused"
        elif cmd == "resume":
            PAUSED = False
            result = "resumed"
        elif cmd == "set_city":
            if city.strip():
                current_city = city.strip()
                safe_send(f"Город для погоды обновлён: {current_city}")
                result = f"city={current_city}"
            else:
                result = "no city"
        elif cmd == "add_template":
            result = add_template(category, text)
        elif cmd == "add_schedule":
            result = add_schedule_row(type_name, time_str, days_str, template_cat, text)
        elif cmd == "list_schedule":
            summary = list_schedule_rows()
            safe_send("Текущее расписание из Notion:\n" + summary)
            result = "listed"
        elif cmd == "reload_schedule":
            reload_schedule(force=True)
            result = "reloaded"
        else:
            result = f"unknown command: {cmd or '(empty)'}"
    except Exception as e:
        result = f"error: {e}"

    update_command_status(page["id"], result_text=result)

def poll_notion_commands():
    for page in fetch_pending_commands():
        exec_command(page)

# -------- Flask keep-alive
app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

@app.route("/trigger_text")
def trigger_text():
    safe_send("Это тестовое сообщение от Коннора. Бот активен и рядом.")
    return "Тестовое сообщение отправлено!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()

if __name__ == "__main__":
    keep_alive()
    print("Бот Коннор запущен. Ждёт своего часа...")

    while True:
        now = datetime.now(seoul_tz)
        current_hour = now.hour
        current_minute = now.minute

        # авто-перечитывание расписания из Notion раз в SCHEDULE_REFRESH_SEC
        reload_schedule(force=False)

        # твои слоты (исходный код)
        if current_minute != last_minute:
            last_minute = current_minute

            if current_hour == 8 and current_minute == 0:
                send_morning()
            elif current_hour == 22 and current_minute == 0:
                send_evening()
            elif current_hour == 8 and current_minute == 30:
                send_weather()
            elif current_hour % 2 == 0 and current_minute == 15:
                send_day_message()

            # + Расписание из Notion (дополнительно)
            run_scheduled_from_notion(now)

        # команды из Notion
        if notion and NOTION_COMMANDS_DB:
            try:
                poll_notion_commands()
            except Exception:
                pass

        time.sleep(20)



