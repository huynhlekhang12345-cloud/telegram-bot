import os
import random
import re
import sqlite3
import time
import asyncio
from telethon import TelegramClient, events, Button

API_ID = 2040
API_HASH = 'b18441a1ff607e10a989891a5462e627'
ADMIN_ID = 8725740462

client = TelegramClient('main_bot_session', API_ID, API_HASH)

def init_db():
    conn = sqlite3.connect('bot_database.db', timeout=5.0)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS bots (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE, username TEXT, owner_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS keys (key_code TEXT PRIMARY KEY, type TEXT, duration_hours INTEGER, used INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS vip_users (user_id INTEGER PRIMARY KEY, expiry_timestamp REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS hidden_files (user_id INTEGER, filename TEXT, content TEXT, PRIMARY KEY (user_id, filename))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS canhsan_tracking (bot_id INTEGER PRIMARY KEY, bot_username TEXT, owner_id INTEGER, chat_id INTEGER, money_text TEXT, start_time TEXT, start_timestamp REAL)''')
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_vip(user_id):
    if is_admin(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT expiry_timestamp FROM vip_users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] > time.time(): return True
    except Exception: pass
    return False

def is_authorized(user_id):
    if is_admin(user_id) or is_vip(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,))
        in_bl = cursor.fetchone()
        conn.close()
        if in_bl: return False
    except Exception: pass
    return True

def get_all_active_bots_with_info():
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT token, username, owner_id FROM bots")
        rows = cursor.fetchall()
        conn.close()
        return [{"token": r[0], "username": r[1], "id": r[2]} for r in rows]
    except Exception: return []

@client.on(events.NewMessage(pattern=r'\.menu'))
async def menu_command(event):
    if not is_authorized(event.sender_id): return
    buttons = [
        [Button.inline("🤖 Kho Bot Phụ", data="menu_bots"), Button.inline("🔑 Kích Hoạt Key", data="menu_keys")],
        [Button.inline("📄 Kho File Ẩn", data="menu_files"), Button.inline("📊 Thống Kê Nhóm", data="menu_stats")],
        [Button.inline("⚙️ Quản Lý Canh Sàn", data="menu_canhsan"), Button.inline("🚫 Blacklist", data="menu_bl")]
    ]
    await event.respond("🌟 **HỆ THỐNG QUẢN LÝ ĐIỀU KHIỂN TỰ ĐỘNG 24/7**\nGõ `.menu` hoặc chọn các tùy chọn bên dưới:", buttons=buttons, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.addbot\s+(.+)'))
async def addbot_command(event):
    if not is_admin(event.sender_id): return
    token = event.pattern_match.group(1).strip()
    try:
        temp_client = TelegramClient(f'temp_{random.randint(1000,9999)}', API_ID, API_HASH)
        temp_client.token = token
        await temp_client.start(bot_token=token)
        me = await temp_client.get_me()
        await temp_client.disconnect()
        
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO bots (token, username, owner_id) VALUES (?, ?, ?)", (token, me.username, event.sender_id))
        conn.commit()
        conn.close()
        await event.respond(f"✅ Thêm bot `@{me.username}` thành công vào hệ thống 24/7!", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi thêm bot: {e}", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.(dsn|checkcanh|listcanh)'))
async def list_canhsan_tracking(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        if is_admin(user_id):
            cursor.execute("SELECT bot_username, bot_id, owner_id, chat_id, money_text, start_time, start_timestamp FROM canhsan_tracking")
        else:
            cursor.execute("SELECT bot_username, bot_id, owner_id, chat_id, money_text, start_time, start_timestamp FROM canhsan_tracking WHERE owner_id = ?", (user_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await event.respond("✨ Không có tiến trình canh sàn nào đang chạy!", parse_mode='markdown')
            return

        current_ts = time.time()
        text = f"📊 **DANH SÁCH SÀN & BOT ĐANG TREO ({len(rows)}):**\n"
        for idx, r in enumerate(rows, 1):
            b_uname, b_id, o_id, c_id, money_txt, start_str, start_ts = r
            run_sec = int(current_ts - start_ts)
            hrs, rem = divmod(run_sec, 3600)
            mins, secs = divmod(rem, 60)
            duration_str = f"{hrs}h {mins}p {secs}s" if hrs > 0 else f"{mins}p {secs}s"
            text += f"`{idx}`. 🤖 @{b_uname} | Sàn: `{money_txt}` | Thời gian chạy: `{duration_str}`\n"
        await event.respond(text, parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}", parse_mode='markdown')

ACTIVE_TOXIC_TASKS = {}
USER_PENDING_TOXIC_SELECTION = {}
ACTIVE_SELECTED_TOXIC_TOKENS = {}

@client.on(events.NewMessage(pattern=r'\.toxic\s+([\d\.]+)'))
async def toxic_command(event):
    user_id = event.sender_id
    if not is_vip(user_id): return
    args = event.raw_text.split()
    try: delay = float(args[1])
    except (ValueError, IndexError): return

    bots_list = get_all_active_bots_with_info()
    if not bots_list: return
    
    USER_PENDING_TOXIC_SELECTION[user_id] = {"delay": delay, "bots": bots_list}
    await event.respond("👉 **Nhập số thứ tự bot phụ cần chạy toxic** (Ví dụ: `1` hoặc `1,2`):", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.toxic\s+off'))
async def toxic_off_command(event):
    chat_id = event.chat_id
    if chat_id in ACTIVE_TOXIC_TASKS:
        for task in ACTIVE_TOXIC_TASKS[chat_id]: task.cancel()
        del ACTIVE_TOXIC_TASKS[chat_id]
        await event.respond("🛑 **Đã tắt toàn bộ tiến trình toxic tại box này!**", parse_mode='markdown')

print("🚀 Hệ thống Bot Tự Động 24/7 đang hoạt động...")
client.start()
client.run_until_disconnected()
