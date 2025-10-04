import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, User, ChannelParticipant, ChannelParticipantSelf
from telethon.tl.functions.channels import EditBannedRequest, GetParticipantRequest
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
        
        # Track banned channels and participants
        self.banned_entities = set()
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
            
            # Get initial participants
            await self.scan_for_channels()
            
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
            
            await self.send_log_message(f"📞 Monitoring voice chat in: {group_title}\n🚫 Auto-banning all channels and channel participants\n⚡ Scan interval: 3 seconds")
            
        except Exception as e:
            logger.error(f"Error getting group info: {e}")
            await self.send_log_message(f"❌ Error accessing group: {e}")

    async def is_channel_entity(self, user):
        """Check if a user entity is a channel"""
        try:
            # Method 1: Direct type check (most reliable)
            if isinstance(user, Channel):
                logger.info(f"✅ Detected Channel by type: {getattr(user, 'title', 'Unknown')} (ID: {user.id})")
                return True

            # Method 2: Check for broadcast flag
            if hasattr(user, 'broadcast') and user.broadcast:
                logger.info(f"✅ Detected Channel by broadcast flag: {getattr(user, 'title', 'Unknown')} (ID: {user.id})")
                return True

            # Method 3: Check for megagroup flag
            if hasattr(user, 'megagroup') and user.megagroup:
                logger.info(f"✅ Detected Channel by megagroup flag: {getattr(user, 'title', 'Unknown')} (ID: {user.id})")
                return True

            # Method 4: Check if it has channel-like properties
            username = getattr(user, 'username', '')
            first_name = getattr(user, 'first_name', '')
            last_name = getattr(user, 'last_name', '')
            title = getattr(user, 'title', '')

            # If it has a title but no first/last name, it's likely a channel
            if title and not first_name and not last_name:
                logger.info(f"✅ Detected Channel by title only: {title} (ID: {user.id})")
                return True

            # If it has no personal name but has username
            if not first_name and not last_name and username:
                logger.info(f"✅ Detected Channel by username only: {username} (ID: {user.id})")
                return True

            return False
            
        except Exception as e:
            logger.error(f"Error checking if entity is channel: {e}")
            return False

    async def get_user_full_info(self, user_id):
        """Get full user info to properly detect channels"""
        try:
            user = await self.client.get_entity(user_id)
            
            # Log user details for debugging
            username = getattr(user, 'username', 'None')
            first_name = getattr(user, 'first_name', 'None')
            last_name = getattr(user, 'last_name', 'None')
            title = getattr(user, 'title', 'None')
            
            logger.info(f"🔍 Checking user: ID={user_id}, Username=@{username}, First={first_name}, Last={last_name}, Title={title}, Type={type(user)}")
            
            return user
        except Exception as e:
            logger.error(f"Error getting user full info for {user_id}: {e}")
            return None

    async def ban_entity(self, entity_id, entity_info):
        """Ban an entity from the group"""
        try:
            if entity_id in self.banned_entities:
                logger.info(f"Entity {entity_id} already banned, skipping")
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

            # Ban the entity
            await self.client(EditBannedRequest(
                channel=self.voice_chat_group_id,
                participant=entity_id,
                banned_rights=banned_rights
            ))
            
            self.banned_entities.add(entity_id)
            
            # Log the ban action
            await self.log_ban(entity_info)
            
            logger.info(f"Successfully banned: {entity_info['name']} (ID: {entity_id})")
            return True
            
        except FloodWaitError as e:
            logger.warning(f"Flood wait when banning {entity_id}: {e.seconds}s")
            await asyncio.sleep(e.seconds)
            return await self.ban_entity(entity_id, entity_info)
        except Exception as e:
            logger.error(f"Error banning {entity_id}: {e}")
            await self.send_log_message(f"❌ Failed to ban {entity_info['name']}: {str(e)}")
            return False

    async def log_ban(self, entity_info):
        """Log ban details"""
        try:
            message = f"🚫 BANNED FROM VOICE CHAT\n"
            message += f"📢 Name: {entity_info['name']}\n"
            message += f"🆔 ID: `{entity_info['id']}`\n"
            
            if entity_info.get('username'):
                message += f"👤 Username: @{entity_info['username']}\n"
            else:
                message += f"👤 Username: No username\n"
            
            message += f"📞 Type: {entity_info.get('type', 'Channel')}\n"
            message += f"⏰ Banned at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"🔒 Action: Permanently banned"
            
            await self.send_log_message(message)
            logger.info(f"Ban logged: {entity_info['name']}")
            
        except Exception as e:
            logger.error(f"Error logging ban: {e}")

    async def scan_for_channels(self):
        """Scan voice chat for channels and ban them immediately"""
        try:
            group = await self.client.get_entity(self.voice_chat_group_id)
            
            # Get all current participants
            current_participants = set()
            participants_list = []
            
            try:
                async for user in self.client.iter_participants(group, limit=200):
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
            
            # Check all participants
            for participant in participants_list:
                if participant.bot:
                    continue
                    
                # Skip if already banned
                if participant.id in self.banned_entities:
                    continue
                
                # Get full user info for better detection
                full_user = await self.get_user_full_info(participant.id)
                if not full_user:
                    continue
                    
                # Check if it's a channel
                if await self.is_channel_entity(full_user):
                    user_id = participant.id
                    username = getattr(full_user, 'username', '')
                    first_name = getattr(full_user, 'first_name', '')
                    last_name = getattr(full_user, 'last_name', '')
                    title = getattr(full_user, 'title', '')
                    
                    # Create display name
                    if title:
                        display_name = title
                    elif first_name and last_name:
                        display_name = f"{first_name} {last_name}"
                    elif first_name:
                        display_name = first_name
                    else:
                        display_name = f"Channel{user_id}"
                    
                    entity_info = {
                        'id': user_id,
                        'name': display_name,
                        'username': username,
                        'type': 'Channel'
                    }
                    
                    logger.info(f"🎯 Attempting to ban channel: {display_name} (ID: {user_id})")
                    
                    # Ban the channel immediately
                    success = await self.ban_entity(user_id, entity_info)
                    if success:
                        channels_found += 1
            
            # Update last participants
            self.last_participants = current_participants
            
            if channels_found > 0:
                logger.info(f"✅ Found and banned {channels_found} channels")
            elif new_participants:
                logger.info(f"❌ No channels found among {len(new_participants)} new participants")
                
        except Exception as e:
            logger.error(f"Error in scan_for_channels: {e}")

    async def periodic_monitoring(self):
        """Periodically scan for channels every 3 seconds"""
        logger.info("Starting periodic channel scanning...")
        
        scan_count = 0
        
        while True:
            try:
                # Scan for channels
                await self.scan_for_channels()
                
                scan_count += 1
                current_time = datetime.now().strftime('%H:%M:%S')
                
                # Log status every 10 scans
                if scan_count % 10 == 0:
                    logger.info(f"Scan #{scan_count} at {current_time} - {len(self.banned_entities)} total bans")
                
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
