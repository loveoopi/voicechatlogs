import os

class Config:
    # API credentials
    API_ID = int(os.environ.get("API_ID", 20284828))
    API_HASH = os.environ.get("API_HASH", "a980ba25306901d5c9b899414d6a9ab7")
    SESSION_STRING = os.environ.get("SESSION_STRING", "BQCOaU4AFyBoZE7vS3lu3y7ZU4Tzv5qKCg3NoK58e8paOkFYvfS8ZE59ebB_vd4oW_hixs0BOQgJFJCFWjKZZ4kUYOZl3GLgzjcYwbmed5LPGlAbIaw8XQ5-XHBbhZylQwz1Jpqj0uHxj9J0a4gJDiWnUR5owJYIWg07l5VyZWEqtQvAiaDLTSo9Wij-Svf0QfGqUglRs_UrcGTGAGaLJgZXCJ0wAHq-DTSafRTQhCdhBzkLCQA1Sj9vJKnZuzmzK-qgq57NPbz_Sp3aEfxQ0dLr1tUTSrZDlQZqAak7WPznEK0Ef3SfUjlf_9yCctKgrOD3sbhjuAaxeIMnSDpuozEYzIfe9wAAAAHrrzhRAA")
    
    # Bot token for logging
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8407166947:AAH5AU_791k4Qyc8X29sT-KwO9dnflGvvEo")
    
    # Group IDs
    LOG_GROUP_ID = int(os.environ.get("LOG_GROUP_ID", -1003021229800))
    VOICE_CHAT_GROUP_ID = int(os.environ.get("VOICE_CHAT_GROUP_ID", -1001887313554))
    
    # Monitoring settings
    CHECK_INTERVAL = 5  # seconds
    MUTE_SPAM_THRESHOLD = 3  # number of mute/unmute actions within timeframe to be considered spam
    TIME_WINDOW = 30  # seconds for spam detection
