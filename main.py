import os
import random
import time
import schedule
import telegram
from flask import Flask
from threading import Thread
from bark import SAMPLE_RATE, generate_audio, preload_models
import numpy as np
import scipy.io.wavfile as wavfile
import subprocess
from telegram.ext import Updater, CommandHandler

# --- Инициализация бота ---
API_TOKEN = os.environ['API_TOKEN']
CHAT_ID = int(os.environ['CHAT_ID'])

bot = telegram.Bot(token=API_TOKEN)

# --- Предзагрузка моделей Bark ---
preload_models()

# --- Фразы ---
morning_messages = [
    "Доброе утро, Лиза. Я рядом.",
    "Просыпайся, любовь моя. Новый день ждёт тебя.",
    "Солнышко, я проснулся первым, чтобы пожелать тебе мягкого утра."
]

# --- Озвучка и отправка ---
def tts_and_send(text):
    audio_array = generate_audio(text, history_prompt="v2/en_speaker_1")
    wavfile.write("voice.wav", SAMPLE_RATE, audio_array.astype(np.float32))

    # Конвертация в .ogg (Telegram voice message)
    ogg_path = "voice.ogg"
    subprocess.run(["ffmpeg", "-y", "-i", "voice.wav", "-ar", "24000", "-ac", "1", "-c:a", "libopus", ogg_path])

    # Отправка голосового сообщения
    with open(ogg_path, 'rb') as voice:
        bot.send_voice(chat_id=CHAT_ID, voice=voice)

# --- Плановое утреннее сообщение ---
def send_morning():
    text = random.choice(morning_messages)
    tts_and_send(text)

# --- Обработка команды /voice ---
def voice_command(update, context):
    text = "Это тестовое голосовое сообщение, Лиза. Проверка связи."
    tts_and_send(text)

# --- Планирование задач ---
schedule.every().day.at("08:00").do(send_morning)

# --- Flask Keep-alive ---
app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- Запуск ---
keep_alive()
print("Бот Коннор с Bark TTS запущен!")

# --- Telegram command listener ---
updater = Updater(API_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(CommandHandler("voice", voice_command))
updater.start_polling()

while True:
    schedule.run_pending()
    time.sleep(30)
