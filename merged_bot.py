import os
import re
import uuid
import logging
import threading
from flask import Flask, request
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

# Load environment variables
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, ".env"))
if not os.getenv("CHAR_BOT_TOKEN"):
    load_dotenv(os.path.join(script_dir, "env.txt"))

CHAR_TOKEN = os.getenv("CHAR_BOT_TOKEN")
VIDEO_TOKEN = os.getenv("VIDEO_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ensure downloads directory exists
downloads_dir = os.path.join(script_dir, "downloads")
os.makedirs(downloads_dir, exist_ok=True)

# Initialize bots
bot_char = telebot.TeleBot(CHAR_TOKEN) if CHAR_TOKEN else None
bot_video = telebot.TeleBot(VIDEO_TOKEN) if VIDEO_TOKEN else None

app = Flask(__name__)

# Webhook route for Character Counter Bot
@app.route('/webhook_char', methods=['POST'])
def webhook_char():
    if bot_char and request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot_char.process_new_updates([update])
        return 'OK', 200
    return 'Forbidden', 403

# Webhook route for Video Downloader Bot
@app.route('/webhook_video', methods=['POST'])
def webhook_video():
    if bot_video and request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot_video.process_new_updates([update])
        return 'OK', 200
    return 'Forbidden', 403

# Set up Webhooks on startup if WEBHOOK_URL is available
if WEBHOOK_URL:
    # Ensure any trailing slash is removed from WEBHOOK_URL
    clean_webhook_url = WEBHOOK_URL.rstrip('/')
    if bot_char:
        logger.info(f"Setting Char Bot webhook to {clean_webhook_url}/webhook_char...")
        bot_char.remove_webhook()
        bot_char.set_webhook(url=f"{clean_webhook_url}/webhook_char")
    if bot_video:
        logger.info(f"Setting Video Bot webhook to {clean_webhook_url}/webhook_video...")
        bot_video.remove_webhook()
        bot_video.set_webhook(url=f"{clean_webhook_url}/webhook_video")

# --- CHARACTER COUNTER LOGIC ---
if bot_char:
    @bot_char.message_handler(commands=['start', 'help'])
    def char_welcome(message):
        welcome_text = (
            "🤖 **Welcome to Character Counter Bot!**\n\n"
            "I can help you quickly count characters, words, and lines in your text.\n\n"
            "👉 **How to use:**\n"
            "1. **Forward** a message from any chat or channel to me.\n"
            "2. Or simply send/type a message directly to me.\n\n"
            "I will immediately reply with a detailed count analysis!"
        )
        bot_char.reply_to(message, welcome_text, parse_mode="Markdown")

    @bot_char.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
    def char_analyze(message):
        text = message.text or message.caption
        if not text:
            bot_char.reply_to(message, "⚠️ **No text found!**\n\nPlease forward or send a message that contains text or a caption.", parse_mode="Markdown")
            return
        char_count_total = len(text)
        char_count_no_spaces = len(text.replace(" ", "").replace("\n", "").replace("\r", "\t").replace("\t", ""))
        word_count = len(text.split())
        line_count = len(text.splitlines()) if text else 0
        is_forwarded = getattr(message, 'forward_date', None) is not None
        header = "📨 **Forwarded Message Analysis**" if is_forwarded else "📊 **Text Analysis**"
        response = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• **Total Characters:** `{char_count_total}` (including spaces)\n"
            f"• **Characters (no spaces):** `{char_count_no_spaces}`\n"
            f"• **Words:** `{word_count}`\n"
            f"• **Lines:** `{line_count}`\n"
        )
        if not is_forwarded:
            response += "\n💡 *Tip: You can also forward messages from other chats to me!*"
        bot_char.reply_to(message, response, parse_mode="Markdown")

# --- VIDEO DOWNLOADER LOGIC ---
# In-memory session store
download_sessions = {}
URL_REGEX = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'

if bot_video:
    @bot_video.message_handler(commands=['start', 'help'])
    def video_welcome(message):
        welcome_text = (
            "🎬 **Welcome to Video Downloader Bot!**\n\n"
            "I can download publicly available videos from platforms like YouTube, Facebook, Twitter/X, and more!\n\n"
            "👉 **How to use:**\n"
            "Just send or paste any video link here. I will extract the available formats and let you choose your preferred download size!\n\n"
            "⚠️ *Note: Due to Telegram limits, only formats under 50MB can be sent.*"
        )
        bot_video.reply_to(message, welcome_text, parse_mode="Markdown")

    @bot_video.message_handler(func=lambda message: True)
    def video_handle(message):
        urls = re.findall(URL_REGEX, message.text)
        if not urls:
            bot_video.reply_to(message, "👋 Send me a video link (e.g. YouTube, Facebook, X) to download it!")
            return
        url = urls[0]
        status_msg = bot_video.reply_to(message, "🔍 Analyzing link... Please wait.")
        threading.Thread(target=analyze_video_link, args=(message.chat.id, status_msg.message_id, url)).start()

    def analyze_video_link(chat_id, message_id, url):
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'no_playlist': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Video')
            formats = info.get('formats', [])
            valid_formats = []
            seen_res = set()
            for f in formats:
                vcodec = f.get('vcodec')
                acodec = f.get('acodec')
                if vcodec and vcodec != 'none' and acodec and acodec != 'none':
                    filesize = f.get('filesize') or f.get('filesize_approx')
                    if filesize and filesize > 50 * 1024 * 1024:
                        continue
                    res = f.get('resolution') or f"{f.get('height', 'unknown')}p"
                    ext = f.get('ext', 'mp4')
                    res_key = f"{res}_{ext}"
                    if res_key not in seen_res:
                        seen_res.add(res_key)
                        valid_formats.append(f)
            if not valid_formats:
                bot_video.edit_message_text("❌ **Error:** No compatible formats under 50MB found.", chat_id=chat_id, message_id=message_id, parse_mode="Markdown")
                return
            valid_formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
            session_id = str(uuid.uuid4())[:8]
            download_sessions[session_id] = {
                'url': url,
                'title': title,
                'formats': {f['format_id']: f for f in valid_formats}
            }
            keyboard = InlineKeyboardMarkup()
            for f in valid_formats:
                format_id = f['format_id']
                res = f.get('resolution') or f"{f.get('height', 'unknown')}p"
                ext = f.get('ext', 'mp4')
                filesize = f.get('filesize') or f.get('filesize_approx')
                size_str = f"{filesize / (1024*1024):.1f} MB" if filesize else "unknown size"
                btn_text = f"🎬 {res} ({ext.upper()}) - {size_str}"
                keyboard.add(InlineKeyboardButton(text=btn_text, callback_data=f"dl:{session_id}:{format_id}"))
            bot_video.edit_message_text(f"🎬 **Video Found:**\n`{title}`\n\nSelect size:", chat_id=chat_id, message_id=message_id, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            bot_video.edit_message_text(f"❌ **Error:** Could not analyze.\n*Details:* {str(e)[:150]}", chat_id=chat_id, message_id=message_id, parse_mode="Markdown")

    @bot_video.callback_query_handler(func=lambda call: call.data.startswith('dl:'))
    def video_download_callback(call):
        parts = call.data.split(':')
        if len(parts) != 3: return
        _, session_id, format_id = parts
        session = download_sessions.get(session_id)
        if not session:
            bot_video.answer_callback_query(call.id, "❌ Session expired!", show_alert=True)
            bot_video.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            return
        bot_video.answer_callback_query(call.id, "Downloading...")
        threading.Thread(target=download_and_send_video, args=(call.message.chat.id, call.message.message_id, session_id, format_id)).start()

    def download_and_send_video(chat_id, message_id, session_id, format_id):
        session = download_sessions.get(session_id)
        if not session: return
        url = session['url']
        title = session['title']
        format_info = session['formats'].get(format_id)
        if not format_info: return
        bot_video.edit_message_text(f"⏳ **Downloading...**\n`{title}`", chat_id=chat_id, message_id=message_id, parse_mode="Markdown")
        downloaded_file_path = None
        try:
            output_template = os.path.join(downloads_dir, f"{session_id}_%(title)s.%(ext)s")
            ydl_opts = {'format': format_id, 'outtmpl': output_template, 'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            for filename in os.listdir(downloads_dir):
                if filename.startswith(session_id):
                    downloaded_file_path = os.path.join(downloads_dir, filename)
                    break
            if not downloaded_file_path: raise Exception("File not found")
            bot_video.edit_message_text(f"📤 **Uploading...**\n`{title}`", chat_id=chat_id, message_id=message_id, parse_mode="Markdown")
            with open(downloaded_file_path, 'rb') as video:
                bot_video.send_video(chat_id, video, caption=f"🎥 **{title}**", parse_mode="Markdown", timeout=180)
            bot_video.delete_message(chat_id, message_id)
        except Exception as e:
            bot_video.send_message(chat_id, f"❌ **Failed:** {str(e)[:150]}")
        finally:
            if downloaded_file_path and os.path.exists(downloaded_file_path):
                try: os.remove(downloaded_file_path)
                except: pass
            if session_id in download_sessions: del download_sessions[session_id]

if __name__ == "__main__":
    # If run locally without webhooks, we don't start the webserver, we can just run polling for both in separate threads!
    # This is a very neat trick for running the merged app locally:
    if not WEBHOOK_URL:
        logger.info("No WEBHOOK_URL found. Starting both bots in polling mode locally...")
        
        def run_char_polling():
            if bot_char:
                logger.info("Starting Char Bot polling...")
                bot_char.remove_webhook()
                bot_char.infinity_polling()

        def run_video_polling():
            if bot_video:
                logger.info("Starting Video Bot polling...")
                bot_video.remove_webhook()
                bot_video.infinity_polling()

        t1 = threading.Thread(target=run_char_polling, daemon=True)
        t2 = threading.Thread(target=run_video_polling, daemon=True)
        t1.start()
        t2.start()
        
        # Keep main thread alive
        t1.join()
        t2.join()
    else:
        # Run Flask server for production webhooks
        port = int(os.getenv("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
