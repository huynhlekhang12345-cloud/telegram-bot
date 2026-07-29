import subprocess
import os
import asyncio
import psutil
import zipfile
from threading import Thread
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# --- WEB SERVER GIẢ LẬP ĐỂ CHẠY FREE TRÊN RENDER ---
app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()
# ---------------------------------------------------

logged_in_admins = set()
spam_tasks = {}
user_pending_actions = {} 
user_delays = {}          
running_processes = {}    

ADMIN_USER = "le nhan"
ADMIN_PASS = "0367120063"

def is_logged_in(user_id):
    return user_id in logged_in_admins

# Quản lý tài khoản
async def login_command(update, context):
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Sai cú pháp! Dùng: `/login [tài_khoản] [mật_khẩu]`", parse_mode="Markdown")
        return

    input_pass = context.args[-1]
    input_username = " ".join(context.args[:-1]).lower()

    if input_username == ADMIN_USER and input_pass == ADMIN_PASS:
        logged_in_admins.add(user_id)
        await update.message.reply_text("✅ Đăng nhập Admin thành công!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Sai tên tài khoản hoặc mật khẩu!")

async def logout_command(update, context):
    user_id = update.effective_user.id
    if user_id in logged_in_admins:
        logged_in_admins.remove(user_id)
        await update.message.reply_text("🔒 Đã đăng xuất Admin thành công!")
    else:
        await update.message.reply_text("⚠️ Bạn chưa đăng nhập.")

# Lệnh /addbot
async def addbot_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    bot_username = context.bot.username
    add_link = f"https://t.me/{bot_username}?startgroup=true"
    keyboard = [[InlineKeyboardButton("➕ Thêm bot vào nhóm ngay", url=add_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🤖 **Thêm bot vào nhóm chat (Box):**", reply_markup=reply_markup, parse_mode="Markdown")

# Lệnh /treo
async def treo_command(update, context):
    user_id = update.effective_user.id
    if not is_logged_in(user_id):
        return
    files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]
    if not files:
        await update.message.reply_text("📁 Thư mục chưa có file nào!")
        return

    user_pending_actions[user_id] = "treo"
    keyboard = [[InlineKeyboardButton(f"📄 {f}", callback_data=f"file_{f}")] for f in files]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📌 Chọn file bạn muốn treo:", reply_markup=reply_markup, parse_mode="Markdown")

# Lệnh /spam
async def spam_command(update, context):
    user_id = update.effective_user.id
    if not is_logged_in(user_id):
        return
    chat_id = update.effective_chat.id

    if context.args and context.args[0].lower() == 'stop':
        if chat_id in spam_tasks:
            spam_tasks[chat_id].cancel()
            del spam_tasks[chat_id]
            await update.message.reply_text("🛑 Đã dừng spam!")
        else:
            await update.message.reply_text("⚠️ Không có tiến trình spam nào đang chạy.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng nhập delay! Ví dụ: `/spam 2`", parse_mode="Markdown")
        return

    try:
        delay = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Delay phải là số hợp lệ!")
        return

    files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]
    if not files:
        await update.message.reply_text("📁 Thư mục chưa có file nào.")
        return

    user_delays[user_id] = delay
    user_pending_actions[user_id] = "spam"
    keyboard = [[InlineKeyboardButton(f"📄 {f}", callback_data=f"file_{f}")] for f in files]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"⏱️ Delay {delay}s. Chọn file để spam:", reply_markup=reply_markup, parse_mode="Markdown")

# Xử lý nút bấm chọn file
async def button_handler(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_logged_in(user_id):
        await query.answer("⛔ Cần đăng nhập Admin!", show_alert=True)
        return
        
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    
    if not data.startswith("file_"):
        return

    file_name = data.replace("file_", "")
    action = user_pending_actions.get(user_id)

    if action == "treo":
        if not os.path.exists(file_name):
            await query.edit_message_text(f"❌ Không tìm thấy `{file_name}`!")
            return
        try:
            log_file = open(f"{file_name}.log", "w")
            process = subprocess.Popen(["python", file_name], stdout=log_file, stderr=log_file)
            running_processes[file_name] = process
            
            await query.edit_message_text(f"🚀 Đang chạy `{file_name}` ngầm trên server!")
            await context.bot.send_message(chat_id=chat_id, text=f"✅ Khởi chạy thành công `{file_name}` (PID: {process.pid})")
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi: {str(e)}")

    elif action == "spam":
        delay = user_delays.get(user_id, 2)
        content_to_spam = f"🔄 Nội dung từ file {file_name}"
        if os.path.exists(file_name):
            try:
                with open(file_name, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                    if file_content:
                        content_to_spam = file_content
            except Exception:
                pass

        if chat_id in spam_tasks:
            spam_tasks[chat_id].cancel()

        task = asyncio.create_task(spam_worker(chat_id, delay, content_to_spam, context))
        spam_tasks[chat_id] = task
        await query.edit_message_text(f"✅ Đã bật spam file `{file_name}` (Delay: {delay}s)!")

    user_pending_actions.pop(user_id, None)

async def spam_worker(chat_id, delay, message_text, context):
    try:
        while True:
            await context.bot.send_message(chat_id=chat_id, text=message_text)
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        pass

# Các tính năng quản lý file và server
async def listfile_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]
    if not files:
        await update.message.reply_text("📁 Thư mục trống.")
        return
    text = "📂 **Danh sách file trên hệ thống:**\n" + "\n".join([f"- `{f}`" for f in files])
    await update.message.reply_text(text, parse_mode="Markdown")

async def them_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Nhập tên file muốn thêm vào ngon! Ví dụ: `/them data.txt`")
        return
    source_file = context.args[0]
    if not os.path.exists(source_file):
        await update.message.reply_text(f"❌ Không tìm thấy `{source_file}`!")
        return
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()
        with open("ngon.py", 'a', encoding='utf-8') as f:
            f.write("\n" + content)
        await update.message.reply_text(f"✅ Đã gộp nội dung vào `ngon.py` thành công!")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")

async def ps_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not running_processes:
        await update.message.reply_text("⚠️ Hiện không có file nào đang được treo ngầm.")
        return
    
    text = "🚀 **Danh sách tiến trình đang chạy:**\n"
    for name, proc in list(running_processes.items()):
        if proc.poll() is None:
            text += f"- `{name}` (PID: {proc.pid}) - Đang hoạt động\n"
        else:
            text += f"- `{name}` - Đã dừng\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def kill_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Nhập tên file cần tắt! Ví dụ: `/kill ngon.py`")
        return
    file_name = context.args[0]
    if file_name in running_processes:
        try:
            running_processes[file_name].terminate()
            del running_processes[file_name]
            await update.message.reply_text(f"🛑 Đã tắt tiến trình của `{file_name}` thành công!")
        except Exception as e:
            await update.message.reply_text(f"❌ Lỗi khi tắt: {str(e)}")
    else:
        await update.message.reply_text(f"⚠️ Không tìm thấy tiến trình đang chạy cho `{file_name}`.")

async def log_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Nhập tên file cần xem log! Ví dụ: `/log ngon`")
        return
    file_name = context.args[0]
    log_path = f"{file_name}.log"
    if not os.path.exists(log_path):
        await update.message.reply_text(f"❌ Không tìm thấy file log của `{file_name}`.")
        return
    
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            last_lines = "".join(lines[-15:])
            if not last_lines:
                last_lines = "File log trống."
            await update.message.reply_text(f"📜 **Log của `{file_name}`:**\n```\n{last_lines}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi đọc log: {str(e)}")

async def server_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    text = (
        f"📊 **Thông số Server hiện tại:**\n"
        f"- **CPU sử dụng:** {cpu}%\n"
        f"- **RAM sử dụng:** {memory.percent}% ({round(memory.used / (1024**3), 2)} GB / {round(memory.total / (1024**3), 2)} GB)\n"
        f"- **Ổ cứng trống:** {round(disk.free / (1024**3), 2)} GB"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# --- CÁC TÍNH NĂNG MỚI BỔ SUNG THÊM ---
async def backup_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    backup_filename = "backup_system.zip"
    try:
        with zipfile.ZipFile(backup_filename, 'w') as zipf:
            for root, dirs, files in os.walk('.'):
                for file in files:
                    if not file.endswith('.zip') and not file.startswith('.'):
                        zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), '.'))
        
        await update.message.reply_document(document=open(backup_filename, 'rb'), caption="📦 **Bản sao lưu toàn bộ hệ thống của bạn đây!**", parse_mode="Markdown")
        os.remove(backup_filename)
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi khi tạo backup: {str(e)}")

async def xem_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Nhập tên file cần xem! Ví dụ: `/xem ngon.py`")
        return
    file_name = context.args[0]
    if not os.path.exists(file_name):
        await update.message.reply_text(f"❌ Không tìm thấy file `{file_name}`!")
        return
    try:
        with open(file_name, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > 3500:
                content = content[:3500] + "\n\n... (Nội dung quá dài, đã cắt bớt)"
            await update.message.reply_text(f"📖 **Nội dung file `{file_name}`:**\n```python\n{content}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi khi đọc file: {str(e)}")

async def delfile_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Nhập tên file cần xóa! Ví dụ: `/delfile rac.txt`")
        return
    file_name = context.args[0]
    if not os.path.exists(file_name):
        await update.message.reply_text(f"❌ Không tìm thấy file `{file_name}`!")
        return
    try:
        os.remove(file_name)
        await update.message.reply_text(f"🗑️ Đã xóa thành công file `{file_name}` khỏi hệ thống!")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi khi xóa file: {str(e)}")

async def restart_bot_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    await update.message.reply_text("🔄 Đang khởi động lại bot...")
    os.execv(sys.executable, ['python'] + sys.argv)
# ---------------------------------------

async def handle_document(update, context):
    if not is_logged_in(update.effective_user.id):
        await update.message.reply_text("⛔ Cần đăng nhập Admin để gửi file!")
        return
        
    document = update.message.document
    file_name = document.file_name
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(file_name)
    await update.message.reply_text(f"📥 Đã nhận và lưu file thành công: `{file_name}`")

if __name__ == '__main__':
    import sys
    keep_alive()

    TOKEN = "8948413828:AAFKfmqJA_By7L63kgOF87-4iwwArnU3vpk"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Đăng ký toàn bộ lệnh
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler("addbot", addbot_command))
    app.add_handler(CommandHandler("treo", treo_command))
    app.add_handler(CommandHandler("spam", spam_command))
    app.add_handler(CommandHandler("listfile", listfile_command))
    app.add_handler(CommandHandler("them", them_command))
    app.add_handler(CommandHandler("ps", ps_command))
    app.add_handler(CommandHandler("kill", kill_command))
    app.add_handler(CommandHandler("log", log_command))
    app.add_handler(CommandHandler("server", server_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("xem", xem_command))
    app.add_handler(CommandHandler("delfile", delfile_command))
    app.add_handler(CommandHandler("restart_bot", restart_bot_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot đang chạy toàn diện...")
    app.run_polling()
