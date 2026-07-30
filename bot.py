import os
import threading
import time
import telebot

# Cấu hình Token và Admin
TOKEN = "8948413828:AAFKfmqJA_By7L63kgOF87-4iwwArnU3vpk"
bot = telebot.TeleBot(TOKEN)

# Danh sách ID Telegram của Admin tối cao (Giữ nguyên quyền ở mọi box, chỉ mất khi gõ /qtv)
ADMINS = [123456789]  # Thay bằng ID Telegram thực tế của bạn

# Dictionary quản lý trạng thái chạy vòng lặp toxic theo từng chat_id
toxic_threads = {}


def toxic_worker(chat_id, delay, lines):
  """Hàm chạy ngầm gửi từng dòng trong file theo vòng lặp vô tận, hỗ trợ tag @."""
  try:
    while chat_id in toxic_threads and toxic_threads[chat_id]["running"]:
      for line in lines:
        if (
            chat_id not in toxic_threads
            or not toxic_threads[chat_id]["running"]
        ):
          break
        # Gửi dòng nội dung trong file (Telegram tự nhận diện @username nếu có)
        bot.send_message(chat_id, line, parse_mode="Markdown")
        time.sleep(delay)
  except Exception as e:
    print(f"Lỗi khi chạy vòng lặp toxic: {e}")


@bot.message_handler(commands=["toxic"])
def handle_toxic(message):
  # Kiểm tra quyền Admin
  if message.from_user.id not in ADMINS:
    bot.reply_to(message, "⚠️ Bạn không có quyền sử dụng lệnh này! Chỉ Admin mới được dùng.")
    return

  args = message.text.split()
  # Cú pháp: /toxic [delay_giây] kèm file txt
  if len(args) < 2:
    bot.reply_to(
        message,
        "⚠️ Sai cú pháp! Dùng: `/toxic [delay]` và **đính kèm file .txt**.\n*(Trong"
        " file bạn có thể viết kèm `@username` để bot tag người khác)*",
        parse_mode="Markdown",
    )
    return

  try:
    delay = float(args[1])
  except ValueError:
    bot.reply_to(message, "⚠️ Thời gian delay phải là một số (Ví dụ: `1` hoặc `1.5`).")
    return

  # Kiểm tra xem người dùng có đính kèm file hay không
  if not message.document:
    bot.reply_to(message, "⚠️ Vui lòng đính kèm file văn bản (.txt) chứa nội dung cần treo!")
    return

  try:
    # Tải file từ Telegram về
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    # Đọc nội dung file và loại bỏ dòng trống
    file_content = downloaded_file.decode("utf-8")
    lines = [
        line.strip() for line in file_content.splitlines() if line.strip()
    ]

    if not lines:
      bot.reply_to(message, "⚠️ File đính kèm trống hoặc không có nội dung hợp lệ!")
      return

    chat_id = message.chat.id

    # Nếu box này đang chạy vòng lặp trước đó thì dừng lại trước khi tạo mới
    if chat_id in toxic_threads:
      toxic_threads[chat_id]["running"] = False

    # Khởi tạo trạng thái vòng lặp mới
    toxic_threads[chat_id] = {"running": True}

    # Chạy vòng lặp trong một luồng (thread) riêng biệt để không làm đơ bot
    t = threading.Thread(
        target=toxic_worker, args=(chat_id, delay, lines), daemon=True
    )
    t.start()

    bot.reply_to(
        message,
        f"🚀 Đã kích hoạt **Toxic Loop** thành công!\n⏱ Delay: `{delay}s`\n📄 Tổng"
        f" số dòng trong file: `{len(lines)}`\n(Dùng lệnh `/stoptoxic` để"
        " dừng)",
        parse_mode="Markdown",
    )

  except Exception as e:
    bot.reply_to(message, f"❌ Có lỗi xảy ra khi xử lý file: {str(e)}")


@bot.message_handler(commands=["stoptoxic"])
def handle_stop_toxic(message):
  # Kiểm tra quyền Admin
  if message.from_user.id not in ADMINS:
    bot.reply_to(message, "⚠️ Bạn không có quyền sử dụng lệnh này!")
    return

  chat_id = message.chat.id
  if chat_id in toxic_threads and toxic_threads[chat_id]["running"]:
    toxic_threads[chat_id]["running"] = False
    bot.reply_to(message, "🛑 Đã dừng vòng lặp toxic trong box này thành công.")
  else:
    bot.reply_to(message, "⚠️ Hiện không có vòng lặp toxic nào đang chạy ở box này.")


@bot.message_handler(commands=["qtv"])
def qtv_command(message):
  user_id = message.from_user.id
  if user_id in ADMINS:
    ADMINS.remove(user_id)
    bot.reply_to(message, "🔒 Bạn đã tự hủy quyền Admin thành công bằng lệnh /qtv.")
  else:
    bot.reply_to(message, "Bạn vốn không có quyền Admin từ trước!")


@bot.message_handler(commands=["menu"])
def menu_command(message):
  menu_text = (
      "📋 **BẢNG MENU HỆ THỐNG BOT** 📋\n\n"
      "• `/menu` - Hiển thị bảng danh sách toàn bộ lệnh.\n"
      "• `/addbot` - Thêm bot vào nhóm chat.\n"
      "• `/treo [nội dung]` - Treo nội dung cơ bản.\n"
      "• `/spam [số lượng]` - Gửi tin nhắn lặp lại có độ trễ an toàn.\n"
      "• `/toxic [delay]` (Đính kèm file `.txt` có chứa nội dung & `@username`)"
      " - Treo lặp lại từng dòng vô tận theo delay có kèm tag.\n"
      "• `/stoptoxic` - Dừng vòng lặp toxic đang chạy.\n"
      "• `/qtv` - Gỡ bỏ quyền Admin của chính tài khoản đang dùng.\n"
  )
  bot.reply_to(message, menu_text, parse_mode="Markdown")


# Khởi động bot chạy liên tục
if __name__ == "__main__":
  print("Bot đang chạy...")
  bot.infinity_polling()
