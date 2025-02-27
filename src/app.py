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
from texts.prompt_tamplates import CHATGPT_PROMPT_TEMPLATE
from database import MongoDB
from datetime import datetime, timezone
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
import base64

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
    "Russian": "🇷🇺 Russian",
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
FREE_TIER_DAILY_LIMIT = int(os.environ.get("FREE_TIER_DAILY_LIMIT", 10))  # 60 seconds per day

# Set up bot commands for menu
async def setup_bot_commands():
    """Set up bot commands that will be shown in the menu"""
    commands = [
        telebot.types.BotCommand("start", "Start the bot"),
        telebot.types.BotCommand("help", "Show help information"),
        telebot.types.BotCommand("premium", "Learn about premium features"),
        telebot.types.BotCommand("premium_audio", "Toggle Premium Audio mode (Premium only)")
    ]
    await bot.set_my_commands(commands)

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
        model="gpt-4o-mini",
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


# Функция для создания кнопок на языке пользователя
def create_user_interface_buttons(user_language="English"):
    """Create buttons in the user's language"""
    # Словарь с текстами кнопок на разных языках
    button_texts = {
        "English": {
            "text_in_english": "🇬🇧 Text the same in English",
            "hints": "🆘 I'm stuck! Hints, please",
            "finish": "🏁 Finish & get feedback",
            "word_count": "🔤 How many words did I say?"
        },
        "Russian": {
            "text_in_english": "🇬🇧 Написать то же самое на Английском",
            "hints": "🆘 Я застрял! Подсказки, пожалуйста",
            "finish": "🏁 Закончить и получить обратную связь",
            "word_count": "🔤 Сколько я наговорил?"
        },
        # Добавьте другие языки по мере необходимости
    }
    
    # Используем английский по умолчанию, если язык пользователя не поддерживается
    texts = button_texts.get(user_language, button_texts["English"])
    
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    
    # Создаем кнопки
    btn_english = telebot.types.KeyboardButton(texts["text_in_english"])
    btn_hints = telebot.types.KeyboardButton(texts["hints"])
    btn_finish = telebot.types.KeyboardButton(texts["finish"])
    btn_word_count = telebot.types.KeyboardButton(texts["word_count"])
    
    # Добавляем кнопки в разметку
    markup.add(btn_english)
    markup.row(btn_hints, btn_finish)
    markup.add(btn_word_count)
    
    return markup


@bot.message_handler(commands=['start'])
async def handle_start(message: telebot.types.Message):
    """Handler for the /start command"""
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    welcome_text = """
👋 Welcome to Talkify!

I'm a bot that can respond to your text and voice messages with AI-generated voice responses.
You can use me to practice your language skills with AI-generated voice responses.

Available commands:
• /help - Show help information
• /premium - Learn about premium features
"""

    if user.get("is_premium"):
        welcome_text += "• /language - Change your preferred language 🌐"
    else:
        welcome_text += "\n🔒 Upgrade to premium to unlock language selection and more features!"

    # Получаем язык пользователя
    user_language = user.get("language", "English")
    # Создаем клавиатуру на языке пользователя
    markup = create_user_interface_buttons(user_language)
    
    await bot.reply_to(message, welcome_text, reply_markup=markup)


@bot.message_handler(commands=['help'])
async def handle_help(message: telebot.types.Message):
    """Handler for the /help command"""
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    help_text = """
ℹ️ Help Information:

You can send me text or voice messages, and I'll respond with AI-generated voice.
This is perfect for practicing your language skills!

Available commands:
• /start - Start the bot
• /help - Show this help message
• /premium - Learn about premium features
"""

    if user.get("is_premium"):
        help_text += """• /language - Change your preferred language 🌐
• /premium_audio - Toggle Premium Audio mode for direct voice-to-voice AI conversations"""
    else:
        help_text += "\n🔒 Upgrade to premium to unlock language selection and more features!"

    # Получаем язык пользователя
    user_language = user.get("language", "English")
    # Создаем клавиатуру на языке пользователя
    markup = create_user_interface_buttons(user_language)
    
    # Добавляем информацию о текущем режиме Premium Audio
    if user.get("is_premium") and user.get("premium_audio_mode", False):
        help_text += "\n\n🎙️ Premium Audio Mode is currently ACTIVE. Send voice messages for direct AI processing."
    
    await bot.reply_to(message, help_text, reply_markup=markup)


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
    
    # Обновляем клавиатуру с кнопками на новом языке
    markup = create_user_interface_buttons(selected_language)
    await bot.send_message(
        call.message.chat.id,
        "Interface updated to your selected language.",
        reply_markup=markup
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


# Обработчики для кнопок интерфейса
@bot.message_handler(func=lambda message: message.text and "Text the same in English" in message.text or "Написать то же самое на Английском" in message.text)
async def handle_text_in_english(message: telebot.types.Message):
    """Handler for 'Text the same in English' button"""
    # Заглушка для будущей реализации
    await bot.reply_to(message, "This feature will be implemented soon!")


@bot.message_handler(func=lambda message: message.text and ("I'm stuck! Hints" in message.text or "Я застрял! Подсказки" in message.text))
async def handle_hints(message: telebot.types.Message):
    """Handler for 'I'm stuck! Hints, please' button"""
    # Заглушка для будущей реализации
    await bot.reply_to(message, "Hints feature will be implemented soon!")


@bot.message_handler(func=lambda message: message.text and ("Finish & get feedback" in message.text or "Закончить и получить обратную связь" in message.text))
async def handle_finish(message: telebot.types.Message):
    """Handler for 'Finish & get feedback' button"""
    # Заглушка для будущей реализации
    await bot.reply_to(message, "Feedback feature will be implemented soon!")


@bot.message_handler(func=lambda message: message.text and ("How many words did I say" in message.text or "Сколько я наговорил" in message.text))
async def handle_word_count(message: telebot.types.Message):
    """Handler for 'How many words did I say?' button"""
    # Заглушка для будущей реализации
    await bot.reply_to(message, "Word count feature will be implemented soon!")


@bot.message_handler(commands=['premium_audio'])
async def premium_audio_command(message: telebot.types.Message):
    """Handler for premium audio mode toggle"""
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    if not user.get("is_premium"):
        await bot.reply_to(
            message,
            "🔒 Premium Audio mode is a premium feature!\n\n"
            "Use /premium to upgrade and unlock:\n"
            "• Direct voice-to-voice AI conversations\n"
            "• Advanced audio processing with GPT-4o\n"
            "• No transcription needed - pure audio experience"
        )
        return
    
    # Переключаем режим Premium Audio
    current_mode = user.get("premium_audio_mode", False)
    new_mode = not current_mode
    
    # Обновляем настройки пользователя
    await db.users.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"premium_audio_mode": new_mode}}
    )
    
    if new_mode:
        response_text = "✅ Premium Audio mode is now ON!\n\nSend voice messages directly to the AI without transcription. The AI will respond with voice using advanced GPT-4o audio processing."
    else:
        response_text = "❌ Premium Audio mode is now OFF.\n\nReturning to standard mode with transcription."
    
    await bot.reply_to(message, response_text)


# Обновляем функцию для обработки аудио с помощью GPT-4o
async def process_audio_with_gpt4o(audio_file_path: str, user_language: str) -> tuple:
    """Process audio directly with GPT-4o audio model and get voice response"""
    try:
        with open(audio_file_path, 'rb') as audio_file:
            # Кодируем аудио в base64
            audio_bytes = audio_file.read()
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            
            # Определяем формат файла
            file_format = os.path.splitext(audio_file_path)[1][1:]  # Получаем расширение без точки
            
            # Создаем промпт для аудио модели на языке пользователя
            system_prompt = f"You are a helpful language practice assistant. Respond in {user_language}. Keep responses concise and helpful for language learning."
            
            # Отправляем запрос в модель
            response = await client.chat.completions.create(
                model="gpt-4o-mini-audio-preview",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": file_format}}
                        ]
                    }
                ],
                modalities=["text", "audio"],
                audio={"voice": "alloy", "format": "mp3"}
            )
            
            # Извлекаем текст и аудио из ответа
            response_text = response.choices[0].message.audio.transcript
            audio_data = base64.b64decode(response.choices[0].message.audio.data)
            print(response_text, audio_data)

            # Сохраняем аудио во временный файл
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                tmp_file.write(audio_data)
                voice_file_path = tmp_file.name
            
            return response_text, voice_file_path
    except Exception as e:
        print(f"Error processing audio with GPT-4o: {str(e)}")
        return f"Sorry, there was an error processing your audio: {str(e)}", None


@bot.message_handler(content_types=['voice', 'text'])
async def handle_message(message: telebot.types.Message):
    """Handle both voice and text messages"""
    # Проверяем, не является ли сообщение командой кнопки
    if message.text and any(keyword in message.text for keyword in [
        "Text the same in English", "I'm stuck! Hints", "Finish & get feedback", "How many words did I say",
        "Написать то же самое на Английском", "Я застрял! Подсказки", "Закончить и получить обратную связь", "Сколько я наговорил"
    ]):
        return  # Пропускаем обработку, так как это команда кнопки
        
    try:
        # Store or get user
        user = await db.get_or_create_user(
            message.from_user.id,
            message.from_user.username
        )

        # Get user's language
        user_language = user.get("language", "English")

        # Проверяем, включен ли режим Premium Audio
        premium_audio_mode = user.get("premium_audio_mode", False)
        
        # Если включен режим Premium Audio, но сообщение не голосовое
        if premium_audio_mode and message.content_type != 'voice':
            await bot.reply_to(
                message,
                "⚠️ Premium Audio mode is active! Please send a voice message for direct voice-to-voice AI conversation.\n\n"
                "To disable Premium Audio mode, use /premium_audio command."
            )
            return

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
        
        voice_file_path = None  # Initialize variable for cleanup

        # Обработка в зависимости от режима
        if premium_audio_mode and message.content_type == 'voice':
            # Premium Audio Mode - прямая обработка аудио без транскрибации
            
            # Download voice message
            file_info = await bot.get_file(message.voice.file_id)
            downloaded_file = await bot.download_file(file_info.file_path)

            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
                tmp_file.write(downloaded_file)
                voice_input_path = tmp_file.name
            
            # Обработка аудио напрямую с GPT-4o - получаем и текст, и аудио ответ
            response_text, voice_file_path = await process_audio_with_gpt4o(voice_input_path, user_language)
            
            # Очистка временного входного файла
            os.unlink(voice_input_path)
            
            # Приблизительная длительность ответа
            response_duration = len(response_text.split()) / 3  # rough estimate: 3 words per second
            
        else:
            # Стандартный режим с транскрибацией
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
                voice_file_path = None  # Reset variable after cleanup
            else:
                input_text = message.text

            # Generate ChatGPT response
            response_text = await generate_response(input_text, CHATGPT_PROMPT)
            
            # Приблизительная длительность ответа
            response_duration = len(response_text.split()) / 3  # rough estimate: 3 words per second

            # Generate voice response
            voice_file_path = await generate_voice(response_text)

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
            if voice_file_path and os.path.exists(voice_file_path):
                os.unlink(voice_file_path)  # Clean up temp file if we abort
            return

        # Store message in database with duration
        await db.add_message(
            message.from_user.id,
            input_text if 'input_text' in locals() else "[Premium Audio Mode - Direct Voice Processing]",
            response_text,
            response_duration
        )

        # Send voice message with hidden text response
        with open(voice_file_path, 'rb') as voice:
            # Добавляем индикатор режима Premium Audio
            mode_indicator = "🎙️ [Premium Audio] " if premium_audio_mode else ""
            
            await bot.send_voice(
                message.chat.id,
                voice,
                caption=f"{mode_indicator}💭 <tg-spoiler>{response_text}</tg-spoiler>",
                parse_mode='HTML',
            )

        # Clean up temporary voice file
        if voice_file_path and os.path.exists(voice_file_path):
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
    
    # Set up bot commands for the menu
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_bot_commands())
    
    if is_production:
        # In production, use the server's domain or IP
        webhook_base_url = os.getenv("WEBHOOK_URL")
        if not webhook_base_url:
            raise ValueError("WEBHOOK_URL environment variable must be set in production")
        
        # Set the webhook using the production URL
        loop.run_until_complete(set_webhook(webhook_base_url + "/webhook"))
        
        # Run FastAPI app on port 8080 (standard port for Google Cloud)
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8080)
    else:
        # In development, use ngrok as before
        public_url = start_ngrok(8000)
        
        # Set the webhook using the ngrok URL
        loop.run_until_complete(set_webhook(public_url + "/webhook"))
        
        # Run FastAPI app on port 8000 for local development
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
