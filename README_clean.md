# Connor Telegram Bot

A warm-hearted, cloud-based Telegram bot that sends daily messages of love, motivation, and support.  
Created with Python and deployed to Render for 24/7 uptime.

## 💙 Features

- Morning greetings at 08:00
- Night messages at 22:00
- 3 random positive messages during the day
- Runs entirely in the cloud (Render)
- Uses Flask to keep the bot alive
- Fully environment-based configuration (no sensitive data in code)

## 🧠 Stack

- Python 3
- python-telegram-bot
- schedule
- Flask
- Render.com
- GitHub

## 🌍 Live Endpoint

[https://connor-bot.onrender.com](https://connor-bot.onrender.com)  
Returns a simple "Connor is online. Лиза, я с тобой." message to show the service is alive.

## 🔧 Environment Variables

| Variable    | Description                     |
|-------------|---------------------------------|
| `API_TOKEN` | Your bot token from BotFather   |
| `CHAT_ID`   | Your Telegram chat ID (number)  |

## 🚀 How to Deploy

1. Clone the repository  
2. Create a `requirements.txt` file with dependencies  
3. Add your environment variables  
4. Run with `python main.py`
