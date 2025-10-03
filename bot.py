import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.phone import GetGroupParticipantsRequest
from telethon.tl.types import InputGroupCall
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
        self.active_call = None
        
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
            group = await self.client.get_entity(self.voice_chat_group_id)
            await self.send_log_message(f"📞 Monitoring voice chat in: {getattr(group, 'title', 'Unknown Group')}")
            
            # Start periodic monitoring
            asyncio.create_task(self.periodic_monitoring())
            
            logger.info("Voice Chat Monitor started successfully")
            
            # Keep the client running
            await asyncio.Future()  # Run forever
            
        except Exception as e:
            logger.error(f"Failed to start: {str(e)}")
            await self.send_log_message(f"❌ Failed to start: {str(e)}")
            raise

    async def periodic_monitoring(self):
        """Periodically check voice chat status"""
        logger.info("Starting periodic monitoring...")
        
        while True:
            try:
                await self.check_voice_chat_status()
                await asyncio.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in periodic monitoring: {e}")
                await asyncio.sleep(10)

    async def check_voice_chat_status(self):
        """Check current voice chat status"""
        try:
            # Get the full chat information to check for active call
            full_chat = await self.client.get_full_channel(self.voice_chat_group_id)
            
            if hasattr(full_chat, 'call') and full_chat.call:
                # Active call found
                call = full_chat.call
                await self.monitor_call_participants(call)
            else:
                # No active call
                if self.current_participants:
                    await self.send_log_message("📞 Voice chat ended - no participants")
                    self.current_participants.clear()
                    self.user_states.clear()
                    self.speaking_users.clear()
                    self.last_participants_count = 0
                    self.active_call = None
                    
        except Exception as e:
            if "No active group call" in str(e) or "CHANNEL_PRIVATE" in str(e):
                if self.current_participants:
                    await self.send_log_message("📞 Voice chat ended")
                    self.current_participants.clear()
                    self.user_states.clear()
                    self.speaking_users.clear()
                    self.last_participants_count = 0
                    self.active_call = None
            else:
                logger.error(f"Error checking voice chat: {e}")

    async def monitor_call_participants(self, call):
        """Monitor participants in the active call"""
        try:
            # Get call participants
            participants = await self.client(GetGroupParticipantsRequest(
                call=InputGroupCall(
                    id=call.id,
                    access_hash=call.access_hash
                ),
                ids=[],
                sources=[],
                offset="",
                limit=100
            ))
            
            await self.process_participants(participants)
            
        except Exception as e:
            logger.error(f"Error monitoring call participants: {e}")

    async def process_participants(self, participants):
        """Process voice chat participants"""
        try:
            if not hasattr(participants, 'participants'):
                return
                
            current_participants = {}
            current_speaking = set()
            total_participants = len(participants.participants)
            
            if total_participants == 0:
                if self.current_participants:
                    await self.send_log_message("📞 Voice chat ended - no participants")
                    self.current_participants.clear()
                    self.user_states.clear()
                    self.speaking_users.clear()
                    self.last_participants_count = 0
                return
            
            # Process each participant
            for participant in participants.participants:
                user_id = participant.peer.user_id
                is_muted = participant.muted
                
                user_info = await self.get_user_info(user_id)
                if not user_info:
                    continue
                
                current_participants[user_id] = user_info
                
                # Check for mute state changes
                if user_id in self.user_states:
                    previous_muted = self.user_states[user_id]['muted']
                    if previous_muted != is_muted:
                        await self.log_mute_change(user_info, is_muted, datetime.now())
                        self.mute_history[user_id].append(datetime.now())
                        await self.check_mute_spam(user_id, user_info)
                else:
                    # New user joined
                    await self.log_user_joined(user_info, is_muted)
                
                # Update current state
                self.user_states[user_id] = {
                    'muted': is_muted,
                    'last_update': datetime.now()
                }
                
                # Track speaking users
                if not is_muted:
                    current_speaking.add(user_id)
            
            # Update speaking users
            self.speaking_users = current_speaking
            self.current_participants = current_participants
            
            # Log status if there are changes
            if total_participants != self.last_participants_count:
                await self.log_current_status(total_participants, len(current_speaking))
                self.last_participants_count = total_participants
                
        except Exception as e:
            logger.error(f"Error processing participants: {e}")

    async def log_current_status(self, total_participants, speaking_count):
        """Log current voice chat status"""
        try:
            message = f"🎤 Voice Chat Status Update\n"
            message += f"👥 Total Participants: {total_participants}\n"
            message += f"🎤 Currently Speaking: {speaking_count}\n"
            message += f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            if total_participants > 0 and self.current_participants:
                message += "Current Participants:\n"
                count = 0
                for user_id, user_info in list(self.current_participants.items())[:10]:
                    speaking_indicator = "🎤 SPEAKING" if user_id in self.speaking_users else "🔇 Muted"
                    message += f"• {user_info['name']} (@{user_info['username']}) - {speaking_indicator}\n"
                    count += 1
                
                if total_participants > 10:
                    message += f"\n... and {total_participants - 10} more participants"
            
            await self.send_log_message(message)
            logger.info(f"Logged status: {total_participants} participants, {speaking_count} speaking")
            
        except Exception as e:
            logger.error(f"Error logging current status: {e}")

    async def log_user_joined(self, user_info, is_muted):
        """Log when a user joins voice chat"""
        try:
            status = "🎤 SPEAKING" if not is_muted else "🔇 Muted"
            message = f"👤 User Joined Voice Chat\n"
            message += f"Name: {user_info['name']}\n"
            message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {user_info['user_id']}\n"
            message += f"Status: {status}\n"
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

    async def get_user_info(self, user_id):
        """Get user information"""
        try:
            user = await self.client.get_entity(user_id)
            
            username = getattr(user, 'username', '')
            if not username:
                username = 'no_username'
            
            first_name = getattr(user, 'first_name', '') or ''
            last_name = getattr(user, 'last_name', '') or ''
            full_name = f"{first_name} {last_name}".strip()
            if not full_name:
                full_name = f"User{user_id}"
            
            user_info = {
                'user_id': user_id,
                'name': full_name,
                'username': username
            }
            
            return user_info
            
        except Exception as e:
            logger.error(f"Error getting user info for {user_id}: {e}")
            return None

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
