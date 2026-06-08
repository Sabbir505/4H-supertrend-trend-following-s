import os
import requests

# Load .env file manually
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("TELEGRAM_CHAT_ID", "@your_channel_username")

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment or .env file")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

payload = {
    "chat_id": CHANNEL_USERNAME,
    "text": "test from bot"
}

requests.post(url, data=payload)
