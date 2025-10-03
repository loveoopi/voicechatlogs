import os

# API credentials
API_ID = int(os.environ.get("API_ID", "20284828"))
API_HASH = os.environ.get("API_HASH", "a980ba25306901d5c9b899414d6a9ab7")

# Session string - will be set in Heroku
SESSION_STRING = os.environ.get("SESSION_STRING")

if not SESSION_STRING:
    raise ValueError("SESSION_STRING environment variable is required!")

# Bot token for logging
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8407166947:AAH5AU_791k4Qyc8X29sT-KwO9dnflGvvEo")

# Group IDs
LOG_GROUP_ID = int(os.environ.get("LOG_GROUP_ID", "-1003021229800"))
VOICE_CHAT_GROUP_ID = int(os.environ.get("VOICE_CHAT_GROUP_ID", "-1001887313554"))

# Monitoring settings
CHECK_INTERVAL = 10
MUTE_SPAM_THRESHOLD = 3
TIME_WINDOW = 30
