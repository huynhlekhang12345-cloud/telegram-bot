import subprocess
import os
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Lưu trữ danh sách các chat_id hoặc user_id đã đăng nhập thành công
logged_in_admins = set()

spam_tasks = {}
user_pending_actions = {} 
user_delays = {}          

# Thông tin tài khoản Admin cố định
ADMIN_USER = "le nhan"
ADMIN_PASS = "0367120063"

# Hàm kiểm tra xem chat/user hiện tại đã đăng nhập admin chưa
def is_logged_in(user_id):
    return user_id in logged_in_admins

# 1. Chức năng đăng nhập: /login le nhan 0367120063
async def login_command(update, context):
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Sai cú pháp! Vui lòng dùng: `/login [tài_khoản] [mật_khẩu]`\nVí dụ: `/login le nhan 0367120063`", parse_mode="Markdown")
        return

    # Lấy tài khoản (có thể gõ "le" hoặc "le nhan") và mật khẩu
    input_user = context.args[0].lower()
    # Ghép phần còn lại làm mật khẩu hoặc tên tài khoản nếu có khoảng trắng
    # Ở đây chúng ta check: tham số cuối là pass, các tham số trước là user
    input_pass = context.args[-1]
    input_username = " ".join(context.args[:-1]).lower()

    if input_username == ADMIN_USER and input_pass == ADMIN_PASS:
        logged_in_admins.add(user_id)
        await update.message.reply_text("✅ Đăng nhập Admin thành công! Bây giờ bạn có thể sử dụng các lệnh `/treo`, `/spam`, `/addbot`, v.v.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Sai tên tài khoản hoặc mật khẩu!")

# Chức năng đăng xuất: /logout
async def logout_command(update, context):
    user_id = update.effective_user.id
    if user_id in logged_in_admins:
        logged_in_admins.remove(user_id)
        await update.message.reply_text("🔒 Đã đăng xuất tài khoản Admin thành công!")
    else:
        await update.message.reply_text("⚠️ Bạn chưa đăng nhập.")

# 2. Lệnh /addbot
async def addbot_command(update, context):
    user_id = update.effective_user.id
    if not is_logged_in(user_id):
        await update.message.reply_text("⛔ Vui lòng đăng nhập trước bằng lệnh `/login le nhan 0367120063`", parse_mode="Markdown")
        return

    bot_username = context.bot.username
    add_link = f"https://t.me/{bot_username}?startgroup=true"
    
    keyboard = [[InlineKeyboardButton("➕ Thêm bot vào nhóm ngay", url=add_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 **Thêm bot vào nhóm chat (Box):**\nBấm vào nút bên dưới để chọn nhóm:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# 3. Lệnh /treo
async def treo_command(update, context):
    user_id = update.effective_user.id
    if not is_logged_in(user_id):
        await update.message.reply_text("⛔ Vui lòng đăng nhập trước bằng lệnh `/login le nhan 0367120063`", parse_mode="Markdown")
        return

    files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]
    if not files:
        await update.message.reply_text("📁 Hiện tại hệ thống chưa có file nào. Hãy gửi file lên trước nhé!")
        return

    user_pending_actions[user_id] = "treo"
    keyboard = [[InlineKeyboardButton(f"📄 {f}", callback_data=f"file_{f}")] for f in files]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("📌 Vui lòng **chọn file** bạn muốn treo:", reply_markup=reply_markup, parse_mode="Markdown")

# 4. Lệnh /spam [delay]
async def spam_command(update, context):
    user_id = update.effective_user.id
    if not is_logged_in(user_id):
        await update.message.reply_text("⛔ Vui lòng đăng nhập trước bằng lệnh `/login le nhan 0367120063`", parse_mode="Markdown")
        return

    chat_id = update.effective_chat.id

    if context.args and context.args[0].lower() == 'stop':
        if chat_id in spam_tasks:
            spam_tasks[chat_id].cancel()
            del spam_tasks[chat_id]
            await update.message.reply_text("🛑 Đã dừng tiến trình spam!")
        else:
            await update.message.reply_text("⚠️ Hiện tại không có tiến trình spam nào đang chạy.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng nhập thời gian delay! Ví dụ: `/spam 2`", parse_mode="Markdown")
        return

    try:
        delay = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Thời gian delay phải là một con số hợp lệ!")
        return

    files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]
    if not files:
        await update.message.reply_text("📁 Hiện tại hệ thống chưa có file nào để spam.")
        return

    user_delays[user_id] = delay
    user_pending_actions[user_id] = "spam"

    keyboard = [[InlineKeyboardButton(f"📄 {f}", callback_data=f"file_{f}")] for f in files]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(f"⏱️ Đã nhận delay {delay}s.\n📌 Vui lòng **chọn file** để spam:", reply_markup=reply_markup, parse_mode="Markdown")

# Xử lý nút bấm chọn file
async def button_handler(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_logged_in(user_id):
        await query.answer("⛔ Bạn cần đăng nhập Admin để bấm nút này!", show_alert=True)
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
            await query.edit_message_text(f"❌ Không tìm thấy file `{file_name}`!")
            return
        try:
            await query.edit_message_text(f"🚀 Đang tiến hành chạy file `{file_name}`...")
            subprocess.Popen(["python", file_name])
            await context.bot.send_message(chat_id=chat_id, text=f"✅ Đã chạy thành công file `{file_name}`!")
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi khi chạy file: {str(e)}")

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
        await query.edit_message_text(f"✅ Đã kích hoạt spam file `{file_name}` với delay {delay}s!")

    user_pending_actions.pop(user_id, None)

async def spam_worker(chat_id, delay, message_text, context):
    try:
        while True:
            await context.bot.send_message(chat_id=chat_id, text=message_text)
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        pass

async def listfile_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]
    if not files:
        await update.message.reply_text("📁 Thư mục hiện tại chưa có file nào.")
        return
    text = "📂 **Danh sách file trên hệ thống:**\n" + "\n".join([f"- `{f}`" for f in files])
    await update.message.reply_text(text, parse_mode="Markdown")

async def them_command(update, context):
    if not is_logged_in(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng nhập tên file muốn thêm vào ngon!")
        return
    source_file = context.args[0]
    if not os.path.exists(source_file):
        await update.message.reply_text(f"❌ Không tìm thấy file `{source_file}`!")
        return
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()
        with open("ngon.py", 'a', encoding='utf-8') as f:
            f.write("\n" + content)
        await update.message.reply_text(f"✅ Đã thêm nội dung vào `ngon.py` thành công!")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")

async def handle_document(update, context):
    if not is_logged_in(update.effective_user.id):
        await update.message.reply_text("⛔ Vui lòng đăng nhập Admin trước khi gửi file lên hệ thống!")
        return
        
    document = update.message.document
    file_name = document.file_name
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(file_name)
    await update.message.reply_text(f"📥 Đã nhận và lưu file thành công: `{file_name}`")

if __name__ == '__main__':
    TOKEN = "8948413828:AAFKfmqJA_By7L63kgOF87-4iwwArnU3vpk"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Đăng ký các lệnh
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler("addbot", addbot_command))
    app.add_handler(CommandHandler("treo", treo_command))
    app.add_handler(CommandHandler("spam", spam_command))
    app.add_handler(CommandHandler("listfile", listfile_command))
    app.add_handler(CommandHandler("them", them_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot đang chạy...")
    app.run_polling()
