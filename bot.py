import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
from telethon.errors import FloodWaitError
from telegram import Bot

# Import config directly
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN, LOG_GROUP_ID, VOICE_CHAT_GROUP_ID, CHECK_INTERVAL

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ChannelBanMonitor:
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
        
        # Track banned channels to avoid duplicate actions
        self.banned_channels = set()
        self.processed_participants = set()
        
        # Flood control
        self.last_participant_check = None
        self.min_check_interval = 10  # Minimum seconds between checks
        
        logger.info("Channel Ban Monitor initialized")

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
            await self.send_log_message(f"🚀 Channel Ban Monitor Started!\nLogged in as: {me.first_name} (@{me.username})")
            
            # Get group info
            await self.get_group_info()
            
            # Start periodic monitoring
            asyncio.create_task(self.periodic_monitoring())
            
            logger.info("Channel Ban Monitor started successfully")
            
            # Keep the client running
            await asyncio.Future()
            
        except Exception as e:
            logger.error(f"Failed to start: {str(e)}")
            await self.send_log_message(f"❌ Failed to start: {str(e)}")
            raise

    async def get_group_info(self):
        """Get basic group information"""
        try:
            group = await self.client.get_entity(self.voice_chat_group_id)
            group_title = getattr(group, 'title', 'Unknown Group')
            logger.info(f"Monitoring group: {group_title}")
            
            await self.send_log_message(f"📞 Monitoring voice chat in: {group_title}\n🚫 Auto-banning all channels")
            
        except Exception as e:
            logger.error(f"Error getting group info: {e}")
            await self.send_log_message(f"❌ Error accessing group: {e}")

    async def is_channel(self, user):
        """Check if a user is a channel with multiple detection methods"""
        try:
            # Method 1: Check if it's a Channel type
            if isinstance(user, Channel):
                return True
            
            # Method 2: Check user attributes
            if hasattr(user, 'bot') and user.bot:
                return False  # Skip bots
                
            # Method 3: Check for channel-specific attributes
            if hasattr(user, 'broadcast') and user.broadcast:
                return True
                
            if hasattr(user, 'megagroup') and user.megagroup:
                return True
                
            # Method 4: Check username patterns
            if hasattr(user, 'username') and user.username:
                username_lower = user.username.lower()
                if any(pattern in username_lower for pattern in ['channel', 'chat', 'group', 'bot']):
                    return True
                    
            # Method 5: Check if first_name/last_name suggests it's a channel
            first_name = getattr(user, 'first_name', '').lower()
            last_name = getattr(user, 'last_name', '').lower()
            full_name = f"{first_name} {last_name}".strip()
            
            channel_keywords = ['channel', 'chat', 'group', 'news', 'broadcast', 'telegram']
            if any(keyword in full_name for keyword in channel_keywords):
                return True
                
            # Method 6: Check if it has no first name but has username (common for channels)
            if not first_name and not last_name and hasattr(user, 'username') and user.username:
                return True
                
            # Method 7: Check for verified channels
            if hasattr(user, 'verified') and user.verified:
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking if user is channel: {e}")
            return False

    async def ban_channel(self, channel_id, channel_info):
        """Ban a channel from the group"""
        try:
            if channel_id in self.banned_channels:
                logger.info(f"Channel {channel_id} already banned, skipping")
                return False

            # Create banned rights (ban forever)
            banned_rights = ChatBannedRights(
                until_date=None,
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
            
        except FloodWaitError as e:
            logger.warning(f"Flood wait when banning channel {channel_id}: {e.seconds}s")
            await asyncio.sleep(e.seconds)
            return await self.ban_channel(channel_id, channel_info)
        except Exception as e:
            logger.error(f"Error banning channel {channel_id}: {e}")
            await self.send_log_message(f"❌ Failed to ban channel {channel_info['name']}: {str(e)}")
            return False

    async def log_channel_ban(self, channel_info):
        """Log channel ban details"""
        try:
            message = f"🚫 CHANNEL BANNED FROM VOICE CHAT\n"
            message += f"📢 Channel Name: {channel_info['name']}\n"
            message += f"🆔 Channel ID: `{channel_info['id']}`\n"
            
            if channel_info.get('username'):
                message += f"👤 Username: @{channel_info['username']}\n"
            else:
                message += f"👤 Username: No username\n"
            
            message += f"📞 Type: {'Public' if channel_info.get('username') else 'Private'} channel\n"
            message += f"⏰ Banned at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"🔒 Action: Permanently banned from group"
            
            await self.send_log_message(message)
            logger.info(f"Channel ban logged: {channel_info['name']}")
            
        except Exception as e:
            logger.error(f"Error logging channel ban: {e}")

    async def scan_for_channels(self):
        """Scan voice chat for channels and ban them immediately"""
        try:
            # Check if we should skip due to flood control
            current_time = datetime.now()
            if (self.last_participant_check and 
                (current_time - self.last_participant_check).total_seconds() < self.min_check_interval):
                return
                
            self.last_participant_check = current_time
            
            group = await self.client.get_entity(self.voice_chat_group_id)
            
            # Get recent participants
            recent_participants = []
            try:
                async for user in self.client.iter_participants(group, limit=100):
                    recent_participants.append(user)
            except FloodWaitError as e:
                logger.warning(f"Flood wait getting participants: {e.seconds}s")
                await asyncio.sleep(e.seconds)
                return
            
            channels_found = 0
            
            for participant in recent_participants:
                if participant.bot:
                    continue
                    
                # Skip if already processed
                if participant.id in self.processed_participants:
                    continue
                    
                # Check if it's a channel
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
                    success = await self.ban_channel(user_id, channel_info)
                    if success:
                        channels_found += 1
                
                # Mark as processed
                self.processed_participants.add(participant.id)
            
            if channels_found > 0:
                logger.info(f"Found and banned {channels_found} channels")
                
        except Exception as e:
            logger.error(f"Error in scan_for_channels: {e}")

    async def periodic_monitoring(self):
        """Periodically scan for channels"""
        logger.info("Starting periodic channel scanning...")
        
        await self.send_log_message("🔄 Starting channel ban monitoring...\n🚫 All channels will be automatically banned.")
        
        while True:
            try:
                # Scan for channels
                await self.scan_for_channels()
                
                current_time = datetime.now().strftime('%H:%M:%S')
                logger.info(f"Channel scan completed at {current_time} - {len(self.banned_channels)} total channels banned")
                
                # Use config interval
                await asyncio.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in periodic monitoring: {e}")
                await asyncio.sleep(30)  # Wait 30 seconds on error

    async def send_log_message(self, message):
        """Send message to log group"""
        try:
            await self.bot.send_message(
                chat_id=self.log_group_id,
                text=message
            )
            logger.info(f"Log message sent: {message[:50]}...")
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
    monitor = ChannelBanMonitor()
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
