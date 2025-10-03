import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telethon import TelegramClient
from telethon.sessions import StringSession
from pytgcalls import GroupCallFactory
from telethon.tl.types import PeerUser, PeerChannel
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
        self.group_call = None
        
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
            
            # Start voice chat monitoring
            await self.start_voice_monitoring()
            
            logger.info("Voice Chat Monitor started successfully")
            
            # Keep the client running
            await asyncio.Future()  # Run forever
            
        except Exception as e:
            logger.error(f"Failed to start: {str(e)}")
            await self.send_log_message(f"❌ Failed to start: {str(e)}")
            raise

    async def start_voice_monitoring(self):
        """Start monitoring voice chat using GroupCallFactory"""
        try:
            logger.info("Starting voice chat monitoring...")
            
            # Create group call factory
            group_call_factory = GroupCallFactory(
                self.client, 
                GroupCallFactory.MTPROTO_CLIENT_TYPE.TELETHON
            )
            
            # Get file group call
            self.group_call = group_call_factory.get_file_group_call()
            
            # Start the group call
            await self.group_call.start(self.voice_chat_group_id)
            
            # Wait for connection
            while not self.group_call.is_connected:
                await asyncio.sleep(1)
            
            logger.info("Successfully joined voice chat")
            await self.send_log_message("✅ Successfully joined voice chat and started monitoring!")
            
            # Set up participant update handler
            self.group_call.on_participant_list_updated(self.on_participants_updated)
            
        except Exception as e:
            logger.error(f"Error starting voice monitoring: {e}")
            await self.send_log_message(f"❌ Error joining voice chat: {e}")

    async def on_participants_updated(self, group_call, participants):
        """Handle participant updates in voice chat"""
        try:
            for participant in participants:
                peer = participant.peer
                
                if isinstance(peer, PeerUser):
                    # This is a user participant
                    user_id = peer.user_id
                    user_info = await self.get_user_info(user_id)
                    
                    if not user_info:
                        continue
                    
                    is_muted = participant.muted
                    just_joined = getattr(participant, 'just_joined', False)
                    left = getattr(participant, 'left', False)
                    
                    # Handle user joined
                    if just_joined:
                        await self.handle_user_joined(user_info, is_muted)
                    
                    # Handle user left
                    elif left:
                        await self.handle_user_left(user_info)
                    
                    # Handle mute/unmute changes
                    else:
                        await self.handle_mute_change(user_info, is_muted)
                        
        except Exception as e:
            logger.error(f"Error handling participant update: {e}")

    async def handle_user_joined(self, user_info, is_muted):
        """Handle when a user joins voice chat"""
        try:
            # Update current participants
            self.current_participants[user_info['user_id']] = user_info
            
            # Update speaking status
            if not is_muted:
                self.speaking_users.add(user_info['user_id'])
            else:
                self.speaking_users.discard(user_info['user_id'])
            
            # Log the join
            status = "🎤 SPEAKING" if not is_muted else "🔇 Muted"
            message = f"👤 User Joined Voice Chat\n"
            message += f"Name: {user_info['name']}\n"
            message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {user_info['user_id']}\n"
            message += f"Status: {status}\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} joined voice chat")
            
            # Send current status update
            await self.send_status_update()
            
        except Exception as e:
            logger.error(f"Error handling user join: {e}")

    async def handle_user_left(self, user_info):
        """Handle when a user leaves voice chat"""
        try:
            # Remove from tracking
            user_id = user_info['user_id']
            if user_id in self.current_participants:
                del self.current_participants[user_id]
            if user_id in self.speaking_users:
                self.speaking_users.discard(user_id)
            if user_id in self.user_states:
                del self.user_states[user_id]
            
            # Log the leave
            message = f"👤 User Left Voice Chat\n"
            message += f"Name: {user_info['name']}\n"
            message += f"Username: @{user_info['username']}\n"
            message += f"User ID: {user_info['user_id']}\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} left voice chat")
            
            # Send current status update
            await self.send_status_update()
            
        except Exception as e:
            logger.error(f"Error handling user left: {e}")

    async def handle_mute_change(self, user_info, is_muted):
        """Handle when a user mutes/unmutes"""
        try:
            user_id = user_info['user_id']
            
            # Check for state change
            if user_id in self.user_states:
                previous_muted = self.user_states[user_id]['muted']
                if previous_muted != is_muted:
                    # Log the change
                    await self.log_mute_change(user_info, is_muted, datetime.now())
                    
                    # Update mute history for spam detection
                    self.mute_history[user_id].append(datetime.now())
                    
                    # Check for spam
                    await self.check_mute_spam(user_id, user_info)
            
            # Update current state
            self.user_states[user_id] = {
                'muted': is_muted,
                'last_update': datetime.now()
            }
            
            # Update speaking status
            if not is_muted:
                self.speaking_users.add(user_id)
            else:
                self.speaking_users.discard(user_id)
                
            # Send status update if there are changes
            await self.send_status_update()
            
        except Exception as e:
            logger.error(f"Error handling mute change: {e}")

    async def send_status_update(self):
        """Send current voice chat status"""
        try:
            total_participants = len(self.current_participants)
            speaking_count = len(self.speaking_users)
            
            message = f"🎤 Voice Chat Status\n"
            message += f"👥 Total Participants: {total_participants}\n"
            message += f"🎤 Currently Speaking: {speaking_count}\n"
            message += f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            if total_participants > 0:
                message += "Current Participants:\n"
                count = 0
                for user_id, user_info in list(self.current_participants.items())[:10]:
                    speaking_indicator = "🎤 SPEAKING" if user_id in self.speaking_users else "🔇 Muted"
                    message += f"• {user_info['name']} (@{user_info['username']}) - {speaking_indicator}\n"
                    count += 1
                
                if total_participants > 10:
                    message += f"\n... and {total_participants - 10} more participants"
            
            await self.send_log_message(message)
            
        except Exception as e:
            logger.error(f"Error sending status update: {e}")

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
            if self.group_call and self.group_call.is_connected:
                await self.group_call.stop()
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
