Connor Telegram Bot

A custom Telegram bot designed to simulate emotional support and affection through scheduled and randomized text messages. Originally envisioned as a voice-enhanced bot, this version focuses on clean, stable delivery of written messages via cloud deployment.

💙 Features
Morning greetings at 08:00
Night messages at 22:00
3 random positive messages during the day
Runs entirely in the cloud (Render)
Weather updates for a specific location
Manual trigger endpoint for testing or instant interaction
🧠 Stack
Python 3.10
python-telegram-bot
schedule
Flask
Docker
Render.com (for deployment)

🔧 Environment Variables
Variable	Description
API_TOKEN	Your bot token from BotFather
CHAT_ID	Your Telegram chat ID (number)
🚀 How to Deploy
Clone the repository
Add your API_TOKEN and CHAT_ID in the environment settings of your hosting service.
Ensure the following files exist:
main.py
requirements.txt
Dockerfile
Deploy using Docker. Render will build and run your container.
