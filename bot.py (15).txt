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

# --- CẤU HÌNH HỆ THỐNG LOGGING (AUDIT LOG) ---
logging.basicConfig(
    filename='bot_activity.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# --- CẤP CỔNG ẢO CHO FLASK (GIÚP RENDER KHÔNG BỊ NGỦ ĐÔNG 24/7) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot System is running smoothly 24/7 with all features!"

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

# Khởi tạo client chính với timeout cao để kết nối bền bỉ
client = TelegramClient('bot_session', API_ID, API_HASH, connection_retries=None, timeout=60).start(bot_token=BOT_TOKEN)

# --- KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE TOÀN DIỆN (TỐI ƯU WAL MODE & INDEX) ---
def init_db():
    conn = sqlite3.connect('bot_database.db', timeout=30.0)
    cursor = conn.cursor()
    
    # Bật chế độ WAL để tăng tốc độ ghi đồng thời, hạn chế tối đa lỗi database locked
    cursor.execute('PRAGMA journal_mode=WAL;')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_kho (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        bot_token TEXT UNIQUE,
                        status TEXT DEFAULT 'ACTIVE'
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS keys (
                        key_code TEXT PRIMARY KEY,
                        seconds INTEGER,
                        created_by INTEGER
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS authorized (
                        user_id INTEGER PRIMARY KEY,
                        expire_time TEXT
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
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_bot_status ON bot_kho(status);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_msg_stats ON message_stats(chat_id, user_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_auth_expire ON authorized(expire_time);')
    
    conn.commit()
    conn.close()

init_db()

ACTIVE_WORKERS = {}
USER_COOLDOWNS = {}
USER_CUSTOM_LINES = {}

PRICING_PACKAGES = {
    "key_1d": {"name": "Gói 1 Ngày", "seconds": 86400, "price": 20000},
    "key_7d": {"name": "Gói 1 Tuần", "seconds": 604800, "price": 50000},
    "key_life": {"name": "Gói Vĩnh Viễn", "seconds": 315360000, "price": 200000}
}

def get_box_tong_id():
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
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

def check_rate_limit(user_id, cooldown_seconds=5):
    now = time.time()
    if user_id in USER_COOLDOWNS:
        elapsed = now - USER_COOLDOWNS[user_id]
        if elapsed < cooldown_seconds:
            return round(cooldown_seconds - elapsed, 1)
    USER_COOLDOWNS[user_id] = now
    return 0

# Hàm kiểm tra token bot bằng urllib (Thư viện chuẩn Python)
def verify_telegram_token(token):
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data.get("ok"):
                return True, data.get("result", {}).get("username")
    except Exception:
        pass
    return False, None

# --- BACKGROUND CRONJOB: TỰ ĐỘNG QUÉT HẾT HẠN KEY ---
async def background_key_expiry_cleaner():
    while True:
        await asyncio.sleep(3600)
        try:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect('bot_database.db', timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM authorized WHERE expire_time < ?", (now_str,))
            expired_users = cursor.fetchall()
            if expired_users:
                cursor.execute("DELETE FROM authorized WHERE expire_time < ?", (now_str,))
                conn.commit()
                for u in expired_users:
                    try:
                        await client.send_message(u[0], "⚠️ **THÔNG BÁO HỆ THỐNG:**\nThời hạn sử dụng dịch vụ của bạn đã hết. Vui lòng mua key mới!", parse_mode='markdown')
                    except Exception: pass
                await send_log_to_boxtong(f"🧹 **CRONJOB:** Đã tự động thu hồi quyền của `{len(expired_users)}` tài khoản hết hạn key.")
            conn.close()
        except Exception as e:
            logging.error(f"Lỗi background cleaner: {e}")

@client.on(events.NewMessage)
async def track_all_users_and_files(event):
    if event.sender_id:
        try:
            conn = sqlite3.connect('bot_database.db', timeout=10.0)
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
        if event.file.size and event.file.size > 1024 * 1024:
            try: await event.respond("⚠️ File `.txt` quá lớn! Vui lòng tải file dưới 1MB.", parse_mode='markdown')
            except Exception: pass
            return
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
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
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
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res is not None
    except Exception: return False

def is_reseller(user_id):
    if is_admin(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM resellers WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res is not None
    except Exception: return False

def is_authorized(user_id):
    if is_admin(user_id) or is_reseller(user_id): return True
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT expire_time FROM authorized WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            expire_time = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            conn.close()
            return datetime.now() < expire_time
        else:
            trial_expire_time = datetime.now() + timedelta(days=3)
            cursor.execute("INSERT INTO authorized (user_id, expire_time) VALUES (?, ?)", (user_id, trial_expire_time.strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()
            return True
    except Exception: return True

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
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        if limit: cursor.execute("SELECT bot_token FROM bot_kho WHERE status = 'ACTIVE' LIMIT ?", (limit,))
        else: cursor.execute("SELECT bot_token FROM bot_kho WHERE status = 'ACTIVE'")
        rows = cursor.fetchall()
        conn.close()
        if rows: return [row[0] for row in rows]
    except Exception: pass
    return []

@client.on(events.NewMessage(pattern=r'\.(help|menu)'))
async def help_menu_handler(event):
    user_id = event.sender_id
    admin_flag = is_admin(user_id)
    reseller_flag = is_reseller(user_id)
    
    help_text = (
        "🤖 **Make by le nhan** 🤖\n"
        "----------------------------------------\n"
        "1️⃣ **`.taobox [số lượng] [tên box]`** - Tạo nhóm tự động.\n"
        "2️⃣ **`.spam [số bot] [delay]`** - Spam bằng bot phụ.\n"
        "3️⃣ **`.toxic [số bot] [delay]`** - Toxic bằng bot phụ.\n"
        "4️⃣ **`.treongon [số bot] [delay]`** - Treo ngôn từ bằng bot phụ.\n"
        "5️⃣ **`.xoatin [số lượng]`** - Xóa tin nhắn.\n"
        "6️⃣ **`.thongke`** - Xem bảng xếp hạng tin nhắn.\n"
        "7️⃣ **`.addbot [token]`** - Thêm bot vào kho.\n"
        "8️⃣ **`.khobot`** & **`.checkbot`** - Quản lý & kiểm tra bot sống/chết.\n"
        "9️⃣ **`.muakey`** - Mua key qua QR.\n"
        "🔟 **`.stopbot`** - Dừng tiến trình."
    )
    if reseller_flag or admin_flag:
        help_text += "\n\n🤝 **RESELLER:**\n• `.taokey [số][h/d/w] [tên]` hoặc `.taokey vv [tên]`"
    if admin_flag:
        help_text += "\n\n👑 **ADMIN:**\n• `.setboxtong` | `.thongbao` | `.addreseller` | `.xoabot`"
    await event.respond(help_text, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.xoatin\s+(\d+)'))
async def xoatin_command(event):
    if not is_authorized(event.sender_id): return
    if not event.is_group and not event.is_channel: return
    limit = int(event.pattern_match.group(1))
    if limit > 100: limit = 100
    try:
        await event.delete()
        messages = []
        async for message in client.iter_messages(event.chat_id, limit=limit):
            messages.append(message.id)
        if messages:
            await client.delete_messages(event.chat_id, messages)
            msg = await event.respond(f"🧹 Đã xóa `{len(messages)}` tin nhắn!")
            await asyncio.sleep(3)
            await msg.delete()
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.thongke'))
async def thongke_command(event):
    if not is_authorized(event.sender_id): return
    if not event.is_group and not event.is_channel: return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, message_count FROM message_stats WHERE chat_id = ? ORDER BY message_count DESC LIMIT 10", (event.chat_id,))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            await event.respond("📊 Chưa có dữ liệu thống kê.", parse_mode='markdown')
            return
        text = "📊 **BẢNG XẾP HẠNG TIN NHẮN TRONG BOX:**\n\n"
        for idx, (uid, count) in enumerate(rows, 1):
            name = await get_user_display_name(uid)
            text += f"{idx}. {name}: `{count}` tin\n"
        await event.respond(text, parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.muakey'))
async def menu_mua_key(event):
    buttons = [[Button.inline(f"🛒 {info['name']} - {info['price']:,} VNĐ".replace(",", "."), data=f"buy_{code}")] for code, info in PRICING_PACKAGES.items()]
    await event.respond("💳 **MUA KEY TỰ ĐỘNG QUA MÃ QR**\nChọn gói bên dưới và gửi ảnh bill:", buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'buy_(.+)'))
async def callback_select_package_bill(event):
    user_id = event.sender_id
    code = event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1)
    if code not in PRICING_PACKAGES: return
    pkg = PRICING_PACKAGES[code]
    if not hasattr(client, '_waiting_for_bill_admin'): client._waiting_for_bill_admin = {}
    client._waiting_for_bill_admin[user_id] = {"seconds": pkg["seconds"], "price": pkg["price"], "name": pkg["name"]}
    await event.edit(f"⚡ **THANH TOÁN: {pkg['name'].upper()}**\n• Số tiền: `{pkg['price']:,} VNĐ`\n📸 Gửi ảnh chụp Bill vào đây để Admin duyệt!", parse_mode='markdown')

@client.on(events.NewMessage(func=lambda e: e.photo))
async def handle_bill(event):
    user_id = event.sender_id
    waiting_dict = getattr(client, '_waiting_for_bill_admin', {})
    if user_id not in waiting_dict: return
    pkg_info = waiting_dict.pop(user_id)
    box_id = get_box_tong_id()
    if not box_id:
        await event.respond("⚠️ Chưa cấu hình Box Tổng nhận bill.", parse_mode='markdown')
        return
    await event.respond("⏳ Đã gửi bill cho Admin chờ duyệt...", parse_mode='markdown')
    approval_id = f"{user_id}_{int(time.time())}"
    if not hasattr(client, '_pending_approvals'): client._pending_approvals = {}
    client._pending_approvals[approval_id] = {"user_id": user_id, "seconds": pkg_info["seconds"], "pkg_name": pkg_info["name"]}
    user_display = await get_user_display_name(user_id)
    buttons = [[Button.inline("✅ Duyệt", data=f"approve_key_{approval_id}"), Button.inline("❌ Từ chối", data=f"reject_key_{approval_id}")]]
    await client.send_message(box_id, f"🔔 **BILL MỚI!**\n• Khách: {user_display}\n• Gói: `{pkg_info['name']}`", file=event.photo, buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'approve_key_(.+)'))
async def callback_approve(event):
    if not is_admin(event.sender_id): return
    approval_id = event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1)
    pending_dict = getattr(client, '_pending_approvals', {})
    if approval_id not in pending_dict: return
    data = pending_dict.pop(approval_id)
    key_code = "LE_NHAN_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO keys (key_code, seconds, created_by) VALUES (?, ?, ?)", (key_code, data["seconds"], event.sender_id))
        expire_time = datetime.now() + timedelta(seconds=data["seconds"])
        cursor.execute("INSERT OR REPLACE INTO authorized (user_id, expire_time) VALUES (?, ?)", (data["user_id"], expire_time.strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        await event.edit(f"✅ Đã duyệt cấp key `{key_code}` thành công!", buttons=None)
        try: await client.send_message(data["user_id"], f"🎉 **CẤP KEY THÀNH CÔNG!**\n• Mã Key: `{key_code}`", parse_mode='markdown')
        except Exception: pass
        await send_log_to_boxtong(f"✅ Key `{key_code}` đã cấp cho User `{data['user_id']}`.")
    except Exception as e:
        await event.answer(f"❌ Lỗi: {e}", alert=True)

@client.on(events.NewMessage(pattern=r'\.addbot(\s+[\s\S]*)?'))
async def add_bot_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    raw_text = event.pattern_match.group(1) or (event.get_reply_message().text if event.is_reply and (await event.get_reply_message()).text else event.raw_text)
    match = re.search(r'(\d{8,10}:[A-Za-z0-9_-]{35})', raw_text)
    if not match:
        await event.respond("❌ Không tìm thấy Token hợp lệ!", parse_mode='markdown')
        return
    bot_token = match.group(1)
    
    is_ok, bot_username = verify_telegram_token(bot_token)
    if not is_ok:
        await event.respond("❌ Token không hợp lệ hoặc bot đã bị khóa!")
        return

    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO bot_kho (user_id, bot_token, status) VALUES (?, ?, ?)", (user_id, bot_token, 'ACTIVE'))
        conn.commit()
        conn.close()
        await event.respond(f"✅ Thêm bot `@{bot_username}` vào kho thành công!")
        await send_log_to_boxtong(f"📦 **THÊM BOT:** User `{user_id}` vừa thêm bot `@{bot_username}`.")
    except sqlite3.IntegrityError:
        await event.respond("⚠️ Bot này đã tồn tại trong kho!")
    except Exception as e:
        await event.respond(f"❌ Lỗi CSDL: {e}")

@client.on(events.NewMessage(pattern=r'\.khobot'))
async def view_kho_bot(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        if is_admin(user_id):
            cursor.execute("SELECT id, user_id, bot_token, status FROM bot_kho")
            rows = cursor.fetchall()
            conn.close()
            text = "👑 **KHO BOT TOÀN HỆ THỐNG:**\n\n" + "".join([f"• ID: `{r[0]}` | User: `{r[1]}`\n  `{r[2]}` — *{r[3]}*\n\n" for r in rows]) if rows else "📦 Trống."
            await event.respond(text + "\n💡 Gõ `.checkbot` để kiểm tra sống/chết.", parse_mode='markdown')
            return
        cursor.execute("SELECT id, bot_token, status FROM bot_kho WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        text = f"📦 **KHO BOT CỦA BẠN (Tổng: {len(rows)}):**\n" + "".join([f"• Bot số `{i}` — *{r[2]}*\n" for i, r in enumerate(rows, 1)]) if rows else "📦 Trống."
        await event.respond(text + "\n💡 Gõ `.checkbot` để kiểm tra.", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.checkbot'))
async def check_bot_status(event):
    if not is_authorized(event.sender_id): return
    msg = await event.respond("⏳ Đang quét kiểm tra kho bot...", parse_mode='markdown')
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        if is_admin(event.sender_id): cursor.execute("SELECT id, bot_token FROM bot_kho")
        else: cursor.execute("SELECT id, bot_token FROM bot_kho WHERE user_id = ?", (event.sender_id,))
        bots = cursor.fetchall()
        conn.close()
        
        active_count, dead_count = 0, 0
        for b_id, token in bots:
            is_ok, _ = verify_telegram_token(token)
            status = 'ACTIVE' if is_ok else 'DEAD'
            if status == 'ACTIVE': active_count += 1
            else: dead_count += 1
            try:
                db = sqlite3.connect('bot_database.db', timeout=10.0)
                cur = db.cursor()
                cur.execute("UPDATE bot_kho SET status = ? WHERE id = ?", (status, b_id))
                db.commit()
                db.close()
            except Exception: pass
            
        await msg.edit(f"✅ **KIỂM TRA HOÀN TẤT!**\n• 🟢 Active: `{active_count}`\n• 🔴 Dead: `{dead_count}`", parse_mode='markdown')
    except Exception as e:
        await msg.edit(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.xoabot\s+(.+)'))
async def delete_bot(event):
    if not is_admin(event.sender_id): return
    target = event.pattern_match.group(1).strip()
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bot_kho WHERE id = ? OR bot_token LIKE ?", (target, f"%{target}%"))
        rowcount = cursor.rowcount
        conn.commit()
        conn.close()
        await event.respond("🗑️ Đã xóa bot!" if rowcount > 0 else "⚠️ Không tìm thấy.")
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.taokey\s+(?:(\d+)([hdw])|(vv))\s+(.+)'))
async def taokey_handler(event):
    user_id = event.sender_id
    if not is_reseller(user_id): return
    match = event.pattern_match
    num_str, unit, is_vv, note = match.group(1), match.group(2), match.group(3), match.group(4).strip()
    seconds = 315360000 if is_vv else int(num_str) * (3600 if unit == 'h' else 86400 if unit == 'd' else 604800)
    key_code = "LE_NHAN_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO keys (key_code, seconds, created_by) VALUES (?, ?, ?)", (key_code, seconds, user_id))
        conn.commit()
        conn.close()
        await event.respond(f"🔑 **TẠO KEY THÀNH CÔNG:**\n• Mã: `{key_code}`\n• Ghi chú: `{note}`", parse_mode='markdown')
        await send_log_to_boxtong(f"🔑 Key mới `{key_code}` tạo bởi `{user_id}`.")
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.addreseller\s+(\d+)'))
async def add_reseller(event):
    if not is_admin(event.sender_id): return
    target_id = int(event.pattern_match.group(1))
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO resellers (user_id) VALUES (?)", (target_id,))
        conn.commit()
        conn.close()
        await event.respond(f"🤝 Đã cấp quyền Reseller cho `{target_id}`!", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

@client.on(events.NewMessage(pattern=r'\.thongbao(\s+[\s\S]*)?'))
async def broadcast_handler(event):
    if not is_admin(event.sender_id): return
    content = event.pattern_match.group(1)
    if not content or not content.strip():
        if event.is_reply:
            r = await event.get_reply_message()
            content = r.text if r else ""
    if not content or not content.strip():
        await event.respond("⚠️ Vui lòng nhập nội dung!", parse_mode='markdown')
        return
    msg = await event.respond("⏳ Đang gửi thông báo...", parse_mode='markdown')
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        all_users = cursor.fetchall()
        conn.close()
        success, failed = 0, 0
        for u in all_users:
            try:
                await client.send_message(u[0], f"📢 **THÔNG BÁO:**\n\n{content}", parse_mode='markdown')
                success += 1
                await asyncio.sleep(0.05)
            except Exception: failed += 1
        await msg.edit(f"✅ Gửi xong! Thành công: `{success}` | Thất bại: `{failed}`", parse_mode='markdown')
    except Exception as e:
        await msg.edit(f"❌ Lỗi: {e}")

async def execute_task_with_custom_bots(chat_id, num_bots, delay, event_msg, command_name):
    user_id = event_msg.sender_id
    remaining = check_rate_limit(user_id, cooldown_seconds=5)
    if remaining > 0:
        await event_msg.respond(f"⏳ Đợi `{remaining}` giây nữa.", parse_mode='markdown')
        return

    content_lines = []
    if event_msg.is_reply:
        r = await event_msg.get_reply_message()
        if r and r.text: content_lines = [l.strip() for l in r.text.splitlines() if l.strip()]

    if not content_lines and user_id in USER_CUSTOM_LINES and USER_CUSTOM_LINES[user_id]:
        files = list(USER_CUSTOM_LINES[user_id].keys())
        if len(files) == 1:
            content_lines = USER_CUSTOM_LINES[user_id][files[0]]
        else:
            buttons = [[Button.inline(f"📁 {fname}", data=f"sel_file_{user_id}_{idx}")] for idx, fname in enumerate(files)]
            if not hasattr(client, '_pending_task_params'): client._pending_task_params = {}
            client._pending_task_params[user_id] = {"chat_id": chat_id, "num_bots": num_bots, "delay": delay, "command_name": command_name}
            await event_msg.respond("📂 Chọn file `.txt` để chạy:", buttons=buttons, parse_mode='markdown')
            return

    if not content_lines:
        await event_msg.respond("⚠️ Chưa có nội dung! Hãy reply tin nhắn hoặc gửi file `.txt`.", parse_mode='markdown')
        return

    sub_tokens = get_sub_bots_from_db(limit=num_bots)
    if sub_tokens:
        task_id = f"{chat_id}_{int(time.time())}"
        await event_msg.respond(f"🚀 Khởi chạy `{len(sub_tokens)}` bot phụ...", parse_mode='markdown')
        tasks = [asyncio.create_task(run_sub_worker(token, chat_id, content_lines, float(delay), idx, task_id)) for idx, token in enumerate(sub_tokens, 1)]
        ACTIVE_WORKERS[task_id] = tasks
    else:
        await event_msg.respond("⚠️ Kho bot phụ trống!", parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'sel_file_(\d+)_(\d+)'))
async def callback_select_file(event):
    user_id_from_cb = int(event.pattern_match.group(1))
    file_idx = int(event.pattern_match.group(2))
    if event.sender_id != user_id_from_cb: return
    user_id = event.sender_id
    files = list(USER_CUSTOM_LINES[user_id].keys())
    selected_filename = files[file_idx]
    content_lines = USER_CUSTOM_LINES[user_id][selected_filename]
    pending_dict = getattr(client, '_pending_task_params', {})
    params = pending_dict.pop(user_id)
    await event.edit(f"✅ Đã chọn `{selected_filename}`. Đang chạy...")
    sub_tokens = get_sub_bots_from_db(limit=params["num_bots"])
    if sub_tokens:
        task_id = f"{params['chat_id']}_{int(time.time())}"
        tasks = [asyncio.create_task(run_sub_worker(token, params['chat_id'], content_lines, float(params['delay']), idx, task_id)) for idx, token in enumerate(sub_tokens, 1)]
        ACTIVE_WORKERS[task_id] = tasks

@client.on(events.NewMessage(pattern=r'\.spam\s+(\d+)\s+([\d\.]+)'))
async def spam_command(event):
    if not is_authorized(event.sender_id): return
    await execute_task_with_custom_bots(event.chat_id, int(event.pattern_match.group(1)), event.pattern_match.group(2), event, "spam")

@client.on(events.NewMessage(pattern=r'\.toxic\s+(\d+)\s+([\d\.]+)'))
async def toxic_command(event):
    if not is_authorized(event.sender_id): return
    await execute_task_with_custom_bots(event.chat_id, int(event.pattern_match.group(1)), event.pattern_match.group(2), event, "toxic")

@client.on(events.NewMessage(pattern=r'\.treongon\s+(\d+)\s+([\d\.]+)'))
async def treongon_command(event):
    if not is_authorized(event.sender_id): return
    await execute_task_with_custom_bots(event.chat_id, int(event.pattern_match.group(1)), event.pattern_match.group(2), event, "treongon")

async def run_sub_worker(token, chat_id, lines, delay, idx, task_id):
    session_name = f'sub_worker_{task_id}_{idx}_{random.randint(1000,9999)}'
    try:
        sub = TelegramClient(session_name, API_ID, API_HASH)
        await sub.start(bot_token=token)
        i = 0
        while True:
            try:
                line = lines[i % len(lines)]
                await sub.send_message(chat_id, line)
                i += 1
                await asyncio.sleep(delay)
            except asyncio.CancelledError: break
            except Exception: await asyncio.sleep(5)
    except Exception: pass
    finally:
        try: await sub.disconnect()
        except Exception: pass
        for ext in ('.session', '.session-journal'):
            try:
                if os.path.exists(session_name + ext): os.remove(session_name + ext)
            except Exception: pass

@client.on(events.NewMessage(pattern=r'\.stopbot'))
async def stopbot(event):
    if not is_authorized(event.sender_id): return
    count = 0
    for tid, tasks in list(ACTIVE_WORKERS.items()):
        for t in tasks: t.cancel(); count += 1
        del ACTIVE_WORKERS[tid]
    await event.respond(f"🛑 Đã dừng toàn bộ ({count} worker)!")

@client.on(events.NewMessage(pattern=r'\.taobox\s+(\d+)\s+(.+)'))
async def taobox(event):
    if not is_authorized(event.sender_id): return
    remaining = check_rate_limit(event.sender_id, cooldown_seconds=10)
    if remaining > 0:
        await event.respond(f"⏳ Chờ `{remaining}` giây.", parse_mode='markdown')
        return
    qty, name = int(event.pattern_match.group(1)), event.pattern_match.group(2).strip()
    if qty > 20: qty = 20
    created = []
    for i in range(1, qty + 1):
        try:
            res = await client(CreateChannelRequest(title=f"{name} {i}", about="Auto", megagroup=True))
            cid = int(f"-100{res.chats[0].id}")
            created.append((i, f"{name} {i}", cid))
            await asyncio.sleep(1)
        except Exception: pass
    if created:
        buttons = [[Button.inline(f"📥 Vô Box {stt}: {title}", data=f"joinbox_{cid}")] for stt, title, cid in created]
        await event.respond(f"📦 Đã tạo thành công {len(created)} box:", buttons=buttons)

@client.on(events.CallbackQuery(pattern=r'joinbox_(.+)'))
async def joinbox(event):
    cid = int(event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1))
    try:
        await client(InviteToChannelRequest(channel=cid, users=[event.sender_id]))
        rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, manage_call=True)
        await client(EditAdminRequest(channel=cid, user_id=event.sender_id, admin_rights=rights, rank="Chủ Tịch"))
        await event.answer("👑 Đã thêm bạn vào box!", alert=True)
    except Exception as e:
        await event.answer(f"❌ Lỗi: {e}", alert=True)

@client.on(events.NewMessage(pattern=r'\.setboxtong'))
async def setboxtong(event):
    if not is_admin(event.sender_id): return
    box_id_val = event.chat_id
    try:
        conn = sqlite3.connect('bot_database.db', timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO system_config (key, value) VALUES ('box_tong', ?)", (str(box_id_val),))
        conn.commit()
        conn.close()
        await event.respond("✅ Đã đặt box này làm **Box Tổng**!", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Lỗi: {e}")

def main():
    keep_alive()
    print("🤖 Bot System is starting with standard libraries...")
    loop = asyncio.get_event_loop()
    loop.create_task(background_key_expiry_cleaner())
    while True:
        try:
            client.run_until_disconnected()
        except Exception as e:
            print(f"⚠️ Mất kết nối, kết nối lại sau 5s... Lỗi: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
