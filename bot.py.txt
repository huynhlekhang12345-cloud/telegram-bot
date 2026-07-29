import sqlite3
import datetime
import asyncio
import re
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ================= ⚙️ CẤU HÌNH BẮT BUỘC =================
TOKEN = "8948413828:AAFKfmqJA_By7L63kgOF87-4iwwArnU3vpk"
BOT_OWNER_ID = 8725740462# ⚠️ Thay ID Telegram cá nhân của bạn vào đây
STK_BANK = "0367120063"
MAX_DAILY_BUDGET = 10_000_000_000  # Hạn mức nạp: 10 tỷ VNĐ / ngày

# Bộ nhớ tạm lưu cấu hình
bot_config = {
    "delay": 2,
    "ngon_treo": [],
    "admin_used_today": 0,
    "last_reset_date": datetime.date.today()
}

# ================= 1. CƠ SỞ DỮ LIỆU SQLITE =================
def init_db():
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_qtvs (
            chat_id INTEGER,
            user_id INTEGER,
            added_by INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

def auto_save_user(user):
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, first_name, balance)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (user.id, user.username, user.first_name))
    
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
    balance = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return balance

def check_and_reset_daily_budget():
    today = datetime.date.today()
    if bot_config["last_reset_date"] != today:
        bot_config["admin_used_today"] = 0
        bot_config["last_reset_date"] = today

def is_box_qtv(chat_id: int, user_id: int) -> bool:
    if user_id == BOT_OWNER_ID:
        return True
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM group_qtvs WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_user_id_by_username(username: str):
    clean_username = username.lstrip("@")
    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (clean_username,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

# ================= 2. 🤫 CHỨC NĂNG ẨN: BẮT LINK VIDEO =================
def extract_direct_video_url(url: str):
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            'title': info.get('title', 'Video'),
            'direct_url': info.get('url', None),
            'ext': info.get('ext', 'mp4')
        }

async def handle_hidden_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    sender_id = update.effective_user.id

    url_pattern = r'https?://[^\s]+'
    match = re.search(url_pattern, text)

    if match:
        url = match.group(0)
        if not is_box_qtv(chat_id, sender_id):
            return

        video_domains = ['tiktok.com', 'youtube.com', 'youtu.be', 'facebook.com', 'fb.watch', 'instagram.com', 'douyin.com']
        if not any(domain in url.lower() for domain in video_domains):
            return

        status_msg = await update.message.reply_text("🔍 *Đang tự động bóc tách link video...*", parse_mode="Markdown")

        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, extract_direct_video_url, url)

            if data and data['direct_url']:
                reply_text = (
                    f"🎬 **KẾT QUẢ TRUY CẬP TỰ ĐỘNG**\n\n"
                    f"📌 **Tiêu đề:** {data['title']}\n"
                    f"🔗 **Link Direct Media:**\n`{data['direct_url']}`"
                )
                keyboard = [[InlineKeyboardButton("📥 Mở Link Direct", url=data['direct_url'])]]
                await status_msg.edit_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                await status_msg.edit_text("❌ Không thể trích xuất direct link từ nền tảng này!")
        except Exception as e:
            await status_msg.edit_text(f"❌ *Lỗi khi truy cập link:* `{str(e)[:100]}`", parse_mode="Markdown")

# ================= 3. GIAO DIỆN & MENU =================
def get_menu_keyboard(is_owner: bool):
    if is_owner:
        keyboard = [
            [InlineKeyboardButton("➕ Add Ngôn", callback_data="menu_add"), InlineKeyboardButton("📜 Ngôn Treo", callback_data="menu_ngontreo")],
            [InlineKeyboardButton("🚀 Gửi Tin", callback_data="menu_spam"), InlineKeyboardButton("⏱ Cài Delay", callback_data="menu_delay")],
            [InlineKeyboardButton("💵 Nạp Tiền (/nap)", callback_data="menu_nap_admin"), InlineKeyboardButton("💳 Cá Nhân", callback_data="menu_info")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("💰 Hướng Dẫn Nạp Tiền", callback_data="menu_naptien")],
            [InlineKeyboardButton("💳 Kiểm Tra Số Dư", callback_data="menu_info")]
        ]
    return InlineKeyboardMarkup(keyboard)

async def start_or_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = auto_save_user(user)
    is_owner = (user.id == BOT_OWNER_ID)

    role_str = "👑 **BOT OWNER**" if is_owner else "👤 **Thành Viên**"
    text = (
        f"🤖 **BẢNG ĐIỀU KHIỂN BOT**\n\n"
        f"• Quyền hạn: {role_str}\n"
        f"• Tên: **{user.first_name}**\n"
        f"• ID Telegram: `{user.id}`\n"
        f"• Số dư: **{balance:,} VNĐ**\n\n"
    )

    if is_owner:
        check_and_reset_daily_budget()
        remaining = MAX_DAILY_BUDGET - bot_config["admin_used_today"]
        text += f"📊 Hạn mức nạp còn lại hôm nay: **{remaining:,} / 10B VNĐ**\n\n"

    text += "Gõ `/addbot` để thêm bot vào box nhóm khác."

    if update.message:
        await update.message.reply_text(text, reply_markup=get_menu_keyboard(is_owner), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_menu_keyboard(is_owner), parse_mode="Markdown")

# ================= 4. LỆNH CƠ BẢN & ADMIN =================
async def add_bot_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_info = await context.bot.get_me()
    add_url = f"https://t.me/{bot_info.username}?startgroup=true"
    keyboard = [[InlineKeyboardButton("➕ Chọn Box Cần Thêm Bot", url=add_url)]]
    await update.message.reply_text("👇 Bấm nút bên dưới để chọn nhóm/box muốn thêm bot vào:", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_qtv_box(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sender_id = update.effective_user.id

    if not is_box_qtv(chat_id, sender_id):
        await update.message.reply_text("⛔ Bạn không có quyền cấp QTV tại box này!")
        return

    target_user_id = None
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
    elif context.args:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            pass

    if not target_user_id:
        await update.message.reply_text("⚠️ **Cú pháp:** Reply tin nhắn người cần thêm hoặc gõ `/qtv <ID_User>`", parse_mode="Markdown")
        return

    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO group_qtvs (chat_id, user_id, added_by) VALUES (?, ?, ?)", (chat_id, target_user_id, sender_id))
        conn.commit()
        await update.message.reply_text(f"✅ Đã thêm ID `{target_user_id}` làm **QTV** của box này!", parse_mode="Markdown")
    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ Người này đã là QTV của box rồi!")
    finally:
        conn.close()

async def ban_qtv_box(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sender_id = update.effective_user.id

    if not is_box_qtv(chat_id, sender_id):
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh ban!")
        return

    target_user_id = None
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
    elif context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            target_user_id = get_user_id_by_username(arg)
            if not target_user_id:
                await update.message.reply_text(f"❌ Không tìm thấy ID của `{arg}` trong CSDL bot!", parse_mode="Markdown")
                return
        else:
            try:
                target_user_id = int(arg)
            except ValueError:
                pass

    if not target_user_id:
        await update.message.reply_text("⚠️ **Cú pháp:** `/ban @username`, `/ban <ID>` hoặc Reply tin nhắn + `/ban`", parse_mode="Markdown")
        return

    if target_user_id == BOT_OWNER_ID:
        await update.message.reply_text("🛡️ **Hệ thống bảo vệ:** Tuyệt đối không thể ban Bot Owner!", parse_mode="Markdown")
        return

    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM group_qtvs WHERE chat_id = ? AND user_id = ?", (chat_id, target_user_id))
    conn.commit()
    conn.close()

    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_user_id)
        await update.message.reply_text(f"🛑 Đã tước quyền QTV và **ban ID `{target_user_id}`** ra khỏi box!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(f"🛑 Đã tước quyền QTV Bot của ID `{target_user_id}` trong box!", parse_mode="Markdown")

async def nap_tien_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Chỉ Bot Owner mới có quyền nạp tiền!")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Cú pháp: `/nap <ID_User> <Số_Tiền>`", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ ID và Số tiền phải là số nguyên!")
        return

    check_and_reset_daily_budget()
    if bot_config["admin_used_today"] + amount > MAX_DAILY_BUDGET:
        remaining = MAX_DAILY_BUDGET - bot_config["admin_used_today"]
        await update.message.reply_text(f"❌ Vượt quá hạn mức 10 tỷ/ngày! Còn lại: **{remaining:,} VNĐ**", parse_mode="Markdown")
        return

    conn = sqlite3.connect("bot_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,))
    row = cursor.fetchone()
    if not row:
        await update.message.reply_text("❌ Người dùng này chưa từng bấm `/start` tương tác với bot!")
        conn.close()
        return

    new_bal = row[0] + amount
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_id))
    conn.commit()
    conn.close()

    bot_config["admin_used_today"] += amount
    await update.message.reply_text(f"✅ Đã cộng **{amount:,} VNĐ** cho ID `{target_id}`.", parse_mode="Markdown")

async def add_ngon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Chỉ Owner mới có quyền add ngôn!")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Cú pháp: `/add <nội dung>`", parse_mode="Markdown")
        return
    txt = " ".join(context.args)
    bot_config["ngon_treo"].append(txt)
    await update.message.reply_text(f"✅ Đã thêm ngôn: `{txt}`", parse_mode="Markdown")

async def list_ngon_treo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Chỉ Owner mới có quyền xem ngôn treo!")
        return
    if not bot_config["ngon_treo"]:
        await update.message.reply_text("📂 Danh sách ngôn treo đang trống!")
        return
    msg = "📜 **DANH SÁCH NGÔN TREO:**\n\n" + "\n".join([f"{i}. {v}" for i, v in enumerate(bot_config["ngon_treo"], 1)])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def send_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Chỉ Owner mới được dùng lệnh này!")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Cú pháp: `/spam @username <nội dung>`", parse_mode="Markdown")
        return
    target, content = context.args[0], " ".join(context.args[1:])
    await update.message.reply_text(f"⏳ Đang xử lý tới {target} (Delay {bot_config['delay']}s)...")
    await asyncio.sleep(bot_config["delay"])
    await update.message.reply_text(f"{target} {content}")

async def set_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Chỉ Owner mới được chỉnh delay!")
        return
    if not context.args:
        await update.message.reply_text(f"⏱ Delay hiện tại: **{bot_config['delay']}s**", parse_mode="Markdown")
        return
    try:
        bot_config["delay"] = max(1.0, float(context.args[0]))
        await update.message.reply_text(f"✅ Đã cập nhật delay: **{bot_config['delay']}s**", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Thời gian delay phải là một số!")

# ================= 5. XỬ LÝ BUTTONS =================
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    is_owner = (user.id == BOT_OWNER_ID)
    balance = auto_save_user(user)
    data = query.data

    if data in ["menu_add", "menu_ngontreo", "menu_spam", "menu_delay", "menu_nap_admin"] and not is_owner:
        await query.message.reply_text("⛔ Quyền truy cập bị từ chối!")
        return

    if data == "menu_info":
        await query.message.reply_text(f"💳 **CÁ NHÂN**\n• ID: `{user.id}`\n• Số dư: **{balance:,} VNĐ**", parse_mode="Markdown")
    elif data == "menu_naptien":
        await query.message.reply_text(f"💰 **NẠP TIỀN**\n• STK: `{STK_BANK}`\n• Nội dung: `NAP {user.id}`", parse_mode="Markdown")
    elif data == "menu_nap_admin":
        await query.message.reply_text("💵 Cú pháp cấp tiền:\n`/nap <ID_User> <Số_Tiền>`", parse_mode="Markdown")
    elif data == "menu_add":
        await query.message.reply_text("➕ Cú pháp: `/add <nội dung>`", parse_mode="Markdown")
    elif data == "menu_ngontreo":
        await list_ngon_treo(update, context)
    elif data == "menu_spam":
        await query.message.reply_text("🚀 Cú pháp: `/spam @username Nội dung`", parse_mode="Markdown")
    elif data == "menu_delay":
        await query.message.reply_text(f"⏱ Cú pháp: `/delay <số_giây>`", parse_mode="Markdown")

# ================= KHỞI CHẠY HỆ THỐNG =================
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    # Đăng ký Command Handler
    app.add_handler(CommandHandler(["start", "menu"], start_or_menu))
    app.add_handler(CommandHandler("addbot", add_bot_to_group))
    app.add_handler(CommandHandler("qtv", add_qtv_box))
    app.add_handler(CommandHandler("ban", ban_qtv_box))
    app.add_handler(CommandHandler("nap", nap_tien_admin))
    app.add_handler(CommandHandler("add", add_ngon))
    app.add_handler(CommandHandler("ngontreo", list_ngon_treo))
    app.add_handler(CommandHandler("spam", send_msg))
    app.add_handler(CommandHandler("delay", set_delay))
    
    # Handler Nút bấm
    app.add_handler(CallbackQueryHandler(handle_button))

    # 🤫 HANDLER ẨN: Bắt link video
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_hidden_video_link))

    print("Bot đang hoạt động...")
    app.run_polling()
