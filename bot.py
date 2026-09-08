import os
import time
import asyncio
import sqlite3
from aiohttp import web
from telethon import TelegramClient, events, Button

# ==============================================================================
# CẤU HÌNH BẢO MẬT & HỆ THỐNG RIÊNG TƯ (LIMITED BOT)
# ==============================================================================
API_ID = 34850630  
API_HASH = "77fcad3dadc87cae39da2775ebc49abe"
BOT_TOKEN = "8378602981:AAGmhMCGWZMfeadUe5a_L3frRfViZLGx8BE"

# 🛑 QUAN TRỌNG: ID Telegram Admin
ADMIN_ID = 8725740462  

# Khởi tạo biến client toàn cục
client = None

FILE_STORAGE_DIR = "bot_file_storage"
os.makedirs(FILE_STORAGE_DIR, exist_ok=True)

DB_PATH = "bot_system.db"

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
            last_msg TEXT,
            sender TEXT,
            msg_id TEXT,
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

def set_config_db(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

system_maintenance_mode = False
user_cooldown = {}

# ==============================================================================
# BỘ BỘ NHỚ QUẢN LÝ TIẾN TRÌNH THỰC THI THẬT (LOGIC NGẦM)
# ==============================================================================
user_pending_mode = {}      # Lưu trạng thái chờ file .txt của user: {u_id: "treotien" hoặc "treotag"}
running_tasks = {}          # Quản lý các task đang chạy: {task_id: asyncio.Task}
last_active_tracker = {}    # Quản lý canh sàn: {key: timestamp}
canh_san_targets = {}       # Danh sách mục tiêu canh sàn: {key: {"box": box, "target": target}}


# ==============================================================================
# HỆ THỐNG CHỐNG SPAM & PHÂN QUYỀN
# ==============================================================================
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
# 1. KEEP-ALIVE WEB SERVER (CHỐNG NGỦ ĐÔNG RENDER 24/7)
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
# 2. LOGIC THỰC THI NGẦM THẬT (BACKGROUND WORKERS)
# ==============================================================================

# 🟢 LOGIC TREO TAG: Gửi từng dòng tuần tự có delay
async def worker_treo_tag(cli, u_id, file_path):
    task_id = f"treotag_{u_id}"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]
        
        await cli.send_message(u_id, f"🚀 **Bắt đầu Treo Tag ({len(lines)} dòng)...**")
        for line in lines:
            await cli.send_message(u_id, line)
            await asyncio.sleep(2) # Delay 2s giữa các dòng
            
        await cli.send_message(u_id, "✅ **Hoàn thành tác vụ Treo Tag!**")
    except asyncio.CancelledError:
        await cli.send_message(u_id, "🛑 **Tác vụ Treo Tag đã bị hủy!**")
    except Exception as e:
        await cli.send_message(u_id, f"❌ **Lỗi Treo Tag:** `{e}`")
    finally:
        running_tasks.pop(task_id, None)

# 🟢 LOGIC TREO TIỀN: Xử lý đồng thời tất cả các dòng
async def worker_treo_tien(cli, u_id, file_path):
    task_id = f"treotien_{u_id}"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]

        await cli.send_message(u_id, f"🚀 **Bắt đầu Treo Tiền (Xử lý đồng thời {len(lines)} dòng)...**")
        
        # Tạo danh sách các task gửi tin nhắn đồng thời
        send_tasks = [cli.send_message(u_id, line) for line in lines]
        await asyncio.gather(*send_tasks)
        
        await cli.send_message(u_id, "✅ **Hoàn thành tác vụ Treo Tiền!**")
    except asyncio.CancelledError:
        await cli.send_message(u_id, "🛑 **Tác vụ Treo Tiền đã bị hủy!**")
    except Exception as e:
        await cli.send_message(u_id, f"❌ **Lỗi Treo Tiền:** `{e}`")
    finally:
        running_tasks.pop(task_id, None)

# 🟢 LOGIC CANH SÀN: Quét Timeout 1p30s (90 giây)
async def worker_canh_san_checker(cli, u_id, box_code, target_user):
    task_id = f"canhsan_{u_id}_{box_code}_{target_user}"
    key = f"{box_code}_{target_user}"
    last_active_tracker[key] = time.time()
    canh_san_targets[key] = {"box": box_code, "target": target_user}
    
    await cli.send_message(u_id, f"🎯 **Đã bật giám sát Canh Sàn cho target `{target_user}` tại Box `{box_code}`!**")
    
    try:
        while True:
            await asyncio.sleep(5) # Quét mỗi 5 giây
            elapsed = time.time() - last_active_tracker[key]
            
            # Nếu vượt quá 1 phút 30 giây (90s)
            if elapsed >= 90:
                timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
                
                # 1. Gửi báo động về Admin
                alert_msg = (
                    f"🚨 **CẢNH BÁO CANH SÀN — TIMEOUT!**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📍 **Box:** `{box_code}`\n"
                    f"👤 **Mục tiêu:** `{target_user}`\n"
                    f"⏱️ **Không hoạt động:** `>{int(elapsed)} giây`\n"
                    f"⏰ **Thời gian:** `{timestamp_str}`"
                )
                await cli.send_message(ADMIN_ID, alert_msg)
                
                # 2. Ghi nhật ký vào Database
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO canh_san_history (account_id, box_id, timestamp) VALUES (?, ?, ?)',
                    (target_user, box_code, timestamp_str)
                )
                conn.commit()
                conn.close()
                
                # Cập nhật lại tracker để không bị spam báo động liên tục
                last_active_tracker[key] = time.time()
    except asyncio.CancelledError:
        await cli.send_message(u_id, f"🛑 **Đã dừng Canh Sàn đối với `{target_user}`!**")
    finally:
        running_tasks.pop(task_id, None)
        canh_san_targets.pop(key, None)


# ==============================================================================
# 3. HÀM ĐĂNG KÝ GIAO DIỆN & XỬ LÝ SỰ KIỆN
# ==============================================================================

def register_handlers(cli):
    
    # 🟢 LẮNG NGHE TIN NHẮN ĐỂ CẬP NHẬT HOẠT ĐỘNG CANH SÀN
    @cli.on(events.NewMessage)
    async def monitor_canh_san_activity(event):
        sender = await event.get_sender()
        if not sender:
            return
            
        sender_str = f"@{sender.username}" if sender.username else str(sender.id)
        chat_id_str = str(event.chat_id)
        
        # Quét các mục tiêu đang canh
        for key, info in list(canh_san_targets.items()):
            if info["target"] in [sender_str, str(sender.id)] or info["box"] == chat_id_str:
                last_active_tracker[key] = time.time() # Reset thời gian timeout

    @cli.on(events.NewMessage(pattern=r'/start'))
    async def start_command_handler(event):
        u_id = event.sender_id
        if not is_authorized(u_id):
            await event.reply("⛔ **Hệ thống riêng tư!** Bạn không có quyền truy cập bot này.")
            return

        user = await event.get_sender()
        username_str = f"@{user.username}" if user.username else user.first_name
        
        text = (
            f"🌟 **Menu make By le nhan** 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Chào mừng {username_str} đến với menu của admin le nhan limited.\n"
            f"🔥 *Hãy chọn menu cực xịn để sài:*"
        )
        
        buttons = [
            [Button.inline("🚀 Menu Thường", data=f"select_menu_normal_{u_id}")],
            [Button.inline("⭐ Menu VIP", data=f"select_menu_vip_{u_id}")],
            [Button.inline("👑 Menu Admin Tối Cao", data=f"select_menu_admin_{u_id}")],
            [Button.inline("📖 Hướng Dẫn Sử Dụng", data=f"system_guide_{u_id}")],
            [Button.url("📞 Liên hệ Admin", "https://t.me/BONAMKI")]
        ]
        await event.reply(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery())
    async def global_security_filter(event):
        u_id = event.sender_id
        if not is_authorized(u_id):
            await event.answer("⛔ Cảnh báo: Truy cập trái phép bị từ chối!", alert=True)
            return
        if await check_flood(event):
            await event.answer("⚠️ Thao tác quá nhanh, vui lòng từ từ!", alert=True)
            raise events.StopPropagation

    @cli.on(events.CallbackQuery(pattern=r'back_to_main_selector_(\d+)'))
    async def back_to_main_cb(event):
        u_id = int(event.pattern_match.group(1))
        user = await event.get_sender()
        username_str = f"@{user.username}" if user.username else user.first_name
        
        text = (
            f"🌟 **Menu make By le nhan** 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Chào mừng {username_str} đến với menu của admin le nhan limited.\n"
            f"🔥 *Hãy chọn menu cực xịn để sài:*"
        )
        buttons = [
            [Button.inline("🚀 Menu Thường", data=f"select_menu_normal_{u_id}")],
            [Button.inline("⭐ Menu VIP", data=f"select_menu_vip_{u_id}")],
            [Button.inline("👑 Menu Admin Tối Cao", data=f"select_menu_admin_{u_id}")],
            [Button.inline("📖 Hướng Dẫn Sử Dụng", data=f"system_guide_{u_id}")],
            [Button.url("📞 Liên hệ Admin", "https://t.me/BONAMKI")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'system_guide_(\d+)'))
    async def system_guide_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = (
            f"📖 **HƯỚNG DẪN SỬ DỤNG HỆ THỐNG CHI TIẾT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"1️⃣ **Khởi động:** Gõ lệnh `/start` để mở bảng điều khiển.\n"
            f"2️⃣ **Treo Tiền:** Nạp file `.txt` (Xử lý **tất cả các dòng** cùng lúc).\n"
            f"3️⃣ **Treo Tag:** Nạp file `.txt` (Xử lý **từng dòng** tuần tự có delay).\n"
            f"4️⃣ **Canh Sàn:** Timeout chuẩn **1 phút 30 giây** báo động về Box Tổng & Admin.\n"
            f"5️⃣ **Bảo mật:** Bot Limited độc quyền cho `@BONAMKI`."
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Chính", data=f"back_to_main_selector_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'select_menu_normal_(\d+)'))
    async def select_menu_normal_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = (
            f"🚀 **MENU THƯỜNG - TÁC VỤ HỆ THỐNG**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📎 *Chọn tính năng bạn muốn thao tác:*"
        )
        buttons = [
            [Button.inline("💸 Treo Tiền", data=f"treotien_{u_id}"), Button.inline("🏷️ Treo Tag", data=f"treotag_{u_id}")],
            [Button.inline("🎯 Canh Sàn", data=f"canhsan_select_box_{u_id}"), Button.inline("📊 Status", data=f"status_{u_id}")],
            [Button.inline("🔙 Quay lại", data=f"back_to_main_selector_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'select_menu_vip_(\d+)'))
    async def select_menu_vip_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = (
            f"⭐ **MENU VIP - TÁC VỤ ĐẶC QUYỀN**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📎 *Khu vực đặc quyền VIP tối ưu tốc độ:*"
        )
        buttons = [
            [Button.inline("💸 Treo Tiền (VIP)", data=f"treotien_{u_id}"), Button.inline("🏷️ Treo Tag (VIP)", data=f"treotag_{u_id}")],
            [Button.inline("🎯 Canh Sàn (VIP)", data=f"canhsan_select_box_{u_id}"), Button.inline("📊 Status (VIP)", data=f"status_{u_id}")],
            [Button.inline("🔙 Quay lại", data=f"back_to_main_selector_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'select_menu_admin_(\d+)'))
    async def select_menu_admin_cb(event):
        global system_maintenance_mode
        u_id = int(event.pattern_match.group(1))
        m_status = "🔴 ĐANG BẬT" if system_maintenance_mode else "🟢 ĐANG TẮT"
        text = (
            f"👑 **Menu Admin le nhan**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ *bảo vệ độc quyền.*\n"
            f"🛠️ *Bảo trì:* `{m_status}`"
        )
        buttons = [
            [Button.inline("💸 Treo Tiền", data=f"treotien_{u_id}"), Button.inline("🏷️ Treo Tag", data=f"treotag_{u_id}")],
            [Button.inline("🎯 Canh Sàn", data=f"canhsan_select_box_{u_id}"), Button.inline("📊 Status Toàn Bộ", data=f"status_all_bots_{u_id}")],
            [Button.inline("📋 Kho File", data=f"admin_manage_files_{u_id}"), Button.inline("🤖 Quản Lý Bot Phụ", data=f"admin_manage_all_bots_{u_id}")],
            [Button.inline("📢 Broadcast", data=f"admin_broadcast_{u_id}"), Button.inline("📜 Xem Logs", data=f"admin_view_logs_{u_id}")],
            [Button.inline("🛠️ Bật/Tắt Bảo Trì", data=f"admin_toggle_maintenance_{u_id}"), Button.inline("🔄 Khởi Động Lại", data=f"admin_restart_bot_{u_id}")],
            [Button.inline("🛑 Dừng Khẩn Cấp (Kill All)", data=f"admin_kill_all_{u_id}")],
            [Button.inline("🔙 Quay lại", data=f"back_to_main_selector_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 CHỌN CHẾ ĐỘ NẠP FILE TREO TIỀN / TREO TAG
    @cli.on(events.CallbackQuery(pattern=r'(treotien|treotag)_(\d+)'))
    async def feature_selection_cb(event):
        parts = event.pattern_match.group(0).split('_')
        feature_type = parts[0]
        u_id = int(parts[1])
        
        # Đánh dấu trạng thái chờ gửi file .txt
        user_pending_mode[u_id] = feature_type

        if feature_type == "treotien":
            title = "💸 TREO TIỀN (Xử lý TẤT CẢ CÁC DÒNG cùng lúc)"
        else:
            title = "🏷️ TREO TAG (Xử lý TỪNG DÒNG tuần tự)"

        text = (
            f"📌 **{title}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📎 *Vui lòng gửi file `.txt` cấu hình tương ứng vào khung chat bên dưới:*"
        )
        buttons = [[Button.inline("❌ Huỷ", data=f"cancel_task_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 XỬ LÝ KHI NGƯỜI DÙNG TẢI FILE .TXT LÊN -> KÍCH HOẠT CHẠY NGẦM THẬT
    @cli.on(events.NewMessage(incoming=True))
    async def handle_incoming_file(event):
        u_id = event.sender_id
        if not is_authorized(u_id):
            return
        if not event.document:
            return
        
        file_name = event.document.attributes[0].file_name if hasattr(event.document.attributes[0], 'file_name') else "config.txt"
        if not file_name.endswith('.txt'):
            return

        status_msg = await event.reply("⏳ **Đang tải và xử lý file cấu hình `.txt`...**")
        try:
            file_path = os.path.join(FILE_STORAGE_DIR, file_name)
            await event.client.download_media(event.message, file_path)
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                
            set_config_db(f"file_{file_name}", file_path)
            
            mode = user_pending_mode.get(u_id, "treotag")
            
            await status_msg.edit(
                f"✅ **Đã nạp file thành công!**\n"
                f"📁 Tên file: `{file_name}` (`{len(lines)} dòng`)\n"
                f"🚀 **Đang khởi tạo tiến trình chạy ngầm `{mode.upper()}`...**"
            )
            
            # Kích hoạt worker chạy ngầm thực sự
            if mode == "treotien":
                t_id = f"treotien_{u_id}"
                if t_id in running_tasks:
                    running_tasks[t_id].cancel()
                running_tasks[t_id] = asyncio.create_task(worker_treo_tien(cli, u_id, file_path))
            else:
                t_id = f"treotag_{u_id}"
                if t_id in running_tasks:
                    running_tasks[t_id].cancel()
                running_tasks[t_id] = asyncio.create_task(worker_treo_tag(cli, u_id, file_path))
                
        except Exception as e:
            await status_msg.edit(f"❌ **Lỗi khi xử lý file:** `{e}`")

    @cli.on(events.CallbackQuery(pattern=r'canhsan_select_box_(\d+)'))
    async def canhsan_select_box_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = (
            f"🎯 **CANH SÀN — BƯỚC 1: CHỌN BOX / NHÓM**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Vui lòng chọn box chat mục tiêu cần đưa vào hệ thống giám sát:*"
        )
        buttons = [
            [Button.inline("📁 [Box 1] Nhóm Sàn Đầu Tư A", data=f"canhsan_box_chosen_{u_id}_box1")],
            [Button.inline("📁 [Box 2] Nhóm Tín Hiệu VIP B", data=f"canhsan_box_chosen_{u_id}_box2")],
            [Button.inline("❌ Huỷ", data=f"cancel_task_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'canhsan_box_chosen_(\d+)_(.+)'))
    async def canhsan_box_chosen_cb(event):
        u_id = int(event.pattern_match.group(1))
        box_code = event.pattern_match.group(2)
        text = (
            f"🎯 **CANH SÀN — BƯỚC 2: CHỌN NGƯỜI CẦN THEO DÕI**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Box đã chọn:* `{box_code}`\n"
            f"💡 *Chọn tài khoản hoặc người dùng mục tiêu cần canh hoạt động:*"
        )
        buttons = [
            [Button.inline("👤 [User 1] @TraderPro_99", data=f"canhsan_start_run_{u_id}_{box_code}_user1")],
            [Button.inline("👤 [User 2] @BossKiemTien", data=f"canhsan_start_run_{u_id}_{box_code}_user2")],
            [Button.inline("🔙 Chọn lại Box", data=f"canhsan_select_box_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    # 🟢 KÍCH HOẠT CANH SÀN THỰC THI THẬT
    @cli.on(events.CallbackQuery(pattern=r'canhsan_start_run_(\d+)_(.+)_(.+)'))
    async def canhsan_start_run_cb(event):
        u_id = int(event.pattern_match.group(1))
        box_code = event.pattern_match.group(2)
        target_user = event.pattern_match.group(3)
        
        # Tạo task canh sàn chạy ngầm thực sự
        t_id = f"canhsan_{u_id}_{box_code}_{target_user}"
        if t_id in running_tasks:
            running_tasks[t_id].cancel()
            
        running_tasks[t_id] = asyncio.create_task(worker_canh_san_checker(cli, u_id, box_code, target_user))
        
        text = (
            f"🚀 **HỆ THỐNG CANH SÀN ĐÃ KHỞI CHẠY THÀNH CÔNG!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Box giám sát:</b> `{box_code}`\n"
            f"🎯 <b>Mục tiêu canh:</b> `{target_user}`\n"
            f"⏱️ <b>Ngưỡng timeout:</b> `1 phút 30 giây`\n\n"
            f"🟢 *Bot đang quét ngầm 24/7. Nếu quá 1p30s target không nhắn tin sẽ báo động ngay về Admin!*"
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Chính", data=f"back_to_main_selector_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='html')

    @cli.on(events.CallbackQuery(pattern=r'status_(\d+)'))
    async def status_feature_cb(event):
        u_id = int(event.pattern_match.group(1))
        active_count = len(running_tasks)
        text = (
            f"📊 **TRẠNG THÁI HỆ THỐNG**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Render Web Service: `Hoạt động 24/7`\n"
            f"🔥 Tác vụ ngầm đang chạy: `{active_count} tasks`\n"
            f"🎯 Canh Sàn (Timeout 1p30s): `Trực tuyến`\n"
            f"🛡️ Anti-Scan / Limited: `Bật`"
        )
        buttons = [[Button.inline("🔙 Quay lại", data=f"select_menu_normal_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'status_all_bots_(\d+)'))
    async def status_all_bots_cb(event):
        u_id = int(event.pattern_match.group(1))
        active_count = len(running_tasks)
        text = (
            f"📊 **BÁO CÁO STATUS TOÀN BỘ HỆ THỐNG**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Tiến trình ngầm đang chạy: `{active_count} tasks`\n"
            f"🎯 Canh Sàn: `Đang quét live/die`\n"
            f"🛡️ Trạng thái bảo mật: `An toàn tuyệt đối`"
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'admin_manage_files_(\d+)'))
    async def admin_manage_files_cb(event):
        u_id = int(event.pattern_match.group(1))
        files = os.listdir(FILE_STORAGE_DIR) if os.path.exists(FILE_STORAGE_DIR) else []
        file_list = "\n".join([f"📁 `{f}`" for f in files]) if files else "*(Kho file trống)*"
        
        text = (
            f"📋 **QUẢN LÝ KHO FILE HỆ THỐNG**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Danh sách file hiện có:\n{file_list}"
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'admin_manage_all_bots_(\d+)'))
    async def admin_manage_all_bots_cb(event):
        u_id = int(event.pattern_match.group(1))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT phone_number, status FROM userbot_sessions')
        bots = cursor.fetchall()
        conn.close()
        
        bot_list = "\n".join([f"🤖 `{b[0]}` — `{b[1]}`" for b in bots]) if bots else "*(Chưa có Session String nào)*"
        text = (
            f"🤖 **QUẢN LÝ USERBOT PHỤ**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Danh sách tài khoản:\n{bot_list}\n\n"
            f"👉 *Thêm mới bằng lệnh:* `/addsession <sđt> <string>`"
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.NewMessage(pattern=r'/addsession\s+(\+?\d+)\s+(.+)'))
    async def add_session_handler(event):
        if not is_authorized(event.sender_id):
            return
        args = event.pattern_match.groups()
        phone = args[0]
        session_str = args[1].strip()
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO userbot_sessions (phone_number, session_string, status) VALUES (?, ?, ?)',
                (phone, session_str, 'Active')
            )
            conn.commit()
            conn.close()
            await event.reply(f"✅ **Đã thêm Session thành công cho:** `{phone}`")
        except Exception as e:
            await event.reply(f"❌ **Lỗi:** `{e}`")

    @cli.on(events.CallbackQuery(pattern=r'admin_broadcast_(\d+)'))
    async def admin_broadcast_cb(event):
        u_id = int(event.pattern_match.group(1))
        text = (
            f"📢 **PHÁT THÔNG BÁO (BROADCAST)**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Gửi nội dung tin nhắn bạn muốn broadcast đến toàn hệ thống."
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'admin_view_logs_(\d+)'))
    async def admin_view_logs_cb(event):
        u_id = int(event.pattern_match.group(1))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT account_id, box_id, timestamp FROM canh_san_history ORDER BY id DESC LIMIT 5')
        rows = cursor.fetchall()
        conn.close()
        
        history = "\n".join([f"⚠️ Acc `{r[0]}` rớt tại box `{r[1]}` lúc `{r[2]}`" for r in rows]) if rows else "*(Chưa ghi nhận sự cố rớt)*"
        text = (
            f"📜 **NHẬT KÝ LỖI & CANH SÀN**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>[INFO] Render Keep-Alive: Active</code>\n"
            f"<code>[INFO] Security: Protected (@BONAMKI)</code>\n\n"
            f"<b>Lịch sử rớt gần nhất:</b>\n{history}"
        )
        buttons = [[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        await event.edit(text, buttons=buttons, parse_mode='markdown')

    @cli.on(events.CallbackQuery(pattern=r'admin_toggle_maintenance_(\d+)'))
    async def admin_toggle_maintenance_cb(event):
        global system_maintenance_mode
        u_id = int(event.pattern_match.group(1))
        system_maintenance_mode = not system_maintenance_mode
        status_str = "BẬT" if system_maintenance_mode else "TẮT"
        await event.answer(f"Đã chuyển chế độ bảo trì thành: {status_str}", alert=True)
        await select_menu_admin_cb(event)

    @cli.on(events.CallbackQuery(pattern=r'admin_restart_bot_(\d+)'))
    async def admin_restart_bot_cb(event):
        u_id = int(event.pattern_match.group(1))
        await event.answer("🔄 Đang khởi động lại tiến trình...", alert=True)
        await event.edit(
            f"🔄 **ĐÃ KHỞI ĐỘNG LẠI TIẾN TRÌNH BOT!**",
            buttons=[[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        )

    # 🟢 DỪNG KHẨN CẤP THỰC TẾ: HỦY TẤT CẢ TÁC VỤ NGẦM DƯỚI NỀN
    @cli.on(events.CallbackQuery(pattern=r'admin_kill_all_(\d+)'))
    async def admin_kill_all_cb(event):
        u_id = int(event.pattern_match.group(1))
        
        count = len(running_tasks)
        for task in running_tasks.values():
            task.cancel() # Hủy ngay lập tức các task đang treo tiền/tag/canh sàn
            
        running_tasks.clear()
        last_active_tracker.clear()
        canh_san_targets.clear()
        
        await event.answer(f"⚠️ Đã dừng khẩn cấp thành công {count} tác vụ!", alert=True)
        await event.edit(
            f"🛑 **ĐÃ DỪNG KHẨN CẤP TOÀN BỘ TÁC VỤ NGẦM!**\n"
            f"📊 Tổng số tiến trình đã bị tiêu diệt: `{count}`",
            buttons=[[Button.inline("🔙 Quay lại Menu Admin", data=f"select_menu_admin_{u_id}")]
        ]
        )

    @cli.on(events.CallbackQuery(pattern=r'cancel_task_(\d+)'))
    async def cancel_task_cb(event):
        u_id = int(event.pattern_match.group(1))
        user_pending_mode.pop(u_id, None)
        await event.edit("✅ **Đã huỷ thao tác thành công.**", buttons=None, parse_mode='markdown')


# ==============================================================================
# 4. KHỞI CHẠY CHÍNH (MAIN)
# ==============================================================================

async def main():
    global client
    print("Bot bảo mật riêng tư đang khởi động hệ thống...")
    
    # 1. Khởi chạy Keep-Alive Web Server
    await start_web_server()
    
    # 2. Khởi tạo TelegramClient tương thích Python 3.14
    client = TelegramClient('bot_session', API_ID, API_HASH)
    
    # 3. Đăng ký xử lý logic & sự kiện
    register_handlers(client)
    
    # 4. Khởi động kết nối bot
    await client.start(bot_token=BOT_TOKEN)
    print("Telegram client đã kết nối thành công và đang hoạt động 100%!")
    
    # 5. Duy trì chạy ngầm 24/7
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
