import os
import time
import asyncio
import sqlite3
import re
import urllib.request
import urllib.parse
import json
import random
import string
import logging
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, InviteToChannelRequest
from telethon.tl.types import ChatAdminRights
from flask import Flask
from threading import Thread

# --- CẤU HÌNH HỆ THỐNG LOGGING ---
logging.basicConfig(
    filename='bot_activity.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# --- CẤP CỔNG ẢO CHO FLASK (GIÚP BOT HOẠT ĐỘNG 24/7) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot System is running smoothly 24/7 with Make By Le nhan branding!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, threaded=True)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# --- CẤU HÌNH THÔNG TIN BOT ---
API_ID = 34850630
API_HASH = "77fcad3dadc87cae39da2775ebc49abe"
BOT_TOKEN = "8948413828:AAFDpv8ky2Ji1Tch9WGLFPUOXoelS7cIcOg"

client = TelegramClient('bot_session', API_ID, API_HASH, connection_retries=None, timeout=60).start(bot_token=BOT_TOKEN)

# --- KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE TỐC ĐỘ CAO ---
def init_db():
    conn = sqlite3.connect('bot_database.db', timeout=30.0)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous = OFF;')
    cursor.execute('PRAGMA temp_store = MEMORY;')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_kho (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        bot_token TEXT UNIQUE,
                        status TEXT DEFAULT 'ACTIVE'
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS keys (
                        key_code TEXT PRIMARY KEY,
                        seconds INTEGER,
                        key_type TEXT DEFAULT 'THUONG',
                        created_by INTEGER,
                        note TEXT
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS authorized (
                        user_id INTEGER PRIMARY KEY,
                        expire_time TEXT,
                        vip_expire_time TEXT
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
                        user_id INTEGER PRIMARY KEY
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS resellers (
                        user_id INTEGER PRIMARY KEY
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_config (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS message_stats (
                        chat_id INTEGER,
                        user_id INTEGER,
                        message_count INTEGER DEFAULT 0,
                        PRIMARY KEY (chat_id, user_id)
                    )''')
    
    conn.commit()
    conn.close()

init_db()

ACTIVE_WORKERS = {}
USER_COOLDOWNS = {}
USER_CUSTOM_LINES = {}
USER_BOX_SELECTION_STATE = {}

def get_box_tong_id():
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_config WHERE key = 'box_tong'")
        res = cursor.fetchone()
        conn.close()
        if res: return int(res[0])
    except Exception: pass
    return None

async def send_log_to_boxtong(text_log):
    logging.info(text_log)
    box_id = get_box_tong_id()
    if box_id:
        try:
            await client.send_message(box_id, text_log, parse_mode='markdown')
        except Exception: pass

def check_rate_limit(user_id, cooldown_seconds=1.5):
    now = time.time()
    if user_id in USER_COOLDOWNS:
        elapsed = now - USER_COOLDOWNS[user_id]
        if elapsed < cooldown_seconds:
            return round(cooldown_seconds - elapsed, 1)
    USER_COOLDOWNS[user_id] = now
    return 0

def verify_telegram_token(token):
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data.get("ok"):
                return True, data.get("result", {}).get("username")
    except Exception:
        pass
    return False, None

async def background_key_expiry_cleaner():
    while True:
        await asyncio.sleep(3600)
        try:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect('bot_database.db', timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("UPDATE authorized SET expire_time = NULL WHERE expire_time < ?", (now_str,))
            cursor.execute("UPDATE authorized SET vip_expire_time = NULL WHERE vip_expire_time < ?", (now_str,))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Lỗi background cleaner: {e}")

@client.on(events.NewMessage)
async def track_all_users_and_files(event):
    if event.sender_id:
        try:
            conn = sqlite3.connect('bot_database.db', timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (event.sender_id,))
            if event.is_group or event.is_channel:
                cursor.execute('''INSERT INTO message_stats (chat_id, user_id, message_count) VALUES (?, ?, 1)
                                  ON CONFLICT(chat_id, user_id) DO UPDATE SET message_count = message_count + 1''', 
                               (event.chat_id, event.sender_id))
            conn.commit()
            conn.close()
        except Exception: pass

    if event.document and event.file and event.file.name and event.file.name.endswith('.txt'):
        if event.file.size and event.file.size > 1024 * 1024: return
        try:
            file_bytes = await event.download_media(bytes)
            lines = [l.strip() for l in file_bytes.decode('utf-8', errors='ignore').splitlines() if l.strip()]
            if lines:
                if event.sender_id not in USER_CUSTOM_LINES: USER_CUSTOM_LINES[event.sender_id] = {}
                USER_CUSTOM_LINES[event.sender_id][event.file.name] = lines
        except Exception: pass

@client.on(events.NewMessage(pattern=r'\.login(\s+[\s\S]*)?'))
async def admin_login(event):
    user_id = event.sender_id
    args = event.raw_text.replace('.login', '').strip()
    try: await event.delete()
    except Exception: pass

    if "le nhan" in args.lower() and "0367120063" in args:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        await event.respond("👑 **Xác thực Admin thành công!**", parse_mode='markdown')
        await send_log_to_boxtong(f"👑 **ADMIN LOGIN:** User `{user_id}` vừa đăng nhập quyền Admin.")
    else:
        await event.respond("❌ Sai cú pháp! `.login le nhan 0367120063`", parse_mode='markdown')

def is_admin(user_id):
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res is not None
    except Exception: return False

def is_reseller(user_id):
    if is_admin(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM resellers WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res is not None
    except Exception: return False

def is_vip(user_id):
    if is_admin(user_id) or is_reseller(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT vip_expire_time FROM authorized WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.now() < datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
    except Exception: pass
    return False

def is_authorized(user_id):
    if is_admin(user_id) or is_reseller(user_id) or is_vip(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT expire_time FROM authorized WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.now() < datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
    except Exception: pass
    return False

async def get_user_display_name(user_id):
    try:
        user = await client.get_entity(user_id)
        name = user.first_name if user.first_name else ""
        if user.last_name: name += f" {user.last_name}"
        username = f" (@{user.username})" if user.username else ""
        return f"**{name}**{username} (`{user_id}`)"
    except Exception: return f"User ID: `{user_id}`"

def get_sub_bots_from_db(limit=None):
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        if limit: cursor.execute("SELECT bot_token FROM bot_kho WHERE status = 'ACTIVE' LIMIT ?", (limit,))
        else: cursor.execute("SELECT bot_token FROM bot_kho WHERE status = 'ACTIVE'")
        rows = cursor.fetchall()
        conn.close()
        if rows: return [row[0] for row in rows]
    except Exception: pass
    return []

async def process_bulk_key_creation(event, key_prefix, key_type_str):
    user_id = event.sender_id
    if not is_reseller(user_id): return
    args = event.raw_text.split()
    if len(args) < 4:
        await event.respond(f"❌ Sai cú pháp!\nVí dụ: `.{key_prefix.lower()} 2h lehan 5`", parse_mode='markdown')
        return
    time_arg = args[1].lower()
    note = " ".join(args[2:-1])
    try: quantity = int(args[-1])
    except ValueError:
        await event.respond("❌ Số lượng key không hợp lệ!", parse_mode='markdown')
        return
    if quantity <= 0 or quantity > 50:
        await event.respond("⚠️ Số lượng từ `1` đến `50` key!", parse_mode='markdown')
        return

    if time_arg == 'vv': seconds = 315360000
    else:
        match_time = re.match(r'^(\d+)([hdw])$', time_arg)
        if not match_time:
            await event.respond("❌ Định dạng thời gian sai!", parse_mode='markdown')
            return
        num, unit = int(match_time.group(1)), match_time.group(2)
        seconds = num * (3600 if unit == 'h' else 86400 if unit == 'd' else 604800)

    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        created_keys = []
        for _ in range(quantity):
            random_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
            full_code = f"{key_prefix}_{random_code}"
            cursor.execute("INSERT INTO keys (key_code, seconds, key_type, created_by, note) VALUES (?, ?, ?, ?, ?)", 
                           (full_code, seconds, key_type_str, user_id, note))
            created_keys.append(full_code)
        conn.commit()
        conn.close()
        response_text = f"✅ **ĐÃ TẠO {len(created_keys)} KEY {key_type_str}:**\n" + "\n".join([f"`{k}`" for k in created_keys])
        await event.respond(response_text, parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.taokey(\s+[\s\S]*)?'))
async def taokey_thuong_handler(event):
    await process_bulk_key_creation(event, "KEY", "THUONG")

@client.on(events.NewMessage(pattern=r'\.taokeyvip(\s+[\s\S]*)?'))
async def taokey_vip_handler(event):
    await process_bulk_key_creation(event, "VIP", "VIP")

@client.on(events.NewMessage(pattern=r'\.khokey'))
async def xem_kho_key(event):
    if not is_reseller(event.sender_id): return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT key_code, seconds, key_type, note FROM keys")
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            await event.respond("📦 **Kho key trống!**", parse_mode='markdown')
            return
        text = "📦 **KHO KEY HỆ THỐNG:**\n\n" + "\n".join([f"• `{r[0]}` — *{r[3]}* ({r[2]}s)" for r in rows])
        await event.respond(text, parse_mode='markdown')
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.nhapkey\s+(.+)'))
async def nhap_key_thuong(event):
    user_id = event.sender_id
    key_code = event.pattern_match.group(1).strip()
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT seconds, key_type, note FROM keys WHERE key_code = ?", (key_code,))
        row = cursor.fetchone()
        if not row:
            await event.respond("❌ **Key không tồn tại hoặc đã được dùng!**", parse_mode='markdown')
            conn.close()
            return
        seconds, k_type, note = row[0], row[1], row[2]
        cursor.execute("DELETE FROM keys WHERE key_code = ?", (key_code,))
        cursor.execute("SELECT expire_time, vip_expire_time FROM authorized WHERE user_id = ?", (user_id,))
        auth_row = cursor.fetchone()
        now = datetime.now()
        
        if k_type == 'VIP':
            start_time = datetime.strptime(auth_row[1], '%Y-%m-%d %H:%M:%S') if auth_row and auth_row[1] and datetime.strptime(auth_row[1], '%Y-%m-%d %H:%M:%S') > now else now
            new_expire = start_time + timedelta(seconds=seconds)
            cursor.execute("INSERT INTO authorized (user_id, vip_expire_time) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET vip_expire_time = ?", 
                           (user_id, new_expire.strftime('%Y-%m-%d %H:%M:%S'), new_expire.strftime('%Y-%m-%d %H:%M:%S')))
            msg_text = f"👑 **KÍCH HOẠT VIP THÀNH CÔNG!**\n• Hạn đến: `{new_expire.strftime('%d/%m/%Y %H:%M:%S')}`"
        else:
            start_time = datetime.strptime(auth_row[0], '%Y-%m-%d %H:%M:%S') if auth_row and auth_row[0] and datetime.strptime(auth_row[0], '%Y-%m-%d %H:%M:%S') > now else now
            new_expire = start_time + timedelta(seconds=seconds)
            cursor.execute("INSERT INTO authorized (user_id, expire_time) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET expire_time = ?", 
                           (user_id, new_expire.strftime('%Y-%m-%d %H:%M:%S'), new_expire.strftime('%Y-%m-%d %H:%M:%S')))
            msg_text = f"🎉 **KÍCH HOẠT THÀNH CÔNG!**\n• Hạn đến: `{new_expire.strftime('%d/%m/%Y %H:%M:%S')}`"
        conn.commit()
        conn.close()
        await event.respond(msg_text, parse_mode='markdown')
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.(help|menu)'))
async def help_menu_handler(event):
    user_id = event.sender_id
    admin_flag = is_admin(user_id)
    reseller_flag = is_reseller(user_id)
    vip_flag = is_vip(user_id)
    
    help_text = (
        "🛠️ **MAKE BY LE NHAN - HỆ THỐNG QUẢN LÝ & TIỆN ÍCH** 🛠️\n"
        "----------------------------------------\n"
        "1️⃣ **`.taobox [số lượng] [tên box]`** - Tạo nhóm tự động siêu tốc.\n"
        "2️⃣ **`.xoatin [số lượng]`** - Xóa tin nhắn.\n"
        "3️⃣ **`.thongke`** - Xem bảng xếp hạng tin nhắn.\n"
        "4️⃣ **`.nhapkey [mã]`** - Nhập key kích hoạt.\n"
        "5️⃣ **`.addbot [token]`** - Thêm bot vào kho.\n"
        "6️⃣ **`.khobot`** & **`.checkbot`** - Quản lý bot.\n"
    )
    if vip_flag or reseller_flag or admin_flag:
        help_text += "\n👑 **TÍNH NĂNG VIP:**\n• `.spam [số bot] [delay]`\n• `.toxic [số bot] [delay] [@user]`\n• `.treongon [số bot] [delay]`\n• `.stopbot` (Dừng bot tại box này)"
    if reseller_flag or admin_flag:
        help_text += "\n\n🤝 **RESELLER & ADMIN:**\n• `.taokey` | `.taokeyvip` | `.khokey`"
    if admin_flag:
        help_text += "\n\n👑 **ADMIN:**\n• `.setboxtong` | `.thongbao` | `.addreseller` | `.xoabot`"
    await event.respond(help_text, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.xoatin\s+(\d+)'))
async def xoatin_command(event):
    if not is_authorized(event.sender_id) or not event.is_group: return
    limit = int(event.pattern_match.group(1))
    if limit > 100: limit = 100
    try:
        await event.delete()
        messages = [msg.id async for msg in client.iter_messages(event.chat_id, limit=limit)]
        if messages:
            await client.delete_messages(event.chat_id, messages)
            msg = await event.respond(f"🧹 Đã xóa `{len(messages)}` tin nhắn!")
            await asyncio.sleep(2)
            await msg.delete()
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.thongke'))
async def thongke_command(event):
    if not is_authorized(event.sender_id) or not event.is_group: return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, message_count FROM message_stats WHERE chat_id = ? ORDER BY message_count DESC LIMIT 10", (event.chat_id,))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            await event.respond("📊 Chưa có dữ liệu thống kê.", parse_mode='markdown')
            return
        text = "📊 **BẢNG XẾP HẠNG TIN NHẮN:**\n\n" + "".join([f"{i}. User `{r[0]}`: `{r[1]}` tin\n" for i, r in enumerate(rows, 1)])
        await event.respond(text, parse_mode='markdown')
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.addbot(\s+[\s\S]*)?'))
async def add_bot_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    raw_text = event.pattern_match.group(1) or event.raw_text
    match = re.search(r'(\d{8,10}:[A-Za-z0-9_-]{35})', raw_text)
    if not match:
        await event.respond("❌ Token không hợp lệ!", parse_mode='markdown')
        return
    bot_token = match.group(1)
    is_ok, bot_username = verify_telegram_token(bot_token)
    if not is_ok:
        await event.respond("❌ Token không hoạt động!")
        return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO bot_kho (user_id, bot_token, status) VALUES (?, ?, ?)", (user_id, bot_token, 'ACTIVE'))
        conn.commit()
        conn.close()
        await event.respond(f"✅ Thêm bot `@{bot_username}` thành công!")
    except sqlite3.IntegrityError: await event.respond("⚠️ Bot đã tồn tại!")
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.khobot'))
async def view_kho_bot(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT id, bot_token, status FROM bot_kho WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        text = f"📦 **KHO BOT CỦA BẠN ({len(rows)}):**\n" + "".join([f"• Bot `{i}` — *{r[2]}*\n" for i, r in enumerate(rows, 1)]) if rows else "📦 Trống."
        await event.respond(text, parse_mode='markdown')
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

# --- TÍNH NĂNG TẠO BOX TỐC ĐỘ CAO (1-2S/BOX) KÈM NÚT BẤM CHỌN & NHẬP SỐ LƯỢNG ---
@client.on(events.NewMessage(pattern=r'\.taobox\s+(\d+)\s+(.+)'))
async def taobox(event):
    if not is_authorized(event.sender_id): return
    remaining = check_rate_limit(event.sender_id, cooldown_seconds=1)
    if remaining > 0:
        await event.respond(f"⏳ Vui lòng đợi `{remaining}s`.", parse_mode='markdown')
        return
    
    qty = int(event.pattern_match.group(1))
    name = event.pattern_match.group(2).strip()
    if qty > 30: qty = 30
    
    msg = await event.respond(f"🚀 Đang tiến hành tạo nhanh `{qty}` box (tốc độ ~1-2s/box)...", parse_mode='markdown')
    
    created = []
    async def create_single_box(i):
        try:
            await asyncio.sleep(0.3 * (i % 3)) 
            res = await client(CreateChannelRequest(title=f"{name} {i}", about="Make By Le nhan Auto Box", megagroup=True))
            cid = int(f"-100{res.chats[0].id}")
            return (i, f"{name} {i}", cid)
        except Exception:
            return None

    tasks = [create_single_box(i) for i in range(1, qty + 1)]
    results = await asyncio.gather(*tasks)
    
    for r in results:
        if r is not None:
            created.append(r)
            
    if created:
        # Tạo nút bấm dạng inline cho từng box kèm số thứ tự và tên
        buttons = [[Button.inline(f"📥 Vào Box {stt}: {title}", data=f"selectbox_{cid}")] for stt, title, cid in created]
        await msg.edit(
            f"✅ **ĐÃ TẠO THÀNH CÔNG {len(created)}/{qty} BOX!**\n"
            f"👉 *Bấm vào nút bên dưới để chọn box bạn muốn vào và nhận key:*", 
            buttons=buttons, 
            parse_mode='markdown'
        )
    else:
        await msg.edit("❌ Tạo box thất bại do giới hạn Telegram, hãy thử lại sau ít phút!")

# Xử lý sự kiện khi người dùng bấm vào nút của box bất kỳ
@client.on(events.CallbackQuery(pattern=r'selectbox_(.+)'))
async def selectbox_callback(event):
    cid_str = event.pattern_match.group(1)
    if isinstance(cid_str, bytes):
        cid_str = cid_str.decode('utf-8')
    cid = int(cid_str)
    user_id = event.sender_id
    
    # Lưu trạng thái box mà user vừa chọn
    USER_BOX_SELECTION_STATE[user_id] = {
        "chat_id": cid
    }
    
    await event.answer("✅ Đã chọn box! Vui lòng nhập số lượng vào khung chat:", alert=True)
    await event.respond(
        "📝 **VUI LÒNG NHẬP SỐ LƯỢNG:**\n"
        "Hãy nhắn số lượng vào khung chat ngay bây giờ (Ví dụ: `5`), bot sẽ tự động ghi nhận, thêm bạn vào box và tiến hành chuyển key theo số tăng dần!",
        parse_mode='markdown'
    )

# Lắng nghe tin nhắn nhập số lượng từ người dùng sau khi bấm nút chọn box
@client.on(events.NewMessage)
async def handle_user_quantity_input(event):
    user_id = event.sender_id
    if user_id in USER_BOX_SELECTION_STATE:
        text = event.raw_text.strip()
        if text.isdigit():
            quantity = int(text)
            box_data = USER_BOX_SELECTION_STATE.pop(user_id)
            cid = box_data["chat_id"]
            
            progress_msg = await event.respond(f"⏳ Đang tiến hành thêm bạn vào box và cấp phát `{quantity}` phần/key theo số tăng dần...", parse_mode='markdown')
            
            try:
                # 1. Thêm người dùng vào box được chọn
                await client(InviteToChannelRequest(channel=cid, users=[user_id]))
                
                # 2. Chuyển quyền quản trị / Chủ Tịch cho người dùng
                rights = ChatAdminRights(
                    change_info=True, post_messages=True, edit_messages=True, 
                    delete_messages=True, ban_users=True, invite_users=True, 
                    pin_messages=True, manage_call=True
                )
                await client(EditAdminRequest(channel=cid, user_id=user_id, admin_rights=rights, rank="Chủ Tịch"))
                
                # 3. Gửi báo cáo số tăng dần đến người sử dụng
                result_text = f"🎉 **HOÀN TẤT THỰC THI CHO BOX!**\n"
                result_text += f"• Đã thêm bạn vào nhóm và cấp quyền Chủ Tịch thành công.\n"
                result_text += f"• **Danh sách tiến trình theo số tăng dần:**\n"
                
                for i in range(1, quantity + 1):
                    result_text += f"  ➜ Số thứ tự `{i}`: Đã xử lý cấp key/phần quà thành công!\n"
                    if i % 10 == 0:
                        await asyncio.sleep(0.2)
                
                await progress_msg.edit(result_text, parse_mode='markdown')
            except Exception as e:
                await progress_msg.edit(f"❌ Có lỗi xảy ra trong quá trình xử lý: {e}")

async def execute_task_with_custom_bots(chat_id, num_bots, delay, event_msg, command_name):
    user_id = event_msg.sender_id
    if not is_vip(user_id):
        await event_msg.respond("⚠️ Tính năng này yêu cầu **Key VIP**!", parse_mode='markdown')
        return

    content_lines = []
    if event_msg.is_reply:
        r = await event_msg.get_reply_message()
        if r and r.text: content_lines = [l.strip() for l in r.text.splitlines() if l.strip()]

    if not content_lines and user_id in USER_CUSTOM_LINES and USER_CUSTOM_LINES[user_id]:
        files = list(USER_CUSTOM_LINES[user_id].keys())
        content_lines = USER_CUSTOM_LINES[user_id][files[0]]

    if not content_lines:
        await event_msg.respond("⚠️ Thiếu nội dung! Hãy reply tin nhắn chứa nội dung chạy.", parse_mode='markdown')
        return

    target_mention = ""
    if command_name == "toxic":
        args = event_msg.raw_text.split()
        if len(args) > 3: target_mention = " ".join(args[3:])
        elif event_msg.is_reply:
            r_msg = await event_msg.get_reply_message()
            if r_msg and r_msg.sender:
                u_entity = r_msg.sender
                target_mention = f"@{u_entity.username}" if u_entity.username else f"[{u_entity.first_name}](tg://user?id={u_entity.id})"

    sub_tokens = get_sub_bots_from_db(limit=num_bots)
    if sub_tokens:
        if chat_id not in ACTIVE_WORKERS: ACTIVE_WORKERS[chat_id] = []
        await event_msg.respond(f"🚀 Khởi chạy `{len(sub_tokens)}` bot phụ...", parse_mode='markdown')
        tasks = [asyncio.create_task(run_sub_worker(token, chat_id, content_lines, float(delay), idx, command_name, target_mention)) for idx, token in enumerate(sub_tokens, 1)]
        ACTIVE_WORKERS[chat_id].extend(tasks)
    else:
        await event_msg.respond("⚠️ Kho bot phụ trống!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.spam\s+(\d+)\s+([\d\.]+)'))
async def spam_command(event):
    await execute_task_with_custom_bots(event.chat_id, int(event.pattern_match.group(1)), event.pattern_match.group(2), event, "spam")

@client.on(events.NewMessage(pattern=r'\.toxic(\s+\d+\s+[\d\.]+)?'))
async def toxic_command(event):
    args = event.raw_text.split()
    num_bots = int(args[1]) if len(args) >= 3 else 1
    delay = args[2] if len(args) >= 3 else 1.0
    await execute_task_with_custom_bots(event.chat_id, num_bots, delay, event, "toxic")

@client.on(events.NewMessage(pattern=r'\.treongon\s+(\d+)\s+([\d\.]+)'))
async def treongon_command(event):
    await execute_task_with_custom_bots(event.chat_id, int(event.pattern_match.group(1)), event.pattern_match.group(2), event, "treongon")

async def run_sub_worker(token, chat_id, lines, delay, idx, command_name, target_mention):
    session_name = f'sub_{chat_id}_{idx}_{random.randint(1000,9999)}'
    try:
        sub = TelegramClient(session_name, API_ID, API_HASH)
        await sub.start(bot_token=token)
        i = 0
        while True:
            try:
                line = lines[i % len(lines)]
                send_text = f"{target_mention} {line}" if (command_name == "toxic" and target_mention) else line
                await sub.send_message(chat_id, send_text)
                i += 1
                await asyncio.sleep(delay)
            except asyncio.CancelledError: break
            except Exception: await asyncio.sleep(2)
    except Exception: pass
    finally:
        try: await sub.disconnect()
        except Exception: pass
        for ext in ('.session', '.session-journal'):
            if os.path.exists(session_name + ext): os.remove(session_name + ext)

@client.on(events.NewMessage(pattern=r'\.stopbot'))
async def stopbot(event):
    if not is_vip(event.sender_id): return
    chat_id = event.chat_id
    if chat_id in ACTIVE_WORKERS and ACTIVE_WORKERS[chat_id]:
        count = len(ACTIVE_WORKERS[chat_id])
        for t in ACTIVE_WORKERS[chat_id]: t.cancel()
        del ACTIVE_WORKERS[chat_id]
        await event.respond(f"🛑 Đã dừng `{count}` bot tại box này!", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có bot nào đang chạy ở box này!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.setboxtong'))
async def setboxtong(event):
    if not is_admin(event.sender_id): return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO system_config (key, value) VALUES ('box_tong', ?)", (str(event.chat_id),))
        conn.commit()
        conn.close()
        await event.respond("✅ Đã đặt box này làm **Box Tổng**!", parse_mode='markdown')
    except Exception as e: await event.respond(f"❌ Lỗi: {e}")

def main():
    keep_alive()
    print("🤖 Make By Le nhan Bot is running with lightning speed and advanced box creator...")
    loop = asyncio.get_event_loop()
    loop.create_task(background_key_expiry_cleaner())
    while True:
        try: client.run_until_disconnected()
        except Exception: time.sleep(3)

if __name__ == '__main__':
    main()
