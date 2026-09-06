import asyncio
import os
import random
import sqlite3
import time
import gc
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityMention, MessageEntityMentionName

# ==================== CẤU HÌNH HỆ THỐNG ====================
API_ID = 34850630
API_HASH = '77fcad3dadc87cae39da2775ebc49abe'
ADMIN_ID = 8725740462
BOT_TOKEN = os.getenv('BOT_TOKEN', '8948413828:AAFDpv8ky2Ji1Tch9WGLFPUOXoelS7cIcOg')

# ==================== WEB SERVER GIẢ LẬP CHO RENDER ====================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running 24/7!")
    def log_message(self, format, *args):
        return

def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_dummy_server, daemon=True).start()

# ==================== KHỞI TẠO TELETHON BOT ====================
client = TelegramClient('main_bot_session', API_ID, API_HASH, connection_retries=10, timeout=60)

def init_db():
    try:
        with sqlite3.connect('bot_database.db', timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS bots (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE, username TEXT, owner_id INTEGER)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS keys (key_code TEXT PRIMARY KEY, type TEXT, duration_hours INTEGER, used INTEGER DEFAULT 0)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS vip_users (user_id INTEGER PRIMARY KEY, expiry_timestamp REAL)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS hidden_files (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER, 
                                filename TEXT, 
                                content TEXT
                            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS canhsan_tracking (
                                bot_id INTEGER PRIMARY KEY, 
                                bot_username TEXT, 
                                owner_id INTEGER, 
                                chat_id INTEGER, 
                                task_type TEXT, 
                                details TEXT, 
                                start_time TEXT, 
                                start_timestamp REAL,
                                target_users TEXT,
                                last_msg_time TEXT,
                                added_by TEXT
                            )''')
            conn.commit()
    except Exception as e:
        print(f"Lỗi khởi tạo DB: {e}")

init_db()

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_vip(user_id):
    if is_admin(user_id): return True
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT expiry_timestamp FROM vip_users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row[0] > time.time(): return True
    except Exception: pass
    return False

def is_authorized(user_id):
    if is_admin(user_id) or is_vip(user_id): return True
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,))
            if cursor.fetchone(): return False
    except Exception: pass
    return True

def get_box_tong_id():
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'box_tong_id'")
            row = cursor.fetchone()
            if row:
                return int(row[0])
    except Exception: pass
    return None

def get_all_active_bots_with_info():
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT token, username, owner_id FROM bots")
            return [{"token": r[0], "username": r[1], "id": r[2]} for r in cursor.fetchall()]
    except Exception: return []

USER_SESSIONS = {}
ACTIVE_TASKS = {}  # Cấu trúc: ACTIVE_TASKS[chat_id] = {"TOXIC": [tasks], "TREOTIEN": [tasks], ...}

@client.on(events.NewMessage(pattern=r'\.start'))
async def start_command(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    role = "👑 Admin" if is_admin(user_id) else ("💎 VIP" if is_vip(user_id) else "👤 Thành viên")
    box_tong = get_box_tong_id()
    text = (
        f"🌟 **Make by le nhan**\n"
        f"----------------------------------------\n"
        f"👤 **Cấp bậc:** `{role}`\n"
        f"📢 **Box Tổng:** `{box_tong if box_tong else 'Chưa thiết lập'}`\n"
        f"➕ **Thêm bot phụ:** `.addbot <token> <username>`\n"
        f"🛑 **Lệnh tắt:** `.treotien off`, `.toxic off`, `.canhsan off`, `.stopbot` (tổng)"
    )
    await event.respond(text, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.addbot'))
async def add_bot_command(event):
    user_id = event.sender_id
    if not is_admin(user_id):
        await event.respond("⚠️ Chỉ có Admin mới có quyền thêm bot phụ!", parse_mode='markdown')
        return
    args = event.raw_text.split(maxsplit=2)
    if len(args) < 3:
        await event.respond("⚠️ Sai cú pháp! Dùng: `.addbot <token> <username>`", parse_mode='markdown')
        return
    token = args[1]
    username = args[2].lstrip('@')
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO bots (token, username, owner_id) VALUES (?, ?, ?)", (token, username, user_id))
            conn.commit()
        await event.respond(f"✅ **Đã thêm bot phụ thành công:** `@{username}`", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.setboxtong'))
async def set_box_tong_command(event):
    user_id = event.sender_id
    if not is_admin(user_id): return
    chat_id = event.chat_id
    args = event.raw_text.split()
    target_box = chat_id
    if len(args) > 1 and args[1].lstrip('-').isdigit():
        target_box = int(args[1])
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('box_tong_id', ?)", (str(target_box),))
            conn.commit()
        await event.respond(f"✅ **Đã cập nhật Box Tổng!** ID: `{target_box}`", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}", parse_mode='markdown')

@client.on(events.NewMessage(func=lambda e: e.document or (e.text and not e.text.startswith('.'))))
async def save_uploaded_file(event):
    user_id = event.sender_id
    if not is_authorized(user_id) or event.is_group: return
    try:
        if event.document:
            file_name = "document_file.txt"
            for attr in event.document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    file_name = attr.file_name
            downloaded = await event.download_media()
            with open(downloaded, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if os.path.exists(downloaded): os.remove(downloaded)
            with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO hidden_files (user_id, filename, content) VALUES (?, ?, ?)", (user_id, file_name, content))
                conn.commit()
            await event.respond(f"✅ Đã lưu file `{file_name}` vào kho ẩn!", parse_mode='markdown')
    except Exception as e:
        print(f"Lỗi lưu file: {e}")

@client.on(events.NewMessage(pattern=r'\.toxic'))
async def toxic_start(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    mentioned_users = []
    if event.message.entities:
        for ent in event.message.entities:
            if isinstance(ent, MessageEntityMention):
                uname = event.raw_text[ent.offset:ent.offset + ent.length]
                mentioned_users.append(uname)
            elif isinstance(ent, MessageEntityMentionName):
                mentioned_users.append(f"ID:{ent.user_id}")
    if not mentioned_users:
        await event.respond("⚠️ Vui lòng tag mục tiêu! Ví dụ: `.toxic @user`", parse_mode='markdown')
        return
    bots_list = get_all_active_bots_with_info()
    if not bots_list:
        await event.respond("⚠️ Kho bot phụ trống! Dùng `.addbot <token> <username>` trước.", parse_mode='markdown')
        return
    USER_SESSIONS[user_id] = {
        "mode": "TOXIC",
        "targets": ", ".join(mentioned_users),
        "chat_id": event.chat_id,
        "selected_bots": [],
        "all_bots": bots_list,
        "delay": 10,
        "step": "choose_bots"
    }
    buttons = []
    for idx, b in enumerate(bots_list):
        buttons.append([Button.inline(f"🔲 @{b['username']}", data=f"toggle_bot_{user_id}_{idx}")])
    buttons.append([Button.inline("✅ Chấp Nhận Chọn Bot", data=f"confirm_bots_{user_id}")])
    await event.respond("🤖 **CHỌN BOT PHỤ CHO TOXIC:**", buttons=buttons, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.treotien'))
async def treotien_start(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    bots_list = get_all_active_bots_with_info()
    if not bots_list:
        await event.respond("⚠️ Kho bot phụ trống! Dùng `.addbot <token> <username>` trước.", parse_mode='markdown')
        return
    USER_SESSIONS[user_id] = {
        "mode": "TREOTIEN",
        "chat_id": event.chat_id,
        "selected_bots": [],
        "all_bots": bots_list,
        "delay": 10,
        "step": "choose_bots"
    }
    buttons = []
    for idx, b in enumerate(bots_list):
        buttons.append([Button.inline(f"🔲 @{b['username']}", data=f"toggle_bot_{user_id}_{idx}")])
    buttons.append([Button.inline("✅ Chấp Nhận Chọn Bot", data=f"confirm_bots_{user_id}")])
    await event.respond("🤖 **CHỌN BOT PHỤ CHO TREO TIỀN:**", buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'toggle_bot_(\d+)_(\d+)'))
async def toggle_bot_cb(event):
    u_id = int(event.pattern_match.group(1))
    b_idx = int(event.pattern_match.group(2))
    if event.sender_id != u_id or u_id not in USER_SESSIONS:
        await event.answer("Không phải phiên của bạn!", alert=True)
        return
    session = USER_SESSIONS[u_id]
    if b_idx in session["selected_bots"]:
        session["selected_bots"].remove(b_idx)
    else:
        session["selected_bots"].append(b_idx)
    buttons = []
    for idx, b in enumerate(session["all_bots"]):
        icon = "☑️" if idx in session["selected_bots"] else "🔲"
        buttons.append([Button.inline(f"{icon} @{b['username']}", data=f"toggle_bot_{u_id}_{idx}")])
    buttons.append([Button.inline("✅ Chấp Nhận Chọn Bot", data=f"confirm_bots_{u_id}")])
    await event.edit("🤖 **CHỌN BOT PHỤ:**", buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'confirm_bots_(\d+)'))
async def confirm_bots_cb(event):
    u_id = int(event.pattern_match.group(1))
    if event.sender_id != u_id or u_id not in USER_SESSIONS:
        await event.answer("Không phải phiên của bạn!", alert=True)
        return
    session = USER_SESSIONS[u_id]
    if not session["selected_bots"]:
        await event.answer("Chọn ít nhất 1 bot!", alert=True)
        return
    session["step"] = "input_delay"
    await event.respond("⏱ **Nhập thời gian Delay (giây) vào khung chat riêng:**", parse_mode='markdown')

@client.on(events.NewMessage)
async def handle_user_inputs(event):
    if not event.is_group:
        user_id = event.sender_id
        if user_id in USER_SESSIONS:
            session = USER_SESSIONS[user_id]
            text = event.raw_text.strip()
            if session["step"] == "input_delay":
                if not text.isdigit():
                    await event.respond("⚠️ Delay phải là số nguyên! Nhập lại:", parse_mode='markdown')
                    return
                session["delay"] = int(text)
                session["step"] = "choose_file"
                try:
                    with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, filename FROM hidden_files WHERE user_id = ?", (user_id,))
                        rows = cursor.fetchall()
                    if not rows:
                        await event.respond("⚠️ Kho file trống! Gửi file text lên trước.", parse_mode='markdown')
                        del USER_SESSIONS[user_id]
                        return
                    buttons = []
                    for r in rows:
                        f_id, f_name = r
                        buttons.append([Button.inline(f"📄 {f_name} (ID: {f_id})", data=f"select_file_{user_id}_{f_id}")])
                    await event.respond("📂 **CHỌN FILE ĐỂ CHẠY:**", buttons=buttons, parse_mode='markdown')
                except Exception as e:
                    await event.respond(f"❌ Lỗi: {e}", parse_mode='markdown')
                    del USER_SESSIONS[user_id]
                raise events.StopPropagation

@client.on(events.CallbackQuery(pattern=r'select_file_(\d+)_(\d+)'))
async def select_file_cb(event):
    u_id = int(event.pattern_match.group(1))
    file_id = int(event.pattern_match.group(2))
    if event.sender_id != u_id or u_id not in USER_SESSIONS:
        await event.answer("Không phải phiên của bạn!", alert=True)
        return
    session = USER_SESSIONS[u_id]
    chat_id = session["chat_id"]
    mode = session["mode"]
    delay = session["delay"]
    chosen_bots = [session["all_bots"][i] for i in session["selected_bots"]]
    targets = session.get("targets", "Toàn bộ nhóm")
    added_by = f"ID: {u_id}"
    start_time_str = time.strftime('%H:%M:%S - %d/%m/%Y')
    start_ts = time.time()
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename, content FROM hidden_files WHERE id = ? AND user_id = ?", (file_id, u_id))
            row = cursor.fetchone()
        if not row:
            await event.answer("Không tìm thấy file!", alert=True)
            return
        f_name, f_content = row
    except Exception as e:
        await event.answer(f"Lỗi: {e}", alert=True)
        return
    del USER_SESSIONS[u_id]

    if chat_id not in ACTIVE_TASKS: 
        ACTIVE_TASKS[chat_id] = {"TOXIC": [], "TREOTIEN": [], "CANHSAN": []}
    
    tasks = [asyncio.create_task(run_file_worker(b['token'], b['username'], chat_id, f_content, targets, added_by, start_time_str, mode, delay)) for b in chosen_bots]
    ACTIVE_TASKS[chat_id][mode].extend(tasks)
    gc.collect()
    await event.edit(f"✅ **Đã kích hoạt {mode} thành công bằng file `{f_name}`!**", buttons=None, parse_mode='markdown')

# ==================== HỆ THỐNG LỆNH TẮT RIÊNG BIỆT & TỔNG ====================
@client.on(events.NewMessage(pattern=r'\.treotien\s+off'))
async def treotien_off(event):
    chat_id = event.chat_id
    if chat_id in ACTIVE_TASKS and ACTIVE_TASKS[chat_id]["TREOTIEN"]:
        for task in ACTIVE_TASKS[chat_id]["TREOTIEN"]: task.cancel()
        ACTIVE_TASKS[chat_id]["TREOTIEN"] = []
        gc.collect()
        await event.respond("🛑 **Đã tắt toàn bộ tiến trình Treo Tiền tại box này!**", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có tiến trình Treo Tiền nào đang chạy tại box này!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.toxic\s+off'))
async def toxic_off(event):
    chat_id = event.chat_id
    if chat_id in ACTIVE_TASKS and ACTIVE_TASKS[chat_id]["TOXIC"]:
        for task in ACTIVE_TASKS[chat_id]["TOXIC"]: task.cancel()
        ACTIVE_TASKS[chat_id]["TOXIC"] = []
        gc.collect()
        await event.respond("🛑 **Đã tắt toàn bộ tiến trình Toxic tại box này!**", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có tiến trình Toxic nào đang chạy tại box này!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.canhsan\s+off'))
async def canhsan_off(event):
    chat_id = event.chat_id
    if chat_id in ACTIVE_TASKS and ACTIVE_TASKS[chat_id]["CANHSAN"]:
        for task in ACTIVE_TASKS[chat_id]["CANHSAN"]: task.cancel()
        ACTIVE_TASKS[chat_id]["CANHSAN"] = []
        gc.collect()
        await event.respond("🛑 **Đã tắt toàn bộ tiến trình Canh Săn tại box này!**", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có tiến trình Canh Săn nào đang chạy tại box này!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.stopbot'))
async def stopbot_general(event):
    chat_id = event.chat_id
    if chat_id in ACTIVE_TASKS:
        count = 0
        for mode in ACTIVE_TASKS[chat_id]:
            for task in ACTIVE_TASKS[chat_id][mode]:
                task.cancel()
                count += 1
        del ACTIVE_TASKS[chat_id]
        gc.collect()
        await event.respond(f"🛑 **[STOPBOT TỔNG] Đã hủy hoàn toàn {count} tiến trình đang chạy và dọn dẹp RAM tại box này!**", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có bất kỳ tiến trình nào đang chạy tại box này!", parse_mode='markdown')

async def run_file_worker(token, bot_username, chat_id, content_text, targets, added_by, start_time_str, task_type, delay):
    session_name = f'{task_type.lower()}_{chat_id}_{bot_username}_{random.randint(10000,99999)}'
    sub = None
    last_msg_time = "Chưa gửi"
    try:
        sub = TelegramClient(session_name, API_ID, API_HASH, connection_retries=5, timeout=30)
        sub.token = token
        await sub.start(bot_token=token)
        lines = [line.strip() for line in content_text.split('\n') if line.strip()]
        if not lines: lines = [content_text]
        while True:
            for text_chunk in lines:
                buttons = [[Button.inline("🔗 Truy cập Sàn / Liên kết", data="action_click")]]
                msg = f"{targets} {text_chunk}" if task_type == "TOXIC" else f"{text_chunk}"
                await sub.send_message(chat_id, msg, buttons=buttons)
                last_msg_time = time.strftime('%H:%M:%S - %d/%m/%Y')
                await asyncio.sleep(delay)
    except asyncio.CancelledError: pass
    except Exception: pass
    finally:
        drop_time_str = time.strftime('%H:%M:%S - %d/%m/%Y')
        if sub:
            try: await sub.disconnect()
            except Exception: pass
        for ext in ('.session', '.session-journal'):
            if os.path.exists(session_name + ext):
                try: os.remove(session_name + ext)
                except Exception: pass
        gc.collect()
        try:
            chat_title = "Không rõ"
            try:
                chat_obj = await client.get_entity(chat_id)
                chat_title = getattr(chat_obj, 'title', f"ID: {chat_id}")
            except: chat_title = f"ID: {chat_id}"
            alert_msg = (
                f"🚨 **THÔNG BÁO BOT RỚT TIẾN TRÌNH ({task_type})!**\n"
                f"----------------------------------------\n"
                f"🏷️ **Tên Box:** `{chat_title}`\n"
                f"🤖 **Bot:** `@{bot_username}`\n"
                f"💬 **Tin nhắn cuối lúc:** `{last_msg_time}`\n"
                f"⏱ **Thời gian rớt:** `{drop_time_str}`"
            )
            await client.send_message(ADMIN_ID, alert_msg, parse_mode='markdown')
            box_tong_id = get_box_tong_id()
            if box_tong_id:
                await client.send_message(box_tong_id, alert_msg, parse_mode='markdown')
        except: pass

if __name__ == '__main__':
    print("🚀 Hệ thống Bot Tự Động đang khởi chạy...")
    client.start(bot_token=BOT_TOKEN)
    print("✨ Bot chính đã hoạt động toàn diện!")
    client.run_until_disconnected()
