import os
import time
import asyncio
import sqlite3
from aiohttp import web
from telethon import TelegramClient, events, Button

# ==============================================================================
# 1. CẤU HÌNH BẢO MẬT & HỆ THỐNG
# ==============================================================================
# Khuyên dùng: Đặt các giá trị này trong Environment Variables của Render
API_ID = int(os.environ.get("API_ID", "34850630"))
API_HASH = os.environ.get("API_HASH", "77fcad3dadc87cae39da2775ebc49abe")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8378602981:AAGmhMCGWZMfeadUe5a_L3frRfViZLGx8BE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8725740462"))

FILE_STORAGE_DIR = "bot_file_storage"
os.makedirs(FILE_STORAGE_DIR, exist_ok=True)
DB_PATH = "bot_system.db"

# ==============================================================================
# 2. KHỞI TẠO DATABASE
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS canh_san_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            box_id TEXT,
            timestamp TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS userbot_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT UNIQUE,
            session_string TEXT,
            status TEXT DEFAULT 'Active'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==============================================================================
# 3. QUẢN LÝ TRẠNG THÁI & LƯU TRỮ TRONG BỘ NHỚ
# ==============================================================================
system_maintenance_mode = False
user_cooldown = {}
user_pending_mode = {}      # {u_id: {"mode": "treotien"|"treotag", "chat_id": chat_id}}
running_tasks = {}          # {task_id: asyncio.Task}
last_active_tracker = {}    # {key: timestamp}
canh_san_targets = {}       # {key: {"box": box_id, "target": target_id}}

def is_authorized(sender_id):
    return sender_id == ADMIN_ID

async def check_flood(event):
    sender_id = event.sender_id
    current_time = time.time()
    if sender_id in user_cooldown:
        if current_time - user_cooldown[sender_id] < 0.8:
            return True
    user_cooldown[sender_id] = current_time
    return False

# ==============================================================================
# 4. KEEP-ALIVE WEB SERVER (CHỐNG NGỦ ĐÔNG RENDER)
# ==============================================================================
async def handle_ping(request):
    return web.Response(text="Bot is running securely 24/7 on Render!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Keep-Alive Web Server đang chạy tại cổng {port}.")

# ==============================================================================
# 5. LOGIC THỰC THI CHẠY NGẦM (BACKGROUND WORKERS)
# ==============================================================================

# 🟢 TREO TAG: Gửi từng dòng tuần tự có Delay
async def worker_treo_tag(cli, u_id, target_chat_id, file_path):
    task_id = f"treotag_{u_id}"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]
        
        await cli.send_message(u_id, f"🚀 **Bắt đầu Treo Tag ({len(lines)} dòng)...**")
        for line in lines:
            await cli.send_message(target_chat_id, line)
            await asyncio.sleep(2) # Delay 2s giữa các tin nhắn
            
        await cli.send_message(u_id, "✅ **Hoàn thành tác vụ Treo Tag!**")
    except asyncio.CancelledError:
        await cli.send_message(u_id, "🛑 **Tác vụ Treo Tag đã bị hủy!**")
    except Exception as e:
        await cli.send_message(u_id, f"❌ **Lỗi Treo Tag:** `{e}`")
    finally:
        running_tasks.pop(task_id, None)

# 🟢 TREO TIỀN: Xử lý đồng thời tất cả các dòng
async def worker_treo_tien(cli, u_id, target_chat_id, file_path):
    task_id = f"treotien_{u_id}"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]

        await cli.send_message(u_id, f"🚀 **Bắt đầu Treo Tiền (Gửi đồng thời {len(lines)} dòng)...**")
        
        send_tasks = [cli.send_message(target_chat_id, line) for line in lines]
        await asyncio.gather(*send_tasks)
        
        await cli.send_message(u_id, "✅ **Hoàn thành tác vụ Treo Tiền!**")
    except asyncio.CancelledError:
        await cli.send_message(u_id, "🛑 **Tác vụ Treo Tiền đã bị hủy!**")
    except Exception as e:
        await cli.send_message(u_id, f"❌ **Lỗi Treo Tiền:** `{e}`")
    finally:
        running_tasks.pop(task_id, None)

# 🟢 CANH SÀN: Giám sát Timeout 1p30s (90 giây)
async def worker_canh_san_checker(cli, u_id, box_code, target_user):
    task_id = f"cs_{u_id}_{box_code}_{target_user}"
    key = f"{box_code}_{target_user}"
    
    last_active_tracker[key] = time.time()
    canh_san_targets[key] = {"box": str(box_code), "target": str(target_user).lower()}
    
    await cli.send_message(u_id, f"🎯 **Đã bật Canh Sàn cho target `{target_user}` tại Box `{box_code}`!**")
    
    try:
        while True:
            await asyncio.sleep(5)
            elapsed = time.time() - last_active_tracker[key]
            
            if elapsed >= 90: # 1 phút 30 giây không tương tác
                timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
                
                alert_msg = (
                    f"🚨 **CẢNH BÁO CANH SÀN — TIMEOUT!**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📍 **Box:** `{box_code}`\n"
                    f"👤 **Mục tiêu:** `{target_user}`\n"
                    f"⏱️ **Không hoạt động:** `>{int(elapsed)} giây`\n"
                    f"⏰ **Thời gian:** `{timestamp_str}`"
                )
                await cli.send_message(ADMIN_ID, alert_msg)
                
                # Ghi vào Database
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO canh_san_history (account_id, box_id, timestamp) VALUES (?, ?, ?)',
                    (str(target_user), str(box_code), timestamp_str)
                )
                conn.commit()
                conn.close()
                
                # Reset bộ đếm để không bị spam báo động liên tục
                last_active_tracker[key] = time.time()
    except asyncio.CancelledError:
        await cli.send_message(u_id, f"🛑 **Đã dừng Canh Sàn đối với `{target_user}`!**")
    finally:
        running_tasks.pop(task_id, None)
        canh_san_targets.pop(key, None)

# ==============================================================================
# 6. ĐĂNG KÝ CÁC EVENT HANDLERS
# ==============================================================================
def register_handlers(cli):

    # 🟢 LẮNG NGHE ĐỂ GIÁM SÁT HOẠT ĐỘNG CANH SÀN
    @cli.on(events.NewMessage)
    async def monitor_canh_san_activity(event):
        sender = await event.get_sender()
        if not sender:
            return
            
        sender_id_str = str(sender.id)
        sender_username = f"@{sender.username}".lower() if getattr(sender, 'username', None) else ""
        chat_id_str = str(event.chat_id)
        
        for key, info in list(canh_san_targets.items()):
            target = info["target"]
            # Kiểm tra xem tin nhắn có thuộc đúng Box và đúng Target hay không
            if info["box"] == chat_id_str:
                if target == sender_id_str or (sender_username and target == sender_username):
                    last_active_tracker[key] = time.time()

    # 🟢 BẢO MẬT & CHỐNG SPAM
    @cli.on(events.CallbackQuery())
    async def global_security_filter(event):
        u_id = event.sender_id
        if not is_authorized(u_id):
            await event.answer("⛔ Cảnh báo: Truy cập trái phép!", alert=True)
            raise events.StopPropagation
        if await check_flood(event):
            await event.answer("⚠️ Thao tác quá nhanh, vui lòng thử lại sau!", alert=True)
            raise events.StopPropagation

    # 🟢 LỆNH /START
    @cli.on(events.NewMessage(pattern=r'^/start$'))
    async def start_command_handler(event):
        u_id = event.sender_id
        if not is_authorized(u_id):
            await event.reply("⛔ **Hệ thống riêng tư!** Bạn không có quyền sử dụng bot.")
            return

        user = await event.get_sender()
        username_str = f"@{user.username}" if getattr(user, 'username', None) else user.first_name
        
        text = (
            f"🌟 **Menu Limited** 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Chào mừng {username_str} đến với hệ thống quản trị.\n"
            f"🔥 *Vui lòng chọn menu bên dưới:*"
        )
        
        buttons = [
            [Button.inline("🚀 Menu Thường", data=f"menu_norm_{u_id}")],
            [Button.inline("⭐ Menu VIP", data=f"menu_vip_{u_id}")],
            [Button.inline("👑 Menu Admin Tối Cao", data=f"menu_adm_{u_id}")],
            [Button.inline("📖 Hướng Dẫn Sử Dụng", data=f"guide_{u_id}")],
            [Button.url("📞 Liên hệ Admin", "https://t.me/BONAMKI")]
        ]
        await event.reply(text, buttons=buttons, parse_mode='markdown')

    # 🟢 QUAY LẠI MENU CHÍNH
    @cli.on(events.CallbackQuery(pattern=r'^back_main_(\d+)$'))
    async def back_to_main_cb(event):
        u_id = int(event.pattern_match.group(1))
        user = await event.get_sender()
        username_str = f"@{user.username}" if getattr(user, 'username', None) else user.first_name
        
        text = (
            f"🌟 **Menu Limited** 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Chào mừng {username_str} đến với hệ thống quản trị.\n"
            f"🔥 *Vui lòng chọn menu bên dưới:*"
        )
        buttons = [
            [Button.inline("🚀 Menu Thường", data=f"menu_norm_{u_id}")],
            [Button.inline("⭐ Menu VIP", data=f"menu_vip_{u_id}")],
            [Button.inline("👑 Menu Admin Tối Cao", data=f"menu_adm_{u_id}")],
            [Button.inline("📖 Hướng Dẫn Sử Dụng", data=f"guide_{u_id}")],
            [Button.url("📞 Liên hệ Admin", "https://t.me/BONAMKI")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 HƯỚNG DẪN SỬ DỤNG
    @cli.on(events.CallbackQuery(pattern=r'^guide_(\d+)$'))
    async def system_guide_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = (
            f"📖 **HƯỚNG DẪN SỬ DỤNG HỆ THỐNG**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"1️⃣ **Treo Tiền/Tag:** Chọn tính năng -> Gửi file `.txt` chứa nội dung.\n"
            f"2️⃣ **Canh Sàn:** Chọn Box & Target -> Bot giám sát Timeout 1p30s.\n"
            f"3️⃣ **Admin Kill All:** Dừng khẩn cấp toàn bộ tác vụ đang thực thi."
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Chính", data=f"back_main_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 SUB-MENUS
    @cli.on(events.CallbackQuery(pattern=r'^menu_norm_(\d+)$'))
    async def select_menu_normal_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = "🚀 **MENU THƯỜNG — TÁC VỤ HỆ THỐNG**\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        buttons = [
            [Button.inline("💸 Treo Tiền", data=f"tr_tien_{u_id}"), Button.inline("🏷️ Treo Tag", data=f"tr_tag_{u_id}")],
            [Button.inline("🎯 Canh Sàn", data=f"cs_box_{u_id}"), Button.inline("📊 Trạng Thái", data=f"status_{u_id}")],
            [Button.inline("🔙 Quay lại", data=f"back_main_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^menu_vip_(\d+)$'))
    async def select_menu_vip_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = "⭐ **MENU VIP — TÁC VỤ ĐẶC QUYỀN**\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        buttons = [
            [Button.inline("💸 Treo Tiền (VIP)", data=f"tr_tien_{u_id}"), Button.inline("🏷️ Treo Tag (VIP)", data=f"tr_tag_{u_id}")],
            [Button.inline("🎯 Canh Sàn (VIP)", data=f"cs_box_{u_id}"), Button.inline("📊 Trạng Thái", data=f"status_{u_id}")],
            [Button.inline("🔙 Quay lại", data=f"back_main_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^menu_adm_(\d+)$'))
    async def select_menu_admin_cb(event):
        global system_maintenance_mode
        u_id = int(event.pattern_match.group(1))
        m_status = "🔴 ĐANG BẬT" if system_maintenance_mode else "🟢 ĐANG TẮT"
        text = (
            f"👑 **MENU ADMIN TỐI CAO**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛠️ **Bảo trì:** `{m_status}`"
        )
        buttons = [
            [Button.inline("💸 Treo Tiền", data=f"tr_tien_{u_id}"), Button.inline("🏷️ Treo Tag", data=f"tr_tag_{u_id}")],
            [Button.inline("🎯 Canh Sàn", data=f"cs_box_{u_id}"), Button.inline("📊 Status All", data=f"st_all_{u_id}")],
            [Button.inline("📋 Kho File", data=f"adm_files_{u_id}"), Button.inline("🤖 Quản Lý Bots", data=f"adm_bots_{u_id}")],
            [Button.inline("📜 Xem Logs", data=f"adm_logs_{u_id}"), Button.inline("🛠️ Bật/Tắt Bảo Trì", data=f"adm_maint_{u_id}")],
            [Button.inline("🛑 Dừng Khẩn Cấp (Kill All)", data=f"adm_kill_{u_id}")],
            [Button.inline("🔙 Quay lại", data=f"back_main_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 CHỌN CHẾ ĐỘ NẠP FILE
    @cli.on(events.CallbackQuery(pattern=r'^(tr_tien|tr_tag)_(\d+)$'))
    async def feature_selection_cb(event):
        action = event.pattern_match.group(1)
        u_id = int(event.pattern_match.group(2))
        
        mode = "treotien" if action == "tr_tien" else "treotag"
        user_pending_mode[u_id] = {"mode": mode, "chat_id": event.chat_id}

        title = "💸 TREO TIỀN" if mode == "treotien" else "🏷️ TREO TAG"
        text = (
            f"📌 **{title}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📎 *Vui lòng gửi file `.txt` chứa danh sách nội dung cần gửi vào đây:*"
        )
        buttons = [[Button.inline("❌ Huỷ", data=f"cancel_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 XỬ LÝ NHẬN FILE .TXT NẠP TIẾN TRÌNH
    @cli.on(events.NewMessage(incoming=True))
    async def handle_incoming_file(event):
        u_id = event.sender_id
        if not is_authorized(u_id) or u_id not in user_pending_mode:
            return
        if not event.document:
            return
        
        file_name = event.document.attributes[0].file_name if hasattr(event.document.attributes[0], 'file_name') else "config.txt"
        if not file_name.endswith('.txt'):
            return

        pending_info = user_pending_mode.pop(u_id)
        mode = pending_info["mode"]
        target_chat_id = pending_info["chat_id"]

        status_msg = await event.reply("⏳ **Đang tải và khởi tạo tiến trình...**")
        try:
            file_path = os.path.join(FILE_STORAGE_DIR, f"{u_id}_{file_name}")
            await event.client.download_media(event.message, file_path)
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f if line.strip()]
            
            await status_msg.edit(
                f"✅ **Đã nạp file thành công!**\n"
                f"📁 File: `{file_name}` (`{len(lines)} dòng`)\n"
                f"🚀 **Chế độ:** `{mode.upper()}`"
            )
            
            if mode == "treotien":
                t_id = f"treotien_{u_id}"
                if t_id in running_tasks:
                    running_tasks[t_id].cancel()
                running_tasks[t_id] = asyncio.create_task(worker_treo_tien(cli, u_id, target_chat_id, file_path))
            else:
                t_id = f"treotag_{u_id}"
                if t_id in running_tasks:
                    running_tasks[t_id].cancel()
                running_tasks[t_id] = asyncio.create_task(worker_treo_tag(cli, u_id, target_chat_id, file_path))
                
        except Exception as e:
            await status_msg.edit(f"❌ **Lỗi xử lý file:** `{e}`")

    # 🟢 LOGIC CANH SÀN UI
    @cli.on(events.CallbackQuery(pattern=r'^cs_box_(\d+)$'))
    async def canhsan_select_box_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = "🎯 **CANH SÀN — CHỌN BOX GIÁM SÁT**\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        buttons = [
            [Button.inline("📁 Box 1 (-100123456789)", data=f"cs_b_{u_id}_-100123456789")],
            [Button.inline("📁 Box Hiện Tại", data=f"cs_b_{u_id}_{event.chat_id}")],
            [Button.inline("❌ Huỷ", data=f"cancel_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^cs_b_(\d+)_(.+)$'))
    async def canhsan_box_chosen_cb(event):
        u_id = int(event.pattern_match.group(1))
        box_code = event.pattern_match.group(2)
        text = f"🎯 **CANH SÀN — CHỌN TARGET**\nBox: `{box_code}`\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        buttons = [
            [Button.inline("👤 Target Demo (@user1)", data=f"cs_run_{u_id}_{box_code}_@user1")],
            [Button.inline("🔙 Chọn lại Box", data=f"cs_box_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^cs_run_(\d+)_(.+)_(.+)$'))
    async def canhsan_start_run_cb(event):
        u_id = int(event.pattern_match.group(1))
        box_code = event.pattern_match.group(2)
        target_user = event.pattern_match.group(3)
        
        t_id = f"cs_{u_id}_{box_code}_{target_user}"
        if t_id in running_tasks:
            running_tasks[t_id].cancel()
            
        running_tasks[t_id] = asyncio.create_task(worker_canh_san_checker(cli, u_id, box_code, target_user))
        
        text = (
            f"🚀 **ĐÃ BẬT CANH SÀN!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 **Box:** `{box_code}`\n"
            f"🎯 **Target:** `{target_user}`\n"
            f"⏱️ **Timeout:** `1 phút 30 giây`"
        )
        buttons = [[Button.inline("🔙 Quay lại Menu", data=f"back_main_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 TRẠNG THÁI HỆ THỐNG
    @cli.on(events.CallbackQuery(pattern=r'^status_(\d+)$'))
    async def status_feature_cb(event):
        u_id = int(event.pattern_match.group(1))
        active_count = len(running_tasks)
        text = (
            f"📊 **TRẠNG THÁI HỆ THỐNG**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Web Service: `Active 24/7`\n"
            f"🔥 Tiến trình ngầm đang chạy: `{active_count}`"
        )
        buttons = [[Button.inline("🔙 Quay lại", data=f"menu_norm_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^st_all_(\d+)$'))
    async def status_all_bots_cb(event):
        u_id = int(event.pattern_match.group(1))
        active_count = len(running_tasks)
        text = f"📊 **STATUS ALL BOTS**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🔥 Active Tasks: `{active_count}`"
        buttons = [[Button.inline("🔙 Quay lại Admin", data=f"menu_adm_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 DỪNG KHẨN CẤP (KILL ALL)
    @cli.on(events.CallbackQuery(pattern=r'^adm_kill_(\d+)$'))
    async def admin_kill_all_cb(event):
        u_id = int(event.pattern_match.group(1))
        count = len(running_tasks)
        
        for task in running_tasks.values():
            task.cancel()
            
        running_tasks.clear()
        last_active_tracker.clear()
        canh_san_targets.clear()
        
        await event.answer(f"⚠️ Đã hủy {count} tiến trình!", alert=True)
        await event.edit(
            f"🛑 **ĐÃ DỪNG KHẨN CẤP TOÀN BỘ TÁC VỤ!**\nSố lượng tiến trình bị ngắt: `{count}`",
            buttons=[[Button.inline("🔙 Quay lại Admin", data=f"menu_adm_{u_id}")]]
        )

    # 🟢 CÁC TIỆN ÍCH ADMIN KHÁC
    @cli.on(events.CallbackQuery(pattern=r'^adm_files_(\d+)$'))
    async def admin_manage_files_cb(event):
        u_id = int(event.pattern_match.group(1))
        files = os.listdir(FILE_STORAGE_DIR) if os.path.exists(FILE_STORAGE_DIR) else []
        file_list = "\n".join([f"📁 `{f}`" for f in files]) if files else "*(Trống)*"
        
        text = f"📋 **KHO FILE HỆ THỐNG**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n{file_list}"
        buttons = [[Button.inline("🔙 Quay lại Admin", data=f"menu_adm_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^adm_logs_(\d+)$'))
    async def admin_view_logs_cb(event):
        u_id = int(event.pattern_match.group(1))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT account_id, box_id, timestamp FROM canh_san_history ORDER BY id DESC LIMIT 5')
        rows = cursor.fetchall()
        conn.close()
        
        history = "\n".join([f"⚠️ `{r[0]}` rớt tại box `{r[1]}` - `{r[2]}`" for r in rows]) if rows else "*(Chưa ghi nhận sự cố)*"
        text = f"📜 **NHẬT KÝ LỖI CANH SÀN**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n{history}"
        buttons = [[Button.inline("🔙 Quay lại Admin", data=f"menu_adm_{u_id}")]]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'^adm_maint_(\d+)$'))
    async def admin_toggle_maintenance_cb(event):
        global system_maintenance_mode
        system_maintenance_mode = not system_maintenance_mode
        status_str = "BẬT" if system_maintenance_mode else "TẮT"
        await event.answer(f"Chế độ bảo trì: {status_str}", alert=True)
        await select_menu_admin_cb(event)

    @cli.on(events.CallbackQuery(pattern=r'^cancel_(\d+)$'))
    async def cancel_task_cb(event):
        u_id = int(event.pattern_match.group(1))
        user_pending_mode.pop(u_id, None)
        await event.edit("✅ **Đã hủy thao tác.**", buttons=None, parse_mode='markdown')

# ==============================================================================
# 7. KHỞI CHẠY MAIN ENGINE
# ==============================================================================
async def main():
    print("Khởi động hệ thống Telegram Bot Limited...")
    
    # 1. Chạy Server Web Keep-Alive (Chống Render ngắt kết nối)
    await start_web_server()
    
    # 2. Khởi tạo Telegram Client
    client = TelegramClient('bot_session', API_ID, API_HASH)
    
    # 3. Đăng ký Events Handlers
    register_handlers(client)
    
    # 4. Connect & Start Bot
    await client.start(bot_token=BOT_TOKEN)
    print("-> Telegram Bot đã trực tuyến 100%!")
    
    # 5. Giữ kết nối ngầm 24/7
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
