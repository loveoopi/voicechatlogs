import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, User
from telethon.tl.functions.channels import EditBannedRequest, GetFullChannelRequest
from telethon.tl.types import ChatBannedRights
from telethon.errors import FloodWaitError
from telegram import Bot

# Import config directly
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN, LOG_GROUP_ID, VOICE_CHAT_GROUP_ID

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
        self.last_participants = set()
        
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
            
            await self.send_log_message(f"📞 Monitoring voice chat in: {group_title}\n🚫 Auto-banning all channels\n⚡ Scan interval: 3 seconds")
            
        except Exception as e:
            logger.error(f"Error getting group info: {e}")
            await self.send_log_message(f"❌ Error accessing group: {e}")

    async def is_channel_participant(self, participant):
        """Check if a participant is a channel by examining their user object"""
        try:
            user_id = participant.id
            
            # Get full user info
            try:
                user = await self.client.get_entity(user_id)
            except Exception as e:
                logger.error(f"Error getting user entity {user_id}: {e}")
                return False

            # Method 1: Direct type check
            if isinstance(user, Channel):
                logger.info(f"Detected channel by type: {getattr(user, 'title', 'Unknown')} (ID: {user_id})")
                return True

            # Method 2: Check for broadcast flag
            if hasattr(user, 'broadcast') and user.broadcast:
                logger.info(f"Detected channel by broadcast flag: {getattr(user, 'title', 'Unknown')} (ID: {user_id})")
                return True

            # Method 3: Check for megagroup flag
            if hasattr(user, 'megagroup') and user.megagroup:
                logger.info(f"Detected channel by megagroup flag: {getattr(user, 'title', 'Unknown')} (ID: {user_id})")
                return True

            # Method 4: Check participant count (channels have participants_count > 0)
            if hasattr(user, 'participants_count') and getattr(user, 'participants_count', 0) > 0:
                logger.info(f"Detected channel by participants count: {getattr(user, 'title', 'Unknown')} (ID: {user_id})")
                return True

            # Method 5: Check if it's a channel by username pattern and lack of personal info
            username = getattr(user, 'username', '')
            first_name = getattr(user, 'first_name', '')
            last_name = getattr(user, 'last_name', '')
            title = getattr(user, 'title', '')

            # If it has a title but no first/last name, it's likely a channel
            if title and not first_name and not last_name:
                logger.info(f"Detected channel by title only: {title} (ID: {user_id})")
                return True

            # If it has channel-like username and no personal name
            if username and any(keyword in username.lower() for keyword in ['channel', 'chat', 'group']) and not first_name:
                logger.info(f"Detected channel by username pattern: {username} (ID: {user_id})")
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
            group = await self.client.get_entity(self.voice_chat_group_id)
            
            # Get all current participants
            current_participants = set()
            participants_list = []
            
            try:
                async for user in self.client.iter_participants(group, limit=150):
                    current_participants.add(user.id)
                    participants_list.append(user)
            except FloodWaitError as e:
                logger.warning(f"Flood wait getting participants: {e.seconds}s")
                await asyncio.sleep(e.seconds)
                return
            
            # Find new participants
            new_participants = current_participants - self.last_participants
            
            if new_participants:
                logger.info(f"Found {len(new_participants)} new participants")
            
            channels_found = 0
            
            # Check all participants, but focus on new ones
            for participant in participants_list:
                if participant.bot:
                    continue
                    
                # Skip if already banned
                if participant.id in self.banned_channels:
                    continue
                    
                # Check if it's a channel
                if await self.is_channel_participant(participant):
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
                    
                    logger.info(f"Attempting to ban channel: {display_name} (ID: {user_id})")
                    
                    # Ban the channel immediately
                    success = await self.ban_channel(user_id, channel_info)
                    if success:
                        channels_found += 1
            
            # Update last participants
            self.last_participants = current_participants
            
            if channels_found > 0:
                logger.info(f"Found and banned {channels_found} channels")
                
        except Exception as e:
            logger.error(f"Error in scan_for_channels: {e}")

    async def periodic_monitoring(self):
        """Periodically scan for channels every 3 seconds"""
        logger.info("Starting periodic channel scanning...")
        
        await self.send_log_message("🔄 Starting channel ban monitoring...\n🚫 All channels will be automatically banned.\n⚡ Scan interval: 3 seconds")
        
        scan_count = 0
        
        while True:
            try:
                # Scan for channels
                await self.scan_for_channels()
                
                scan_count += 1
                current_time = datetime.now().strftime('%H:%M:%S')
                
                # Log status every 5 scans to avoid spam
                if scan_count % 5 == 0:
                    logger.info(f"Scan #{scan_count} completed at {current_time} - {len(self.banned_channels)} total channels banned")
                
                # Fast scan interval: 3 seconds
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Error in periodic monitoring: {e}")
                await asyncio.sleep(3)

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
