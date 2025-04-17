import logging
import datetime
import pytz
import gspread
import os
import json
from time import time
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, CallbackContext, filters
from oauth2client.service_account import ServiceAccountCredentials

# ====== Danh sách ID nhân viên nội bộ ======
INTERNAL_USERS_ID = [7934716459, 7985186615, 6129180120, 6278235756, 675815864]

# ====== CACHE GOOGLE SHEET Dữ LIỆU NHÓM ======
GROUP_CACHE = {"data": [], "last_updated": 0}
CACHE_TTL = 300  # giây (5 phút)

# ========== CONFIG GOOGLE SHEETS ==========
SHEET_ID = "1ASeRadkkokhqOflRETw6sGJTyJ65Y0XQi5mvFmivLnY"
SHEET_NAME = "Sheet1"

GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
if not GOOGLE_CREDS_JSON:
    raise ValueError("❌ GOOGLE_CREDS_JSON environment variable is missing!")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def get_cached_group_data():
    now = time()
    if now - GROUP_CACHE["last_updated"] > CACHE_TTL:
        GROUP_CACHE["data"] = sheet.get_all_records()
        GROUP_CACHE["last_updated"] = now
    return GROUP_CACHE["data"]

# Kiểm tra sự có mặt của nhân viên trong nhóm
async def check_internal_users_in_group(chat_id, context):
    try:
        # Lấy danh sách tất cả các quản trị viên của nhóm
        members = await context.bot.get_chat_administrators(chat_id)
        
        # Lọc ra danh sách các ID và tên của các quản trị viên
        current_user_ids = [admin.user.id for admin in members]
        current_user_names = [admin.user.full_name for admin in members]

        # Kiểm tra nếu có bất kỳ nhân viên nào trong danh sách nội bộ
        for uid, name in zip(current_user_ids, current_user_names):
            if uid in INTERNAL_USERS_ID:
                logger.info(f"✅ Nhân viên nội bộ {name} (ID: {uid}) có mặt trong nhóm {chat_id}. Không cần phản hồi khách hàng.")
                return True  # Nhóm có nhân viên nội bộ, không cần phản hồi
        
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra nhân viên trong nhóm {chat_id}: {e}")
    
    return False  # Nhóm không có nhân viên nội bộ, bot sẽ phản hồi

# ========== LOGGING ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

user_states = {}

def check_office_hours() -> bool:
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.datetime.now(tz)
    if now.weekday() < 6:
        if (8 < now.hour < 17) or (now.hour == 8 and now.minute >= 30):
            return True
    return False

# Kiểm tra nếu nhóm có hoạt động
def is_group_active(group_id: int) -> bool:
    records = get_cached_group_data()
    for row in records:
        if str(row["group_id"]) == str(group_id) and str(row["active"]).lower() == "true":
            return True
    return False

def is_group_registered(group_id: int) -> bool:
    records = get_cached_group_data()
    return any(str(row["group_id"]) == str(group_id) for row in records)

# Welcome new member
async def welcome_new_member(update: Update, context: CallbackContext):
    chat = update.effective_chat
    group_id = chat.id
    group_name = chat.title or "N/A"

    if not is_group_registered(group_id):
        await update.message.reply_text(
            f"🚨 BOT được thêm vào nhóm chưa đăng ký!\nID: `{group_id}`\nTên nhóm: {group_name}",
            parse_mode="Markdown"
        )
        return

    if not is_group_active(group_id):
        return

    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            return

        message = (
            "Xin chào Quý khách.\n"
            "Cảm ơn Quý khách đã tin tưởng sử dụng dịch vụ của CVT.\n"
            "Nếu Quý khách cần hỗ trợ hoặc có bất kỳ vấn đề nào cần trao đổi, vui lòng để lại tin nhắn tại đây. Đội ngũ tư vấn sẽ theo dõi và phản hồi Quý khách trong thời gian sớm nhất có thể ạ."
        )
        await update.message.reply_text(message)

# Hàm xử lý tin nhắn từ khách hàng
async def handle_message(update: Update, context: CallbackContext):
    msg = update.message
    logger.info(f"🧩 Nhận từ user: {msg.from_user.full_name} - ID: {msg.from_user.id}")
    
    # Kiểm tra xem có phải là tin nhắn từ nhân viên nội bộ không
    if msg.from_user.id in INTERNAL_USERS_ID:
        logger.info(f"⏩ Bỏ qua tin nhắn từ nhân viên nội bộ: {msg.from_user.full_name} - ID: {msg.from_user.id}")
        return
    
    # Kiểm tra nhóm xem có nhân viên nội bộ không trước khi phản hồi
    chat_id = update.effective_chat.id
    if await check_internal_users_in_group(chat_id, context):  # Đảm bảo truyền context vào
        logger.info(f"Nhóm {chat_id} có nhân viên nội bộ. Bot không phản hồi khách hàng.")
        return  # Nếu có nhân viên trong nhóm, bot không phản hồi khách hàng

    if not msg or msg.from_user.is_bot:
        return

    # Bỏ qua tin nhắn forward
    if getattr(msg, "forward_from", None) or getattr(msg, "forward_from_chat", None):
        logger.warning(f"❌ Bị chặn: Tin nhắn forward - {msg.text}")
        return

    # Kiểm tra spam
    if msg.text:
        lowered = msg.text.lower()
        spam_keywords = ["http", "t.me/", "@bot", "vpn", "@speeeedvpnbot", "free", "trial", "proxy", "telegram bot", "subscribe"]
        if any(keyword in lowered for keyword in spam_keywords):
            logger.warning(f"❌ Bị chặn: Tin nhắn spam - {msg.text}")
            return

    user_id = update.message.from_user.id
    is_office_hours = check_office_hours()
    current_state = user_states.get(user_id)

    # Kiểm tra giờ làm việc và trạng thái của người dùng
    if not is_office_hours and current_state != "notified_out_of_office":
        await update.message.reply_text(
            "🎉 Xin chào Quý khách!\n"
            "Cảm ơn Quý khách đã liên hệ với Công ty Cổ phần Tư vấn và Đầu tư CVT.\n"
            "Chúng tôi sẽ phản hồi trong thời gian sớm nhất.\n\n"
            "🕒 Giờ làm việc: 08:30 – 17:00 (Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa).\n"
            "🗓  Chủ nhật & Ngày lễ: Nghỉ.\n"
            "Ngoài giờ làm việc, Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ phản hồi ngay khi làm việc sớm nhất."
        )
        user_states[user_id] = "notified_out_of_office"
        return

    # Nếu đã thông báo ngoài giờ làm việc, không cần thông báo lại
    if not is_office_hours and current_state == "notified_out_of_office":
        await update.message.reply_text(
            "🌙 Hiện tại, Công ty Cổ phần Tư vấn và Đầu tư CVT đang ngoài giờ làm việc (08:30 – 17:00, Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa).\n"
            "Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ liên hệ lại trong thời gian làm việc sớm nhất.\n"
            "Trân trọng cảm ơn!"
        )
        return

    # Phản hồi xác nhận
    await send_confirmation(update)
    user_states[user_id] = "active"

async def send_confirmation(update: Update):
    msg = update.message
    text = ""

    if msg.photo:
        text = "✅ CVT đã nhận được hình ảnh."
    elif msg.document:
        text = f"✅ CVT đã nhận được tài liệu.\n📄 Tên file: {msg.document.file_name}"
    elif msg.video:
        duration = str(datetime.timedelta(seconds=msg.video.duration))
        text = f"✅ CVT đã nhận được video.\n🎧 Thời lượng: {duration}"
    elif msg.voice:
        duration = str(datetime.timedelta(seconds=msg.voice.duration))
        text = f"✅ CVT đã nhận được tin nhắn thoại.\n🎧 Thời lượng: {duration}"
    else:
        text = "✅ CVT đã nhận được tin nhắn."

    follow_up = ("\nBộ phận Dịch vụ khách hàng sẽ phản hồi trong thời gian sớm nhất.\nCảm ơn Quý khách!")
    await msg.reply_text(text + follow_up)

async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update {update} caused error {context.error}')

app = Flask('')

@app.route('/')
def home():
    return "🤖 CVT Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run_web).start()

def main():
    token = os.environ.get("BOT_TOKEN")
    application = Application.builder().token(token).build()

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.VOICE,
        handle_message
    ))

    application.add_error_handler(error)
    keep_alive()

    # ✅ Chắc chắn không xử lý tin nhắn cũ khi bot restart
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
