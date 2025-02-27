"""
Migration script to add premium_audio_mode field to existing users
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get MongoDB connection URL
MONGO_URL = os.getenv("MONGO_URL", "mongodb://admin:admin@localhost:27017/")

async def migrate():
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URL)
    db = client.telegram_bot
    users = db.users
    
    print("Starting migration: Adding premium_audio_mode field to users...")
    
    # Update all users that don't have the premium_audio_mode field
    result = await users.update_many(
        {"premium_audio_mode": {"$exists": False}},
        {"$set": {"premium_audio_mode": False}}
    )
    
    print(f"Migration completed. Updated {result.modified_count} users.")
    
    # Optional: Verify the migration
    total_users = await users.count_documents({})
    users_with_field = await users.count_documents({"premium_audio_mode": {"$exists": True}})
    
    print(f"Total users: {total_users}")
    print(f"Users with premium_audio_mode field: {users_with_field}")
    
    if total_users == users_with_field:
        print("All users have been successfully updated!")
    else:
        print(f"Warning: {total_users - users_with_field} users still don't have the premium_audio_mode field.")
    
    # Close the connection
    client.close()

if __name__ == "__main__":
    # Run the migration
    asyncio.run(migrate()) 