from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
import asyncio


class MongoDB:
    def __init__(self, connection_url: str):
        self.client = AsyncIOMotorClient(connection_url)
        self.client.get_io_loop = asyncio.get_running_loop
        self.db = self.client.telegram_bot
        self.users = self.db.users
        self.messages = self.db.messages

    async def get_or_create_user(self, user_id: int, username: Optional[str] = None) -> Dict:
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            user = {
                "user_id": user_id,
                "username": username,
                "is_premium": False,
                "language": "English",  # Default language
                "premium_audio_mode": False,  # Default Premium Audio mode setting
                "created_at": datetime.now(timezone.utc)
            }
            await self.users.insert_one(user)
        return user

    async def add_message(self, user_id: int, input_text: str, response_text: str, response_duration: float):
        message = {
            "user_id": user_id,
            "input_text": input_text,
            "response_text": response_text,
            "response_duration": response_duration,
            "created_at": datetime.now(timezone.utc)
        }
        await self.messages.insert_one(message)
        return message

    async def get_user_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        cursor = self.messages.find({"user_id": user_id}).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_total_voice_duration(self, user_id: int) -> float:
        """Get total duration of voice responses in the last 24 hours"""
        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        cursor = self.messages.find({
            "user_id": user_id,
            "created_at": {"$gte": twenty_four_hours_ago}
        })
        total_duration = 0.0
        async for message in cursor:
            total_duration += message.get("response_duration", 0)
        return total_duration

    async def set_premium_status(self, user_id: int, is_premium: bool):
        """Update user's premium status"""
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_premium": is_premium}}
        )

    async def set_user_language(self, user_id: int, language: str):
        """Update user's preferred language"""
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"language": language}}
        )
        
    async def set_premium_audio_mode(self, user_id: int, enabled: bool):
        """Update user's Premium Audio mode setting"""
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"premium_audio_mode": enabled}}
        )

    async def add_conversation(self, user_id: int, topic: str, messages: list, feedback: str):
        """Store a completed conversation with feedback"""
        conversation = {
            "user_id": user_id,
            "topic": topic,
            "messages": messages,
            "feedback": feedback,
            "created_at": datetime.now(timezone.utc)
        }
        await self.db.conversations.insert_one(conversation)
        return conversation

    async def get_user_conversations(self, user_id: int, limit: int = 5) -> List[Dict]:
        """Get user's recent conversations"""
        cursor = self.db.conversations.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
