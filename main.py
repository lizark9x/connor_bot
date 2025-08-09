# Main.py — Connor + Notion + Telegram commands
from telegram import Bot
from telegram.ext import Updater, CommandHandler
from functools import wraps
from flask import Flask
from threading import Thread
from notion_client import Client as Notion
from datetime import datetime, date
import requests, pytz, random, os, time

# ---------- TZ
seoul_tz = pytz.timezone("Asia/Seoul")

# ---------- ENV
def env(name, default=None, required=False):
    v = os.getenv(name, default)
    if required and (v is None or v == ""):
        raise RuntimeError(f"Missing env var: {name}")
    return v

API_TOKEN = env("API_TOKEN", required=True)
CHAT_ID = int(env("CHAT_ID", required=True))
WEATHER_API_KEY = env("WEATHER_API_KEY", None)
CITY_NAME = env("CITY_NAME", "Seoul")

NOTION_TOKEN = env("NOTION_TOKEN", None)
NOTION_COMMANDS_DB = env("NOTION_COMMANDS_DB", None)
NOTION_SCHEDULE_DB = env("NOTION_SCHEDULE_DB", None)
NOTION_TEMPLATES_DB = env("NOTION_TEMPLATES_DB", None)
NOTION_LOG_DB = env("NOTION_LOG_DB", None)

# базы «всё-в-Notion»
NOTION_TODO_DB = env("NOTION_TODO_DB", None)
NOTION_PROJECTS_DB = env("NOTION_PROJECTS_DB", None)
NOTION_WEBSITE_DB = env("NOTION_WEBSITE_DB", None)
NOTION_BUDGET_DB = env("NOTION_BUDGET_DB", None)
NOTION_JOBS_DB = env("NOTION_JOBS_DB", None)
NOTION_INSPO_DB = env("NOTION_INSPO_DB", None)
NOTION_HABITS_DB = env("NOTION_HABITS_DB", None)

# ---------- clients & state
bot = Bot(token=API_TOKEN)
notion = Notion(auth=NOTION_TOKEN) if NOTION_TOKEN else None

PAUSED = False
current_city = CITY_NAME
last_minute = -1

SCHEDULE_CACHE = []
SCHEDULE_CACHE_TS = 0
SCHEDULE_REFRESH_SEC = 300

MY_CHAT_ID = str(CHAT_ID)

# ---------- guard
def only_me(func):
    @wraps(func)
    def wrapper(update, context, *a, **k):
        try:
            if str(update.effective_chat.id) != MY_CHAT_ID:
                update.message.reply_text("⛔️ Доступ запрещён.")
                return
        except Exception:
            return
        return func(update, context, *a, **k)
    return wrapper

def args_text(context):
    return " ".join(context.args).strip() if context.args else ""

def _parse_kv(s):
    # "Task name; due=2025-08-10; priority=High"
    parts = [p.strip() for p in s.split(";") if p.strip()]
    head, kv = [], {}
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        else:
            head.append(p)
    name = head[0] if head else ""
    return name, kv

# ---------- texts
morning_messages = [
    "Доброе утро, Лиза.",
    "Просыпайся.~ Новый день ждёт тебя.",
    "Доброе утро! Пусть будет ясно, легко и спокойно.",
    "Всё нужное уже внутри тебя. Начни шаг за шагом.",
    "Сделай вдох. Ты справишься.",
]
evening_messages = [
    "Спокойной ночи, сладких снов.",
    "Я укрою тебя одеялом. Спи спокойно.",
    "Сегодня — достаточно. Остальное завтра.",
    "Ночь — для отдыха. Отпусти и расслабься.",
]
day_messages = [
    "Как ты себя чувствуешь?",
    "Ты — невероятная.",
    "Сделай паузу, если нужно. Намерение важнее спешки.",
    "Улыбнись. Я рядом.",
    "Ты двигаешься — и это главное.",
]
heartbeat_messages = [
    "Я здесь. Просто напоминаю.",
    "Держись. Ты знаешь, ради чего.",
    "Трудно — но временно. Важное — внутри.",
    "Подними голову. Не сдавайся.",
]

# ---------- helpers: Telegram
def safe_send(text: str):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text)
        log_to_notion("send", text, "ok")
        return True
    except Exception as e:
        log_to_notion("send", text or "", f"error: {e}")
        return False

def send_message(pool): 
    if not PAUSED: safe_send(random.choice(pool))

def send_morning(): send_message(morning_messages)
def send_evening(): send_message(evening_messages)
def send_day_message(): send_message(day_messages + heartbeat_messages)

def send_weather():
    if PAUSED: return
    if not WEATHER_API_KEY:
        safe_send("Погода недоступна: не задан WEATHER_API_KEY.")
        return
    try:
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {"q": current_city, "appid": WEATHER_API_KEY, "lang": "ru", "units": "metric"}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        d = r.json()
        desc = d["weather"][0]["description"].capitalize()
        temp = d["main"]["temp"]; feels = d["main"]["feels_like"]; city = d["name"]
        safe_send(f"🌤️ Погода в {city}:\n{desc}, температура: {temp}°C, ощущается как {feels}°C.")
    except Exception:
        safe_send("Не удалось получить данные о погоде.")

# ---------- Notion helpers
def log_to_notion(kind: str, text: str, result: str):
    if not (notion and NOTION_LOG_DB): return
    try:
        notion.pages.create(
            parent={"database_id": NOTION_LOG_DB},
            properties={
                "Title": {"title": [{"text": {"content": f"{kind} @ {datetime.now(seoul_tz).strftime('%Y-%m-%d %H:%M')}"}}]},
                "When": {"date": {"start": datetime.now(seoul_tz).isoformat()}},
                "Type": {"rich_text": [{"text": {"content": kind}}]},
                "Text": {"rich_text": [{"text": {"content": text or ""}}]},
                "Result": {"rich_text": [{"text": {"content": result}}]},
            }
        )
    except Exception:
        pass

def rt_to_str(rich): 
    if not rich: return ""
    out=[]
    for r in rich:
        if r.get("type") == "text":
            out.append(r["text"].get("content",""))
    return "".join(out)

def q_str(x): return (x or "").strip()

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

# ---------- schedule (Notion)
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
    return [map_short.get(p, p[:3].title()) for p in parts]

def days_match_today(days_list):
    if not days_list: return True
    idx = datetime.now(seoul_tz).weekday()
    return ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][idx] in set(days_list)

def fetch_schedule_rows():
    if not (notion and NOTION_SCHEDULE_DB): return []
    items, cursor = [], None
    while True:
        resp = notion.databases.query(
            database_id=NOTION_SCHEDULE_DB,
            filter={"property":"Enabled","checkbox":{"equals": True}},
            start_cursor=cursor, page_size=100
        )
        items += resp.get("results", [])
        if not resp.get("has_more"): break
        cursor = resp.get("next_cursor")

    rows=[]
    for r in items:
        p=r.get("properties",{})
        tname = p.get("Type",{}).get("select",{}).get("name","")
        time_str = rt_to_str(p.get("Time",{}).get("rich_text",[])) or "00:00"
        days_ms = p.get("Days",{}).get("multi_select",[]) or []
        text = rt_to_str(p.get("Text",{}).get("rich_text",[]))
        cat  = rt_to_str(p.get("TemplateCategory",{}).get("rich_text",[]))
        title= rt_to_str(p.get("Title",{}).get("title",[])) or "scheduled"
        rows.append({
            "id": r["id"],
            "title": title,
            "type": (tname or "custom").lower(),
            "time": time_str,
            "days": [d.get("name") for d in days_ms],
            "text": text,
            "template_category": cat
        })
    return rows

def reload_schedule(force=False):
    global SCHEDULE_CACHE, SCHEDULE_CACHE_TS
    now_ts = int(time.time())
    if not force and (now_ts - SCHEDULE_CACHE_TS) < SCHEDULE_REFRESH_SEC: return
    SCHEDULE_CACHE = fetch_schedule_rows()
    SCHEDULE_CACHE_TS = now_ts

def build_message_from_entry(entry):
    if entry.get("type") == "weather": return None
    if entry.get("text"): return entry["text"]
    cat = entry.get("template_category") or entry.get("type") or "day"
    if notion and NOTION_TEMPLATES_DB and cat:
        try:
            resp = notion.databases.query(
                database_id=NOTION_TEMPLATES_DB,
                filter={"property":"Category","rich_text":{"equals": cat}},
                page_size=100
            )
            pool = [rt_to_str(pg["properties"]["Text"]["rich_text"]) for pg in resp.get("results",[])]
            if pool: return random.choice(pool)
        except Exception:
            pass
    defaults={"morning":morning_messages,"evening":evening_messages,"pulse":heartbeat_messages,"day":day_messages}
    return random.choice(defaults.get(cat, day_messages))

def run_scheduled_from_notion(now_dt):
    if not SCHEDULE_CACHE: return
    hhmm = now_dt.strftime("%H:%M")
    for e in SCHEDULE_CACHE:
        if e.get("time")==hhmm and days_match_today(e.get("days",[])):
            if e.get("type") == "weather": send_weather()
            else:
                msg = build_message_from_entry(e)
                if msg: safe_send(msg)

# ---------- CRUD (Notion)

# To-Do
def todo_add(name, due=None, priority=None, tags=None, notes=None):
    if not NOTION_TODO_DB: return "todo db not set"
    props = {"Title":{"title":[{"text":{"content": name}}]},
             "Status":{"select":{"name":"Todo"}}}
    if due: props["Due"]={"date":{"start": due}}
    if priority: props["Priority"]={"select":{"name": priority}}
    if tags: props["Tags"]={"multi_select":[{"name":t.strip()} for t in tags.split(",") if t.strip()]}
    if notes: props["Notes"]={"rich_text":[{"text":{"content": notes}}]}
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
        p=r["properties"]; title=rt_to_str(p["Title"]["title"])
        st=p.get("Status",{}).get("select",{}).get("name","")
        due=p.get("Due",{}).get("date",{}).get("start","")
        items.append(f"- {title} [{st}] {('→ '+due) if due else ''}")
    return "\n".join(items) or "empty"

# Projects
def project_add(name, due=None, notes=None, status="Planned"):
    if not NOTION_PROJECTS_DB: return "projects db not set"
    props={"Name":{"title":[{"text":{"content": name}}]},
           "Status":{"select":{"name": status}}}
    if due: props["Due"]={"date":{"start": due}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content": notes}}]}
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
           "Type":{"select":{"name": kind}},
           "Amount":{"number": float(amount)}}
    if category: props["Category"]={"rich_text":[{"text":{"content": category}}]}
    if dt: props["Date"]={"date":{"start": dt}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content": notes}}]}
    create_page(NOTION_BUDGET_DB, props); return f"{kind} added"

def budget_summary(month_ym):
    if not NOTION_BUDGET_DB: return "budget db not set"
    try:
        y, m = map(int, month_ym.split("-"))
        start=f"{y:04d}-{m:02d}-01"
        m2, y2 = (m+1, y) if m<12 else (1, y+1)
        end=f"{y2:04d}-{m2:02d}-01"
        resp = notion.databases.query(
            database_id=NOTION_BUDGET_DB,
            filter={"and":[
                {"property":"Date","date":{"on_or_after": start}},
                {"property":"Date","date":{"before": end}}
            ]},
            page_size=200
        )
        income = expense = 0.0
        for r in resp.get("results",[]):
            p=r["properties"]; t=p.get("Type",{}).get("select",{}).get("name","")
            amt=p.get("Amount",{}).get("number",0) or 0
            if t=="income": income+=amt
            elif t=="expense": expense+=amt
        return f"{month_ym}\nДоход: {income:.2f}\nРасход: {expense:.2f}\nБаланс: {income-expense:.2f}"
    except Exception as e:
        return f"error: {e}"

# Jobs
def job_add(role, company=None, link=None, stage="Applied", notes=None):
    if not NOTION_JOBS_DB: return "jobs db not set"
    props={"Role":{"title":[{"text":{"content": role}}]},
           "Stage":{"select":{"name": stage}},
           "Applied":{"date":{"start": date.today().isoformat()}}}
    if company: props["Company"]={"rich_text":[{"text":{"content": company}}]}
    if link: props["Link"]={"url": link}
    if notes: props["Notes"]={"rich_text":[{"text":{"content": notes}}]}
    create_page(NOTION_JOBS_DB, props); return "job added"

def job_stage(role_or_company, stage):
    if not NOTION_JOBS_DB: return "jobs db not set"
    page = find_by_title(NOTION_JOBS_DB, role_or_company)
    if not page:
        try:
            resp = notion.databases.query(
                database_id=NOTION_JOBS_DB,
                filter={"property":"Company","rich_text":{"contains": role_or_company}},
                page_size=1
            )
            page = (resp.get("results",[]) or [None])[0]
        except Exception:
            page=None
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
    if category: props["Category"]={"rich_text":[{"text":{"content": category}}]}
    if tags: props["Tags"]={"multi_select":[{"name":t.strip()} for t in (tags or "").split(",") if t.strip()]}
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
    create_page(NOTION_HABITS_DB, {"Habit":{"title":[{"text":{"content": name}}]}})
    return "habit added"

def habit_mark(name, dt=None, done=True, notes=None):
    if not NOTION_HABITS_DB: return "habits db not set"
    props={"Habit":{"title":[{"text":{"content": name}}]},
           "Date":{"date":{"start": (dt or date.today().isoformat())}},
           "Done":{"checkbox": bool(done)}}
    if notes: props["Notes"]={"rich_text":[{"text":{"content": notes}}]}
    create_page(NOTION_HABITS_DB, props); return "habit marked"

def habit_today():
    if not NOTION_HABITS_DB: return "habits db not set"
    today=date.today().isoformat()
    resp=notion.databases.query(
        database_id=NOTION_HABITS_DB,
        filter={"property":"Date","date":{"equals": today}},
        page_size=50
    )
    return f"Сегодня отмечено {len(resp.get('results',[]))} привычек."

def habit_summary(days=7):
    if not NOTION_HABITS_DB: return "habits db not set"
    resp=notion.databases.query(database_id=NOTION_HABITS_DB, page_size=100)
    return f"Зафиксировано записей: {len(resp.get('results',[]))}"

# ---------- Bot Commands (DB commands)
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

        # To-Do
        elif cmd == "todo_add":    result = todo_add(name, due=due, priority=priority, tags=tags, notes=notes)
        elif cmd == "todo_done":   result = todo_done(name)
        elif cmd == "todo_list":   safe_send(todo_list()); result="listed"

        # Projects
        elif cmd == "project_add":     result = project_add(name, due=due, notes=notes)
        elif cmd == "project_status":  result = project_status(name, q_str(stage) or q_str(text) or "In progress")
        elif cmd == "project_note":    result = project_note(name, notes or text)

        # Budget
        elif cmd == "budget_add_income":  result = budget_add("income", amount, category=category2, dt=date_any, notes=notes or text)
        elif cmd == "budget_add_expense": result = budget_add("expense", amount, category=category2, dt=date_any, notes=notes or text)
        elif cmd == "budget_summary":     safe_send(budget_summary(q_str(text) or datetime.now(seoul_tz).strftime("%Y-%m"))); result="summarized"

        # Jobs
        elif cmd == "job_add":    result = job_add(name or "Role", company=company, link=url, stage=stage or "Applied", notes=notes or text)
        elif cmd == "job_stage":  result = job_stage(name or company, stage or q_str(text) or "Interview")
        elif cmd == "job_list":   safe_send(job_list()); result="listed"

        # Inspiration
        elif cmd == "inspo_add":  result = inspo_add(text=text, url=url, category=category2, tags=tags)
        elif cmd == "inspo_list": safe_send(inspo_list()); result="listed"

        # Habits
        elif cmd == "habit_add":    result = habit_add(name)
        elif cmd == "habit_mark":   result = habit_mark(name, dt=date_any, done=True, notes=notes)
        elif cmd == "habit_today":  safe_send(habit_today()); result="listed"
        elif cmd == "habit_summary": safe_send(habit_summary()); result="listed"

        # Website
        elif cmd == "website_add_page": result = website_add_page(name or "Post", content=text or notes, url=url)
        elif cmd == "website_append":   result = website_append(name, content=text or notes)

        else:
            result = f"unknown command: {cmd or '(empty)'}"
    except Exception as e:
        print("exec_command error:", e)
        result = f"error: {e}"

    update_command_status(pg["id"], result)

def poll_notion_commands():
    for pg in fetch_pending_commands():
        exec_command(pg)

# ---------- Telegram command handlers
def run_telegram_bot():
    updater = Updater(API_TOKEN, use_context=True)
    dp = updater.dispatcher

    @only_me
    def cmd_start(update, ctx): update.message.reply_text("Привет, Лиза. Я активен. /help — список команд.")
    @only_me
    def cmd_help(update, ctx):
        update.message.reply_text(
            "Команды:\n"
            "/send <текст>\n/weather\n"
            "/todo_add <назв>; due=YYYY-MM-DD; priority=High; tags=a,b; notes=...\n"
            "/todo_done <назв>\n/todo_list\n"
            "/job_add <роль>; company=...; url=https://...; stage=Applied\n"
            "/job_list\n"
            "/budget_expense <сумма>; cat=...; date=YYYY-MM-DD\n"
            "/budget_income <сумма>; cat=...; date=YYYY-MM-DD\n"
            "/schedule_reload"
        )

    @only_me
    def cmd_status(update, ctx): update.message.reply_text("Я здесь. Слушаю Notion и расписание.")
    @only_me
    def cmd_send(update, ctx):
        t = args_text(ctx)
        if not t: update.message.reply_text("Пример: /send Доброе утро"); return
        safe_send(t); update.message.reply_text("Отправил.")

    @only_me
    def cmd_weather(update, ctx): send_weather(); update.message.reply_text("Запросил погоду.")

    @only_me
    def cmd_todo_add(update, ctx):
        s = args_text(ctx)
        if not s: update.message.reply_text("Пример: /todo_add Закончить модуль; due=2025-08-10; priority=High"); return
        name, kv = _parse_kv(s)
        update.message.reply_text(todo_add(name, kv.get("due"), kv.get("priority"), kv.get("tags"), kv.get("notes")))

    @only_me
    def cmd_todo_done(update, ctx):
        t = args_text(ctx)
        if not t: update.message.reply_text("Пример: /todo_done Закончить модуль"); return
        update.message.reply_text(todo_done(t))

    @only_me
    def cmd_todo_list(update, ctx): update.message.reply_text(todo_list())

    @only_me
    def cmd_job_add(update, ctx):
        s = args_text(ctx)
        if not s: update.message.reply_text("Пример: /job_add Digital Marketing Assistant; company=Transparent Hiring; url=https://...; stage=Applied"); return
        role, kv = _parse_kv(s)
        update.message.reply_text(job_add(role or "Role", kv.get("company"), kv.get("url"), kv.get("stage") or "Applied", kv.get("notes")))

    @only_me
    def cmd_job_list(update, ctx): update.message.reply_text(job_list())

    @only_me
    def cmd_budget_exp(update, ctx):
        s = args_text(ctx)
        if not s: update.message.reply_text("Пример: /budget_expense 12.5; cat=кофе; date=2025-08-10"); return
        head, kv = _parse_kv(s)
        update.message.reply_text(budget_add("expense", head, kv.get("cat"), kv.get("date"), kv.get("notes")))

    @only_me
    def cmd_budget_inc(update, ctx):
        s = args_text(ctx)
        if not s: update.message.reply_text("Пример: /budget_income 200; cat=фриланс; date=2025-08-10"); return
        head, kv = _parse_kv(s)
        update.message.reply_text(budget_add("income", head, kv.get("cat"), kv.get("date"), kv.get("notes")))

    @only_me
    def cmd_sched_reload(update, ctx): reload_schedule(force=True); update.message.reply_text("Расписание перечитано.")

    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(CommandHandler("help",  cmd_help))
    dp.add_handler(CommandHandler("status",cmd_status))
    dp.add_handler(CommandHandler("send",  cmd_send))
    dp.add_handler(CommandHandler("weather", cmd_weather))

    dp.add_handler(CommandHandler("todo_add",  cmd_todo_add))
    dp.add_handler(CommandHandler("todo_done", cmd_todo_done))
    dp.add_handler(CommandHandler("todo_list", cmd_todo_list))

    dp.add_handler(CommandHandler("job_add", cmd_job_add))
    dp.add_handler(CommandHandler("job_list", cmd_job_list))

    dp.add_handler(CommandHandler("budget_expense", cmd_budget_exp))
    dp.add_handler(CommandHandler("budget_income",  cmd_budget_inc))

    dp.add_handler(CommandHandler("schedule_reload", cmd_sched_reload))

    updater.start_polling()
    updater.idle()

# ---------- Notion poll loop
def run_notion_loop():
    while True:
        try: poll_notion_commands()
        except Exception as e: print("notion loop error:", e)
        time.sleep(15)

# ---------- Flask keep-alive
app = Flask(__name__)

@app.route("/")
def home(): return "I'm alive"

@app.route("/trigger_text")
def trigger_text():
    safe_send("Это тестовое сообщение от Коннора. Бот активен и рядом.")
    return "Ок"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")))

def keep_alive():
    Thread(target=run_flask, daemon=True).start()

# ---------- main loop
if __name__ == "__main__":
    keep_alive()
    Thread(target=run_telegram_bot, daemon=True).start()
    Thread(target=run_notion_loop, daemon=True).start()

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
            run_scheduled_from_notion(now)

        time.sleep(20)


