import os
import time
import asyncio
import sqlite3
import re
import requests
import random
import string
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, InviteToChannelRequest
from telethon.tl.types import ChatAdminRights
from flask import Flask
from threading import Thread

# --- CẤP CỔNG ẢO CHO FLASK (GIÚP HOSTING KHÔNG BỊ NGỦ ĐÔNG) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- CẤU HÌNH THÔNG TIN BOT ---
API_ID = 34850630
API_HASH = "77fcad3dadc87cae39da2775ebc49abe"
BOT_TOKEN = "8948413828:AAFDpv8ky2Ji1Tch9WGLFPUOXoelS7cIcOg"

client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE ---
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_kho (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        bot_token TEXT UNIQUE,
                        status TEXT DEFAULT 'ACTIVE'
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS keys (
                        key_code TEXT PRIMARY KEY,
                        seconds INTEGER
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS authorized (
                        user_id INTEGER PRIMARY KEY,
                        expire_time TEXT
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
                        user_id INTEGER PRIMARY KEY
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_config (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY
                    )''')
    conn.commit()
    conn.close()

init_db()

BOX_TONG_ID = None 
ACTIVE_TASKS = {} 
AUTO_CREATED_BOXES = {} 
SYSTEM_LOCKED = False

PRICING_PACKAGES = {
    "key_1d": {"name": "Gói 1 Ngày", "seconds": 86400, "price": 20000},
    "key_7d": {"name": "Gói 1 Tuần", "seconds": 604800, "price": 50000},
    "key_life": {"name": "Gói Vĩnh Viễn", "seconds": 315360000, "price": 200000}
}

# ==========================================
# --- TỰ ĐỘNG LƯU USER ID ---
# ==========================================
@client.on(events.NewMessage)
async def track_all_users(event):
    if event.is_private and event.sender_id:
        try:
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (event.sender_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

# ==========================================
# --- XÁC THỰC ADMIN ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.login(\s+[\s\S]*)?'))
async def admin_login(event):
    user_id = event.sender_id
    args = event.raw_text.replace('.login', '').strip()
    
    if "le nhan" in args.lower() and "0367120063" in args:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        try: await event.delete()
        except Exception: pass
        await event.respond("👑 **Xác thực Admin tối cao thành công!** Gõ `.menu` hoặc `.help` để hiển thị bảng quản trị.", parse_mode='markdown')
    else:
        await event.respond("❌ Sai cú pháp! Cú pháp đúng: `.login le nhan 0367120063`", parse_mode='markdown')

def is_admin(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def is_authorized(user_id):
    if is_admin(user_id): return True
    if SYSTEM_LOCKED: return False
    
    conn = sqlite3.connect('bot_database.db')
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

async def get_user_display_name(user_id):
    try:
        user = await client.get_entity(user_id)
        name = user.first_name if user.first_name else ""
        if user.last_name: name += f" {user.last_name}"
        username = f" (@{user.username})" if user.username else ""
        return f"**{name}**{username} (`{user_id}`)"
    except Exception:
        return f"User ID: `{user_id}`"

def get_sub_bots_from_db(limit_count=1):
    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT bot_token FROM bot_kho LIMIT ?", (limit_count,))
        rows = cursor.fetchall()
        conn.close()
        if rows: return [row[0] for row in rows]
    except Exception: pass
    return []

# ==========================================
# --- MENU & TRỢ GIÚP ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.(help|menu)'))
async def help_menu_handler(event):
    user_id = event.sender_id
    admin_flag = is_admin(user_id)
    
    help_text = (
        "🤖 **HỆ THỐNG BOT QUẢN LÝ & TIỆN ÍCH** 🤖\n"
        "----------------------------------------\n"
        "1️⃣ **`.taobox [số lượng] [tên box]`** - Tạo hàng loạt nhóm tự động.\n"
        "2️⃣ **`.tagbox`** - Chọn box hệ thống để đưa bot vào quản lý.\n"
        "3️⃣ **`.spam [delay]`** - Chạy spam kèm file `.txt` hoặc Reply.\n"
        "4️⃣ **`.treongon [delay]`** - Treo ngôn ngữ tự động.\n"
        "5️⃣ **`.addbot [token]`** - Thêm bot cá nhân vào kho.\n"
        "6️⃣ **`.khobot`** - Xem danh sách bot cá nhân trong kho.\n"
        "7️⃣ **`.muakey`** - Mua key tự động qua mã QR.\n"
        "8️⃣ **`.stopbot`** - Dừng toàn bộ tiến trình đang chạy."
    )

    if admin_flag:
        help_text += (
            "\n\n👑 **QUẢN TRỊ ADMIN:**\n"
            "• `.taokey [số][h/d/w] [tên]` hoặc `.taokey vv [tên]` - Tạo key thủ công.\n"
            "• `.setboxtong` - Đặt box hiện tại nhận log và bill.\n"
            "• `.thongbao [nội dung]` - Gửi thông báo đến toàn bộ user.\n"
            "• `.xoabot [ID/Token]` - Xóa bot khỏi kho.\n"
            "• `.khobot` - Xem toàn bộ kho bot toàn hệ thống."
        )

    await event.respond(help_text, parse_mode='markdown')

# ==========================================
# --- MUA KEY & DUYỆT BILL ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.muakey'))
async def menu_mua_key(event):
    buttons = [[Button.inline(f"🛒 {info['name']} - {info['price']:,} VNĐ".replace(",", "."), data=f"buy_{code}")] for code, info in PRICING_PACKAGES.items()]
    await event.respond("💳 **HỆ THỐNG MUA KEY TỰ ĐỘNG QUA MÃ QR**\nChọn gói bên dưới và gửi ảnh bill cho bot để duyệt!", buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'buy_(.+)'))
async def callback_select_package_bill(event):
    user_id = event.sender_id
    code = event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1)
    if code not in PRICING_PACKAGES: return
    pkg = PRICING_PACKAGES[code]
    
    if not hasattr(client, '_waiting_for_bill_admin'): client._waiting_for_bill_admin = {}
    client._waiting_for_bill_admin[user_id] = {"seconds": pkg["seconds"], "price": pkg["price"], "name": pkg["name"]}

    await event.edit(f"⚡ **THANH TOÁN: {pkg['name'].upper()}**\n• Số tiền: `{pkg['price']:,} VNĐ`\n📸 Hãy gửi ảnh chụp Bill vào đây để Admin duyệt cấp key!", parse_mode='markdown')

@client.on(events.NewMessage(func=lambda e: e.photo))
async def handle_bill(event):
    user_id = event.sender_id
    waiting_dict = getattr(client, '_waiting_for_bill_admin', {})
    if user_id not in waiting_dict: return
    pkg_info = waiting_dict.pop(user_id)
    
    global BOX_TONG_ID
    if not BOX_TONG_ID:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_config WHERE key = 'box_tong'")
        res = cursor.fetchone()
        conn.close()
        if res: BOX_TONG_ID = int(res[0])

    if not BOX_TONG_ID:
        await event.respond("⚠️ Chưa cấu hình Box Tổng nhận bill.", parse_mode='markdown')
        return

    await event.respond("⏳ Đã gửi bill cho Admin chờ duyệt...", parse_mode='markdown')
    approval_id = f"{user_id}_{int(time.time())}"
    if not hasattr(client, '_pending_approvals'): client._pending_approvals = {}
    client._pending_approvals[approval_id] = {"user_id": user_id, "seconds": pkg_info["seconds"], "pkg_name": pkg_info["name"]}

    user_display = await get_user_display_name(user_id)
    buttons = [[Button.inline("✅ Duyệt & Cấp Key", data=f"approve_key_{approval_id}"), Button.inline("❌ Từ chối", data=f"reject_key_{approval_id}")]];
    await client.send_message(BOX_TONG_ID, f"🔔 **DUYỆT MUA KEY!**\n• Khách: {user_display}\n• Gói: `{pkg_info['name']}`", file=event.photo, buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'approve_key_(.+)'))
async def callback_approve(event):
    if not is_admin(event.sender_id): return
    approval_id = event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1)
    pending_dict = getattr(client, '_pending_approvals', {})
    if approval_id not in pending_dict: return
    data = pending_dict.pop(approval_id)
    
    key_code = "LE_NHAN_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO keys (key_code, seconds) VALUES (?, ?)", (key_code, data["seconds"]))
    expire_time = datetime.now() + timedelta(seconds=data["seconds"])
    cursor.execute("INSERT OR REPLACE INTO authorized (user_id, expire_time) VALUES (?, ?)", (data["user_id"], expire_time.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

    await event.edit(f"✅ Đã duyệt cấp key `{key_code}` thành công!", buttons=None)
    try: await client.send_message(data["user_id"], f"🎉 **CẤP KEY THÀNH CÔNG!**\n• Mã Key: `{key_code}`", parse_mode='markdown')
    except Exception: pass

# ==========================================
# --- QUẢN LÝ KHO BOT ---
# ==========================================
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
    
    try:
        res = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10).json()
        if not res.get("ok"):
            await event.respond("❌ Token không hợp lệ!")
            return
        bot_username = res.get("result", {}).get("username")
    except Exception:
        await event.respond("❌ Lỗi kết nối Telegram API.")
        return

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO bot_kho (user_id, bot_token, status) VALUES (?, ?, ?)", (user_id, bot_token, 'ACTIVE'))
        conn.commit()
        await event.respond(f"✅ Thêm bot `@{bot_username}` vào kho thành công!")
    except sqlite3.IntegrityError:
        await event.respond("⚠️ Bot này đã tồn tại trong kho!")
    finally:
        conn.close()

@client.on(events.NewMessage(pattern=r'\.khobot'))
async def view_kho_bot(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    if is_admin(user_id):
        cursor.execute("SELECT id, user_id, bot_token, status FROM bot_kho")
        rows = cursor.fetchall()
        conn.close()
        text = "👑 **KHO BOT TOÀN HỆ THỐNG (ADMIN):**\n\n" + "".join([f"• ID Kho: `{r[0]}` | User: `{r[1]}`\n  `{r[2]}` — *{r[3]}*\n\n" for r in rows]) if rows else "📦 Kho trống."
        await event.respond(text, parse_mode='markdown')
        return

    cursor.execute("SELECT id, bot_token, status FROM bot_kho WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    text = f"📦 **KHO BOT CỦA BẠN ({len(rows)} bot):**\n" + "".join([f"• Bot số `{i}`\n" for i, r in enumerate(rows, 1)]) if rows else "📦 Kho bot trống."
    await event.respond(text, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.xoabot\s+(.+)'))
async def delete_bot(event):
    if not is_admin(event.sender_id): return
    target = event.pattern_match.group(1).strip()
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_kho WHERE id = ? OR bot_token LIKE ?", (target, f"%{target}%"))
    rowcount = cursor.rowcount
    conn.commit()
    conn.close()
    await event.respond("🗑️ Đã xóa bot thành công!" if rowcount > 0 else "⚠️ Không tìm thấy bot.")

# ==========================================
# --- THÔNG BÁO HÀNG LOẠT (BROADCAST) ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.thongbao(\s+[\s\S]*)?'))
async def broadcast_handler(event):
    if not is_admin(event.sender_id): 
        return
    
    content = event.pattern_match.group(1)
    if not content or not content.strip():
        if event.is_reply:
            r = await event.get_reply_message()
            content = r.text if r else ""
    
    if not content or not content.strip():
        await event.respond("⚠️ Vui lòng nhập nội dung thông báo hoặc reply tin nhắn cần gửi!\nCú pháp: `.thongbao [Nội dung]`", parse_mode='markdown')
        return

    msg = await event.respond("⏳ Đang gửi thông báo hàng loạt, vui lòng đợi...", parse_mode='markdown')
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    all_users = cursor.fetchall()
    conn.close()
    
    success = 0
    failed = 0
    
    for u in all_users:
        uid = u[0]
        try:
            await client.send_message(uid, f"📢 **THÔNG BÁO TỪ HỆ THỐNG:**\n\n{content}", parse_mode='markdown')
            success += 1
            await asyncio.sleep(0.1) 
        except Exception:
            failed += 1

    await msg.edit(f"✅ **GỬI THÔNG BÁO HOÀN TẤT!**\n• Thành công: `{success}` người\n• Thất bại (Chặn bot): `{failed}` người", parse_mode='markdown')

# ==========================================
# --- SPAM & TREO NGÔN ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.spam\s+(\d+)'))
async def spam_handler(event):
    if not is_authorized(event.sender_id): return
    delay = int(event.pattern_match.group(1))
    content_lines = []
    if event.document:
        try: content_lines = [l.strip() for l in (await event.download_media(bytes)).decode('utf-8', errors='ignore').splitlines() if l.strip()]
        except Exception: pass
    elif event.is_reply:
        r = await event.get_reply_message()
        if r and r.text: content_lines = [l.strip() for l in r.text.splitlines() if l.strip()]
    
    if not content_lines:
        await event.respond("⚠️ Cần gửi file `.txt` hoặc reply văn bản!", parse_mode='markdown')
        return

    chat_id = event.chat_id
    buttons = [[Button.inline(f"💬 Gửi: {line[:25]}", data=f"spamline_{chat_id}_{i}_{int(time.time())}")] for i, line in enumerate(content_lines[:20], 1)]
    if not hasattr(client, '_spam_file_cache'): client._spam_file_cache = {}
    for i, line in enumerate(content_lines[:20], 1):
        client._spam_file_cache[f"spamline_{chat_id}_{i}_{int(time.time())}"] = {"line": line, "delay": delay, "chat_id": chat_id}
    await client.send_message(chat_id, f"📋 **BẢNG SPAM (Delay: {delay}s):**", buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'spamline_(.+)'))
async def callback_spam_choice(event):
    if not is_authorized(event.sender_id): return
    data_key = event.raw_data.decode('utf-8') if isinstance(event.raw_data, bytes) else event.raw_data
    buttons = [[Button.inline("✅ Dùng bot phụ", data=f"sub_spam_yes_{data_key}"), Button.inline("❌ Chỉ bot tổng", data=f"sub_spam_no_{data_key}")]];
    await event.edit("🤖 **Dùng bot phụ từ kho?**", buttons=buttons)

@client.on(events.CallbackQuery(pattern=r'sub_spam_(yes|no)_(.+)'))
async def callback_spam_run(event):
    choice, data_key = event.pattern_match.group(1), event.pattern_match.group(2)
    cache = getattr(client, '_spam_file_cache', {}).get(data_key)
    if not cache: return
    if choice == 'no':
        task_id = f"task_{int(time.time())}"
        ACTIVE_TASKS[task_id] = {"running": True, "chat_id": cache["chat_id"]}
        asyncio.create_task(run_loop(task_id, cache["chat_id"], cache["line"], cache["delay"], client))
        await event.edit("🚀 Đã chạy bằng **Bot tổng**!")
    else:
        await event.edit("🔢 Nhập số lượng bot phụ muốn dùng (Reply số, ví dụ: `1`)")
        if not hasattr(client, '_waiting_for_spam_count'): client._waiting_for_spam_count = {}
        client._waiting_for_spam_count[event.sender_id] = data_key

@client.on(events.NewMessage(func=lambda e: e.is_reply))
async def handle_sub_count(event):
    waiting = getattr(client, '_waiting_for_spam_count', {})
    if event.sender_id in waiting:
        data_key = waiting.pop(event.sender_id)
        try: count = int(event.raw_text.strip())
        except ValueError: return
        cache = getattr(client, '_spam_file_cache', {}).get(data_key)
        if not cache: return
        tokens = get_sub_bots_from_db(count)
        if not tokens:
            await event.respond("⚠️ Kho không đủ bot phụ!")
            return
        await event.respond(f"⚙️ Đang chạy {len(tokens)} bot phụ...")
        for i, token in enumerate(tokens, 1):
            asyncio.create_task(run_sub_worker(token, cache["chat_id"], cache["line"], cache["delay"], i))

async def run_sub_worker(token, chat_id, line, delay, idx):
    try:
        sub = TelegramClient(f'sub_{idx}_{int(time.time())}', API_ID, API_HASH)
        await sub.start(bot_token=token)
        while True:
            await sub.send_message(chat_id, line)
            await asyncio.sleep(float(delay))
    except Exception: pass

async def run_loop(task_id, chat_id, content, delay, bot_inst):
    try:
        while ACTIVE_TASKS.get(task_id, {}).get("running", False):
            await bot_inst.send_message(chat_id, content)
            await asyncio.sleep(float(delay))
    except Exception: pass
    finally:
        if task_id in ACTIVE_TASKS: del ACTIVE_TASKS[task_id]

@client.on(events.NewMessage(pattern=r'\.stopbot'))
async def stopbot(event):
    if not is_authorized(event.sender_id): return
    count = 0
    for t_id, info in list(ACTIVE_TASKS.items()):
        if info["chat_id"] == event.chat_id:
            info["running"] = False
            del ACTIVE_TASKS[t_id]
            count += 1
    await event.respond(f"🛑 Đã dừng `{count}` tiến trình!")

# ==========================================
# --- TẠO BOX & QUẢN LÝ KEY ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.taobox\s+(\d+)\s+(.+)'))
async def taobox(event):
    if not is_authorized(event.sender_id): return
    qty, name = int(event.pattern_match.group(1)), event.pattern_match.group(2).strip()
    if qty > 20: qty = 20
    created = []
    for i in range(1, qty + 1):
        try:
            res = await client(CreateChannelRequest(title=f"{name} {i}", about="Auto", megagroup=True))
            cid = int(f"-100{res.chats[0].id}")
            AUTO_CREATED_BOXES[cid] = {"title": f"{name} {i}"}
            created.append((i, f"{name} {i}", cid))
            await asyncio.sleep(1)
        except Exception: pass
    buttons = [[Button.inline(f"📥 Vô Box {stt}: {title}", data=f"joinbox_{cid}")] for stt, title, cid in created]
    await event.respond(f"📦 Đã tạo {len(created)} box:", buttons=buttons)

@client.on(events.CallbackQuery(pattern=r'joinbox_(.+)'))
async def joinbox(event):
    cid = int(event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1))
    try:
        await client(InviteToChannelRequest(channel=cid, users=[event.sender_id]))
        rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, manage_call=True)
        await client(EditAdminRequest(channel=cid, user_id=event.sender_id, admin_rights=rights, rank="Chủ Tịch"))
        await event.answer("👑 Đã thêm bạn vào box và cấp quyền!", alert=True)
    except Exception as e:
        await event.answer(f"❌ Lỗi: {e}", alert=True)

@client.on(events.NewMessage(pattern=r'\.taokey\s+(?:(\d+)([hdw])|(vv))\s+(.+)'))
async def taokey(event):
    if not is_admin(event.sender_id): return
    match = event.pattern_match
    num_str, unit, is_vv, note = match.group(1), match.group(2), match.group(3), match.group(4).strip()
    seconds = 315360000 if is_vv else int(num_str) * (3600 if unit == 'h' else 86400 if unit == 'd' else 604800)
    key_code = "LE_NHAN_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO keys (key_code, seconds) VALUES (?, ?)", (key_code, seconds))
    conn.commit()
    conn.close()
    await event.respond(f"🔑 **TẠO KEY THÀNH CÔNG:**\n• Mã: `{key_code}`\n• Ghi chú: `{note}`", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.setboxtong'))
async def setboxtong(event):
    if not is_admin(event.sender_id): return
    global BOX_TONG_ID
    BOX_TONG_ID = event.chat_id
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO system_config (key, value) VALUES ('box_tong', ?)", (str(BOX_TONG_ID),))
    conn.commit()
    conn.close()
    await event.respond(f"✅ Đã đặt box này làm Box Tổng!", parse_mode='markdown')

def main():
    keep_alive()
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
