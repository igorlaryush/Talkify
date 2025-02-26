"""Telegram bot implementation using FastAPI and ngrok for webhook handling."""

import os
import asyncio
from fastapi import FastAPI, Request
from telebot.async_telebot import AsyncTeleBot
import telebot.types
from pyngrok import ngrok
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pathlib import Path
import tempfile
from texts import CHATGPT_PROMPT_TEMPLATE
from database import MongoDB
from datetime import datetime, timezone
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage

# read .env file
load_dotenv()

# get tokens from .env file
API_TOKEN = os.getenv("API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Configure OpenAI
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Add available languages
AVAILABLE_LANGUAGES = {
    "English": "🇬🇧 English",
    "Spanish": "🇪🇸 Spanish",
    "French": "🇫🇷 French",
    "German": "🇩🇪 German",
    "Italian": "🇮🇹 Italian",
    "Portuguese": "🇵🇹 Portuguese",
}

# Create state storage
state_storage = StateMemoryStorage()
bot = AsyncTeleBot(API_TOKEN, state_storage=state_storage)

# Initialize FastAPI app
app = FastAPI()

# Add after loading environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://admin:admin@localhost:27017/")
db = MongoDB(MONGO_URL)

# Add constants for time limits
FREE_TIER_DAILY_LIMIT = 10  # 60 seconds per day

def start_ngrok(port: int):
    "Function to start ngrok and get the public URL"
    # Open a ngrok tunnel on the given port
    url = ngrok.connect(port).public_url
    print(f"Ngrok tunnel \"{url}\" is now live!")
    return url


@app.post("/webhook")
async def webhook_endpoint(request: Request):
    "Function to handle the webhook"
    json_data = await request.json()
    # Parse the incoming JSON update from Telegram
    update = telebot.types.Update.de_json(json_data)
    # Process the update asynchronously
    await bot.process_new_updates([update])
    return "ok"


async def transcribe_voice(file_path: str) -> str:
    """Transcribe voice message using OpenAI Whisper"""
    with open(file_path, 'rb') as audio_file:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
        return transcript.text


async def generate_response(message: str, CHATGPT_PROMPT: str) -> str:
    """Generate response using ChatGPT"""
    response = await client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": CHATGPT_PROMPT},
            {"role": "user", "content": message}
        ]
    )
    return response.choices[0].message.content


async def generate_voice(text: str) -> str:
    """Generate voice message using OpenAI TTS"""
    response = await client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text
    )

    # Save the audio to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
        tmp_file.write(response.content)
        return tmp_file.name


@bot.message_handler(commands=['start', 'help'])
async def send_welcome(message: telebot.types.Message):
    """Function to send the welcome message"""
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    welcome_text = """
Hello! I'm a bot that can respond to your text and voice messages with AI-generated voice responses.
You can use me to practice your language skills with AI-generated voice responses.

Available commands:
• /help - Show this help message
• /premium - Learn about premium features
"""

    if user.get("is_premium"):
        welcome_text += "• /language - Change your preferred language 🌐"
    else:
        welcome_text += "\n🔒 Upgrade to premium to unlock language selection and more features!"

    await bot.reply_to(message, welcome_text)


@bot.message_handler(commands=['premium'])
async def handle_premium(message: telebot.types.Message):
    """Handler for premium subscription"""
    try:
        # Open and send the local premium image
        with open("src/assets/paywall.png", 'rb') as photo:
            await bot.send_photo(
                message.chat.id,
                photo,
                caption="""🌟 Upgrade to Premium! 
With premium subscription you get:
• Unlimited voice responses
• Priority message processing
• Advanced language practice features
• Multiple language selection 🌐

Contact @igor_laryush to purchase premium."""
            )
    except FileNotFoundError:
        # Fallback if image is not found
        await bot.send_message(
            message.chat.id,
            """🌟 Upgrade to Premium! 
            
With premium subscription you get:
• Unlimited voice responses
• Priority message processing
• Advanced language practice features
• Multiple language selection 🌐

Contact @igor_laryush to purchase premium."""
        )


@bot.message_handler(commands=['language'])
async def language_command(message: telebot.types.Message):
    """Handle language selection command"""
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    if not user.get("is_premium"):
        await bot.reply_to(
            message,
            "🔒 Language selection is a premium feature!\n\n"
            "Use /premium to upgrade and unlock:\n"
            "• Custom language selection\n"
            "• Unlimited voice responses\n"
            "• Priority message processing"
        )
        return

    markup = telebot.types.InlineKeyboardMarkup()
    for lang_code, lang_name in AVAILABLE_LANGUAGES.items():
        markup.add(telebot.types.InlineKeyboardButton(
            text=lang_name,
            callback_data=f"lang_{lang_code}"
        ))

    await bot.send_message(
        message.chat.id,
        "🌐 Select your preferred language:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
async def callback_language(call: telebot.types.CallbackQuery):
    """Handle language selection callback"""
    user = await db.get_or_create_user(call.from_user.id)
    
    if not user.get("is_premium"):
        await bot.answer_callback_query(
            call.id,
            "This feature is only available for premium users! Use /premium to upgrade.",
            show_alert=True
        )
        return

    selected_language = call.data.replace('lang_', '')
    await db.set_user_language(call.from_user.id, selected_language)
    
    await bot.answer_callback_query(call.id)
    await bot.edit_message_text(
        f"✅ Language set to {AVAILABLE_LANGUAGES[selected_language]}",
        call.message.chat.id,
        call.message.message_id
    )


async def check_usage_limits(user_id: int) -> tuple[bool, float]:
    """Check if user has exceeded their daily limit
    Returns (has_access, remaining_seconds)
    """
    user = await db.users.find_one({"user_id": user_id})
    if user.get("is_premium"):
        return True, float('inf')

    total_duration = await db.get_total_voice_duration(user_id)
    remaining_seconds = FREE_TIER_DAILY_LIMIT - total_duration

    return remaining_seconds > 0, remaining_seconds


@bot.message_handler(content_types=['voice', 'text'])
async def handle_message(message: telebot.types.Message):
    """Handle both voice and text messages"""
    try:
        # Store or get user
        user = await db.get_or_create_user(
            message.from_user.id,
            message.from_user.username
        )

        # Get user's language
        user_language = user.get("language", "English")

        # Update CHATGPT_PROMPT with user's language
        CHATGPT_PROMPT = CHATGPT_PROMPT_TEMPLATE.substitute(
            language=user_language,
            domain="language practice"
        )

        # Check usage limits
        has_access, remaining_seconds = await check_usage_limits(message.from_user.id)
        
        if not has_access:
            await bot.reply_to(
                message,
                f"""⚠️ You've reached your daily limit for voice responses!

                🌟 Upgrade to Premium for unlimited access!
                
                Use /premium to learn more about premium features.
                
                Your limit will reset in {24 - datetime.now(timezone.utc).hour} hours."""
            )
            return

        # Уведомление о записи голоса
        await bot.send_chat_action(message.chat.id, 'record_voice')

        # Get input text either from voice or text message
        if message.content_type == 'voice':
            # Download voice message
            file_info = await bot.get_file(message.voice.file_id)
            downloaded_file = await bot.download_file(file_info.file_path)

            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
                tmp_file.write(downloaded_file)
                voice_file_path = tmp_file.name

            # Transcribe voice to text
            input_text = await transcribe_voice(voice_file_path)
            os.unlink(voice_file_path)  # Clean up temp file
        else:
            input_text = message.text

        # Generate ChatGPT response
        response_text = await generate_response(input_text, CHATGPT_PROMPT)

        # Generate voice response
        voice_file_path = await generate_voice(response_text)

        # Calculate response duration (approximate)
        response_duration = len(response_text.split()) / 3  # rough estimate: 3 words per second

        # Check if this response would exceed the limit
        if not user.get("is_premium") and remaining_seconds < response_duration:
            await bot.reply_to(
                message,
                f"""⚠️ This response would exceed your daily limit!
                
                Remaining time: {remaining_seconds:.1f} seconds
                Response length: {response_duration:.1f} seconds
                
                🌟 Upgrade to Premium for unlimited access!
                Use /premium to learn more."""
            )
            os.unlink(voice_file_path)
            return

        # Store message in database with duration
        await db.add_message(
            message.from_user.id,
            input_text,
            response_text,
            response_duration
        )

        # Send voice message with hidden text response
        with open(voice_file_path, 'rb') as voice:
            await bot.send_voice(
                message.chat.id,
                voice,
                caption=f"💭 <tg-spoiler>{response_text}</tg-spoiler>",
                parse_mode='HTML',
            )

        # Clean up temporary voice file
        os.unlink(voice_file_path)

    except Exception as e:
        await bot.reply_to(message, f"Sorry, an error occurred: {str(e)}")


async def set_webhook(webhook_url: str):
    "Function to configure the webhook with Telegram"
    await bot.remove_webhook()
    await bot.set_webhook(url=webhook_url)

# Main entry point
if __name__ == "__main__":
    # Check if we're running in production (on Google Cloud)
    is_production = os.getenv("ENVIRONMENT") == "production"
    
    if is_production:
        # In production, use the server's domain or IP
        webhook_base_url = os.getenv("WEBHOOK_URL")
        if not webhook_base_url:
            raise ValueError("WEBHOOK_URL environment variable must be set in production")
        
        # Set the webhook using the production URL
        loop = asyncio.get_event_loop()
        loop.run_until_complete(set_webhook(webhook_base_url + "/webhook"))
        
        # Run FastAPI app on port 8080 (standard port for Google Cloud)
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8080)
    else:
        # In development, use ngrok as before
        public_url = start_ngrok(8000)
        
        # Set the webhook using the ngrok URL
        loop = asyncio.get_event_loop()
        loop.run_until_complete(set_webhook(public_url + "/webhook"))
        
        # Run FastAPI app on port 8000 for local development
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
