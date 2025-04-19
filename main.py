import logging
import datetime
import pytz
import gspread
import os
import json
import asyncio
from time import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackContext, filters
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

async def send_file_confirmation(msg):
    if msg.document:
        text = f"""✅ Công ty Cổ phần Tư vấn và Đầu tư CVT đã nhận được tài liệu.
📄 Tên file: {msg.document.file_name}"""
    elif msg.photo:
        text = "✅ Công ty Cổ phần Tư vấn và Đầu tư CVT đã nhận được hình ảnh."
    elif msg.video:
        duration = str(datetime.timedelta(seconds=msg.video.duration))
        text = f"""✅ Công ty Cổ phần Tư vấn và Đầu tư CVT đã nhận được video.
⏱ Thời gian: {duration}"""
    elif msg.voice:
        duration = str(datetime.timedelta(seconds=msg.voice.duration))
        text = f"""✅ Công ty Cổ phần Tư vấn và Đầu tư CVT đã nhận được tin nhắn thoại.
⏱ Thời gian: {duration}"""
    else:
        text = "✅ Công ty Cổ phần Tư vấn và Đầu tư CVT đã nhận được tin nhắn của Quý khách"

    follow_up = "\nBộ phận Chăm sóc Khách hàng sẽ xem xét và phản hồi trong thời gian sớm nhất.\nCảm ơn Quý khách đã tin tưởng và lựa chọn dịch vụ của CVT!"
    await msg.reply_text(text + follow_up)

async def handle_message(update: Update, context: CallbackContext):
    msg = update.message
    chat_id = update.effective_chat.id
    user_id = msg.from_user.id

    if not msg or msg.from_user.is_bot or not is_group_active(chat_id):
        return

    if hasattr(msg, "forward_from") or hasattr(msg, "forward_from_chat"):
        return

    text = msg.text.lower() if msg.text else ""
    if any(keyword in text for keyword in ["http", "t.me", "@bot", "vpn"]):
        return

    is_office = check_office_hours()
    time_slot = get_time_slot()
    state = user_states.get(user_id)

    # Xử lý ngoài giờ làm việc
    if not is_office:
        if state == "notified_out_of_office":
            await msg.reply_text(
                "🌙 Hiện tại, Công ty Cổ phần Tư vấn và Đầu tư CVT đang ngoài giờ làm việc (08:30 – 17:00, Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa).\n"
                "Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ liên hệ lại trong thời gian làm việc sớm nhất.\n"
                "Trân trọng cảm ơn!"
            )
        elif time_slot == "early_evening":
            await msg.reply_text(
                "🎉 Xin chào Quý khách!\n"
                "Cảm ơn Quý khách đã liên hệ với Công ty Cổ phần Tư vấn và Đầu tư CVT.\n"
                "Chúng tôi sẽ phản hồi trong thời gian sớm nhất.\n\n"
                "🕒 Giờ làm việc: 08:30 – 17:00 (Thứ 2 đến Thứ 7)\n"
                "📅 Chủ nhật & Ngày lễ: Nghỉ\n"
                "Ngoài giờ làm việc, Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ phản hồi ngay khi làm việc sớm nhất."
            )
            user_states[user_id] = "notified_out_of_office"
        else:
            await msg.reply_text(
                "🌙 Hiện tại, Công ty Cổ phần Tư vấn và Đầu tư CVT đang ngoài giờ làm việc (08:30 – 17:00, Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa).\n"
                "Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ liên hệ lại trong thời gian làm việc sớm nhất.\n"
                "Trân trọng cảm ơn!"
            )
        return

    # Trong giờ làm việc – chào khách
    if state is None:
        await msg.reply_text(
            "Xin chào Quý khách.\n"
            "Cảm ơn Quý khách đã tin tưởng sử dụng dịch vụ của CVT.\n"
            "Nếu Quý khách cần hỗ trợ hoặc có bất kỳ vấn đề nào cần trao đổi, vui lòng để lại tin nhắn tại đây.\n"
            "Đội ngũ tư vấn sẽ theo dõi và phản hồi Quý khách trong thời gian sớm nhất có thể ạ."
        )
        user_states[user_id] = "active"

    # Nếu có tập tin
    if msg.document or msg.photo or msg.video or msg.voice:
        await send_file_confirmation(msg)

    # Cập nhật thời gian cuối và người xử lý
    conversation_last_message_time[chat_id] = time()
    conversation_handlers[chat_id] = user_id if user_id in INTERNAL_USERS_ID else None

async def monitor_conversations(application):
    while True:
        now = time()
        for chat_id, last_time in list(conversation_last_message_time.items()):
            if now - last_time > MAX_IDLE_TIME:
                handler_id = conversation_handlers.get(chat_id)
                if handler_id:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=f"⏱ Nhân viên đã rời cuộc trò chuyện. CVT xin cảm ơn Quý khách đã trao đổi. Chúng tôi sẽ hỗ trợ tiếp nếu cần!"
                    )
                conversation_handlers.pop(chat_id, None)
                conversation_last_message_time[chat_id] = now
        await asyncio.sleep(30)

async def main():
    token = os.environ.get("BOT_TOKEN")
    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    asyncio.create_task(monitor_conversations(application))
    print("✅ Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
