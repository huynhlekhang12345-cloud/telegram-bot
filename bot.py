import os
import threading
import telebot
from flask import Flask

# 1. Khởi tạo Bot Telegram
TOKEN = "8948413828:AAGEiiFZQKptDfkNJzRUor4J5qJxCSgNx1g"
bot = telebot.TeleBot(TOKEN)

# Định nghĩa các lệnh cho bot của bạn ở đây
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Chào bạn, bot đang chạy mượt mà trên Render!")

# Hàm chạy bot Telegram ở một luồng (thread) riêng biệt
def run_bot():
    print("Bot Telegram đang bắt đầu chạy...")
    bot.infinity_polling(skip_pending=True)

# 2. Khởi tạo Flask để mở cổng cho Render nhận diện
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Telegram is running successfully!"

# 3. Chạy song song cả Web server và Bot Telegram
if __name__ == "__main__":
    # Khởi chạy bot Telegram trong một background thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Lấy cổng PORT từ biến môi trường của Render (mặc định là 5000 nếu chạy local)
    port = int(os.environ.get("PORT", 5000))
    
    # Chạy Flask server lắng nghe trên tất cả các interface (0.0.0.0)
    app.run(host="0.0.0.0", port=port)
