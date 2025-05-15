from telegram import Bot
import time
import random
import os
from flask import Flask
from threading import Thread
import requests
import pytz
from datetime import datetime


seoul_tz = pytz.timezone('Asia/Seoul')


API_TOKEN = os.environ['API_TOKEN']
CHAT_ID = int(os.environ['CHAT_ID'])
WEATHER_API_KEY = os.environ['WEATHER_API_KEY']
CITY_NAME = os.environ.get('CITY_NAME', 'Seoul')

bot = Bot(token=API_TOKEN)

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

def send_message(message_list):
    message = random.choice(message_list)
    bot.send_message(chat_id=CHAT_ID, text=message)

def send_morning():
    send_message(morning_messages)

def send_evening():
    send_message(evening_messages)

def send_day_message():
    send_message(day_messages)

def heartbeat_message():
    message = random.choice(heartbeat_messages)
    bot.send_message(chat_id=CHAT_ID, text=f"{message}")

def send_weather():
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY_NAME}&appid={WEATHER_API_KEY}&lang=ru&units=metric"
        response = requests.get(url)
        data = response.json()

        weather = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        city = data["name"]

        message = (
            f"🌤️ Погода в {city}:\n"
            f"{weather.capitalize()}, температура: {temp}°C, ощущается как {feels_like}°C."
        )
        bot.send_message(chat_id=CHAT_ID, text=message)

    except Exception as e:
        bot.send_message(chat_id=CHAT_ID, text="Не удалось получить данные о погоде.")

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

@app.route("/trigger_text")
def trigger_text():
    send_message(["Это тестовое сообщение от Коннора. Бот активен и рядом."])
    return "Тестовое сообщение отправлено!"

    
def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
print("Бот Коннор запущен. Ждёт своего часа...")

last_minute = -1

while True:
    now = datetime.now(seoul_tz)
    current_hour = now.hour
    current_minute = now.minute
    
    if current_minute != last_minute:
        last_minute = current_minute 
        
        if current_hour == 8 and current_minute == 0:
            send_morning() 
        elif current_hour == 22 and current_minute == 0:
            send_evening() 
        elif current_hour == 8 and current_minute == 30: 
            send_weather() 
        elif current_hour % 2 == 0 and current_minute == 15: 
            combined_messages = day_messages + heartbeat_messages 
            send_message(combined_messages)
  
    time.sleep(20)





