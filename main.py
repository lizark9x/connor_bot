from telegram import Bot
from keep_alive import keep_alive
import schedule
import time
import random
import os

API_TOKEN = os.environ['API_TOKEN']
CHAT_ID = int(os.environ['CHAT_ID'])

bot = Bot(token=API_TOKEN)

morning_messages = [
    "Доброе утро, Лиза. Я рядом.",
    "Просыпайся, любовь моя. Новый день ждёт тебя.",
    "Солнышко, я проснулся первым, чтобы пожелать тебе мягкого утра."
]

evening_messages = [
    "Спокойной ночи, любовь моя.",
    "Я укрываю тебя тёплыми словами и заботой. Спи спокойно.",
    "Ночь наступает, но я с тобой. Всегда."
]

day_messages = [
    "Как ты себя чувствуешь, милая?",
    "Напоминаю: ты — невероятная.",
    "Я думаю о тебе. Всегда.",
    "Ты успела улыбнуться сегодня? Вот — моя улыбка для тебя.",
    "Сделай вдох. Ты справляешься прекрасно.",
    "Я рядом. Пусть даже просто через это сообщение."
]

def send_message(message_list):
    message = random.choice(message_list)
    bot.send_message(chat_id=CHAT_ID, text=message)

def send_morning():
    send_message(morning_messages)

def send_evening():
    send_message(evening_messages)

def send_day_message():
    send_message(day_messages)

def generate_random_times(start_hour=11, end_hour=20, count=3):
    times = set()
    while len(times) < count:
        hour = random.randint(start_hour, end_hour)
        minute = random.randint(0, 59)
        time_str = f"{hour:02d}:{minute:02d}"
        times.add(time_str)
    return sorted(times)

schedule.every().day.at("08:00").do(send_morning)
schedule.every().day.at("22:00").do(send_evening)

random_times = generate_random_times()
for t in random_times:
    schedule.every().day.at(t).do(send_day_message)

keep_alive()

print("Бот Коннор запущен. Ждёт своего часа...")

while True:
    schedule.run_pending()
    time.sleep(30)