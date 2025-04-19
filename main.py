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
from telegram.ext import Application, MessageHandler, CallbackContext, filters, CallbackQueryHandler
from oauth2client.service_account import ServiceAccountCredentials

# ==== ENV CONFIG ====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")

if not BOT_TOKEN or not GOOGLE_CREDS_JSON:
    raise ValueError("Missing environment variables BOT_TOKEN or GOOGLE_CREDS_JSON")

# ==== LOGGING ====
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==== GOOGLE SHEET SETUP ====
SHEET_ID = "1ASeRadkkokhqOflRETw6sGJTyJ65Y0XQi5mvFmivLnY"
SHEET_NAME = "Sheet1"
GROUP_CACHE = {"data": [], "last_updated": 0}
CACHE_TTL = 300

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# ==== CONSTANTS ====
INTERNAL_USERS_ID = [7934716459, 7985186615, 6129180120, 6278235756]
user_states = {}
conversation_last_message_time = {}
conversation_handlers = {}
MAX_IDLE_TIME = 1800

# ==== FLASK KEEP ALIVE ====
app = Flask('')
@app.route('/')
def home(): return "CVT bot is live."
def run_web(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run_web).start()

# ==== TIME CHECK ====
def check_office_hours():
    now = datetime.datetime.now(pytz.timezone('Asia/Ho_Chi_Minh'))
    return now.weekday() < 6 and (now.hour > 8 or (now.hour == 8 and now.minute >= 30)) and now.hour < 17

def get_time_slot():
    now = datetime.datetime.now(pytz.timezone('Asia/Ho_Chi_Minh'))
    if 17 <= now.hour < 19:
        return "early_evening"
    elif 19 <= now.hour <= 23:
        return "late_evening"
    return "office_hours"

# ==== GROUP STATUS ====
def get_cached_group_data():
    now = time()
    if now - GROUP_CACHE["last_updated"] > CACHE_TTL:
        GROUP_CACHE["data"] = sheet.get_all_records()
        GROUP_CACHE["last_updated"] = now
    return GROUP_CACHE["data"]

def is_group_active(group_id):
    records = get_cached_group_data()
    return any(str(row["group_id"]) == str(group_id) and str(row["active"]).lower() == "true" for row in records)

# ==== WELCOME HANDLER ====
async def welcome_new_member(update: Update, context: CallbackContext):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text(
                "Xin chào Quý khách.\nCảm ơn Quý khách đã tin tưởng sử dụng dịch vụ của CVT.\nNếu Quý khách cần hỗ trợ hoặc có bất kỳ vấn đề nào cần trao đổi, vui lòng để lại tin nhắn tại đây. Đội ngũ tư vấn sẽ theo dõi và phản hồi trong thời gian sớm nhất có thể ạ."
            )

# ==== HANDLE MESSAGE ====
async def handle_message(update: Update, context: CallbackContext):
    msg = update.message
    chat_id = msg.chat.id
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
    state = user_states.get(user_id, None)

    conversation_last_message_time[chat_id] = time()
    if chat_id not in conversation_handlers:
        conversation_handlers[chat_id] = None

    if not is_office:
        if state == "notified_out_of_office":
            await msg.reply_text(
                "🌙 Hiện tại, Công ty Cổ phần Tư vấn và Đầu tư CVT đang ngoài giờ làm việc (08:30 – 17:00, Thứ 2 đến Thứ 7, không tính thời gian nghỉ trưa).\nQuý khách vui lòng để lại tin nhắn – chúng tôi sẽ liên hệ lại trong thời gian làm việc sớm nhất.\nTrân trọng cảm ơn!"
            )
        elif time_slot == "early_evening":
            await msg.reply_text(
                "🎉 Xin chào Quý khách!\nCảm ơn Quý khách đã liên hệ với Công ty Cổ phần Tư vấn và Đầu tư CVT.\nChúng tôi sẽ phản hồi trong thời gian sớm nhất.\n🕒 Giờ làm việc: 08:30 – 17:00 (Thứ 2 đến Thứ 7)\n🗓 Chủ nhật & Ngày lễ: Nghỉ\nNgoài giờ, Quý khách vui lòng để lại tin nhắn."
            )
            user_states[user_id] = "notified_out_of_office"
        else:
            await msg.reply_text(
                "🌙 Hiện tại, CVT đang ngoài giờ làm việc. Vui lòng để lại tin nhắn – chúng tôi sẽ liên hệ trong giờ làm việc!"
            )
        return

    if state is None:
        await msg.reply_text(
            "Xin chào Quý khách.\nCảm ơn Quý khách đã tin tưởng sử dụng dịch vụ của CVT.\nNếu Quý khách cần hỗ trợ hoặc có vấn đề, vui lòng để lại tin nhắn tại đây. Đội ngũ sẽ phản hồi sớm nhất ạ."
        )
        user_states[user_id] = "active"

    if msg.document or msg.photo or msg.video or msg.voice:
        await send_file_confirmation(msg)

    if conversation_handlers[chat_id] is None:
        keyboard = [[InlineKeyboardButton("Start", callback_data=f"start_{chat_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.reply_text("Chào bạn! Nhấn nút 'Start' để bắt đầu trò chuyện với khách hàng", reply_markup=reply_markup)

# ==== FILE CONFIRMATION ====
async def send_file_confirmation(msg):
    if msg.document:
        text = f"✅ CVT đã nhận được tài liệu.\n📄 Tên file: {msg.document.file_name}"
    elif msg.photo:
        text = "✅ CVT đã nhận được hình ảnh."
    elif msg.video:
        duration = str(datetime.timedelta(seconds=msg.video.duration))
        text = f"✅ CVT đã nhận được video.\n⏱ Thời gian: {duration}"
    elif msg.voice:
        duration = str(datetime.timedelta(seconds=msg.voice.duration))
        text = f"✅ CVT đã nhận được tin nhắn thoại.\n⏱ Thời gian: {duration}"
    else:
        text = "✅ CVT đã nhận được tin nhắn."
    follow_up = "\nBộ phận Dịch vụ khách hàng sẽ phản hồi trong thời gian sớm nhất.\nCảm ơn Quý khách đã tin tưởng CVT!"
    await msg.reply_text(text + follow_up)

# ==== CALLBACK BUTTON ====
async def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    if not data.startswith("start_"):
        return
    chat_id = int(data.split("_")[1])

    conversation_handlers[chat_id] = user_id
    await query.message.reply_text(f"Nhân viên {query.from_user.full_name} đã tiếp nhận tin nhắn này. Cuộc trò chuyện sẽ được chuyển tiếp cho nhân viên phụ trách.")

# ==== MAIN ====
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.VOICE, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
