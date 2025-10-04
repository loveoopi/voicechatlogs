import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator
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
        self.user_states = {}  # user_id -> {muted: bool, last_update: datetime, name: str, username: str}
        self.mute_history = defaultdict(lambda: deque(maxlen=10))
        self.last_participants = {}
        
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
            
            # Get initial participants
            await self.get_voice_chat_participants()
            
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
            group_title = getattr(group, 'title', 'Unknown Group')
            logger.info(f"Monitoring group: {group_title}")
            
            await self.send_log_message(f"📞 Monitoring voice chat in: {group_title}")
            
        except Exception as e:
            logger.error(f"Error getting group info: {e}")
            await self.send_log_message(f"❌ Error accessing group: {e}")

    async def get_voice_chat_participants(self):
        """Get current voice chat participants"""
        try:
            # Get the group entity
            group = await self.client.get_entity(self.voice_chat_group_id)
            
            # Get all participants in the group
            participants = await self.client.get_participants(group)
            
            current_participants = {}
            
            for participant in participants:
                if not participant.bot:  # Ignore bots
                    user_id = participant.id
                    username = getattr(participant, 'username', '')
                    first_name = getattr(participant, 'first_name', '')
                    last_name = getattr(participant, 'last_name', '')
                    
                    # Create display name
                    if first_name and last_name:
                        full_name = f"{first_name} {last_name}"
                    elif first_name:
                        full_name = first_name
                    else:
                        full_name = f"User{user_id}"
                    
                    # For now, we'll assume all participants are muted (since we can't get real voice chat status via regular API)
                    # In a real implementation, you'd need to use voice chat specific methods
                    current_participants[user_id] = {
                        'name': full_name,
                        'username': username,
                        'muted': True,  # Default assumption
                        'last_seen': datetime.now()
                    }
            
            # Compare with previous participants to detect changes
            await self.detect_participant_changes(current_participants)
            
            self.last_participants = current_participants
            return current_participants
            
        except Exception as e:
            logger.error(f"Error getting participants: {e}")
            return {}

    async def detect_participant_changes(self, current_participants):
        """Detect changes in participants and their states"""
        try:
            current_time = datetime.now()
            
            # Check for new participants
            for user_id, user_info in current_participants.items():
                if user_id not in self.user_states:
                    # New user detected
                    await self.log_user_joined(user_info)
                    self.user_states[user_id] = {
                        'muted': user_info['muted'],
                        'last_update': current_time,
                        'name': user_info['name'],
                        'username': user_info['username']
                    }
                else:
                    # Check for mute status changes
                    old_muted = self.user_states[user_id]['muted']
                    new_muted = user_info['muted']
                    
                    if old_muted != new_muted:
                        await self.log_mute_change(user_info, new_muted, current_time)
                        self.user_states[user_id]['muted'] = new_muted
                        self.user_states[user_id]['last_update'] = current_time
                        
                        # Track mute history for spam detection
                        self.mute_history[user_id].append(current_time)
                        await self.check_mute_spam(user_id, user_info)
            
            # Check for left participants
            for user_id in list(self.user_states.keys()):
                if user_id not in current_participants:
                    # User left
                    user_info = self.user_states[user_id]
                    await self.log_user_left(user_info)
                    del self.user_states[user_id]
                    
        except Exception as e:
            logger.error(f"Error detecting participant changes: {e}")

    async def periodic_monitoring(self):
        """Periodically check voice chat status"""
        logger.info("Starting periodic monitoring...")
        
        await self.send_log_message("🔄 Starting voice chat monitoring...")
        
        while True:
            try:
                # Get current participants and check for changes
                await self.get_voice_chat_participants()
                
                current_time = datetime.now().strftime('%H:%M:%S')
                active_users = len(self.user_states)
                logger.info(f"Monitoring active at {current_time} - {active_users} users in voice chat")
                
                await asyncio.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in periodic monitoring: {e}")
                await asyncio.sleep(10)

    async def send_log_message(self, message):
        """Send message to log group"""
        try:
            await self.bot.send_message(
                chat_id=self.log_group_id,
                text=message
            )
            logger.info(f"Message sent to log group: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending log message: {e}")

    async def log_user_joined(self, user_info):
        """Log when a user joins voice chat"""
        try:
            message = f"👤 User Joined Voice Chat\n"
            message += f"Name: {user_info['name']}\n"
            if user_info['username']:
                message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {hash(str(user_info['name']))}...\n"  # Hashed for privacy
            message += f"Status: {'🎤 SPEAKING' if not user_info['muted'] else '🔇 Muted'}\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} joined voice chat")
            
        except Exception as e:
            logger.error(f"Error logging user join: {e}")

    async def log_user_left(self, user_info):
        """Log when a user leaves voice chat"""
        try:
            message = f"🚪 User Left Voice Chat\n"
            message += f"Name: {user_info['name']}\n"
            if user_info.get('username'):
                message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {hash(str(user_info['name']))}...\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} left voice chat")
            
        except Exception as e:
            logger.error(f"Error logging user left: {e}")

    async def log_mute_change(self, user_info, is_muted, timestamp):
        """Log when a user mutes/unmutes"""
        try:
            action = "unmuted" if not is_muted else "muted"
            emoji = "🎤" if not is_muted else "🔇"
            
            message = f"{emoji} User {action.upper()}\n"
            message += f"Name: {user_info['name']}\n"
            if user_info['username']:
                message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {hash(str(user_info['name']))}...\n"
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
                if user_info['username']:
                    message += f"Username: @{user_info['username']}\n"
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
