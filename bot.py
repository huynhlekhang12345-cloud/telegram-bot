import os
import time
import asyncio
from datetime import datetime
from telethon import TelegramClient, events
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

# --- TELEGRAM BOT ---
API_ID = 34850630
API_HASH = "77fcad3dadc87cae39da2775ebc49abe"
BOT_TOKEN = os.getenv("BOT_TOKEN", "8948413828:AAFDpv8ky2Ji1Tch9WGLFPUOXoelS7cIcOg")

client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

UPLOAD_FOLDER = "bot_files"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

AUTHORIZED_USERS = set()
ADMIN_IDS = set()
ACTIVE_TASKS = {}
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
    return user_id in ADMIN_IDS

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

@client.on(events.NewMessage(incoming=True))
async def save_file(event):
    if event.document and is_admin(event.sender_id):
        try:
            file_name = event.file.name or "file.txt"
            await event.download_media(os.path.join(UPLOAD_FOLDER, file_name))
        except Exception as e:
            print(f"Lỗi lưu file ẩn của admin: {e}")

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
        "📌 **Danh sách tiến trình chi tiết:**\n"
    )
    
    if ACTIVE_TASKS:
        for tid, info in ACTIVE_TASKS.items():
            status_text += f"• `ID: {tid}`\n  └ Chức năng: **{info['name']}** (Chat ID: `{info['chat_id']}`)\n"
    else:
        status_text += "*(Hiện không có tiến trình nào đang chạy)*\n"
        
    status_text += "\n*(Dùng `.stop [Task_ID]` để dừng riêng hoặc `.stop` để dừng tất cả trong chat)*"
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
        await event.respond(f"🛑 Đã dừng toàn bộ {stopped_count} tiến trình đang chạy trong đoạn chat này!")
    else:
        await event.respond("⚠️ Không có tiến trình nào đang chạy để dừng.")

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
        if task_id in ACTIVE_TASKS:
            del ACTIVE_TASKS[task_id]

@client.on(events.NewMessage(pattern=r'\.toxic'))
async def cmd_toxic(event):
    if not is_admin(event.sender_id): return
    parts = event.text.split(maxsplit=3)
    if len(parts) < 3:
        await event.respond("⚠️ Cú pháp: `.toxic [delay] [file] [@tag]`", parse_mode='markdown')
        return
    
    delay = parts[1]
    file_name = parts[2]
    mention = parts[3] if len(parts) > 3 else ""
    target_path = os.path.join(UPLOAD_FOLDER, file_name)
    
    if not os.path.exists(target_path):
        await event.respond(f"❌ Không tìm thấy file `{file_name}`!", parse_mode='markdown')
        return
        
    task_id = f"tox_{int(time.time())}"
    chat_id = event.chat_id
    ACTIVE_TASKS[task_id] = {"running": True, "chat_id": chat_id, "name": f"Toxic ({file_name})"}
    
    await event.respond(f"🔥 Đã kích hoạt **TOXIC**!\n• Mã Task ID: `{task_id}`\n• Gõ `.stop {task_id}` để dừng riêng lệnh này.", parse_mode='markdown')
    asyncio.create_task(run_toxic_loop(task_id, chat_id, target_path, delay, mention))

async def run_file_loop(task_id, chat_id, file_path, delay, cmd_name):
    try:
        if not os.path.exists(file_path): return
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        while ACTIVE_TASKS.get(task_id, {}).get("running", False):
            await client.send_message(chat_id, f"📁 [{cmd_name.upper()}]\n{content}")
            await asyncio.sleep(float(delay))
    except Exception as e:
        print(f"Lỗi {cmd_name}: {e}")
    finally:
        if task_id in ACTIVE_TASKS:
            del ACTIVE_TASKS[task_id]

@client.on(events.NewMessage(pattern=r'\.(spam|treongon)'))
async def handle_file_cmds(event):
    if not is_admin(event.sender_id): return
    cmd_name = event.raw_text.split()[0][1:]
    parts = event.text.split()
    
    if len(parts) < 3:
        await event.respond(f"⚠️ Cú pháp: `.{cmd_name} [delay] [tên_file]`", parse_mode='markdown')
        return
        
    delay = parts[1]
    file_name = parts[2]
    target_path = os.path.join(UPLOAD_FOLDER, file_name)
    
    if not os.path.exists(target_path):
        await event.respond(f"❌ Không tìm thấy file `{file_name}`!", parse_mode='markdown')
        return
        
    task_id = f"{cmd_name[:3]}_{int(time.time())}"
    chat_id = event.chat_id
    ACTIVE_TASKS[task_id] = {"running": True, "chat_id": chat_id, "name": f"{cmd_name.upper()} ({file_name})"}
    
    await event.respond(f"🚀 Đã kích hoạt `.{cmd_name}`!\n• Mã Task ID: `{task_id}`\n• Gõ `.stop {task_id}` để dừng riêng lệnh này.", parse_mode='markdown')
    asyncio.create_task(run_file_loop(task_id, chat_id, target_path, delay, cmd_name))

@client.on(events.NewMessage(pattern=r'\.menu'))
async def menu_handler(event):
    if not is_admin(event.sender_id): return
    menu = (
        "🤖 **MENU BOT Le Nhan Limited** 🤖\n"
        "----------------------------------------\n"
        "• `.toxic [delay] [file] [@tag]`\n"
        "• `.treongon [delay] [file]`\n"
        "• `.spam [delay] [file]`\n"
        "• `.status` - Xem bot đang chạy chức năng nào\n"
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
