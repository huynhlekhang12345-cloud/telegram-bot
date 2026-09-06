import asyncio
import os
import random
import sqlite3
import time
import gc
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityMention, MessageEntityMentionName

API_ID = 2040
API_HASH = 'b18441a1ff607e10a989891a5462e627'
ADMIN_ID = 8725740462
BOT_TOKEN = os.getenv('BOT_TOKEN', '8948413828:AAFDpv8ky2Ji1Tch9WGLFPUOXoelS7cIcOg')
BOX_TONG_ID = -1001234567890

client = TelegramClient('main_bot_session', API_ID, API_HASH)

def init_db():
    try:
        with sqlite3.connect('bot_database.db', timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS bots (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE, username TEXT, owner_id INTEGER)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS keys (key_code TEXT PRIMARY KEY, type TEXT, duration_hours INTEGER, used INTEGER DEFAULT 0)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS vip_users (user_id INTEGER PRIMARY KEY, expiry_timestamp REAL)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY)''')
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

def get_all_active_bots_with_info():
    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT token, username, owner_id FROM bots")
            return [{"token": r[0], "username": r[1], "id": r[2]} for r in cursor.fetchall()]
    except Exception: return []

USER_SESSIONS = {}
ACTIVE_TASKS = {}

@client.on(events.NewMessage(pattern=r'\.start'))
async def start_command(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    role = "👑 Admin" if is_admin(user_id) else ("💎 VIP" if is_vip(user_id) else "👤 Thành viên")
    text = (
        f"🌟 **Make by le nhan**\n"
        f"----------------------------------------\n"
        f"👤 **Cấp bậc:** `{role}`\n"
        f"📂 Gửi file văn bản trực tiếp cho bot để lưu tự động vào kho ẩn.\n"
        f"🧹 Tích hợp cơ chế tự động dọn RAM và báo cáo rớt mạng chuẩn xác."
    )
    await event.respond(text, parse_mode='markdown')

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
            await event.respond(f"✅ Đã lưu file `{file_name}` vào kho ẩn của bạn!", parse_mode='markdown')
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
        await event.respond("⚠️ Kho bot phụ trống!", parse_mode='markdown')
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

    await event.respond("🤖 **CHỌN CÁC CON BOT PHỤ (Bấm vào để tích chọn):**", buttons=buttons, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.treotien'))
async def treotien_start(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return

    bots_list = get_all_active_bots_with_info()
    if not bots_list:
        await event.respond("⚠️ Kho bot phụ trống!", parse_mode='markdown')
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

    await event.respond("🤖 **CHỌN CÁC CON BOT PHỤ (Bấm vào để tích chọn):**", buttons=buttons, parse_mode='markdown')

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

    await event.edit("🤖 **CHỌN CÁC CON BOT PHỤ (Đã cập nhật tích chọn):**", buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'confirm_bots_(\d+)'))
async def confirm_bots_cb(event):
    u_id = int(event.pattern_match.group(1))
    if event.sender_id != u_id or u_id not in USER_SESSIONS:
        await event.answer("Không phải phiên của bạn!", alert=True)
        return

    session = USER_SESSIONS[u_id]
    if not session["selected_bots"]:
        await event.answer("Vui lòng chọn ít nhất 1 con bot!", alert=True)
        return

    session["step"] = "input_delay"
    await event.respond("⏱ **Vui lòng nhập thời gian Delay (giây) bằng cách nhắn tin vào khung chat riêng:**", parse_mode='markdown')

@client.on(events.NewMessage)
async def handle_user_inputs(event):
    if not event.is_group:
        user_id = event.sender_id
        if user_id in USER_SESSIONS:
            session = USER_SESSIONS[user_id]
            text = event.raw_text.strip()
            
            if session["step"] == "input_delay":
                if not text.isdigit():
                    await event.respond("⚠️ Delay phải là một số nguyên (giây)! Nhập lại:", parse_mode='markdown')
                    return
                session["delay"] = int(text)
                session["step"] = "choose_file"
                
                try:
                    with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, filename FROM hidden_files WHERE user_id = ?", (user_id,))
                        rows = cursor.fetchall()
                    if not rows:
                        await event.respond("⚠️ Kho file của bạn đang trống! Hãy gửi file text lên trước.", parse_mode='markdown')
                        del USER_SESSIONS[user_id]
                        return

                    buttons = []
                    for r in rows:
                        f_id, f_name = r
                        buttons.append([Button.inline(f"📄 {f_name} (ID: {f_id})", data=f"select_file_{user_id}_{f_id}")])
                    
                    await event.respond("📂 **CHỌN FILE TRONG KHO ĐỂ TIẾN HÀNH TREO:**", buttons=buttons, parse_mode='markdown')
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

    try:
        with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
            cursor = conn.cursor()
            for idx, b in enumerate(chosen_bots, 1):
                cursor.execute(
                    "INSERT OR REPLACE INTO canhsan_tracking (bot_id, bot_username, owner_id, chat_id, task_type, details, start_time, start_timestamp, target_users, last_msg_time, added_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (777000 + idx, b['username'], u_id, chat_id, mode, f"File: {f_name}", start_time_str, start_ts, targets, "Chưa gửi", added_by)
                )
            conn.commit()
    except Exception: pass

    if chat_id not in ACTIVE_TASKS: ACTIVE_TASKS[chat_id] = []
    tasks = [asyncio.create_task(run_file_worker(b['token'], b['username'], chat_id, f_content, targets, added_by, start_time_str, mode, delay)) for b in chosen_bots]
    ACTIVE_TASKS[chat_id].extend(tasks)

    gc.collect()

    await event.edit(f"✅ **Đã kích hoạt {mode} thành công bằng file `{f_name}`!**\n• Số bot chạy: `{len(chosen_bots)}`\n• Delay: `{delay}s`\n🧹 **Đã tự động dọn RAM hệ thống.**", buttons=None, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.canhsan\s+off'))
async def canhsan_off_command(event):
    chat_id = event.chat_id
    if chat_id in ACTIVE_TASKS:
        for task in ACTIVE_TASKS[chat_id]: task.cancel()
        del ACTIVE_TASKS[chat_id]
        gc.collect()
        await event.respond("🛑 **Đã tắt toàn bộ tiến trình và dọn dẹp RAM thành công tại box này!**", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có tiến trình nào đang chạy tại box này!", parse_mode='markdown')

async def run_file_worker(token, bot_username, chat_id, content_text, targets, added_by, start_time_str, task_type, delay):
    session_name = f'{task_type.lower()}_{chat_id}_{bot_username}_{random.randint(10000,99999)}'
    sub = None
    last_msg_time = "Chưa gửi"
    drop_time_str = ""
    
    try:
        sub = TelegramClient(session_name, API_ID, API_HASH, connection_retries=5, timeout=30)
        sub.token = token
        await sub.start(bot_token=token)
        
        lines = [line.strip() for line in content_text.split('\n') if line.strip()]
        if not lines:
            lines = [content_text]

        loop_count = 0
        while True:
            for text_chunk in lines:
                buttons = [[Button.inline("🔗 Truy cập Sàn / Liên kết", data="action_click")]]
                if task_type == "TOXIC":
                    msg = f"{targets} {text_chunk}"
                else:
                    msg = f"{text_chunk}"
                
                await sub.send_message(chat_id, msg, buttons=buttons)
                
                last_msg_time = time.strftime('%H:%M:%S - %d/%m/%Y')
                
                try:
                    with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("UPDATE canhsan_tracking SET last_msg_time = ? WHERE bot_username = ? AND chat_id = ?", (last_msg_time, bot_username, chat_id))
                        conn.commit()
                except Exception: pass

                await asyncio.sleep(delay)
            
            loop_count += 1
            if loop_count >= 5:
                loop_count = 0
                gc.collect()
            
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
            with sqlite3.connect('bot_database.db', timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM canhsan_tracking WHERE bot_username = ? AND chat_id = ?", (bot_username, chat_id))
                conn.commit()
        except Exception: pass

        try:
            chat_title = "Không rõ"
            try:
                chat_obj = await client.get_entity(chat_id)
                chat_title = getattr(chat_obj, 'title', f"ID: {chat_id}")
            except Exception:
                chat_title = f"ID: {chat_id}"

            alert_msg = (
                f"🚨 **THÔNG BÁO BOT RỚT TIẾN TRÌNH ({task_type})!**\n"
                f"----------------------------------------\n"
                f"🏷️ **Tên Box:** `{chat_title}`\n"
                f"📂 **Box Chat ID:** `{chat_id}`\n"
                f"🤖 **Bot:** `@{bot_username}`\n"
                f"👤 **Người Add:** `{added_by}`\n"
                f"💬 **Tin nhắn cuối lúc:** `{last_msg_time}`\n"
                f"⏱ **Thời gian rớt:** `{drop_time_str}`\n"
                f"----------------------------------------"
            )
            await client.send_message(ADMIN_ID, alert_msg, parse_mode='markdown')
            await client.send_message(BOX_TONG_ID, alert_msg, parse_mode='markdown')
        except Exception: pass

if __name__ == '__main__':
    print("🚀 Hệ thống Bot Tự Động 24/7 đang khởi chạy...")
    client.start(bot_token=BOT_TOKEN)
    print("✨ Bot chính đã hoạt động toàn diện!")
    client.run_until_disconnected()
