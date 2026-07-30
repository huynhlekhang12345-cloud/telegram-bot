import os
import time
import threading
import telebot
from telebot import types
from flask import Flask

TOKEN = "8948413828:AAEdz9HIH9wM8BXApLeRvIelloAorU7Cydo"
bot = telebot.TeleBot(TOKEN)

# --- QUẢN LÝ QUYỀN HẠN & TIẾN TRÌNH ---
ADMIN_ID = 8725740462         
QUAN_TRIVIEN = set()          
NGUOI_THUE = set()            

# Từ điển lưu trạng thái chạy để có thể stop theo chat_id
ACTIVE_TASKS = {}

# Lưu lại tất cả các chat_id (nhóm hoặc cá nhân) mà bot từng tương tác để khi tắt máy sẽ thông báo
ACTIVE_CHATS_FILE = "active_chats.txt"

def load_active_chats():
    if os.path.exists(ACTIVE_CHATS_FILE):
        with open(ACTIVE_CHATS_FILE, "r", encoding="utf-8") as f:
            return set(int(line.strip()) for line in f if line.strip().isdigit())
    return set()

def save_active_chat(chat_id):
    chats = load_active_chats()
    if chat_id not in chats:
        chats.add(chat_id)
        with open(ACTIVE_CHATS_FILE, "w", encoding="utf-8") as f:
            for cid in chats:
                f.write(f"{cid}\n")

# Thư mục lưu trữ file vĩnh viễn trên Render
UPLOAD_FOLDER = "bot_files"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- HỆ THỐNG MENU ---
@bot.message_handler(commands=['menu'])
def show_menu(message):
    save_active_chat(message.chat.id)
    menu_text = (
        "🤖 **MENU BOT LE NHAN** 🤖\n"
        "----------------------------------------\n"
        "👑 **ADMIN / QTV** | 👤 **BÌNH THƯỜNG**\n"
        "----------------------------------------\n"
        "• `/qtv` - Thêm QTV       | • `/toxic [delay] [file] [@tag]`\n"
        "• `/thue` - Thêm thuê     | • `/treo [delay] [nội_dung]`\n"
        "• `/stop` - Dừng tất cả   | • `/treongon [delay] [file]`\n"
        "•                         | • `/spam [delay] [file]`\n"
        "•                         | • `/help` - Trợ giúp\n"
        "----------------------------------------\n"
        "*(Gửi file trực tiếp vào chat để hệ thống tự động nhận diện)*"
    )
    bot.reply_to(message, menu_text, parse_mode="Markdown")

# --- TỰ ĐỘNG NHẬN DIỆN VÀ LƯU FILE KHI ADMIN GỬI ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    save_active_chat(message.chat.id)
    
    if message.from_user.id != ADMIN_ID:
        return

    target_doc = message.document
    if not target_doc:
        return

    try:
        file_info = bot.get_file(target_doc.file_id)
        file_name = target_doc.file_name
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_path = os.path.join(UPLOAD_FOLDER, file_name)
        with open(file_path, 'wb') as f:
            f.write(downloaded_file)
            
        bot.reply_to(message, f"✅ Đã tự động lưu file `{file_name}` vào hệ thống vĩnh viễn!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi khi tự động lưu file: {str(e)}")

# --- LỆNH /STOP: DỪNG TẤT CẢ TIẾN TRÌNH ĐANG CHẠY ---
@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    save_active_chat(message.chat.id)
    user_id = message.from_user.id
    if user_id != ADMIN_ID and user_id not in QUAN_TRIVIEN:
        bot.reply_to(message, "❌ Bạn không có quyền dừng lệnh!")
        return

    chat_id = message.chat.id
    if chat_id in ACTIVE_TASKS:
        ACTIVE_TASKS[chat_id]["running"] = False
        del ACTIVE_TASKS[chat_id]
        bot.reply_to(message, "🛑 **Đã dừng toàn bộ vòng lặp đang chạy trong nhóm này!**", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ Hiện tại không có tiến trình nào đang chạy để dừng.", parse_mode="Markdown")

# --- HÀM TẠO BẢNG CHỌN FILE (INLINE KEYBOARD) ---
def get_file_keyboard(cmd_name, delay):
    markup = types.InlineKeyboardMarkup()
    if os.path.exists(UPLOAD_FOLDER):
        files = os.listdir(UPLOAD_FOLDER)
        for f in files:
            # Callback data dạng: cmd|delay|filename
            callback_data = f"{cmd_name}|{delay}|{f}"
            markup.add(types.InlineKeyboardButton(text=f"📁 {f}", callback_data=callback_data))
    return markup

# --- LỆNH /TOXIC ---
def run_toxic_loop(chat_id, file_path, delay, mention_target):
    try:
        while ACTIVE_TASKS.get(chat_id, {}).get("running", False):
            if not os.path.exists(file_path):
                break
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            if not lines:
                break
                
            for line in lines:
                if not ACTIVE_TASKS.get(chat_id, {}).get("running", False):
                    break
                content = line.strip()
                if not content:
                    continue
                
                final_message = f"{mention_target} {content}" if mention_target else content
                bot.send_message(chat_id, final_message)
                
                elapsed = 0
                delay_f = float(delay)
                while elapsed < delay_f:
                    if not ACTIVE_TASKS.get(chat_id, {}).get("running", False):
                        break
                    time.sleep(0.2)
                    elapsed += 0.2
    except Exception as e:
        print(f"Lỗi tiến trình toxic: {e}")
    finally:
        if chat_id in ACTIVE_TASKS:
            del ACTIVE_TASKS[chat_id]

@bot.message_handler(commands=['toxic'])
def cmd_toxic(message):
    save_active_chat(message.chat.id)
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Chức năng này chỉ dành riêng cho Admin!")
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Cú pháp: `/toxic [delay] [@username]`", parse_mode="Markdown")
        return

    delay_time = parts[1]
    mention_target = parts[2] if len(parts) > 2 else ""

    # Nếu người dùng nhập đủ tên file luôn thì chạy luôn, ngược lại hiện bảng chọn file
    if len(parts) >= 3 and not parts[2].startswith("@"):
        file_name = parts[2]
        mention_target = parts[3] if len(parts) > 3 else ""
        target_path = os.path.join(UPLOAD_FOLDER, file_name)
        if not os.path.exists(target_path):
            bot.reply_to(message, f"❌ Không tìm thấy file `{file_name}`!")
            return
        chat_id = message.chat.id
        ACTIVE_TASKS[chat_id] = {"running": True}
        bot.reply_to(message, f"🔥 **Đã kích hoạt TOXIC với file `{file_name}`!** Gõ `/stop` để dừng.", parse_mode="Markdown")
        threading.Thread(target=run_toxic_loop, args=(chat_id, target_path, float(delay_time), mention_target), daemon=True).start()
    else:
        markup = get_file_keyboard(f"toxic_{mention_target}", delay_time)
        bot.reply_to(message, "📂 **Chọn file bạn muốn sử dụng cho lệnh TOXIC:**", reply_markup=markup, parse_mode="Markdown")

# --- LỆNH /TREO ---
def run_treo_loop(chat_id, text_to_send, delay):
    try:
        delay_f = float(delay)
        while ACTIVE_TASKS.get(chat_id, {}).get("running", False):
            bot.send_message(chat_id, text_to_send)
            
            elapsed = 0
            while elapsed < delay_f:
                if not ACTIVE_TASKS.get(chat_id, {}).get("running", False):
                    break
                time.sleep(0.2)
                elapsed += 0.2
    except Exception as e:
        print(f"Lỗi tiến trình treo: {e}")
    finally:
        if chat_id in ACTIVE_TASKS:
            del ACTIVE_TASKS[chat_id]

@bot.message_handler(commands=['treo'])
def cmd_treo(message):
    save_active_chat(message.chat.id)
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Chức năng này chỉ dành riêng cho Admin!")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "⚠️ Cú pháp: `/treo [delay] [nội_dung]`", parse_mode="Markdown")
        return

    try:
        delay_time = float(parts[1])
        text_to_send = parts[2]
        chat_id = message.chat.id

        ACTIVE_TASKS[chat_id] = {"running": True}
        bot.reply_to(message, f"🚀 **Đã kích hoạt TREO!** Gõ `/stop` để dừng.", parse_mode="Markdown")
        threading.Thread(target=run_treo_loop, args=(chat_id, text_to_send, delay_time), daemon=True).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Có lỗi xảy ra: {str(e)}")

# --- CÁC LỆNH DÙNG FILE CHUNG (/spam, /treongon) ---
def run_full_file_task(chat_id, file_path, delay, cmd_name):
    try:
        if not os.path.exists(file_path):
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
            
        delay_f = float(delay)
        while ACTIVE_TASKS.get(chat_id, {}).get("running", False):
            bot.send_message(chat_id, f"📁 [{cmd_name.upper()}]\n{file_content}")
            
            elapsed = 0
            while elapsed < delay_f:
                if not ACTIVE_TASKS.get(chat_id, {}).get("running", False):
                    break
                time.sleep(0.2)
                elapsed += 0.2
    except Exception as e:
        print(f"Lỗi tiến trình {cmd_name}: {e}")
    finally:
        if chat_id in ACTIVE_TASKS:
            del ACTIVE_TASKS[chat_id]

def handle_file_command(message, cmd_name):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Chức năng này chỉ dành riêng cho Admin!")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, f"⚠️ Cú pháp: `/{cmd_name} [delay]`", parse_mode="Markdown")
        return

    delay_time = parts[1]
    
    # Nếu người dùng nhập luôn tên file phía sau
    if len(parts) >= 3:
        file_name = parts[2]
        target_path = os.path.join(UPLOAD_FOLDER, file_name)
        if not os.path.exists(target_path):
            bot.reply_to(message, f"❌ Không tìm thấy file `{file_name}`!")
            return
        chat_id = message.chat.id
        ACTIVE_TASKS[chat_id] = {"running": True}
        bot.reply_to(message, f"🚀 **Đã kích hoạt `/{cmd_name}` với file `{file_name}`!** Gõ `/stop` để dừng.", parse_mode="Markdown")
        threading.Thread(target=run_full_file_task, args=(chat_id, target_path, float(delay_time), cmd_name), daemon=True).start()
    else:
        # Nếu chỉ gõ /spam 2, bot sẽ hiển thị danh sách file để chọn
        markup = get_file_keyboard(cmd_name, delay_time)
        bot.reply_to(message, f"📂 **Chọn file bạn muốn sử dụng cho lệnh `/{cmd_name}`:**", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['spam'])
def cmd_spam(message):
    save_active_chat(message.chat.id)
    handle_file_command(message, 'spam')

@bot.message_handler(commands=['treongon'])
def cmd_treongon(message):
    save_active_chat(message.chat.id)
    handle_file_command(message, 'treongon')

# --- XỬ LÝ KHI BẤM NÚT CHỌN FILE (CALLBACK QUERY) ---
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    try:
        data_parts = call.data.split("|")
        cmd_info = data_parts[0]
        delay_time = data_parts[1]
        file_name = data_parts[2]
        
        chat_id = call.message.chat.id
        target_path = os.path.join(UPLOAD_FOLDER, file_name)
        
        if not os.path.exists(target_path):
            bot.answer_callback_query(call.id, "❌ File không tồn tại!")
            return

        ACTIVE_TASKS[chat_id] = {"running": True}
        bot.answer_callback_query(call.id, f"Đã chọn file: {file_name}")

        if cmd_info.startswith("toxic"):
            mention_target = cmd_info.replace("toxic_", "")
            bot.send_message(chat_id, f"🔥 **Đã kích hoạt TOXIC với file `{file_name}`!** Gõ `/stop` để dừng.", parse_mode="Markdown")
            threading.Thread(target=run_toxic_loop, args=(chat_id, target_path, float(delay_time), mention_target), daemon=True).start()
        else:
            bot.send_message(chat_id, f"🚀 **Đã kích hoạt `/{cmd_info}` với file `{file_name}`!** Gõ `/stop` để dừng.", parse_mode="Markdown")
            threading.Thread(target=run_full_file_task, args=(chat_id, target_path, float(delay_time), cmd_info), daemon=True).start()
            
    except Exception as e:
        print(f"Lỗi callback: {e}")

# --- PHÂN QUYỀN KHÁC ---
@bot.message_handler(commands=['qtv'])
def add_qtv(message):
    save_active_chat(message.chat.id)
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Chỉ Admin tối cao mới được cấp quyền QTV.")
        return
    try:
        target_id = int(message.text.split()[1])
        QUAN_TRIVIEN.add(target_id)
        bot.reply_to(message, f"✅ Đã thêm ID `{target_id}` làm QTV!", parse_mode="Markdown")
    except (IndexError, ValueError):
        bot.reply_to(message, "⚠️ Cú pháp: `/qtv [User_ID]`", parse_mode="Markdown")

@bot.message_handler(commands=['thue'])
def add_thue(message):
    save_active_chat(message.chat.id)
    user_id = message.from_user.id
    if user_id != ADMIN_ID and user_id not in QUAN_TRIVIEN:
        bot.reply_to(message, "❌ Bạn không có quyền cấp phát chức năng này!")
        return
    try:
        target_id = int(message.text.split()[1])
        NGUOI_THUE.add(target_id)
        bot.reply_to(message, f"✅ Đã cấp quyền Thuê Admin cho ID `{target_id}`!", parse_mode="Markdown")
    except (IndexError, ValueError):
        bot.reply_to(message, "⚠️ Cú pháp: `/thue [User_ID]`", parse_mode="Markdown")

@bot.message_handler(commands=['ban'])
def handle_ban(message):
    save_active_chat(message.chat.id)
    user_id = message.from_user.id
    if user_id != ADMIN_ID and user_id not in QUAN_TRIVIEN and user_id not in NGUOI_THUE:
        bot.reply_to(message, "❌ Bạn không có quyền ban người dùng!")
        return
    bot.reply_to(message, "🔨 Đã thực hiện lệnh ban thành công!")

@bot.message_handler(commands=['help'])
def send_help(message):
    save_active_chat(message.chat.id)
    bot.reply_to(message, "Gõ lệnh `/menu` để xem toàn bộ danh sách chức năng.", parse_mode="Markdown")

# --- HÀM THÔNG BÁO KHI BOT BỊ TẮT ---
def notify_shutdown():
    chats = load_active_chats()
    warning_text = "⚠️ Box đang update có gì liên hệ zalo admin :0367120063"
    for chat_id in chats:
        try:
            bot.send_message(chat_id, warning_text)
        except Exception:
            pass

import atexit
atexit.register(notify_shutdown)

# --- CHẠY SERVER FLASK VÀ BOT ---
def run_bot():
    print("Bot Telegram đang bắt đầu chạy...")
    bot.infinity_polling(skip_pending=True)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Telegram is running successfully!"

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
