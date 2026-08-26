import os
import time
import asyncio
import sys
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, JoinChannelRequest
from telethon.tl.types import ChatAdminRights
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

AUTHORIZED_USERS = {} # Lưu dạng {user_id: expire_time}
ADMIN_IDS = set()
ACTIVE_TASKS = {}
BOT_TOKENS_LIST = [] 
KEYS_DATABASE = {} # Kho lưu trữ key (Mỗi key chỉ dùng 1 lần duy nhất)
BOX_TONG_ID = None 
BLACK_BOXES = set()
SYSTEM_LOCKED = False

# Lưu vết các box tự tạo hoặc các box được thêm vào hệ thống
AUTO_CREATED_BOXES = {} # {chat_id: {"created_at": datetime, "used": False, "title": str}}
# Lưu trạng thái chọn box của từng user khi dùng .tagbox: {user_id: [list_chat_ids_đã_chọn]}
USER_SELECTED_BOXES = {}

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
# --- 1. TẠO BOX SỐ LƯỢNG LỚN + STT + TỰ XÓA SAU 1-2 NGÀY ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.taobox\s+(\d+)\s+(.+)'))
async def create_multiple_boxes(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền! Hãy mua key và dùng `.nhapkey [key]`.", parse_mode='markdown')
        return
        
    quantity = int(event.pattern_match.group(1))
    base_name = event.pattern_match.group(2).strip()
    
    if quantity > 20:
        await event.respond("⚠️ Để tránh spam hệ thống Telegram, bạn chỉ được tạo tối đa 20 box một lúc!", parse_mode='markdown')
        return

    await event.respond(f"⏳ Đang tiến hành khởi tạo `{quantity}` nhóm với tên gốc **`{base_name}`**, vui lòng chờ...", parse_mode='markdown')
    
    created_list = []
    for i in range(1, quantity + 1):
        box_title = f"{base_name} {i}"
        try:
            result = await client(CreateChannelRequest(
                title=box_title,
                about="Auto-created box system. Unused groups will be deleted after 48h.",
                megagroup=True
            ))
            chat_id = None
            for chat in result.chats:
                chat_id = chat.id
            
            full_chat_id = int(f"-100{chat_id}")
            
            AUTO_CREATED_BOXES[full_chat_id] = {
                "created_at": datetime.now(),
                "used": False,
                "title": box_title,
                "creator_id": user_id
            }
            created_list.append((i, box_title, full_chat_id))
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Lỗi tạo box {i}: {e}")

    summary_text = f"📦 **ĐÃ TẠO THÀNH CÔNG {len(created_list)} BOX!**\nBạn có muốn vào các box này không?:\n"
    buttons = []
    for stt, title, cid in created_list:
        buttons.append([Button.inline(f"📥 Vô Box {stt}: {title}", data=f"joinbox_{cid}")])

    await event.respond(summary_text, buttons=buttons, parse_mode='markdown')
    user_name = await get_user_display_name(user_id)
    await send_admin_log(f"📦 User `{user_name}` vừa tạo hàng loạt `{len(created_list)}` nhóm với tên tiền tố `{base_name}`.")

@client.on(events.CallbackQuery(pattern=r'joinbox_(.+)'))
async def callback_join_box(event):
    user_id = event.sender_id
    chat_id = int(event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1))
    
    try:
        from telethon.tl.functions.channels import InviteToChannelRequest
        await client(InviteToChannelRequest(channel=chat_id, users=[user_id]))
        
        admin_rights = ChatAdminRights(
            change_info=True, post_messages=True, edit_messages=True,
            delete_messages=True, ban_users=True, invite_users=True,
            pin_messages=True, manage_call=True, anonymous=False
        )
        await client(EditAdminRequest(channel=chat_id, user_id=user_id, admin_rights=admin_rights, rank="Chủ Tịch"))
        
        if chat_id in AUTO_CREATED_BOXES:
            AUTO_CREATED_BOXES[chat_id]["used"] = True

        await event.answer("👑 Đã thêm bạn vào box và cấp quyền Quản trị viên thành công!", alert=True)
    except Exception as e:
        await event.answer(f"❌ Không thể vào box (Có thể bạn đã ở trong box): {e}", alert=True)

# ==========================================
# --- 2. TÍNH NĂNG CHỌN NHIỀU BOX ĐỂ THÊM BOT (.TAGBOX) ---
# ==========================================
@client.on(events.NewMessage(pattern=r'\.tagbox'))
async def tagbox_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền dùng lệnh này!", parse_mode='markdown')
        return

    if not AUTO_CREATED_BOXES:
        await event.respond("⚠️ Hiện tại hệ thống chưa ghi nhận box tự động nào được tạo!", parse_mode='markdown')
        return

    # Khởi tạo danh sách box đang chọn cho user này (ban đầu trống)
    USER_SELECTED_BOXES[user_id] = set()
    
    await send_tagbox_menu(event, user_id, edit_message=False)

async def send_tagbox_menu(event, user_id, edit_message=False):
    selected_set = USER_SELECTED_BOXES.get(user_id, set())
    
    text = (
        "📋 **DANH SÁCH HỆ THỐNG BOX CỦA BẠN**\n"
        "• Bấm vào tên box để **Chọn/Bỏ chọn** nhiều box cùng lúc.\n"
        "• Sau khi chọn xong, bấm nút **Xác Nhận** ở dưới cùng.\n"
        "----------------------------------------\n"
    )
    
    buttons = []
    for cid, info in AUTO_CREATED_BOXES.items():
        title = info["title"]
        is_selected = cid in selected_set
        icon = "☑️" if is_selected else "◻️"
        # Nút bấm toggle chọn box
        buttons.append([Button.inline(f"{icon} {title}", data=f"togglebox_{cid}")])
    
    # Nút xác nhận thêm bot vào các box đã chọn
    buttons.append([Button.inline("🚀 XÁC NHẬN THÊM BOT VÀO CÁC BOX ĐÃ CHỌN", data="confirm_add_bot_boxes")])

    if edit_message:
        await event.edit(text, buttons=buttons, parse_mode='markdown')
    else:
        await event.respond(text, buttons=buttons, parse_mode='markdown')

@client.on(events.CallbackQuery(pattern=r'togglebox_(.+)'))
async def callback_toggle_box(event):
    user_id = event.sender_id
    chat_id = int(event.pattern_match.group(1).decode('utf-8') if isinstance(event.pattern_match.group(1), bytes) else event.pattern_match.group(1))
    
    if user_id not in USER_SELECTED_BOXES:
        USER_SELECTED_BOXES[user_id] = set()
        
    if chat_id in USER_SELECTED_BOXES[user_id]:
        USER_SELECTED_BOXES[user_id].remove(chat_id)
    else:
        USER_SELECTED_BOXES[user_id].add(chat_id)
        
    # Cập nhật lại giao diện menu inline ngay lập tức cho user
    await send_tagbox_menu(event, user_id, edit_message=True)
    await event.answer("Đã cập nhật lựa chọn!")

@client.on(events.CallbackQuery(pattern=r'confirm_add_bot_boxes'))
async def callback_confirm_add_bot(event):
    user_id = event.sender_id
    selected_set = USER_SELECTED_BOXES.get(user_id, set())
    
    if not selected_set:
        await event.answer("⚠️ Bạn chưa chọn box nào cả!", alert=True)
        return
        
    success_count = 0
    for cid in selected_set:
        try:
            # Bot tự tham gia vào box (nếu có link mời hoặc quyền thêm)
            await client(JoinChannelRequest(channel=cid))
            success_count += 1
            # Đánh dấu box đã được dùng
            if cid in AUTO_CREATED_BOXES:
                AUTO_CREATED_BOXES[cid]["used"] = True
        except Exception as e:
            print(f"Bot không thể vào box {cid}: {e}")
            
    await event.edit(f"✅ **Đã hoàn tất!** Bot đã được thêm thành công vào `{success_count}` / `{len(selected_set)}` box bạn đã chọn.", parse_mode='markdown')
    if user_id in USER_SELECTED_BOXES:
        del USER_SELECTED_BOXES[user_id]

# Tiến trình nền tự xóa box sau 48h nếu không sử dụng
async def background_box_cleanup_worker():
    while True:
        await asyncio.sleep(3600)
        now = datetime.now()
        to_delete = []
        for cid, info in list(AUTO_CREATED_BOXES.items()):
            if not info["used"] and (now - info["created_at"]) > timedelta(hours=48):
                to_delete.append(cid)
                
        for cid in to_delete:
            try:
                from telethon.tl.functions.channels import DeleteChannelRequest
                await client(DeleteChannelRequest(channel=cid))
                title = AUTO_CREATED_BOXES[cid]["title"]
                await send_admin_log(f"🗑️ *[TỰ ĐỘNG XÓA BOX]* Box `{title}` (ID: `{cid}`) đã bị xóa do không sử dụng sau 2 ngày.")
                del AUTO_CREATED_BOXES[cid]
            except Exception as e:
                print(f"Lỗi xóa box: {e}")

# ==========================================
# --- 3. CÁC TÍNH NĂNG KHÁC (GIỮ NGUYÊN) ---
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
    await event.respond(f"✅ Đã gửi thông báo thành công tới `{success_count}` người dùng!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.setboxtong'))
async def set_box_tong(event):
    if not is_admin(event.sender_id): return
    global BOX_TONG_ID
    BOX_TONG_ID = event.chat_id
    await event.respond(f"✅ Đã thiết lập box này (`{BOX_TONG_ID}`) làm **Box Tổng nhận log toàn hệ thống**!", parse_mode='markdown')

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
        f"• Lưu ý: Key chỉ dùng **1 lần duy nhất**!\n"
        f"• Cú pháp kích hoạt: `.nhapkey {key_code}`"
    )
    await event.respond(text, parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.nhapkey\s+(.+)'))
async def redeem_key(event):
    user_id = event.sender_id
    if is_admin(user_id):
        await event.respond("👑 Bạn là Admin, không cần nhập key!", parse_mode='markdown')
        return
    key_code = event.pattern_match.group(1).strip()
    if key_code in KEYS_DATABASE:
        seconds = KEYS_DATABASE.pop(key_code) 
        expire_time = datetime.now() + timedelta(seconds=seconds)
        AUTHORIZED_USERS[user_id] = expire_time
        await event.respond(f"✅ **Kích hoạt key thành công!** Quyền sử dụng đến `{expire_time.strftime('%H:%M:%S - %d/%m/%Y')}`.", parse_mode='markdown')
    else:
        await event.respond("❌ Key không hợp lệ hoặc đã được sử dụng!", parse_mode='markdown')

@client.on(events.NewMessage(pattern=r'\.(spam|treongon|toxic)\s+(\d+)(\s+(.+))?'))
async def handle_direct_spam(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền! Hãy mua key và dùng `.nhapkey [key]`.", parse_mode='markdown')
        return

    cmd_name = event.pattern_match.group(1)
    delay = event.pattern_match.group(2)
    content = event.pattern_match.group(4)

    if not content and event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.text:
            content = reply_msg.text

    if not content:
        await event.respond(f"⚠️ Vui lòng nhập nội dung cần spam hoặc reply tin nhắn!", parse_mode='markdown')
        return

    chat_id = event.chat_id
    task_group_id = f"group_{int(time.time())}"
    t_id = f"{cmd_name[:3]}_{task_group_id}_0"
    
    ACTIVE_TASKS[t_id] = {
        "running": True, "chat_id": chat_id, "user_id": user_id,
        "name": f"{cmd_name.upper()}", "bot_instance": client, "content": content
    }
    async asyncio.create_task(run_loop(t_id, chat_id, content, delay, client))
    await event.respond(f"🚀 Đã kích hoạt `.{cmd_name}` thành công với delay `{delay}s`!", parse_mode='markdown')

async def run_loop(task_id, chat_id, content, delay, bot_instance):
    try:
        while ACTIVE_TASKS.get(task_id, {}).get("running", False):
            await bot_instance.send_message(chat_id, content)
            await asyncio.sleep(float(delay))
    except Exception: pass
    finally:
        if task_id in ACTIVE_TASKS: del ACTIVE_TASKS[task_id]

@client.on(events.NewMessage(pattern=r'\.stopbot'))
async def cmd_stopbot(event):
    user_id = event.sender_id
    if not is_authorized(user_id): return
    chat_id = event.chat_id
    stopped_count = 0
    for t_id, info in list(ACTIVE_TASKS.items()):
        if info["chat_id"] == chat_id:
            info["running"] = False
            del ACTIVE_TASKS[t_id]
            stopped_count += 1
    if stopped_count > 0:
        await event.respond(f"🛑 Đã dừng `{stopped_count}` tiến trình bot trong box này!", parse_mode='markdown')
    else:
        await event.respond("⚠️ Không có tiến trình bot nào đang chạy.")

@client.on(events.NewMessage(pattern=r'\.menu'))
async def menu_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.respond("⛔ Bạn chưa có quyền dùng bot! Hãy dùng `.nhapkey [key]`.", parse_mode='markdown')
        return
    
    menu = (
        "🤖 **MENU BOT LE NHAN LIMITED** 🤖\n"
        "----------------------------------------\n"
        "• `.taobox [số lượng] [tên]` - Tạo hàng loạt box tự động có STT\n"
        "• `.tagbox` - Hiển thị danh sách box để chọn nhiều box và đưa bot vào\n"
        "• `.treongon [delay] [nội dung]` - Treo tin nhắn\n"
        "• `.spam [delay] [nội dung]` - Spam tin nhắn\n"
        "• `.toxic [delay] [nội dung]` - Gửi tin nhắn liên tục\n"
        "• `.stopbot` - Dừng toàn bộ bot đang treo\n"
        "• `.nhapkey [key]` - Kích hoạt bản quyền\n"
    )
    if is_admin(user_id):
        menu += (
            "----------------------------------------\n"
            "👑 **ADMIN TỐI CAO:**\n"
            "• `.ghichu [nội dung]` - Gửi thông báo toàn hệ thống\n"
            "• `.taokey [số][h/d]` - Tạo key bản quyền\n"
            "• `.setboxtong` - Cài đặt box nhận log\n"
        )
    await event.respond(menu, parse_mode='markdown')

def main():
    keep_alive()
    client.loop.create_task(background_box_cleanup_worker())
    client.run_until_disconnected()

if __name__ == 'main' or __name__ == '__main__':
    main()
