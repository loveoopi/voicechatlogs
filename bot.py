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
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN, LOG_GROUP_ID, VOICE_CHAT_GROUP_ID

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VoiceChatChannelMonitor:
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
        
        # Track banned channels and voice chat participants
        self.banned_channels = set()
        self.current_voice_participants = set()
        
        logger.info("Voice Chat Channel Monitor initialized")

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
            await self.send_log_message(f"🚀 Voice Chat Channel Monitor Started!\nLogged in as: {me.first_name} (@{me.username})")
            
            # Get group info
            await self.get_group_info()
            
            # Start periodic monitoring
            asyncio.create_task(self.periodic_monitoring())
            
            logger.info("Voice Chat Channel Monitor started successfully")
            
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
            logger.info(f"Monitoring voice chat in group: {group_title}")
            
            await self.send_log_message(f"📞 Monitoring voice chat in: {group_title}\n🚫 Auto-banning all channels in voice chat\n⚡ Scan interval: 3 seconds")
            
        except Exception as e:
            logger.error(f"Error getting group info: {e}")
            await self.send_log_message(f"❌ Error accessing group: {e}")

    async def get_voice_chat_participants(self):
        """Get current participants in the active voice chat"""
        try:
            # Get the group
            group = await self.client.get_entity(self.voice_chat_group_id)
            
            # Get active voice chat participants
            # Note: This uses Telethon's methods to get current call participants
            call = await self.client.get_active_call(group)
            
            if not call:
                logger.info("No active voice chat found")
                return set()
            
            voice_participants = set()
            
            # Get participants from the active call
            participants = await self.client.get_call_participants(call)
            
            for participant in participants:
                user_id = participant.user_id
                voice_participants.add(user_id)
                
                # Get user details for logging
                try:
                    user = await self.client.get_entity(user_id)
                    username = getattr(user, 'username', '')
                    first_name = getattr(user, 'first_name', '')
                    last_name = getattr(user, 'last_name', '')
                    
                    logger.info(f"Voice chat participant: {first_name} {last_name} (@{username}) ID: {user_id}")
                    
                except Exception as e:
                    logger.error(f"Error getting user info for {user_id}: {e}")
            
            return voice_participants
            
        except Exception as e:
            logger.info(f"No active voice chat or error getting participants: {e}")
            return set()

    async def is_channel_user(self, user_id):
        """Check if a user is a channel"""
        try:
            user = await self.client.get_entity(user_id)
            
            # Method 1: Direct type check
            if isinstance(user, Channel):
                return True
                
            # Method 2: Check for broadcast flag
            if hasattr(user, 'broadcast') and user.broadcast:
                return True
                
            # Method 3: Check for megagroup flag
            if hasattr(user, 'megagroup') and user.megagroup:
                return True
                
            # Method 4: Check if it has channel-like properties
            username = getattr(user, 'username', '')
            first_name = getattr(user, 'first_name', '')
            last_name = getattr(user, 'last_name', '')
            title = getattr(user, 'title', '')
            
            # If it has a title but no first/last name, it's likely a channel
            if title and not first_name and not last_name:
                return True
                
            # If it has no personal name but has username
            if not first_name and not last_name and username:
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking if user {user_id} is channel: {e}")
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
            
            logger.info(f"Successfully banned channel from voice chat: {channel_info['name']} (ID: {channel_id})")
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

    async def monitor_voice_chat(self):
        """Monitor active voice chat for channels"""
        try:
            # Get current voice chat participants
            current_participants = await self.get_voice_chat_participants()
            
            # Find new participants in voice chat
            new_participants = current_participants - self.current_voice_participants
            
            if new_participants:
                logger.info(f"Found {len(new_participants)} new participants in voice chat")
            
            channels_found = 0
            
            # Check new participants for channels
            for user_id in new_participants:
                # Skip if already banned
                if user_id in self.banned_channels:
                    continue
                    
                # Check if this user is a channel
                if await self.is_channel_user(user_id):
                    # Get channel details
                    try:
                        user = await self.client.get_entity(user_id)
                        username = getattr(user, 'username', '')
                        first_name = getattr(user, 'first_name', '')
                        last_name = getattr(user, 'last_name', '')
                        title = getattr(user, 'title', '')
                        
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
                        
                        logger.info(f"🎯 Detected channel in voice chat: {display_name} (ID: {user_id})")
                        
                        # Ban the channel immediately
                        success = await self.ban_channel(user_id, channel_info)
                        if success:
                            channels_found += 1
                            
                    except Exception as e:
                        logger.error(f"Error getting channel info for {user_id}: {e}")
            
            # Update current voice participants
            self.current_voice_participants = current_participants
            
            if channels_found > 0:
                logger.info(f"✅ Found and banned {channels_found} channels from voice chat")
                
        except Exception as e:
            logger.error(f"Error in monitor_voice_chat: {e}")

    async def periodic_monitoring(self):
        """Periodically monitor voice chat every 3 seconds"""
        logger.info("Starting voice chat monitoring...")
        
        scan_count = 0
        
        while True:
            try:
                # Monitor voice chat for channels
                await self.monitor_voice_chat()
                
                scan_count += 1
                current_time = datetime.now().strftime('%H:%M:%S')
                
                # Log status every 10 scans
                if scan_count % 10 == 0:
                    logger.info(f"Voice chat scan #{scan_count} at {current_time} - {len(self.banned_channels)} total channels banned")
                
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
    monitor = VoiceChatChannelMonitor()
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
