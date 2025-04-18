import logging
import datetime
import pytz
import gspread
import os
import json
from time import time
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackContext, filters, CommandHandler, CallbackQueryHandler
from oauth2client.service_account import ServiceAccountCredentials

# ====== Danh sách ID nhân viên nội bộ ======
INTERNAL_USERS_ID = [7934716459, 7985186615, 6129180120, 6278235756]

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
        members = await context.bot.get_chat_administrators(chat_id)
        current_user_ids = [admin.user.id for admin in members]

        for uid in current_user_ids:
            if uid in INTERNAL_USERS_ID:
                logger.info(f"✅ Nhân viên nội bộ (ID: {uid}) có mặt trong nhóm {chat_id}. Không cần phản hồi khách hàng.")
                return True
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra nhân viên trong nhóm {chat_id}: {e}")
    return False

# ========== LOGGING ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

user_states = {}

# Lưu thời gian cuối cùng nhận tin nhắn từ mỗi người dùng
conversation_last_message_time = {}

# Đặt thời gian chờ tối đa (30 phút = 1800 giây)
MAX_IDLE_TIME = 1800  # 30 minutes

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

# ====== Welcome new member ======
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

# ====== Xử lý tin nhắn từ khách hàng ======
async def handle_message(update: Update, context: CallbackContext):
    msg = update.message
    chat_id = update.effective_chat.id
    logger.info(f"🧩 Nhận từ user: {msg.from_user.full_name} - ID: {msg.from_user.id}")
    
    if msg.from_user.id in INTERNAL_USERS_ID:
        logger.info(f"⏩ Bỏ qua tin nhắn từ nhân viên nội bộ: {msg.from_user.full_name} - ID: {msg.from_user.id}")
        return
    
    if await check_internal_users_in_group(chat_id, context):
        logger.info(f"Nhóm {chat_id} có nhân viên nội bộ. Bot không phản hồi khách hàng.")
        return  # Nếu có nhân viên trong nhóm, bot không phản hồi khách hàng

    # Gửi nút "Start" cho khách hàng khi họ gửi tin nhắn
    keyboard = [
        [InlineKeyboardButton("Start", callback_data="start_conversation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Chào bạn! Nhấn nút 'Start' để bắt đầu trò chuyện", reply_markup=reply_markup)

# ====== Xử lý callback khi nhấn nút Start ======
async def start_conversation(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    # Đảm bảo chỉ có nhân viên mới nhận được tin nhắn sau khi nhấn Start
    if user_id not in INTERNAL_USERS_ID:
        await query.answer("Chỉ nhân viên mới có thể nhận và trả lời tin nhắn.")
        return

    # Đánh dấu trạng thái cuộc trò chuyện của khách hàng
    user_states[user_id] = "active"
    await query.message.reply_text(f"Nhân viên {query.from_user.full_name} đã bắt đầu phản hồi! Cuộc trò chuyện đã được chuyển cho nhân viên.")

# Phản hồi xác nhận nhận được thông tin
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

# Xử lý lỗi
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update {update} caused error {context.error}')

# Flask server để giữ bot sống
app = Flask('')

@app.route('/')
def home():
    return "🤖 CVT Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run_web).start()

# Main function
def main():
    token = os.environ.get("BOT_TOKEN")
    application = Application.builder().token(token).build()

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.VOICE,
        handle_message
    ))

    application.add_handler(CallbackQueryHandler(start_conversation, pattern="start_conversation"))
    application.add_error_handler(error)
    keep_alive()

    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
