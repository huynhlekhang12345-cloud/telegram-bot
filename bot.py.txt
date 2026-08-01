import os
import time
import asyncio
from datetime import datetime
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

# Thư mục lưu trữ file (Được liên kết trực tiếp với Render Disk để không bao giờ bị mất khi update)
UPLOAD_FOLDER = "bot_files"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

AUTHORIZED_USERS = set()
ADMIN_IDS = set()
ACTIVE_TASKS = {}
MUTED_USERS = {}
BOT_START_TIME = datetime.now()

@client.on(events.NewMessage(pattern=r'\.login\s+le\s+nhan\s+0367120063'))
async def admin_login(event):
    admin_id = event.sender_id
    ADMIN_IDS.add(admin_id)
    try:
        await event.delete()
    except Exception:
        pass
    await event.respond("👑 Xác thực Admin thành công! Bạn có toàn quyền sử dụng bot ở mọi nơi.", parse_mode='markdown')

def is_admin(user_id):
    return user_id in ADMIN_IDS or user_id in AUTHORIZED_USERS

@client.on(events.NewMessage(pattern=r'\.capquyen'))
async def grant_permission(event):
    if not is_admin(event.sender_id):
        return
    try:
        target_id = int(event.text.split()[1])
        AUTHORIZED_USERS.add(target_id)
        await event.respond(f"✅ Đã cấp quyền cho User ID: `{target_id}`", parse_mode='markdown')
    except (IndexError, ValueError):
        await event.respond("⚠️ Cú pháp: `.capquyen [User_ID]`", parse_mode='markdown')

# --- TÍNH NĂNG TỰ ĐỘNG LƯU FILE VÀO Ổ CỨNG VĨNH VIỄN ---
@client.on(events.NewMessage(incoming=True))
async def save_file_to_disk(event):
    if event.document and is_admin(event.sender_id):
        try:
            file_name = event.file.name or f"file_{int(time.time())}.txt"
            local_path = os.path.join(UPLOAD_FOLDER, file_name)
            await event.download_media(local_path)
            print(f"Đã lưu file {file_name} vào ổ cứng vĩnh viễn thành công!")
        except Exception as e:
            print(f"Lỗi lưu file: {e}")

# --- QUẢN LÝ TRẠNG THÁI & DỪNG TIẾN TRÌNH ---
@client.on(events.NewMessage(pattern=r'\.status'))
async def check_status(event):
    if not is_admin(event.sender_id): return
    uptime = str(datetime.now() - BOT_START_TIME).split('.')[0]
    total_tasks = len(ACTIVE_TASKS)
    
    status_text = (
        "📊 **TRẠNG THÁI HOẠT ĐỘNG CỦA BOT** 📊\n"
        "----------------------------------------\n"
        f"• ⏰ **Khởi động lúc:** {BOT_START_TIME.strftime('%H:%M:%S - %d/%m/%Y')}\n"
        f"• ⏱️ **Thời gian chạy (Uptime):** {uptime}\n"
        f"• ⚡ **Số tiến trình đang chạy:** {total_tasks}\n"
        "----------------------------------------\n"
    )
    if ACTIVE_TASKS:
        for tid, info in ACTIVE_TASKS.items():
            status_text += f"• `ID: {tid}`\n  └ Chức năng: **{info['name']}** (Chat ID: `{info['chat_id']}`)\n"
    else:
        status_text += "*(Hiện không có tiến trình nào đang chạy)*\n"
        
    await event.respond(status_text, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.stop'))
async def cmd_stop(event):
    if not is_admin(event.sender_id): return
    args = event.text.split()
    chat_id = event.chat_id
    stopped_count = 0
    
    if len(args) > 1:
        task_id = args[1]
        if task_id in ACTIVE_TASKS:
            ACTIVE_TASKS[task_id]["running"] = False
            del ACTIVE_TASKS[task_id]
            await event.respond(f"🛑 Đã dừng tiến trình mã số `{task_id}` thành công!")
            return
        else:
            await event.respond(f"⚠️ Không tìm thấy mã tiến trình `{task_id}`.")
            return

    for t_id, info in list(ACTIVE_TASKS.items()):
        if info["chat_id"] == chat_id:
            info["running"] = False
            del ACTIVE_TASKS[t_id]
            stopped_count += 1
            
    if stopped_count > 0:
        await event.respond(f"🛑 Đã dừng toàn bộ {stopped_count} tiến trình đang chạy trong chat này!")
    else:
        await event.respond("⚠️ Không có tiến trình nào đang chạy để dừng.")

# --- TÍNH NĂNG MUTE (XÓA TIN NHẮN LIÊN TỤC) ---
@client.on(events.NewMessage(incoming=True))
async def auto_delete_muted_user(event):
    chat_id = event.chat_id
    sender_id = event.sender_id
    if chat_id in MUTED_USERS and sender_id in MUTED_USERS[chat_id]:
        try:
            await event.delete()
        except Exception:
            pass

@client.on(events.NewMessage(pattern=r'\.mute\s+(on|off)'))
async def mute_handler(event):
    if not is_admin(event.sender_id): return
    args = event.text.split()
    action = args[1].lower()
    chat_id = event.chat_id
    target_id = None
    target_name = ""
    
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        target_id = reply_msg.sender_id
        target_name = f"ID: {target_id}"
    elif len(args) > 2:
        target_input = args[2]
        try:
            user = await client.get_entity(target_input)
            target_id = user.id
            target_name = target_input
        except Exception:
            await event.respond(f"❌ Không tìm thấy người dùng `{target_input}`!", parse_mode='markdown')
            return
            
    if not target_id:
        await event.respond("⚠️ Cú pháp: `.mute on @username` (hoặc Reply tin nhắn rồi gõ `.mute on`)", parse_mode='markdown')
        return
        
    if chat_id not in MUTED_USERS:
        MUTED_USERS[chat_id] = set()
        
    if action == 'on':
        MUTED_USERS[chat_id].add(target_id)
        await event.respond(f"🔇 Đã bật **MUTE** người dùng `{target_name}`. Tin nhắn sẽ bị xóa tự động!", parse_mode='markdown')
    elif action == 'off':
        if target_id in MUTED_USERS[chat_id]:
            MUTED_USERS[chat_id].remove(target_id)
        await event.respond(f"🔊 Đã tắt **MUTE** cho người dùng `{target_name}`.", parse_mode='markdown')
    try: await event.delete()
    except Exception: pass

# --- TÍNH NĂNG XÓA FILE BẰNG NÚT BẤM (.xoafile) ---
@client.on(events.NewMessage(pattern=r'\.xoafile'))
async def cmd_xoafile(event):
    if not is_admin(event.sender_id): return
    if not os.path.exists(UPLOAD_FOLDER):
        await event.respond("❌ Thư mục chứa file trống!", parse_mode='markdown')
        return
        
    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.txt')]
    if not files:
        await event.respond("❌ Không có file `.txt` nào để xóa!", parse_mode='markdown')
        return
        
    buttons = []
    for file_name in files:
        buttons.append([Button.inline(f"🗑️ Xóa: {file_name}", data=f"delete|{file_name}".encode('utf-8'))])
        
    await event.respond(
        "🗑️ **QUẢN LÝ XÓA FILE HỆ THỐNG**\n👇 Hãy nhấn vào file bạn muốn xóa vĩnh viễn:",
        buttons=buttons,
        parse_mode='markdown'
    )

# --- HÀM TẠO NÚT CHỌN FILE CHO SPAM / TREONGON / TOXIC ---
def get_file_buttons(cmd_name, delay, mention=""):
    if not os.path.exists(UPLOAD_FOLDER): return None, "❌ Thư mục trống!"
    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.txt')]
    if not files: return None, "❌ Không tìm thấy file `.txt` nào!"
    
    buttons = []
    for f_name in files:
        data = f"{cmd_name}|{f_name}|{delay}|{mention}"
        buttons.append([Button.inline(f"📄 {f_name}", data=data.encode('utf-8'))])
    return buttons, None

@client.on(events.NewMessage(pattern=r'\.(spam|treongon|toxic)'))
async def handle_file_menu(event):
    if not is_admin(event.sender_id): return
    text = event.text.split()
    cmd_name = text[0][1:]
    
    if len(text) < 2:
        await event.respond(f"⚠️ Cú pháp sai! Dùng: `.{cmd_name} [delay]`", parse_mode='markdown')
        return
        
    delay = text[1]
    mention = ""
    if cmd_name == "toxic" and len(text) > 2 and text[2].startswith('@'):
        mention = text[2]
        
    buttons, err = get_file_buttons(cmd_name, delay, mention)
    if err:
        await event.respond(err, parse_mode='markdown')
        return
        
    await event.respond(
        f"📂 **CHỌN FILE ĐỂ CHẠY `.{cmd_name.upper()}`**\n• Delay: `{delay}s`\n👇 Nhấn vào file bên dưới:",
        buttons=buttons,
        parse_mode='markdown'
    )

# --- VÒNG LẶP THỰC THI CHẠY LỆNH ---
async def run_toxic_loop(task_id, chat_id, file_path, delay, mention):
    try:
        while ACTIVE_TASKS.get(task_id, {}).get("running", False):
            if not os.path.exists(file_path): break
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if not lines: break
            for line in lines:
                if not ACTIVE_TASKS.get(task_id, {}).get("running", False): break
                content = line.strip()
                if not content: continue
                final_msg = f"{mention} {content}" if mention else content
                await client.send_message(chat_id, final_msg)
                await asyncio.sleep(float(delay))
    except Exception as e:
        print(f"Lỗi toxic: {e}")
    finally:
        if task_id in ACTIVE_TASKS: del ACTIVE_TASKS[task_id]

async def run_file_loop(task_id, chat_id, file_path, delay, cmd_name):
    try:
        while ACTIVE_TASKS.get(task_id, {}).get("running", False):
            if not os.path.exists(file_path): break
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if not content: break
            await client.send_message(chat_id, content)
            await asyncio.sleep(float(delay))
    except Exception as e:
        print(f"Lỗi {cmd_name}: {e}")
    finally:
        if task_id in ACTIVE_TASKS: del ACTIVE_TASKS[task_id]

# --- XỬ LÝ SỰ KIỆN BẤM NÚT (CALLBACK QUERY) ---
@client.on(events.CallbackQuery)
async def handle_callback(event):
    if not is_admin(event.sender_id):
        await event.answer("⚠️ Bạn không có quyền!", alert=True)
        return
        
    data = event.data.decode('utf-8')
    parts = data.split('|')
    action = parts[0]
    
    # Xử lý sự kiện Xóa file từ ổ cứng vĩnh viễn
    if action == "delete":
        file_name = parts[1]
        local_path = os.path.join(UPLOAD_FOLDER, file_name)
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
            await event.edit(f"🗑️ Đã xóa vĩnh viễn file `{file_name}` khỏi ổ cứng bot!")
        except Exception as e:
            await event.edit(f"❌ Lỗi khi xóa file: {e}")
        return

    # Xử lý sự kiện chọn file chạy lệnh spam/treongon/toxic
    if len(parts) < 3: return
    cmd_name = parts[0]
    file_name = parts[1]
    delay = parts[2]
    mention = parts[3] if len(parts) > 3 else ""
    
    target_path = os.path.join(UPLOAD_FOLDER, file_name)
    if not os.path.exists(target_path):
        await event.edit("❌ File này không còn tồn tại!")
        return
        
    chat_id = event.chat_id
    task_id = f"{cmd_name[:3]}_{int(time.time())}"
    
    if cmd_name == "toxic":
        ACTIVE_TASKS[task_id] = {"running": True, "chat_id": chat_id, "name": f"Toxic ({file_name})"}
        asyncio.create_task(run_toxic_loop(task_id, chat_id, target_path, delay, mention))
        await event.edit(f"🔥 Đã kích hoạt **TOXIC** với file `{file_name}`!\n• Task ID: `{task_id}`")
    else:
        ACTIVE_TASKS[task_id] = {"running": True, "chat_id": chat_id, "name": f"{cmd_name.upper()} ({file_name})"}
        asyncio.create_task(run_file_loop(task_id, chat_id, target_path, delay, cmd_name))
        await event.edit(f"🚀 Đã kích hoạt `.{cmd_name}` với file `{file_name}`!\n• Task ID: `{task_id}`")

@client.on(events.NewMessage(pattern=r'\.menu'))
async def menu_handler(event):
    if not is_admin(event.sender_id): return
    menu = (
        "🤖 **MENU BOT Le Nhan Limited** 🤖\n"
        "----------------------------------------\n"
        "• `.toxic [delay] [@tag]` (Chọn file bằng nút bấm)\n"
        "• `.treongon [delay]` (Chọn file bằng nút bấm)\n"
        "• `.spam [delay]` (Chọn file bằng nút bấm)\n"
        "• `.xoafile` (Mở danh sách file để bấm xóa)\n"
        "• `.mute on @username` (Xóa tin nhắn liên tục)\n"
        "• `.mute off @username` (Tắt mute)\n"
        "• `.status` - Xem tiến trình đang chạy\n"
        "• `.stop` - Dừng tất cả tiến trình trong box\n"
        "• `.stop [Task_ID]` - Dừng riêng 1 lệnh\n"
        "• `.capquyen [ID]` - Cấp quyền dùng ké\n"
    )
    await event.respond(menu, parse_mode='markdown')

def main():
    keep_alive()
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
