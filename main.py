import logging
import datetime
import pytz
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext
from telegram.ext import filters

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Lưu trạng thái người dùng
user_states = {}

# Giờ làm việc
def check_office_hours() -> bool:
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.datetime.now(tz)
    if now.weekday() < 6:  # Thứ 2 đến Thứ 7
        if (8 < now.hour < 17) or (now.hour == 8 and now.minute >= 30):
            return True
    return False

# TH1: Người mới được thêm vào nhóm
async def welcome_new_member(update: Update, context: CallbackContext):
    for member in update.message.new_chat_members:
        # Nếu người mới là chính bot → bỏ qua
        if member.id == context.bot.id:
            return

        message = (
            "Xin chào Quý khách.\n"
            "Cảm ơn Quý khách đã tin tưởng sử dụng dịch vụ của CVT.\n"
            "Nếu Quý khách cần hỗ trợ hoặc có bất kỳ vấn đề nào cần trao đổi, vui lòng để lại tin nhắn tại đây. "
            "Đội ngũ tư vấn sẽ theo dõi và phản hồi Quý khách trong thời gian sớm nhất có thể ạ."
        )
        await update.message.reply_text(message)

# TH2, TH3, TH4: Xử lý các tin nhắn người dùng
async def handle_message(update: Update, context: CallbackContext):
    if not update.message or update.message.from_user.is_bot:
        return

    user_id = update.message.from_user.id
    is_office_hours = check_office_hours()
    current_state = user_states.get(user_id)

    # TH3: Lần đầu gửi tin ngoài giờ
    if not is_office_hours and current_state != "notified_out_of_office":
        message = (
            "🎉 Xin chào quý khách!\n"
            "Cảm ơn Quý khách đã liên hệ với CVT.\n"
            "Chúng tôi sẽ phản hồi trong thời gian sớm nhất.\n"
            "🕐 Giờ làm việc: 8h30 – 17h00 (Thứ 2 đến Thứ 7)\n"
            "Chủ nhật và ngày lễ: Nghỉ\n"
            "Trong thời gian ngoài giờ, Quý khách vẫn có thể để lại tin nhắn – "
            "chúng tôi sẽ phản hồi ngay khi làm việc trở lại."
        )
        await update.message.reply_text(message)
        user_states[user_id] = "notified_out_of_office"
        return

    # TH4: Ngoài giờ & đã được thông báo trước đó
    if not is_office_hours and current_state == "notified_out_of_office":
        await send_confirmation(update)
        return

    # TH2: Trong giờ làm việc
    user_states[user_id] = "active"
    await send_confirmation(update)

# Phản hồi xác nhận đã nhận tin nhắn / tập tin
async def send_confirmation(update: Update):
    confirmation_message = ""

    if update.message.photo:
        confirmation_message = "✅ CVT đã nhận được hình ảnh của quý khách."

    elif update.message.document:
        doc = update.message.document
        confirmation_message = f"✅ CVT đã nhận được tài liệu của quý khách.\n📄 Tên file: {doc.file_name}"

    elif update.message.video:
        video = update.message.video
        duration = str(datetime.timedelta(seconds=video.duration))
        confirmation_message = f"✅ CVT đã nhận được video của quý khách.\n⏱ Thời lượng: {duration}"

    elif update.message.voice:
        voice = update.message.voice
        duration = str(datetime.timedelta(seconds=voice.duration))
        confirmation_message = f"✅ CVT đã nhận được tin nhắn thoại của quý khách.\n⏱ Thời lượng: {duration}"

    else:
        confirmation_message = "✅ CVT đã nhận được tin nhắn của quý khách."

    follow_up = (
        "\nBộ phận Dịch vụ khách hàng sẽ xem xét và phản hồi trong thời gian sớm nhất.\n"
        "Cảm ơn Quý khách đã tin tưởng và lựa chọn dịch vụ của chúng tôi."
    )
    await update.message.reply_text(confirmation_message + follow_up)

# Xử lý lỗi
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update {update} caused error {context.error}')
    try:
        raise context.error
    except Exception as e:
        logger.exception(f"Exception while handling an update: {str(e)}")

# Chạy bot
def main():
    token = '8131925759:AAGDAQA8gojjkhLXaf-IzV0J-Heu-J2s1nI'
    application = Application.builder().token(token).build()

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.Document.ALL |  filters.VIDEO | filters.VOICE,
        handle_message
    ))

    application.add_error_handler(error)
    
    # ✅ Gọi Flask server để giữ Replit online
    keep_alive()
    
    # ✅ Khởi động bot
    application.run_polling()
# === Flask server để giữ Replit luôn online ===
app = Flask('')

@app.route('/')
def home():
    return "🤖 CVT Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()
    
if __name__ == '__main__':
    main()
