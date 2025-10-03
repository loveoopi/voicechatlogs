import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telethon import TelegramClient, events
from telegram import Bot
from telegram.error import TelegramError
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VoiceChatMonitor:
    def __init__(self):
        self.client = TelegramClient(
            "voice_monitor_session",
            config.API_ID,
            config.API_HASH
        )
        
        self.bot = Bot(token=config.BOT_TOKEN)
        self.log_group_id = config.LOG_GROUP_ID
        self.voice_chat_group_id = config.VOICE_CHAT_GROUP_ID
        
        # Track user states
        self.user_states = {}  # user_id -> {muted: bool, last_update: datetime}
        self.mute_history = defaultdict(lambda: deque(maxlen=10))  # user_id -> deque of mute/unmute timestamps
        self.speaking_users = set()
        
        # Track current participants
        self.current_participants = {}  # user_id -> user_info
        
        logger.info("Voice Chat Monitor initialized")

    async def start(self):
        """Start the monitoring service"""
        await self.client.start(config.SESSION_STRING)
        logger.info("Client started successfully")
        
        # Register event handlers
        self.client.add_event_handler(
            self.handle_voice_chat_update,
            events.CallUpdated
        )
        
        # Start periodic monitoring
        asyncio.create_task(self.periodic_monitoring())
        
        logger.info("Voice Chat Monitor started")
        await self.send_log_message("🚀 Voice Chat Monitor Started!")
        
        # Keep the client running
        await self.client.run_until_disconnected()

    async def handle_voice_chat_update(self, event):
        """Handle voice chat participant updates"""
        try:
            if not hasattr(event.call, 'participants') or not event.call.participants:
                return
            
            call = event.call
            current_time = datetime.now()
            
            # Update participant states
            for participant in event.call.participants:
                user_id = participant.user_id
                is_muted = participant.muted
                
                # Get user info
                user_info = await self.get_user_info(user_id)
                if not user_info:
                    continue
                
                # Update current participants
                self.current_participants[user_id] = user_info
                
                # Check for state change
                if user_id in self.user_states:
                    previous_state = self.user_states[user_id]
                    if previous_state['muted'] != is_muted:
                        # State changed - log it
                        await self.log_mute_change(
                            user_info, 
                            is_muted, 
                            current_time
                        )
                        
                        # Update mute history for spam detection
                        self.mute_history[user_id].append(current_time)
                        
                        # Check for spam behavior
                        await self.check_mute_spam(user_id, user_info)
                
                # Update current state
                self.user_states[user_id] = {
                    'muted': is_muted,
                    'last_update': current_time
                }
                
                # Update speaking status
                if not is_muted:
                    self.speaking_users.add(user_id)
                else:
                    self.speaking_users.discard(user_id)
                    
        except Exception as e:
            logger.error(f"Error handling voice chat update: {e}")

    async def periodic_monitoring(self):
        """Periodically check voice chat status"""
        while True:
            try:
                await self.check_current_status()
                await asyncio.sleep(config.CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in periodic monitoring: {e}")
                await asyncio.sleep(10)

    async def check_current_status(self):
        """Check current voice chat status and log if needed"""
        try:
            # Get current call information
            call = await self.client.get_call(config.VOICE_CHAT_GROUP_ID)
            if not call or not hasattr(call, 'participants'):
                return
            
            total_participants = len(call.participants)
            speaking_count = len([p for p in call.participants if not p.muted])
            
            # Log significant changes
            if total_participants > 0:
                await self.log_current_status(total_participants, speaking_count)
                
        except Exception as e:
            logger.error(f"Error checking current status: {e}")

    async def log_current_status(self, total_participants, speaking_count):
        """Log current voice chat status"""
        try:
            message = f"🎤 **Voice Chat Status**\n"
            message += f"👥 Total Participants: {total_participants}\n"
            message += f"🎤 Currently Speaking: {speaking_count}\n"
            message += f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            if total_participants > 0:
                message += "**Current Participants:**\n"
                for user_id, user_info in list(self.current_participants.items())[:20]:  # Limit to first 20
                    speaking_indicator = "🎤 **SPEAKING**" if user_id in self.speaking_users else "🔇 Muted"
                    message += f"• {user_info['name']} ({user_info['username']}) - {speaking_indicator}\n"
                
                if total_participants > 20:
                    message += f"\n... and {total_participants - 20} more participants"
            
            await self.send_log_message(message)
            
        except Exception as e:
            logger.error(f"Error logging current status: {e}")

    async def log_mute_change(self, user_info, is_muted, timestamp):
        """Log when a user mutes/unmutes"""
        try:
            action = "unmuted" if not is_muted else "muted"
            emoji = "🎤" if not is_muted else "🔇"
            
            message = f"{emoji} **User {action.upper()}**\n"
            message += f"👤 Name: {user_info['name']}\n"
            message += f"📱 Username: @{user_info['username']}\n"
            message += f"🆔 User ID: `{user_info['user_id']}`\n"
            message += f"⏰ Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} {action} at {timestamp}")
            
        except Exception as e:
            logger.error(f"Error logging mute change: {e}")

    async def check_mute_spam(self, user_id, user_info):
        """Check if user is spamming mute/unmute"""
        try:
            history = self.mute_history[user_id]
            current_time = datetime.now()
            time_window = current_time - timedelta(seconds=config.TIME_WINDOW)
            
            # Count actions in time window
            recent_actions = len([t for t in history if t > time_window])
            
            if recent_actions >= config.MUTE_SPAM_THRESHOLD:
                message = f"🚨 **MUTE/UNMUTE SPAM DETECTED**\n"
                message += f"👤 User: {user_info['name']}\n"
                message += f"📱 Username: @{user_info['username']}\n"
                message += f"🆔 User ID: `{user_info['user_id']}`\n"
                message += f"🔢 Actions: {recent_actions} in {config.TIME_WINDOW} seconds\n"
                message += f"⏰ Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
                
                await self.send_log_message(message)
                logger.warning(f"Mute spam detected for user {user_info['name']}")
                
                # Clear history after reporting
                self.mute_history[user_id].clear()
                
        except Exception as e:
            logger.error(f"Error checking mute spam: {e}")

    async def get_user_info(self, user_id):
        """Get user information"""
        try:
            user = await self.client.get_entity(user_id)
            
            user_info = {
                'user_id': user_id,
                'name': f"{user.first_name or ''} {user.last_name or ''}".strip(),
                'username': getattr(user, 'username', 'No Username')
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
                text=message,
                parse_mode='Markdown'
            )
        except TelegramError as e:
            logger.error(f"Error sending log message: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending log message: {e}")

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
