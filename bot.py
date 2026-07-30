import os
import threading
import telebot
from flask import Flask

# Token mới nhất của bạn
TOKEN = "8948413828:AAGEiiFZQKptDfkNJzRUor4J5qJxCSgNx1g"
bot = telebot.TeleBot(TOKEN)

# 1. Các lệnh và sự kiện của Bot Telegram
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Chào bạn, bot đang chạy mượt mà trên Render!")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"Bạn vừa nói: {message.text}")

# Hàm chạy bot ở luồng riêng, dùng skip_pending=True để tránh lỗi 409 Conflict
def run_bot():
    print("Bot Telegram đang bắt đầu chạy...")
    bot.infinity_polling(skip_pending=True)

# 2. Khởi tạo Flask để mở cổng web server cho Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Telegram is running successfully!"

# 3. Chạy song song Web Server và Bot Telegram
if __name__ == "__main__":
    # Chạy bot Telegram trong background thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Lấy cổng PORT từ Render cấp phát
    port = int(os.environ.get("PORT", 5000))
    
    # Chạy Flask lắng nghe
    app.run(host="0.0.0.0", port=port)
