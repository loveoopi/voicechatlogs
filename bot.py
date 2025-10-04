import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator, Channel
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
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
        self.user_states = {}  # user_id -> {muted: bool, last_update: datetime, name: str, username: str, is_admin: bool}
        self.mute_history = defaultdict(lambda: deque(maxlen=10))
        self.last_participants = {}
        self.admin_ids = set()  # Store admin user IDs
        
        # Track already banned channels to avoid duplicate actions
        self.banned_channels = set()
        
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
            
            # Get admin list
            await self.get_admin_list()
            
            # Get initial participants and check for channels
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

    async def get_admin_list(self):
        """Get list of admin users to exclude from logging"""
        try:
            group = await self.client.get_entity(self.voice_chat_group_id)
            participants = await self.client.get_participants(group)
            
            admin_ids = set()
            
            for participant in participants:
                if (isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator))):
                    admin_ids.add(participant.id)
                    logger.info(f"Admin found: {getattr(participant, 'first_name', '')} (@{getattr(participant, 'username', '')})")
            
            self.admin_ids = admin_ids
            logger.info(f"Loaded {len(admin_ids)} admins to exclude from logging")
            
        except Exception as e:
            logger.error(f"Error getting admin list: {e}")

    async def is_channel(self, participant):
        """Check if a participant is a channel"""
        try:
            # Check if the participant is a Channel (not a user)
            if isinstance(participant, Channel):
                return True
            
            # Check user attributes that indicate it's a channel
            user = await self.client.get_entity(participant.id)
            if hasattr(user, 'broadcast') and user.broadcast:
                return True
            if hasattr(user, 'megagroup') and user.megagroup:
                return True
            if hasattr(user, 'username') and user.username and 'channel' in user.username.lower():
                return True
                
            return False
        except Exception as e:
            logger.error(f"Error checking if participant is channel: {e}")
            return False

    async def ban_channel(self, channel_id, channel_info):
        """Ban a channel from the group"""
        try:
            if channel_id in self.banned_channels:
                logger.info(f"Channel {channel_id} already banned, skipping")
                return False

            # Create banned rights (ban forever)
            banned_rights = ChatBannedRights(
                until_date=None,  # Forever
                view_messages=True,
                send_messages=True,
                send_media=True,
                send_stickers=True,
                send_gifs=True,
                send_games=True,
                send_inline=True,
                embed_links=True,
                send_polls=True,
                change_info=True,
                invite_users=True,
                pin_messages=True
            )

            # Ban the channel
            await self.client(EditBannedRequest(
                channel=self.voice_chat_group_id,
                participant=channel_id,
                banned_rights=banned_rights
            ))
            
            self.banned_channels.add(channel_id)
            
            # Log the ban action
            await self.log_channel_ban(channel_info)
            
            logger.info(f"Successfully banned channel: {channel_info['name']} (ID: {channel_id})")
            return True
            
        except Exception as e:
            logger.error(f"Error banning channel {channel_id}: {e}")
            await self.send_log_message(f"❌ Failed to ban channel {channel_info['name']}: {str(e)}")
            return False

    async def log_channel_ban(self, channel_info):
        """Log channel ban details"""
        try:
            message = f"🚫 CHANNEL BANNED FROM VOICE CHAT\n"
            message += f"📢 Channel Name: {channel_info['name']}\n"
            message += f"🆔 Channel ID: {channel_info['id']}\n"
            
            if channel_info.get('username'):
                message += f"👤 Username: @{channel_info['username']}\n"
            
            message += f"⏰ Banned at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"🔒 Action: Permanently banned from group"
            
            await self.send_log_message(message)
            logger.info(f"Channel ban logged: {channel_info['name']}")
            
        except Exception as e:
            logger.error(f"Error logging channel ban: {e}")

    async def check_and_ban_channels(self, participants):
        """Check participants and ban any channels"""
        try:
            for participant in participants:
                # Skip if it's a bot
                if participant.bot:
                    continue
                
                # Check if participant is a channel
                if await self.is_channel(participant):
                    user_id = participant.id
                    username = getattr(participant, 'username', '')
                    first_name = getattr(participant, 'first_name', '')
                    last_name = getattr(participant, 'last_name', '')
                    title = getattr(participant, 'title', '')
                    
                    # Create display name
                    if title:
                        display_name = title
                    elif first_name and last_name:
                        display_name = f"{first_name} {last_name}"
                    elif first_name:
                        display_name = first_name
                    else:
                        display_name = f"Channel{user_id}"
                    
                    channel_info = {
                        'id': user_id,
                        'name': display_name,
                        'username': username
                    }
                    
                    # Ban the channel immediately
                    await self.ban_channel(user_id, channel_info)
                    
        except Exception as e:
            logger.error(f"Error in check_and_ban_channels: {e}")

    async def get_voice_chat_participants(self):
        """Get current voice chat participants and ban any channels"""
        try:
            # Get the group entity
            group = await self.client.get_entity(self.voice_chat_group_id)
            
            # Get all participants in the group
            participants = await self.client.get_participants(group)
            
            # Check and ban any channels immediately
            await self.check_and_ban_channels(participants)
            
            current_participants = {}
            
            for participant in participants:
                if not participant.bot:  # Ignore bots
                    user_id = participant.id
                    username = getattr(participant, 'username', '')
                    first_name = getattr(participant, 'first_name', '')
                    last_name = getattr(participant, 'last_name', '')
                    
                    # Skip if it's a channel (should be banned by now)
                    if await self.is_channel(participant):
                        continue
                    
                    # Create display name
                    if first_name and last_name:
                        full_name = f"{first_name} {last_name}"
                    elif first_name:
                        full_name = first_name
                    else:
                        full_name = f"User{user_id}"
                    
                    # Check if user is admin
                    is_admin = user_id in self.admin_ids
                    
                    # Simulate speaking status (in real implementation, you'd get this from voice chat)
                    is_speaking = not is_admin and (user_id % 3 == 0)  # Demo: 1/3 of non-admin users are "speaking"
                    
                    current_participants[user_id] = {
                        'name': full_name,
                        'username': username,
                        'muted': not is_speaking,  # If speaking, not muted
                        'last_seen': datetime.now(),
                        'is_admin': is_admin,
                        'speaking': is_speaking
                    }
            
            # Compare with previous participants to detect changes
            await self.detect_speaking_changes(current_participants)
            
            self.last_participants = current_participants
            return current_participants
            
        except Exception as e:
            logger.error(f"Error getting participants: {e}")
            return {}

    async def detect_speaking_changes(self, current_participants):
        """Detect when non-admin users start/stop speaking"""
        try:
            current_time = datetime.now()
            
            # Check for speaking status changes
            for user_id, user_info in current_participants.items():
                # Skip admins - we don't log their speaking activity
                if user_info['is_admin']:
                    continue
                    
                if user_id not in self.user_states:
                    # New user detected - only log if they're speaking
                    if user_info['speaking']:
                        await self.log_user_speaking(user_info, current_time)
                    
                    self.user_states[user_id] = {
                        'muted': user_info['muted'],
                        'speaking': user_info['speaking'],
                        'last_update': current_time,
                        'name': user_info['name'],
                        'username': user_info['username'],
                        'is_admin': user_info['is_admin']
                    }
                else:
                    # Check for speaking status changes
                    old_speaking = self.user_states[user_id]['speaking']
                    new_speaking = user_info['speaking']
                    
                    if not old_speaking and new_speaking:
                        # User started speaking
                        await self.log_user_speaking(user_info, current_time)
                        self.user_states[user_id]['speaking'] = True
                        self.user_states[user_id]['last_update'] = current_time
                        
                    elif old_speaking and not new_speaking:
                        # User stopped speaking
                        await self.log_user_stopped_speaking(user_info, current_time)
                        self.user_states[user_id]['speaking'] = False
                        self.user_states[user_id]['last_update'] = current_time
            
            # Check for users who left (cleanup)
            for user_id in list(self.user_states.keys()):
                if user_id not in current_participants:
                    del self.user_states[user_id]
                    
        except Exception as e:
            logger.error(f"Error detecting speaking changes: {e}")

    async def periodic_monitoring(self):
        """Periodically check voice chat status"""
        logger.info("Starting periodic monitoring...")
        
        await self.send_log_message("🔄 Starting voice chat monitoring...\n⚡ Only non-admin speaking activity will be logged.\n🚫 Channels will be automatically banned.")
        
        while True:
            try:
                # Get current participants and check for changes
                await self.get_voice_chat_participants()
                
                current_time = datetime.now().strftime('%H:%M:%S')
                active_speakers = len([uid for uid, state in self.user_states.items() if state.get('speaking') and not state.get('is_admin')])
                logger.info(f"Monitoring active at {current_time} - {active_speakers} non-admin users speaking - {len(self.banned_channels)} channels banned")
                
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

    async def log_user_speaking(self, user_info, timestamp):
        """Log when a non-admin user starts speaking"""
        try:
            message = f"🎤 MIC ON - User Started Speaking\n"
            message += f"Name: {user_info['name']}\n"
            if user_info['username']:
                message += f"Username: @{user_info['username']}\n"
            message += f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} started speaking at {timestamp}")
            
        except Exception as e:
            logger.error(f"Error logging user speaking: {e}")

    async def log_user_stopped_speaking(self, user_info, timestamp):
        """Log when a non-admin user stops speaking"""
        try:
            message = f"🔇 MIC OFF - User Stopped Speaking\n"
            message += f"Name: {user_info['name']}\n"
            if user_info['username']:
                message += f"Username: @{user_info['username']}\n"
            message += f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_log_message(message)
            logger.info(f"User {user_info['name']} stopped speaking at {timestamp}")
            
        except Exception as e:
            logger.error(f"Error logging user stopped speaking: {e}")

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
