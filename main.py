import logging
import datetime
import pytz
import gspread
import os
import json
import gspread
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, CallbackContext, filters
from oauth2client.service_account import ServiceAccountCredentials

# ========== CONFIG GOOGLE SHEETS ==========
SHEET_ID = "1ASeRadkkokhqOflRETw6sGJTyJ65Y0XQi5mvFmivLnY"
SHEET_NAME = "Sheet1"

# ✅ Lấy credentials từ biến môi trường GOOGLE_CREDS_JSON
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
if not GOOGLE_CREDS_JSON:
    raise ValueError("❌ GOOGLE_CREDS_JSON environment variable is missing!")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# ========== LOGGING ==========
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

user_states = {}

def check_office_hours() -> bool:
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.datetime.now(tz)
    if now.weekday() < 6:
        if (8 < now.hour < 17) or (now.hour == 8 and now.minute >= 30):
            return True
    return False

def is_group_active(group_id: int) -> bool:
    records = sheet.get_all_records()
    for row in records:
        if str(row["group_id"]) == str(group_id) and str(row["active"]).lower() == "true":
            return True
    return False

def is_group_registered(group_id: int) -> bool:
    records = sheet.get_all_records()
    return any(str(row["group_id"]) == str(group_id) for row in records)

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
            "Nếu Quý khách cần hỗ trợ hoặc có bất kỳ vấn đề nào cần trao đổi, "
            "vui lòng để lại tin nhắn tại đây. Đội ngũ tư vấn sẽ theo dõi và phản hồi Quý khách trong thời gian sớm nhất có thể ạ."
        )
        await update.message.reply_text(message)

async def handle_message(update: Update, context: CallbackContext):
    if not update.message or update.message.from_user.is_bot:
        return

    if update.message.forward_from or update.message.forward_from_chat:
        return

    text = update.message.text or ""
    if "@" in text or "http" in text or "t.me/" in text:
        return

    chat_id = update.effective_chat.id
    if not is_group_active(chat_id):
        return

    user_id = update.message.from_user.id
    is_office_hours = check_office_hours()
    current_state = user_states.get(user_id)

    if not is_office_hours and current_state != "notified_out_of_office":
        message = (
            "🎉 Xin chào Quý khách!\n"
            "Cảm ơn Quý khách đã liên hệ với Công ty Cổ phần Tư vấn và Đầu tư CVT.\n"
            "Chúng tôi sẽ phản hồi trong thời gian sớm nhất.\n\n"
            "🕒 Giờ làm việc: 08:30 – 17:00 (Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa)\n"
            "📅 Chủ nhật & Ngày lễ: Nghỉ\n\n"
            "Ngoài giờ làm việc, Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ phản hồi ngay khi làm việc sớm nhất."
        )
        await update.message.reply_text(message)
        user_states[user_id] = "notified_out_of_office"
        return

    if not is_office_hours and current_state == "notified_out_of_office":
        await update.message.reply_text(
            "🌙 Hiện tại, Công ty Cổ phần Tư vấn và Đầu tư CVT đang ngoài giờ làm việc (08:30 – 17:00, Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa).\n"
            "Quý khách vui lòng để lại tin nhắn – chúng tôi sẽ liên hệ lại trong thời gian làm việc sớm nhất.\n"
            "Trân trọng cảm ơn!"
        )
        return

    await send_confirmation(update)
    user_states[user_id] = "active"

async def send_confirmation(update: Update):
    msg = update.message
    text = ""

    if msg.photo:
        text = "✅ CVT đã nhận được hình ảnh của quý khách."
    elif msg.document:
        text = f"✅ CVT đã nhận được tài liệu.\n📄 Tên file: {msg.document.file_name}"
    elif msg.video:
        duration = str(datetime.timedelta(seconds=msg.video.duration))
        text = f"✅ CVT đã nhận được video.\n⏱ Thời lượng: {duration}"
    elif msg.voice:
        duration = str(datetime.timedelta(seconds=msg.voice.duration))
        text = f"✅ CVT đã nhận được tin nhắn thoại.\n⏱ Thời lượng: {duration}"
    else:
        text = "✅ CVT đã nhận được tin nhắn của quý khách."

    follow_up = (
        "\nBộ phận Dịch vụ khách hàng sẽ phản hồi trong thời gian sớm nhất.\n"
        "Cảm ơn Quý khách đã tin tưởng CVT!"
    )
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
    token = "8131925759:AAGDAQA8gojjkhLXaf-IzV0J-Heu-J2s1nI"
    application = Application.builder().token(token).build()

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.VOICE,
        handle_message
    ))

    application.add_error_handler(error)
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
