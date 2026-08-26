import os
import time
import asyncio
import sys
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from flask import Flask
from threading import Thread

# --- CẤP CỔNG ẢO CHO FLASK (GIÚP RENDER KHÔNG BỊ NGỦ ĐÔNG) ---
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

ADMIN_FOLDER = "admin_files"
USER_FOLDER = "user_files"
for folder in [ADMIN_FOLDER, USER_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

AUTHORIZED_USERS = {} # Lưu dạng {user_id: expire_time}
ADMIN_IDS = set()
ACTIVE_TASKS = {}
BOT_TOKENS_LIST = [] 
KEYS_DATABASE = {} # Kho lưu trữ key (Mỗi key chỉ dùng 1 lần duy nhất)
BOX_TONG_ID = None 
BLACK_BOXES = set()
SYSTEM_LOCKED = False
BOT_START_TIME = datetime.now()

@client.on(events.NewMessage(pattern=r'\.login\s+le\s+nhan\s+0367120063'))
async def admin_login(event):
    admin_id = event.sender_id
    ADMIN_IDS.add(admin_id)
    try: await event.delete()
    except Exception: pass
    await event.respond("👑 Xác thực Admin tối cao thành công!", parse_mode='markdown')
    await send_admin_log(f"👑 Admin `{admin_id}` vừa đăng nhập hệ thống tối cao.")

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_authorized(user_id):
    if SYSTEM_LOCKED and not is_admin(user_id):
        return False
    if is_admin(user_id):
        return True
    if user_id in AUTHORIZED_USERS:
        if datetime.now() < AUTHORIZED_USERS[user_id]:
            return True
        else:
            del AUTHORIZED_USERS[user_id]
    return False

async def get_user_display_name(user_id):
    try:
        user = await client.get_entity(user_id)
        if user.username: return f"@{user.username}"
        elif user.first_name: return f"{user.first_name}"
    except Exception: pass
    return f"ID: {user_id}"

async def send_admin_log(message_text):
    global BOX_TONG_ID
    full_msg = f"🛡️ **[HỆ THỐNG LOG]**\n{message_text}"
    if BOX_TONG_ID:
        try:
            await client.send_message(BOX_TONG_ID, full_msg, parse_mode='markdown')
            return
        except Exception: pass
    
    for admin_id in ADMIN_IDS:
        try: await client.send_message(admin_id, full_msg, parse_mode='markdown')
        except Exception: pass

# ==========================================
# --- 1. GỬI GHI CHÚ/THÔNG BÁO TỚI USER ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.ghichu\s+(.+)'))
async def broadcast_announcement(event):
    if not is_admin(event.sender_id): return
    content = event.pattern_match.group(1).strip()
    
    target_users = set(AUTHORIZED_USERS.keys()) | ADMIN_IDS
    success_count = 0
    
    notice_msg = f"📢 **THÔNG BÁO TỪ ADMIN HỆ THỐNG:**\n----------------------------------------\n{content}"
    
    for uid in target_users:
        try:
            await client.send_message(uid, notice_msg, parse_mode='markdown')
            success_count += 1
        except Exception: pass
        
    await event.respond(f"✅ Đã gửi thông báo thành công tới `{success_count}` người dùng đang sử dụng bot!", parse_mode='markdown')
    await send_admin_log(f"📢 Admin vừa phát thông báo hệ thống tới `{success_count}` user.")

# --- QUẢN LÝ BOX TỔNG & KEY BẢN QUYỀN (1 KEY CHỈ DÙNG 1 LẦN) ---
@client.on(events.NewMessage(pattern=r'\.setboxtong'))
async def set_box_tong(event):
    if not is_admin(event.sender_id): return
    global BOX_TONG_ID
    BOX_TONG_ID = event.chat_id
    await event.respond(f"✅ Đã thiết lập box này (`{BOX_TONG_ID}`) làm **Box Tổng nhận log toàn hệ thống**!", parse_mode='markdown')
    await send_admin_log(f"📢 Box tổng vừa được cấu hình thành công bởi Admin.")

@client.on(events.NewMessage(pattern=r'\.taokey\s+(\d+)([hdm])'))
async def create_key(event):
    if not is_admin(event.sender_id): return
    num = int(event.pattern_match.group(1))
    unit = event.pattern_match.group(2)
    seconds = num * 3600 if unit == 'h' else (num * 86400 if unit == 'd' else num * 60)
    
    import random, string
    key_code = "LE_NHAN_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    KEYS_DATABASE[key_code] = seconds
    time_str = f"{num} giờ" if unit == 'h' else (f"{num} ngày" if unit == 'd' else f"{num} phút")
    
    text = (
        f"🔑 **ĐÃ TẠO KEY THÀNH CÔNG!**\n"
        f"----------------------------------------\n"
        f"• Key: `{key_code}`\n"
        f"• Thời hạn: `{time_str}`\n"
        f"• Lưu ý: Key chỉ sử dụng được **1 lần duy nhất**!\n"
        f"• Cú pháp kích hoạt: `.nhapkey {key_code}`"
    )
    await event.respond(text, parse_mode='markdown')
    await send_admin_log(f"🔑 Admin vừa tạo key mới: `{key_code}` (Hạn: `{time_str}`)")

@client.on(events.NewMessage(pattern=r'\.nhapkey\s+(.+)'))
async def redeem_key(event):
    user_id = event.sender_id
    if is_admin(user_id):
        await event.respond("👑 Bạn là Admin, không cần nhập key!", parse_mode='markdown')
        return
        
    key_code = event.pattern_match.group(1).strip()
    
    # Kiểm tra key có tồn tại trong kho không
    if key_code in KEYS_DATABASE:
        seconds = KEYS_DATABASE.pop(key_code) # .pop() giúp lấy ra và XÓA LUÔN key khỏi kho (chỉ dùng được 1 lần)
        expire_time = datetime.now() + timedelta(seconds=seconds)
        AUTHORIZED_USERS[user_id] = expire_time
        
        user_name = await get_user_display_name(user_id)
        await event.respond(f"✅ **Kích hoạt key thành công!** Quyền sử dụng đến `{expire_time.strftime('%H:%M:%S - %d/%m/%Y')}`.", parse_mode='markdown')
        await send_admin_log(f"👤 User `{user_name}` (ID: `{user_id}`) vừa kích hoạt thành công key bản quyền!")
    else:
        await event.respond("❌ Key không hợp lệ hoặc đã được sử dụng trước đó!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.addbot\s+(.+)'))
async def add_bot_token(event):
    if not is_admin(event.sender_id): return
    token = event.pattern_match.group(1).strip()
    if token not in BOT_TOKENS_LIST:
        BOT_TOKENS_LIST.append(token)
        await event.respond(f"✅ Đã thêm Bot phụ mới! Tổng số: `{len(BOT_TOKENS_LIST)}`", parse_mode='markdown')
        await send_admin_log(f"🤖 Admin vừa thêm 1 bot phụ mới.")
    else:
        await event.respond("⚠️ Token đã tồn tại!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.listbot'))
async def list_bot_tokens(event):
    if not is_admin(event.sender_id): return
    if not BOT_TOKENS_LIST:
        await event.respond("📋 Chưa có bot phụ nào.", parse_mode='markdown')
        return
    text = f"📋 **DANH SÁCH BOT PHỤ ({len(BOT_TOKENS_LIST)} con):**\n"
    for i, t in enumerate(BOT_TOKENS_LIST, 1):
        text += f"{i}. `{t[:10]}...{t[-5:]}`\n"
    await event.respond(text, parse_mode='markdown')

# ==========================================
# --- QUẢN LÝ LỆNH TREO & NÚT BẤM CHỌN FILE ---
# ==========================================
def get_file_buttons(user_id, cmd_name, delay, duration=0):
    folder = ADMIN_FOLDER if is_admin(user_id) else USER_FOLDER
    if not os.path.exists(folder): return None, "❌ Thư mục trống!"
    files = [f for f in os.listdir(folder) if f.endswith('.txt')]
    if not files: return None, "❌ Không tìm thấy file `.txt` nào!"
    
    buttons = []
    for f_name in files:
        data = f"file|{cmd_name}|{folder}|{f_name}|{delay}|{duration}"
        buttons.append([Button.inline(f"📄 {f_name}", data=data.encode('utf-8'))])
    return buttons, None

@client.on(events.NewMessage(pattern=r'\.(spam|treongon|toxic)'))
async def handle_file_menu(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền! Hãy mua key và dùng `.nhapkey [key]`.", parse_mode='markdown')
        return
    if event.chat_id in BLACK_BOXES:
        await event.respond("⛔ Box này đã bị Admin cấm chạy bot!")
        return

    text = event.text.split()
    cmd_name = text[0][1:]
    if len(text) < 2:
        await event.respond(f"⚠️ Cú pháp: `.{cmd_name} [delay]`", parse_mode='markdown')
        return
        
    delay = text[1]
    duration = int(text[2]) if len(text) > 2 and text[2].isdigit() else 0

    buttons, err = get_file_buttons(user_id, cmd_name, delay, duration)
    if err:
        await event.respond(err, parse_mode='markdown')
        return
        
    dur_text = f"\n• ⏱️ Tự dừng sau: `{duration} phút`" if duration > 0 else ""
    await event.respond(f"📂 **CHỌN FILE CHẠY `.{cmd_name.upper()}`** (Delay: `{delay}s`{dur_text})", buttons=buttons, parse_mode='markdown')

# --- MENU SIÊU TREO & NÚT BẤM (CALLBACK QUERY) ---
@client.on(events.NewMessage(pattern=r'\.(sieutreo|menu)'))
async def cmd_sieu_treo_menu(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền! Hãy nhập key qua `.nhapkey [key]`.", parse_mode='markdown')
        return
    
    buttons = [
        [
            Button.inline("🚀 Treo Ngon (2s)", data=b"st_menu|treongon|2"),
            Button.inline("🔥 Spam (3s)", data=b"st_menu|spam|3")
        ],
        [
            Button.inline("☣️ Toxic (5s)", data=b"st_menu|toxic|5"),
            Button.inline("🛑 Dừng Bot", data=b"st_stop")
        ],
        [
            Button.inline("📋 Xem Bot Phụ", data=b"st_listbot"),
            Button.inline("🗑️ Xóa File", data=b"st_xoafile")
        ]
    ]
    
    text = "⚡ **BẢNG ĐIỀU KHIỂN MENU SIÊU TREO** ⚡\n----------------------------------------\nChọn nhanh cấu hình chạy:"
    await event.respond(text, buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=b'st_(.+)'))
async def handle_sieu_treo_callbacks(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.answer("⚠️ Bạn không có quyền!", alert=True)
        return
        
    data = event.data.decode('utf-8')
    parts = data.split('|')
    action = parts[1] if len(parts) > 1 else parts[0]
    
    if action == "menu":
        cmd_name, delay = parts[2], parts[3]
        buttons, err = get_file_buttons(user_id, cmd_name, delay, 0)
        if err:
            await event.answer(err, alert=True)
            return
        await event.edit(f"📂 **[MENU SIÊU TREO] Chọn file chạy `.{cmd_name.upper()}` (Delay: `{delay}s`):**", buttons=buttons)
        return

    elif action == "stop":
        stopped_count = 0
        chat_id = event.chat_id
        for t_id, info in list(ACTIVE_TASKS.items()):
            if info["chat_id"] == chat_id and (is_admin(user_id) or info["user_id"] == user_id):
                info["running"] = False
                del ACTIVE_TASKS[t_id]
                stopped_count += 1
        if stopped_count > 0:
            await event.answer(f"🛑 Đã dừng {stopped_count} tiến trình bot!", alert=True)
            await event.edit(f"🛑 **STOPBOT:** Đã dừng thành công `{stopped_count}` tiến trình!")
        else:
            await event.answer("⚠️ Không có tiến trình nào đang chạy!", alert=True)

    elif action == "listbot":
        if not BOT_TOKENS_LIST:
            await event.answer("📋 Chưa có bot phụ nào!", alert=True)
            return
        text = f"📋 **DANH SÁCH BOT PHỤ ({len(BOT_TOKENS_LIST)} con):**\n"
        for i, t in enumerate(BOT_TOKENS_LIST, 1):
            text += f"{i}. `{t[:10]}...{t[-5:]}`\n"
        await event.edit(text, parse_mode='markdown')

    elif action == "xoafile":
        folder = ADMIN_FOLDER if is_admin(user_id) else USER_FOLDER
        files = [f for f in os.listdir(folder) if f.endswith('.txt')] if os.path.exists(folder) else []
        if not files:
            await event.answer("❌ Không có file `.txt` nào!", alert=True)
            return
        buttons = [[Button.inline(f"🗑️ Xóa: {f}", data=f"delete|{folder}|{f}".encode('utf-8'))] for f in files]
        await event.edit("🗑️ **[MENU SIÊU TREO] Chọn file muốn xóa:**", buttons=buttons)

@client.on(events.CallbackQuery)
async def handle_callback(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.answer("⚠️ Bạn không có quyền!", alert=True)
        return
        
    data = event.data.decode('utf-8')
    parts = data.split('|')
    action = parts[0]
    
    if action == "delete":
        folder, file_name = parts[1], parts[2]
        local_path = os.path.join(folder, file_name)
        try:
            if os.path.exists(local_path): os.remove(local_path)
            await event.edit(f"🗑️ Đã xóa vĩnh viễn file `{file_name}`!")
        except Exception as e: await event.edit(f"❌ Lỗi: {e}")
        return

    if action == "file":
        cmd_name, folder, file_name, delay, duration = parts[1], parts[2], parts[3], parts[4], parts[5]
        buttons = [
            [
                Button.inline("✅ Có", data=f"usebot|yes|{cmd_name}|{folder}|{file_name}|{delay}|{duration}".encode('utf-8')),
                Button.inline("❌ Không", data=f"usebot|no|{cmd_name}|{folder}|{file_name}|{delay}|{duration}".encode('utf-8'))
            ]
        ]
        await event.edit("🤖 **Bạn có muốn sử dụng Bot phụ để treo không?**", buttons=buttons)
        return

    if action == "usebot":
        use_choice, cmd_name, folder, file_name, delay, duration = parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        
        if use_choice == "no":
            await start_running_task(event, user_id, cmd_name, folder, file_name, delay, int(duration), use_sub_bots=False, sub_bot_count=0)
        else:
            if not BOT_TOKENS_LIST:
                await event.edit("⚠️ Chưa có bot phụ nào (`.addbot`). Chuyển về chạy bot chính!")
                await start_running_task(event, user_id, cmd_name, folder, file_name, delay, int(duration), use_sub_bots=False, sub_bot_count=0)
                return

            buttons = [
                [
                    Button.inline(f"🎯 Tất cả ({len(BOT_TOKENS_LIST)} bot)", data=f"qty|all|{cmd_name}|{folder}|{file_name}|{delay}|{duration}".encode('utf-8')),
                    Button.inline("🔢 Nhập số lượng", data=f"qty|custom|{cmd_name}|{folder}|{file_name}|{delay}|{duration}".encode('utf-8'))
                ]
            ]
            await event.edit("📊 **Lựa chọn số lượng bot phụ:**", buttons=buttons)
        return

    if action == "qty":
        qty_type, cmd_name, folder, file_name, delay, duration = parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        
        if qty_type == "all":
            count = len(BOT_TOKENS_LIST)
            await start_running_task(event, user_id, cmd_name, folder, file_name, delay, int(duration), use_sub_bots=True, sub_bot_count=count)
        else:
            await event.edit(f"💬 Gõ cú pháp `.sl [số lượng]` trong khung chat (Ví dụ: `.sl 3`) để chạy file `{file_name}`!")
            event.client.pending_config = {
                "user_id": user_id, "cmd_name": cmd_name, "folder": folder,
                "file_name": file_name, "delay": delay, "duration": int(duration)
            }
        return

@client.on(events.NewMessage(pattern=r'\.sl\s+(\d+)'))
async def handle_set_quantity(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    
    if not hasattr(client, 'pending_config') or client.pending_config.get('user_id') != user_id:
        await event.respond("⚠️ Không tìm thấy tiến trình chờ chọn số lượng bot phụ.")
        return
        
    count = int(event.pattern_match.group(1))
    max_avail = len(BOT_TOKENS_LIST)
    if count > max_avail: count = max_avail
        
    cfg = client.pending_config
    del client.pending_config
    
    await start_running_task(event, user_id, cfg['cmd_name'], cfg['folder'], cfg['file_name'], cfg['delay'], cfg['duration'], use_sub_bots=True, sub_bot_count=count)

async def start_running_task(event, user_id, cmd_name, folder, file_name, delay, duration, use_sub_bots, sub_bot_count):
    target_path = os.path.join(folder, file_name)
    if not os.path.exists(target_path):
        if event.query: await event.edit("❌ File không tồn tại!")
        else: await event.respond("❌ File không tồn tại!")
        return
        
    chat_id = event.chat_id
    task_group_id = f"group_{int(time.time())}"
    
    bots_to_run = [client]
    if use_sub_bots and sub_bot_count > 0:
        selected_tokens = BOT_TOKENS_LIST[:sub_bot_count]
        for t in selected_tokens:
            try:
                sub_client = TelegramClient(f'sub_bot_{t[:5]}', API_ID, API_HASH).start(bot_token=t)
                bots_to_run.append(sub_client)
            except Exception as e: print(f"Lỗi khởi động bot phụ: {e}")

    for i, bot_instance in enumerate(bots_to_run):
        t_id = f"{cmd_name[:3]}_{task_group_id}_{i}"
        ACTIVE_TASKS[t_id] = {
            "running": True, "chat_id": chat_id, "user_id": user_id,
            "name": f"{cmd_name.upper()} ({file_name})", "bot_instance": bot_instance, "start_time": datetime.now()
        }
        asyncio.create_task(run_loop(t_id, chat_id, target_path, delay, cmd_name, duration, bot_instance))

    user_name = await get_user_display_name(user_id)
    msg_text = f"🚀 Đã kích hoạt `.{cmd_name}` thành công!\n• **Hình thức:** {'Bot phụ (' + str(len(bots_to_run)-1) + ' con)' if use_sub_bots else 'Bot chính'}\n• **Nhóm Task ID:** `{task_group_id}`"
    if event.query: await event.edit(msg_text)
    else: await event.respond(msg_text, parse_mode='markdown')
    
    await send_admin_log(f"🚀 User `{user_name}` vừa khởi chạy lệnh `.{cmd_name}` với file `{file_name}` tại chat ID: `{chat_id}`.")

async def run_loop(task_id, chat_id, file_path, delay, cmd_name, duration, bot_instance):
    start_t = time.time()
    try:
        while ACTIVE_TASKS.get(task_id, {}).get("running", False):
            if duration > 0 and (time.time() - start_t) > (duration * 60): break
            if not os.path.exists(file_path): break
            with open(file_path, 'r', encoding='utf-8') as f: content = f.read().strip()
            if not content: break
            await bot_instance.send_message(chat_id, content)
            await asyncio.sleep(float(delay))
    except Exception as e: print(f"Lỗi loop: {e}")
    finally:
        if task_id in ACTIVE_TASKS: del ACTIVE_TASKS[task_id]

@client.on(events.NewMessage(pattern=r'\.stopbot'))
async def cmd_stopbot(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    
    chat_id = event.chat_id
    stopped_count = 0
    for t_id, info in list(ACTIVE_TASKS.items()):
        if info["chat_id"] == chat_id and (is_admin(user_id) or info["user_id"] == user_id):
            info["running"] = False
            del ACTIVE_TASKS[t_id]
            stopped_count += 1
            
    if stopped_count > 0:
        await event.respond(f"🛑 **STOPBOT:** Đã dừng `{stopped_count}` tiến trình bot trong box này!", parse_mode='markdown')
        await send_admin_log(f"🛑 Tiến trình bot tại chat ID `{chat_id}` vừa bị dừng bởi User ID `{user_id}`.")
    else:
        await event.respond("⚠️ Không có tiến trình bot nào đang hoạt động để dừng.")

@client.on(events.NewMessage(pattern=r'\.menu'))
async def menu_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền dùng bot! Hãy nhập key qua cú pháp `.nhapkey [key]`.", parse_mode='markdown')
        return
    
    menu = (
        "🤖 **MENU BOT LE NHAN LIMITED** 🤖\n"
        "----------------------------------------\n"
        "• `.sieutreo` hoặc `.menu` - Mở bảng điều khiển nút bấm\n"
        "• `.treongon [delay]` (Chọn file qua bảng nút bấm trực quan)\n"
        "• `.spam [delay]`\n"
        "• `.stopbot` - Dừng toàn bộ các bot đang treo\n"
        "• `.nhapkey [key]` - Kích hoạt bản quyền (1 key chỉ dùng 1 lần)\n"
    )
    if is_admin(user_id):
        menu += (
            "----------------------------------------\n"
            "👑 **ADMIN TỐI CAO:**\n"
            "• `.ghichu [nội dung]` - Gửi thông báo đến toàn bộ người dùng bot\n"
            "• `.taokey [số][h/d]` - Tạo key (Ví dụ: `.taokey 2h`)\n"
            "• `.setboxtong` - Cài đặt box nhận log toàn hệ thống\n"
            "• `.addbot [token]` - Thêm bot phụ\n"
            "• `.listbot` - Xem danh sách bot phụ\n"
        )
    await event.respond(menu, parse_mode='markdown')

def main():
    keep_alive()
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
