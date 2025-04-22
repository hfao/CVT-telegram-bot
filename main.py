import logging
import datetime
import pytz
import gspread
import os
import json
import asyncio
from time import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackContext, filters, ChatMemberHandler, CallbackQueryHandler
from oauth2client.service_account import ServiceAccountCredentials

# ====== Danh sách ID nhân viên nội bộ ======
INTERNAL_USERS_ID = [7934716459, 7985186615, 6129180120, 6278235756]

# ====== Trạng thái cuộc trò chuyện ======
user_states = {}
conversation_last_message_time = {}
conversation_handlers = {}
MAX_IDLE_TIME = 300  # 5 phút

# ========== Google Sheets ==========
SHEET_ID = "1ASeRadkkokhqOflRETw6sGJTyJ65Y0XQi5mvFmivLnY"
SHEET_NAME = "Sheet1"

GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
if not GOOGLE_CREDS_JSON:
    raise ValueError("Missing GOOGLE_CREDS_JSON")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# Cache group data
GROUP_CACHE = {"data": [], "last_updated": 0}
CACHE_TTL = 300

def get_cached_group_data():
    now = time()
    if now - GROUP_CACHE["last_updated"] > CACHE_TTL:
        GROUP_CACHE["data"] = sheet.get_all_records()
        GROUP_CACHE["last_updated"] = now
    return GROUP_CACHE["data"]

def is_group_active(group_id: int) -> bool:
    records = get_cached_group_data()
    for row in records:
        if str(row["group_id"]) == str(group_id) and str(row["active"]).lower() == "true":
            return True
    return False

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_office_hours():
    tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now = datetime.datetime.now(tz)
    return now.weekday() < 6 and (8 < now.hour < 17 or (now.hour == 8 and now.minute >= 30))

def get_time_slot():
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.datetime.now(tz)
    hour = now.hour
    if 17 <= hour < 19:
        return "early_evening"
    elif 19 <= hour <= 23:
        return "late_evening"
    else:
        return "other"

# Function to add group_id to Google Sheets
def add_group_to_sheet(group_id):
    logger.info(f"Adding Group ID: {group_id} to Google Sheets")
    sheet.append_row([group_id])  # Append the group_id to the first column in the sheet

# Logging khi bot vào nhóm và in ra ID nhóm, tên nhóm vào tin nhắn
async def log_group_info(update: Update, context: CallbackContext):
    logger.info("log_group_info function is called")
    
    # Kiểm tra xem chat_member có tồn tại không
    if update.chat_member:
        logger.info(f"Received chat_member data: {update.chat_member}")  # Log dữ liệu chat_member
        if update.chat_member.new_chat_member:
            member = update.chat_member.new_chat_member
            logger.info(f"New chat member added: {member.user.id}")  # Log khi thành viên mới được thêm vào
            if member.user.id == context.bot.id:  # Kiểm tra nếu bot được thêm vào nhóm
                group_id = update.effective_chat.id  # Lấy group_id
                group_name = update.effective_chat.title  # Lấy tên nhóm
                logger.info(f"Bot được thêm vào nhóm: {group_name} (ID nhóm: {group_id})")

                # Ghi group_id và tên nhóm vào Google Sheets
                add_group_to_sheet(group_id)
                
                # Gửi tin nhắn cho người quản trị thông báo rằng bot đã được thêm vào nhóm
                await update.effective_chat.send_message(
                    f"✅ Bot đã được thêm vào nhóm: **{group_name}** (ID nhóm: {group_id})."
                )
            else:
                logger.info(f"Bot không phải là thành viên mới trong nhóm.")
    else:
        logger.info("No chat_member data in update.")

# Xử lý khi có tin nhắn từ khách hàng
async def handle_message(update: Update, context: CallbackContext):
    msg = update.message
    chat_id = update.effective_chat.id
    user_id = msg.from_user.id

    # Kiểm tra tin nhắn từ người dùng và bot không phải là người gửi
    if not msg or msg.from_user.is_bot or not is_group_active(chat_id):
        return

    # Nếu tin nhắn có từ khóa spam, bỏ qua
    text = msg.text.lower() if msg.text else ""
    if any(keyword in text for keyword in ["http", "vpn", "t.me", "@bot"]):
        return  # Bỏ qua tin nhắn có chứa từ khóa spam

    # Tạo nút "Start" cho nhân viên nội bộ
    keyboard = [[InlineKeyboardButton("Start", callback_data="start_processing")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Trả lời tự động cho khách hàng
    await msg.reply_text(
        "Xin chào Quý khách.\nCảm ơn Quý khách đã liên hệ với Công ty Cổ phần Tư vấn và Đầu tư CVT.\n"
        "Nếu Quý khách cần hỗ trợ hoặc có bất kỳ vấn đề nào cần trao đổi, vui lòng để lại tin nhắn tại đây.\n"
        "Đội ngũ tư vấn sẽ theo dõi và phản hồi Quý khách trong thời gian sớm nhất có thể ạ.",
        reply_markup=reply_markup
    )

    # Lưu lại trạng thái, cho phép xử lý bởi nhân viên nếu chưa có
    if user_id not in user_states:
        user_states[user_id] = {"waiting_for_processing": True}
        conversation_last_message_time[chat_id] = time()

# Xử lý khi nhân viên nhấn nút "Start"
async def start_processing(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # Kiểm tra nếu là nhân viên nội bộ mới có quyền xử lý
    if user_id not in INTERNAL_USERS_ID:
        await query.answer("Bạn không có quyền xử lý tin nhắn này.")
        return

    # Chuyển quyền xử lý tin nhắn cho nhân viên nội bộ
    if user_id in user_states and user_states[user_id]["waiting_for_processing"]:
        # Thông báo cho khách hàng rằng nhân viên đã tiếp nhận
        await context.bot.send_message(
            chat_id,
            text=f"Nhân viên {query.from_user.first_name} đã tiếp nhận thông tin và đang xử lý."
        )

        # Ngừng tự động trả lời
        user_states[user_id]["waiting_for_processing"] = False
        await query.answer("Nhân viên đã tiếp nhận thông tin, đang xử lý.")

        # Hủy nút Start sau khi nhân viên đã nhấn
        await query.edit_message_reply_markup(reply_markup=None)

# Thêm handler cho callback khi nhấn nút "Start"
application = Application.builder().token(os.getenv("BOT_TOKEN")).build()
application.add_handler(MessageHandler(filters.ALL, handle_message))
application.add_handler(CallbackQueryHandler(start_processing, pattern="^start_processing$"))  # Thêm handler cho nút Start
application.add_handler(ChatMemberHandler(log_group_info))  # Thêm ChatMemberHandler để theo dõi khi bot vào nhóm

# Xóa webhook trước khi bắt đầu polling
async def remove_webhook(application):
    try:
        await application.bot.delete_webhook()  # Xóa webhook nếu có
        logger.info("Webhook deleted successfully.")
    except Exception as e:
        logger.error(f"Failed to delete webhook: {e}")

# Chạy chương trình chính trong môi trường hỗ trợ async
if __name__ == "__main__":
    print("✅ Bot is running...")

    # Lấy event loop và khởi chạy polling
    loop = asyncio.get_event_loop()  # Lấy event loop
    loop.run_until_complete(remove_webhook(application))  # Xóa webhook trước khi chạy polling
    loop.run_until_complete(application.run_polling())  # Chạy polling với event loop
