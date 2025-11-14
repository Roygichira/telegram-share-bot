import os
import uuid
import logging
from flask import Flask, request, send_file
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import sqlite3
from PIL import Image
import io
import tempfile

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get('8264953444:AAEh0TKGeBRXlANmsQujB8caJavYqaopBfg')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
PORT = int(os.environ.get('PORT', 10000))

# Initialize Flask app
app = Flask(__name__)

# Initialize database
def init_db():
    conn = sqlite3.connect('images.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS images (
            session_id TEXT PRIMARY KEY,
            image_data BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Store active sessions
user_sessions = {}

# Bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
📸 **Image Sharing Bot**

🤖 **How it works:**
1. Press **'Get Link'** to generate a unique sharing session
2. Share any image with me
3. Get a public link to view your shared image
4. Anyone with the link can see your image

🔗 Your images are stored temporarily and accessible via unique session IDs.

📱 **Commands:**
/start - Show this help message
/getlink - Generate a new sharing session
    """
    
    await update.message.reply_text(welcome_text)

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session_id = str(uuid.uuid4())[:8]
    user_sessions[user_id] = session_id
    public_url = f"{WEBHOOK_URL}/view/{session_id}"
    
    message = f"""
🆕 **New Sharing Session Created!**

🔑 **Session ID:** `{session_id}`
🔗 **Public URL:** {public_url}

📤 Now send me an image to share publicly!
    
⚠️ **Note:** Anyone with this link can view your image.
    """
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_sessions:
        await update.message.reply_text(
            "⚠️ Please press 'Get Link' first to create a sharing session, then send your image."
        )
        return
    
    session_id = user_sessions[user_id]
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        image_data = await photo_file.download_as_bytearray()
        
        conn = sqlite3.connect('images.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM images WHERE session_id = ?', (session_id,))
        cursor.execute(
            'INSERT INTO images (session_id, image_data) VALUES (?, ?)',
            (session_id, bytes(image_data))
        )
        conn.commit()
        conn.close()
        
        public_url = f"{WEBHOOK_URL}/view/{session_id}"
        
        success_message = f"""
✅ **Image Shared Successfully!**

📸 Your image is now publicly available
🔗 **Share this link:** {public_url}

🆕 Want to share another image? Press 'Get Link' for a new session!
        """
        
        await update.message.reply_text(success_message)
        del user_sessions[user_id]
        
    except Exception as e:
        logger.error(f"Error handling image: {e}")
        await update.message.reply_text("❌ Error processing image. Please try again.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Send me an image after pressing 'Get Link', or use /start for instructions."
    )

# Flask routes
@app.route('/')
def home():
    return """
    <html>
        <head>
            <title>Telegram Image Sharing</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
                .container { text-align: center; }
                .info { background: #f0f0f0; padding: 20px; border-radius: 10px; margin: 20px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📸 Telegram Image Sharing</h1>
                <div class="info">
                    <h3>How to use:</h3>
                    <p>1. Start the Telegram bot</p>
                    <p>2. Use /getlink to create a sharing session</p>
                    <p>3. Send your image to the bot</p>
                    <p>4. Share the generated link with anyone!</p>
                </div>
                <p>This service allows you to share images via Telegram with unique session IDs.</p>
            </div>
        </body>
    </html>
    """

@app.route('/view/<session_id>')
def view_image(session_id):
    try:
        conn = sqlite3.connect('images.db')
        cursor = conn.cursor()
        cursor.execute('SELECT image_data FROM images WHERE session_id = ?', (session_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            image_data = result[0]
            return send_file(
                io.BytesIO(image_data),
                mimetype='image/jpeg',
                as_attachment=False,
                download_name=f'image_{session_id}.jpg'
            )
        else:
            return """
            <html>
                <head>
                    <title>Image Not Found</title>
                    <style>
                        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                    </style>
                </head>
                <body>
                    <h1>❌ Image Not Found</h1>
                    <p>The shared image doesn't exist or has expired.</p>
                    <p>Session ID: <code>{}</code></p>
                </body>
            </html>
            """.format(session_id), 404
            
    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return "Error serving image", 500

@app.route('/health')
def health_check():
    return "OK", 200

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is required")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getlink", get_link))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        application.run_polling()

if __name__ == "__main__":
    main()