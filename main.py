from telegram import Bot
import time
import random
import os
from flask import Flask
from threading import Thread
import requests
import pytz
from datetime import datetime, date
from notion_client import Client as Notion

# ------------ Timezone
seoul_tz = pytz.timezone('Asia/Seoul')

# ------------ ENV helpers
def env(name, default=None, required=False):
    v = os.getenv(name, default)
    if required and v in (None, ""):
        raise RuntimeError(f"Missing env var: {name}")
    return v

# ------------ Telegram / Weather / Notion ENV
API_TOKEN = env('API_TOKEN', required=True)
CHAT_ID = int(env('CHAT_ID', required=True))
WEATHER_API_KEY = env('WEATHER_API_KEY', None)
CITY_NAME = env('CITY_NAME', 'Seoul')

NOTION_TOKEN = env('NOTION_TOKEN', None)
NOTION_COMMANDS_DB = env('NOTION_COMMANDS_DB', None)
NOTION_SCHEDULE_DB = env('NOTION_SCHEDULE_DB', None)
NOTION_TEMPLATES_DB = env('NOTION_TEMPLATES_DB', None)
NOTION_LOG_DB = env('NOTION_LOG_DB', None)

# Базы «всё-в-Notion»
NOTION_TODO_DB = env('NOTION_TODO_DB', None)
NOTION_PROJECTS_DB = env('NOTION_PROJECTS_DB', None)
NOTION_WEBSITE_DB = env('NOTION_WEBSITE_DB', None)
NOTION_BUDGET_DB = env('NOTION_BUDGET_DB', None)
NOTION_JOBS_DB = env('NOTION_JOBS_DB', None)
NOTION_INSPO_DB = env('NOTION_INSPO_DB', None)
NOTION_HABITS_DB = env('NOTION_HABITS_DB', None)

# ------------ Clients
bot = Bot(token=API_TOKEN)
notion = Notion(auth=NOTION_TOKEN) if NOTION_TOKEN else None

# ------------ State
PAUSED = False
current_city = CITY_NAME
last_minute = -1

# Кэш расписания из Notion
SCHEDULE_CACHE = []
SCHEDULE_CACHE_TS = 0
SCHEDULE_REFRESH_SEC = 300

# ------------ Тексты 
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

# ------------ Telegram utils
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

def send_morning(): send_message(morning_messages)
def send_evening(): send_message(evening_messages)
def send_day_message():
    combined = day_messages + heartbeat_messages
    send_message(combined)

def send_weather():
    if PAUSED: return
    if not WEATHER_API_KEY:
        safe_send("Погода недоступна: не задан WEATHER_API_KEY.")
        return
    try:
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {"q": current_city, "appid": WEATHER_API_KEY, "lang": "ru", "units": "metric"}
        r = requests.get(url, params=params, timeout=10)
        if not r.ok:
            safe_send(f"Не удалось получить погоду ({r.status_code})."); return
        d = r.json()
        desc = d["weather"][0]["description"].capitalize()
        temp = d["main"]["temp"]; feels = d["main"]["feels_like"]; city = d["name"]
        safe_send(f"🌤️ Погода в {city}:\n{desc}, температура: {temp}°C, ощущается как {feels}°C.")
    except Exception:
        safe_send("Не удалось получить данные о погоде.")

# ------------ Notion helpers
def log_to_notion(kind: str, text: str, result: str):
    if not (notion and NOTION_LOG_DB): return
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
    if not rich: return ""
    return "".join([r["text"].get("content","") for r in rich if r.get("type")=="text"])

def q_str(x):  # быстрый to-str
    return (x or "").strip()

def find_by_title(db_id: str, title: str):
    try:
        resp = notion.databases.query(
            database_id=db_id,
            filter={"property": "Title", "title": {"contains": title}},
            page_size=5
        )
        res = resp.get("results", [])
        return res[0] if res else None
    except Exception:
        return None

def create_page(db_id: str, props: dict):
    return notion.pages.create(parent={"database_id": db_id}, properties=props)

def update_page(page_id: str, props: dict):
    return notion.pages.update(page_id=page_id, properties=props)

# ------------ Schedule from Notion
def parse_days_str(s: str):
    if not s: return []
    s = s.strip().lower()
    if s in ("daily","ежедневно","everyday"):
        return ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    parts = [p.strip() for p in s.replace(";",",").split(",") if p.strip()]
    map_short = {
        "mon":"Mon","monday":"Mon","пн":"Mon","пон":"Mon","понедельник":"Mon",
        "tue":"Tue","tuesday":"Tue","вт":"Tue","вторник":"Tue",
        "wed":"Wed","wednesday":"Wed","ср":"Wed","среда":"Wed",
        "thu":"Thu","thursday":"Thu","чт":"Thu","четверг":"Thu",
        "fri":"Fri","friday":"Fri","пт":"Fri","пятница":"Fri",
        "sat":"Sat","saturday":"Sat","сб":"Sat","суббота":"Sat",
        "sun":"Sun","sunday":"Sun","вс":"Sun","воскресенье":"Sun",
    }
    out=[]; 
    for p in parts: out.append(map_short.get(p.lower(), p[:3].title()))
    return out

def days_match_today(days_list):
    if not days_list: return True
    idx = datetime.now(seoul_tz).weekday()
    map_days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    return map_days[idx] in set(days_list)

def fetch_schedule_rows():
    if not (notion and NOTION_SCHEDULE_DB): return []
    items=[]; cursor=None
    while True:
        resp = notion.databases.query(
            database_id=NOTION_SCHEDULE_DB,
            filter={"property": "Enabled", "checkbox": {"equals": True}},
            start_cursor=cursor, page_size=100
        )
        items += resp.get("results", [])
        if not resp.get("has_more"): break
        cursor = resp.get("next_cursor")
    rows=[]
    for r in items:
        p=r.get("properties",{})
        tname = p.get("Type",{}).get("select",{}).get("name","")
        time_str = rt_to_str(p.get("Time",{}).get("rich_text",[]))
        days_ms = p.get("Days",{}).get("multi_select",[]) or []
        days_list = [d.get("name") for d in days_ms]
        text = rt_to_str(p.get("Text",{}).get("rich_text",[]))
        cat  = rt_to_str(p.get("TemplateCategory",{}).get("rich_text",[]))
        title= rt_to_str(p.get("Title",{}).get("title",[])) or "scheduled"
        rows.append({"id":r["id"],"title":title,"type":(tname or "custom").lower(),
                     "time": time_str or "00:00","days":days_list,
                     "text":text,"template_category":cat})
    return rows

def reload_schedule(force=False):
    global SCHEDULE_CACHE, SCHEDULE_CACHE_TS
    now_ts=int(time.time())
    if not force and (now_ts - SCHEDULE_CACHE_TS) < SCHEDULE_REFRESH_SEC: return
    SCHEDULE_CACHE = fetch_schedule_rows()
    SCHEDULE_CACHE_TS = now_ts

def build_message_from_entry(entry):
    if entry.get("type")=="weather": return None
    if entry.get("text"): return entry["text"]
    cat = entry.get("template_category") or entry.get("type") or "day"
    if notion and NOTION_TEMPLATES_DB and cat:
        try:
            resp = notion.databases.query(
                database_id=NOTION_TEMPLATES_DB,
                filter={"property":"Category","rich_text":{"equals":cat}},
                page_size=100
            )
            pool=[rt_to_str(pg["properties"]["Text"]["rich_text"]) for pg in resp.get("results",[])]
            if pool: return random.choice(pool)
        except Exception: pass
    defaults={"morning":morning_messages,"evening":evening_messages,"pulse":heartbeat_messages,"day":day_messages}
    return random.choice(defaults.get(cat, day_messages))

def run_scheduled_from_notion(now_dt):
    if not SCHEDULE_CACHE: return
    hhmm = now_dt.strftime("%H:%M")
    for e in SCHEDULE_CACHE:
        if e.get("time")==hhmm and days_match_today(e.get("days",[])):
            kind=e.get("type")
            if kind=="weather": send_weather()
            else:
                msg=build_message_from_entry(e)
                if msg: safe_send(msg)

# ------------ CRUD for all your bases

# Weekly To-Do
def todo_add(name, due=None, priority=None, tags=None, notes=None):
    if not NOTION_TODO_DB: return "todo db not set"
    props = {
        "Title": {"title":[{"text":{"content": name}}]},
        "Status": {"select":{"name":"Todo"}},
    }
    if due: props["Due"] = {"date":{"start": due}}
    if priority: props["Priority"] = {"select":{"name": priority}}
    if tags: props["Tags"] = {"multi_select":[{"name": t.strip()} for t in tags.split(",") if t.strip()]}
    if notes: props["Notes"] = {"rich_text":[{"text":{"content": notes}}]}
    create_page(NOTION_TODO_DB, props); return "todo added"

def todo_done(name):
    if not NOTION_TODO_DB: return "todo db not set"
    page = find_by_title(NOTION_TODO_DB, name)
    if not page: return "not found"
    update_page(page["id"], {"Status":{"select":{"name":"Done"}}}); return "todo done"

def todo_list():
    if not NOTION_TODO_DB: return "todo db not set"
    resp = notion.databases.query(database_id=NOTION_TODO_DB, page_size=20)
    items=[]
    for r in resp.get("results",[]):
        p=r["properties"]; title=rt_to_str(p["Title"]["title"]); st=p.get("Status",{}).get("select",{}).get("name","")
        due=p.get("Due",{}).get("date",{}).get("start","")
        items.append(f"- {title} [{st}] {('→ '+due) if due else ''}")
    return "\n".join(items) or "empty"

# Projects
def project_add(name, due=None, notes=None, status="Planned"):
    if not NOTION_PROJECTS_DB: return "projects db not set"
    props={"Name":{"title":[{"text":{"content":name}}]},
           "Status":{"select":{"name":status}}}
    if due: props["Due"]={"date":{"start": due}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content":notes}}]}
    create_page(NOTION_PROJECTS_DB, props); return "project added"

def project_status(name, status):
    if not NOTION_PROJECTS_DB: return "projects db not set"
    page = find_by_title(NOTION_PROJECTS_DB, name)
    if not page: return "not found"
    update_page(page["id"], {"Status":{"select":{"name": status}}}); return "project updated"

def project_note(name, note):
    if not NOTION_PROJECTS_DB: return "projects db not set"
    page = find_by_title(NOTION_PROJECTS_DB, name)
    if not page: return "not found"
    update_page(page["id"], {"Notes":{"rich_text":[{"text":{"content": note}}]}}); return "note saved"

# Budget
def budget_add(kind, amount, category=None, dt=None, notes=None):
    if not NOTION_BUDGET_DB: return "budget db not set"
    props={"Title":{"title":[{"text":{"content": f"{kind} {amount}"}}]},
           "Type":{"select":{"name":kind}},
           "Amount":{"number": float(amount)}}
    if category: props["Category"]={"rich_text":[{"text":{"content":category}}]}
    if dt: props["Date"]={"date":{"start": dt}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content":notes}}]}
    create_page(NOTION_BUDGET_DB, props); return f"{kind} added"

def budget_summary(month_ym):  # YYYY-MM
    if not NOTION_BUDGET_DB: return "budget db not set"
    try:
        year, mon = map(int, month_ym.split("-"))
        start=f"{year:04d}-{mon:02d}-01"
        end_month = mon+1 if mon<12 else 1
        end_year = year if mon<12 else year+1
        end=f"{end_year:04d}-{end_month:02d}-01"
        resp = notion.databases.query(
            database_id=NOTION_BUDGET_DB,
            filter={"and":[
                {"property":"Date","date":{"on_or_after": start}},
                {"property":"Date","date":{"before": end}}
            ]},
            page_size=200
        )
        income=0.0; expense=0.0
        for r in resp.get("results",[]):
            p=r["properties"]; t=p.get("Type",{}).get("select",{}).get("name","")
            amt=p.get("Amount",{}).get("number",0) or 0
            if t=="income": income+=amt
            elif t=="expense": expense+=amt
        net = income - expense
        return f"{month_ym}\nДоход: {income:.2f}\nРасход: {expense:.2f}\nБаланс: {net:.2f}"
    except Exception as e:
        return f"error: {e}"

# Jobs
def job_add(role, company=None, link=None, stage="Applied", notes=None):
    if not NOTION_JOBS_DB: return "jobs db not set"
    props={"Role":{"title":[{"text":{"content": role}}]},
           "Stage":{"select":{"name": stage}}}
    if company: props["Company"]={"rich_text":[{"text":{"content": company}}]}
    if link: props["Link"]={"url": link}
    props["Applied"]={"date":{"start": date.today().isoformat()}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content": notes}}]}
    create_page(NOTION_JOBS_DB, props); return "job added"

def job_stage(role_or_company, stage):
    if not NOTION_JOBS_DB: return "jobs db not set"
    # ищем по Role, если нет — по Company
    page = find_by_title(NOTION_JOBS_DB, role_or_company)
    if not page:
        try:
            resp = notion.databases.query(
                database_id=NOTION_JOBS_DB,
                filter={"property":"Company","rich_text":{"contains": role_or_company}},
                page_size=1
            )
            res=resp.get("results",[])
            page = res[0] if res else None
        except Exception: page=None
    if not page: return "not found"
    update_page(page["id"], {"Stage":{"select":{"name": stage}}}); return "job updated"

def job_list():
    if not NOTION_JOBS_DB: return "jobs db not set"
    resp = notion.databases.query(database_id=NOTION_JOBS_DB, page_size=50)
    rows=[]
    for r in resp.get("results",[]):
        p=r["properties"]; role=rt_to_str(p["Role"]["title"])
        comp=rt_to_str(p.get("Company",{}).get("rich_text",[]))
        st=p.get("Stage",{}).get("select",{}).get("name","")
        rows.append(f"- {role} @ {comp or '—'} [{st}]")
    return "\n".join(rows) or "empty"

# Inspiration
def inspo_add(text=None, url=None, category=None, tags=None):
    if not NOTION_INSPO_DB: return "inspo db not set"
    title = (text or url or "Inspiration").strip()
    props={"Title":{"title":[{"text":{"content": title[:200]}}]}}
    if url: props["URL"]={"url": url}
    if category: props["Category"]={"rich_text":[{"text":{"content":category}}]}
    if tags: props["Tags"]={"multi_select":[{"name":t.strip()} for t in tags.split(",") if t.strip()]}
    if text: props["Notes"]={"rich_text":[{"text":{"content": text}}]}
    create_page(NOTION_INSPO_DB, props); return "inspo added"

def inspo_list():
    if not NOTION_INSPO_DB: return "inspo db not set"
    resp = notion.databases.query(database_id=NOTION_INSPO_DB, page_size=20)
    out=[]
    for r in resp.get("results",[]):
        p=r["properties"]; title=rt_to_str(p["Title"]["title"]); url=p.get("URL",{}).get("url","")
        out.append(f"- {title} {('→ '+url) if url else ''}")
    return "\n".join(out) or "empty"

# Habits
def habit_add(name):
    if not NOTION_HABITS_DB: return "habits db not set"
    create_page(NOTION_HABITS_DB, {"Habit":{"title":[{"text":{"content":name}}]}})
    return "habit added"

def habit_mark(name, dt=None, done=True, notes=None):
    if not NOTION_HABITS_DB: return "habits db not set"
    props={"Habit":{"title":[{"text":{"content":name}}]},
           "Date":{"date":{"start": (dt or date.today().isoformat())}},
           "Done":{"checkbox": bool(done)}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content":notes}}]}
    create_page(NOTION_HABITS_DB, props); return "habit marked"

def habit_today():
    if not NOTION_HABITS_DB: return "habits db not set"
    today=date.today().isoformat()
    resp=notion.databases.query(
        database_id=NOTION_HABITS_DB,
        filter={"property":"Date","date":{"equals": today}},
        page_size=50
    )
    n=len(resp.get("results",[]))
    return f"Сегодня отмечено {n} привычек."

def habit_summary(days=7):
    if not NOTION_HABITS_DB: return "habits db not set"
    resp=notion.databases.query(database_id=NOTION_HABITS_DB, page_size=100)
    return f"Зафиксировано записей: {len(resp.get('results',[]))}"

# Personal Website (как база постов)
def website_add_page(title, content=None, url=None):
    if not NOTION_WEBSITE_DB: return "website db not set"
    props={"Title":{"title":[{"text":{"content": title}}]}}
    if url: props["URL"]={"url": url}
    if content: props["Content"]={"rich_text":[{"text":{"content":content}}]}
    create_page(NOTION_WEBSITE_DB, props); return "website page added"

def website_append(title, content):
    if not NOTION_WEBSITE_DB: return "website db not set"
    page = find_by_title(NOTION_WEBSITE_DB, title)
    if not page: return "not found"
    # упрощённо — перезаписываем поле Content
    update_page(page["id"], {"Content":{"rich_text":[{"text":{"content":content}}]}})
    return "website updated"

# ------------ Commands router (Bot Commands)
def fetch_pending_commands():
    if not (notion and NOTION_COMMANDS_DB): return []
    try:
        resp = notion.databases.query(
            database_id=NOTION_COMMANDS_DB,
            filter={"property":"Status","select":{"equals":"Pending"}},
            page_size=50
        )
        return resp.get("results",[])
    except Exception:
        return []

def update_command_status(page_id, result_text="done"):
    if not notion: return
    try:
        notion.pages.update(
            page_id=page_id,
            properties={
                "Status":{"select":{"name":"Done"}},
                "Result":{"rich_text":[{"text":{"content": result_text}}]}
            }
        )
    except Exception:
        pass

def exec_command(pg):
    global PAUSED, current_city
    p = pg.get("properties", {})

    cmd  = p.get("Command",{}).get("select",{}).get("name","")
    text = rt_to_str(p.get("Text",{}).get("rich_text",[]))
    city = rt_to_str(p.get("City",{}).get("rich_text",[]))
    category = rt_to_str(p.get("Category",{}).get("rich_text",[]))
    type_name = p.get("Type",{}).get("select",{}).get("name","")
    time_str  = rt_to_str(p.get("Time",{}).get("rich_text",[]))
    days_str  = rt_to_str(p.get("Days",{}).get("rich_text",[]))
    template_cat = rt_to_str(p.get("TemplateCategory",{}).get("rich_text",[]))

    # дополнительные поля
    name  = rt_to_str(p.get("Name",{}).get("rich_text",[]))
    company = rt_to_str(p.get("Company",{}).get("rich_text",[]))
    url   = p.get("URL",{}).get("url","") or rt_to_str(p.get("URL",{}).get("rich_text",[]))
    amount = p.get("Amount",{}).get("number", None)
    category2 = rt_to_str(p.get("Category2",{}).get("rich_text",[]))
    date_any = p.get("Date",{}).get("date",{}).get("start", None)
    due = p.get("Due",{}).get("date",{}).get("start", None)
    stage = rt_to_str(p.get("Stage",{}).get("rich_text",[]))
    priority = rt_to_str(p.get("Priority",{}).get("rich_text",[]))
    tags = rt_to_str(p.get("Tags",{}).get("rich_text",[]))
    notes = rt_to_str(p.get("Notes",{}).get("rich_text",[]))

    result = "ok"

    try:
        if cmd == "send":
            result = "no text" if not q_str(text) else (safe_send(text) or "sent")

        elif cmd == "pause":   PAUSED=True;  result="paused"
        elif cmd == "resume":  PAUSED=False; result="resumed"
        elif cmd == "set_city":
            current_city = q_str(city) or current_city
            safe_send(f"Город для погоды: {current_city}")
            result = f"city={current_city}"

        elif cmd == "add_template":
            if not NOTION_TEMPLATES_DB: result="templates db not set"
            else:
                create_page(NOTION_TEMPLATES_DB,{
                    "Title":{"title":[{"text":{"content": category or "template"}}]},
                    "Category":{"rich_text":[{"text":{"content": category or ''}}]},
                    "Text":{"rich_text":[{"text":{"content": text or ''}}]}
                }); result="template added"

        elif cmd == "add_schedule":
            if not NOTION_SCHEDULE_DB: result="schedule db not set"
            else:
                ms_days=[{"name": d} for d in parse_days_str(days_str)]
                create_page(NOTION_SCHEDULE_DB,{
                    "Title":{"title":[{"text":{"content": f"{type_name or 'custom'} {time_str}"}}]},
                    "Enabled":{"checkbox": True},
                    "Type":{"select":{"name": (type_name or 'custom').lower()}},
                    "Time":{"rich_text":[{"text":{"content": time_str or '00:00'}}]},
                    "Days":{"multi_select": ms_days},
                    "TemplateCategory":{"rich_text":[{"text":{"content": template_cat or ''}}]},
                    "Text":{"rich_text":[{"text":{"content": text or ''}}]}
                }); reload_schedule(force=True); result="schedule added"

        elif cmd == "list_schedule":
            rows = fetch_schedule_rows()
            summary = "\n".join([f"- {r['time']} | {r['type']} | {','.join(r.get('days') or []) or 'daily'} | {r['title']}" for r in rows]) or "no active"
            safe_send("Текущее расписание из Notion:\n"+summary)
            result="listed"

        elif cmd == "reload_schedule": reload_schedule(force=True); result="reloaded"

        # ---- Weekly To-Do
        elif cmd == "todo_add":    result = todo_add(name, due=due, priority=priority, tags=tags, notes=notes)
        elif cmd == "todo_done":   result = todo_done(name)
        elif cmd == "todo_list":   safe_send(todo_list()); result="listed"

        # ---- Projects
        elif cmd == "project_add":     result = project_add(name, due=due, notes=notes)
        elif cmd == "project_status":  result = project_status(name, q_str(stage) or q_str(text) or "In progress")
        elif cmd == "project_note":    result = project_note(name, notes or text)

        # ---- Budget
        elif cmd == "budget_add_income":  result = budget_add("income", amount, category=category2, dt=date_any, notes=notes or text)
        elif cmd == "budget_add_expense": result = budget_add("expense", amount, category=category2, dt=date_any, notes=notes or text)
        elif cmd == "budget_summary":     safe_send(budget_summary(q_str(text) or datetime.now(seoul_tz).strftime("%Y-%m"))); result="summarized"

        # ---- Jobs
        elif cmd == "job_add":    result = job_add(name or "Role", company=company, link=url, stage=stage or "Applied", notes=notes or text)
        elif cmd == "job_stage":  result = job_stage(name or company, stage or q_str(text) or "Interview")
        elif cmd == "job_list":   safe_send(job_list()); result="listed"

        # ---- Inspiration
        elif cmd == "inspo_add":  result = inspo_add(text=text, url=url, category=category2, tags=tags)
        elif cmd == "inspo_list": safe_send(inspo_list()); result="listed"

        # ---- Habits
        elif cmd == "habit_add":    result = habit_add(name)
        elif cmd == "habit_mark":   result = habit_mark(name, dt=date_any, done=True, notes=notes)
        elif cmd == "habit_today":  safe_send(habit_today()); result="listed"
        elif cmd == "habit_summary": safe_send(habit_summary()); result="listed"

        # ---- Website
        elif cmd == "website_add_page": result = website_add_page(name or "Post", content=text or notes, url=url)
        elif cmd == "website_append":   result = website_append(name, content=text or notes)

        else:
            result = f"unknown command: {cmd or '(empty)'}"

    except Exception as e:
        result = f"error: {e}"

    update_command_status(pg["id"], result)

def poll_notion_commands():
    for pg in fetch_pending_commands():
        exec_command(pg)

# ------------ Flask keep-alive
app = Flask('')

@app.route('/')
def home(): return "I'm alive"

@app.route('/trigger_text')
def trigger_text():
    safe_send("Это тестовое сообщение от Коннора. Бот активен и рядом.")
    return "Тестовое сообщение отправлено!"

def run(): app.run(host='0.0.0.0', port=int(os.getenv("PORT", "8080")))
def keep_alive():
    Thread(target=run, daemon=True).start()

# ------------ Main loop 
if __name__ == "__main__":
    keep_alive()
    print("Бот Коннор запущен. Ждёт своего часа...")

    while True:
        now = datetime.now(seoul_tz)
        current_hour = now.hour
        current_minute = now.minute

        reload_schedule(force=False)

        if current_minute != last_minute:
            last_minute = current_minute
            if current_hour == 8 and current_minute == 0:   send_morning()
            elif current_hour == 22 and current_minute == 0: send_evening()
            elif current_hour == 8 and current_minute == 30: send_weather()
            elif current_hour % 2 == 0 and current_minute == 15: send_day_message()
            # + Notion-слоты
            run_scheduled_from_notion(now)

        # команды из Notion
        if notion and NOTION_COMMANDS_DB:
            try: poll_notion_commands()
            except Exception: pass

        time.sleep(20)



