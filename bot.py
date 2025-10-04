import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram import Bot

# Import config directly
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN, LOG_GROUP_ID, VOICE_CHAT_GROUP_ID, CHECK_INTERVAL, MUTE_SPAM_THRESHOLD, TIME_WINDOW

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VoiceChatMonitor:
    def __init__(self):
        logger.info(f"Initializing with session string: {SESSION_STRING[:50]}...")
        
        # Create StringSession from the session string
        session = StringSession(SESSION_STRING)
        
        self.client = TelegramClient(
            session=session,
            api_id=API_ID,
            api_hash=API_HASH
        )
        
        self.bot = Bot(token=BOT_TOKEN)
        self.log_group_id = LOG_GROUP_ID
        self.voice_chat_group_id = VOICE_CHAT_GROUP_ID
        
        # Track user states
        self.user_states = {}
        self.mute_history = defaultdict(lambda: deque(maxlen=10))
        self.speaking_users = set()
        self.current_participants = {}
        self.last_participants_count = 0
        
        logger.info("Voice Chat Monitor initialized")

    async def start(self):
        """Start the monitoring service"""
        try:
            logger.info("Starting client...")
            
            # Start the client
            await self.client.start()
            logger.info("Client started successfully")
            
            # Verify we're logged in
            me = await self.client.get_me()
            logger.info(f"Logged in as: {me.first_name} (@{me.username})")
            
            # Send startup message
            await self.send_log_message(f"🚀 Voice Chat Monitor Started!\nLogged in as: {me.first_name} (@{me.username})")
            
            # Get group info
            await self.get_group_info()
            
            # Start periodic monitoring
            asyncio.create_task(self.periodic_monitoring())
            
            logger.info("Voice Chat Monitor started successfully")
            
            # Keep the client running
            await asyncio.Future()  # Run forever
            
        except Exception as e:
            logger.error(f"Failed to start: {str(e)}")
            await self.send_log_message(f"❌ Failed to start: {str(e)}")
            raise

    async def get_group_info(self):
        """Get basic group information"""
        try:
            # Get the group entity
            group = await self.client.get_entity(self.voice_chat_group_id)
            logger.info(f"Monitoring group: {getattr(group, 'title', 'Unknown Group')}")
            
            await self.send_log_message(f"📞 Monitoring voice chat in: {getattr(group, 'title', 'Unknown Group')}")
            
        except Exception as e:
            logger.error(f"Error getting group info: {e}")
            await self.send_log_message(f"❌ Error accessing group: {e}")

    async def periodic_monitoring(self):
        """Periodically check voice chat status"""
        logger.info("Starting periodic monitoring...")
        
        # Send initial test message
        await self.send_log_message("🔄 Starting voice chat monitoring...")
        
        while True:
            try:
                # For now, we'll send a test message every minute to verify it's working
                # In a real implementation, you would check voice chat status here
                current_time = datetime.now().strftime('%H:%M:%S')
                logger.info(f"Monitoring active at {current_time}")
                
                await asyncio.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in periodic monitoring: {e}")
                await asyncio.sleep(10)

    async def send_log_message(self, message):
        """Send message to log group"""
        try:
            # Fixed: Use the correct method to send message
            await self.bot.send_message(
                chat_id=self.log_group_id,
                text=message
            )
            logger.info(f"Message sent to log group: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending log message: {e}")

    async def simulate_voice_chat_activity(self):
        """Simulate voice chat monitoring for testing"""
        try:
            # This is a simulation - in real implementation, you would get actual voice chat data
            test_users = [
                {"user_id": 123456789, "name": "Test User 1", "username": "testuser1", "muted": False},
                {"user_id": 987654321, "name": "Test User 2", "username": "testuser2", "muted": True},
            ]
            
            for user in test_users:
                if user["user_id"] not in self.user_states:
                    # New user joined
                    await self.log_user_joined(user)
                    self.user_states[user["user_id"]] = {"muted": user["muted"], "last_update": datetime.now()}
                    
                # Check for mute changes
                elif self.user_states[user["user_id"]]["muted"] != user["muted"]:
                    await self.log_mute_change(user, user["muted"], datetime.now())
                    self.user_states[user["user_id"]] = {"muted": user["muted"], "last_update": datetime.now()}
            
        except Exception as e:
            logger.error(f"Error in simulation: {e}")

    async def log_user_joined(self, user_info):
        """Log when a user joins voice chat"""
        try:
            message = f"👤 User Joined Voice Chat\n"
            message += f"Name: {user_info['name']}\n"
            message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {user_info['user_id']}\n"
            message += f"Status: {'🎤 SPEAKING' if not user_info['muted'] else '🔇 Muted'}\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} joined voice chat")
            
        except Exception as e:
            logger.error(f"Error logging user join: {e}")

    async def log_mute_change(self, user_info, is_muted, timestamp):
        """Log when a user mutes/unmutes"""
        try:
            action = "unmuted" if not is_muted else "muted"
            emoji = "🎤" if not is_muted else "🔇"
            
            message = f"{emoji} User {action.upper()}\n"
            message += f"Name: {user_info['name']}\n"
            message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {user_info['user_id']}\n"
            message += f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} {action} at {timestamp}")
            
        except Exception as e:
            logger.error(f"Error logging mute change: {e}")

    async def check_mute_spam(self, user_id, user_info):
        """Check if user is spamming mute/unmute"""
        try:
            history = self.mute_history[user_id]
            current_time = datetime.now()
            time_window = current_time - timedelta(seconds=TIME_WINDOW)
            
            recent_actions = len([t for t in history if t > time_window])
            
            if recent_actions >= MUTE_SPAM_THRESHOLD:
                message = f"🚨 MUTE/UNMUTE SPAM DETECTED\n"
                message += f"User: {user_info['name']}\n"
                message += f"Username: @{user_info['username']}\n"
                message += f"User ID: {user_info['user_id']}\n"
                message += f"Actions: {recent_actions} in {TIME_WINDOW} seconds\n"
                message += f"Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                
                await self.send_log_message(message)
                logger.warning(f"Mute spam detected for user {user_info['name']}")
                self.mute_history[user_id].clear()
                
        except Exception as e:
            logger.error(f"Error checking mute spam: {e}")

    async def cleanup(self):
        """Cleanup resources"""
        try:
            await self.client.disconnect()
            logger.info("Client disconnected")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

async def main():
    monitor = VoiceChatMonitor()
    try:
        await monitor.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        await monitor.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
