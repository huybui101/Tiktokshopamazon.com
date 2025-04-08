import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Cơ sở dữ liệu SQLite
def connect_db():
    try:
        conn = sqlite3.connect('shift_tracking.db')
        return conn
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        return None

def create_db():
    conn = connect_db()
    if conn is None:
        logger.error("Không thể kết nối đến cơ sở dữ liệu.")
        return

    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS shifts (
                    user_id INTEGER,
                    shift_start TEXT,
                    shift_end TEXT,
                    total_work_time INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS breaks (
                    user_id INTEGER,
                    break_type TEXT,
                    break_start TEXT,
                    break_end TEXT,
                    duration INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS break_stats (
                    user_id INTEGER,
                    break_type TEXT,
                    count INTEGER,
                    total_duration INTEGER)''')
    conn.commit()
    conn.close()

# Bàn phím cố định với các lệnh
def get_menu_keyboard():
    keyboard = [
        [KeyboardButton("/start_shift LÊN CA - 上班"), KeyboardButton("/end_shift XUỐNG CA - 下班")],
        [KeyboardButton("/meal ĂN CƠM - 吃饭"), KeyboardButton("/wc WC - 上厕所"), KeyboardButton("/smoke HÚT THUỐC - 抽烟")],
        [KeyboardButton("/back QUAY LẠI - 回座")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Lệnh /start - Hiển thị menu cho người dùng
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Chào bạn! Hãy chọn một hành động từ bàn phím bên dưới:",
        reply_markup=get_menu_keyboard()
    )

# Lệnh /start_shift - Bắt đầu ca làm việc
async def start_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = connect_db()
    if conn is None:
        await update.message.reply_text("Lỗi kết nối đến cơ sở dữ liệu.")
        return
    
    try:
        user_id = update.message.from_user.id
        user_name = update.message.from_user.first_name
        start_time = datetime.now().strftime("%m/%d %H:%M:%S")

        # Kiểm tra nếu người dùng đã bắt đầu ca làm việc mà chưa kết thúc
        c = conn.cursor()
        c.execute("SELECT shift_end FROM shifts WHERE user_id = ? AND shift_end IS NULL", (user_id,))
        existing_shift = c.fetchone()

        if existing_shift is not None:
            await update.message.reply_text("Bạn đã có một ca làm việc chưa kết thúc. Vui lòng kết thúc ca hiện tại trước khi bắt đầu ca mới.")
            return

        # Ghi vào cơ sở dữ liệu khi bắt đầu ca
        c.execute("INSERT INTO shifts (user_id, shift_start) VALUES (?, ?)", (user_id, start_time))
        
        # Reset lại số lần và thời gian nghỉ khi bắt đầu ca
        c.execute("DELETE FROM break_stats WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM breaks WHERE user_id = ?", (user_id,))
        
        conn.commit()

        # Thông báo khi bắt đầu ca làm việc
        notification = f"用户：{user_name} {user_id}\n" \
                       f"用户标识：{user_id}\n" \
                       f"✅ 打卡成功：上班 - {start_time}\n" \
                       f"提示：请记得下班时打卡下班"
        await update.message.reply_text(notification, reply_markup=get_menu_keyboard())
        
    except sqlite3.Error as e:
        logger.error(f"Error during start shift operation: {e}")
        await update.message.reply_text("Có lỗi xảy ra trong quá trình bắt đầu ca làm việc.")
    finally:
        conn.close()

# Lệnh /end_shift - Kết thúc ca làm việc
async def end_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = connect_db()
    if conn is None:
        await update.message.reply_text("Lỗi kết nối đến cơ sở dữ liệu.")
        return

    try:
        user_id = update.message.from_user.id
        user_name = update.message.from_user.first_name
        shift_end = datetime.now().strftime("%m/%d %H:%M:%S")
        
        # Lấy thời gian bắt đầu ca
        c = conn.cursor()
        c.execute("SELECT shift_start FROM shifts WHERE user_id = ? AND shift_end IS NULL", (user_id,))
        shift_start = c.fetchone()

        if shift_start is None:
            await update.message.reply_text("Chưa có ca làm việc nào bắt đầu.")
            return
        
        shift_start_time = datetime.strptime(shift_start[0], "%m/%d %H:%M:%S")
        shift_end_time = datetime.strptime(shift_end, "%m/%d %H:%M:%S")
        total_work_time = (shift_end_time - shift_start_time).seconds

        # Lấy thời gian nghỉ trong ngày
        c.execute("""SELECT SUM(duration) FROM breaks WHERE user_id = ?""", (user_id,))
        total_break_time = c.fetchone()[0] or 0

        pure_work_time = total_work_time - total_break_time

        # Cập nhật dữ liệu ca làm việc
        c.execute("UPDATE shifts SET shift_end = ?, total_work_time = ? WHERE user_id = ? AND shift_end IS NULL", 
                  (shift_end, total_work_time, user_id))
        conn.commit()

        # Tính tổng thời gian làm việc và nghỉ
        total_work_time_str = str(timedelta(seconds=total_work_time))
        pure_work_time_str = str(timedelta(seconds=pure_work_time))
        total_break_time_str = str(timedelta(seconds=total_break_time))

        # Thống kê tổng số lần và thời gian nghỉ trong ngày
        c.execute("SELECT break_type, COUNT(*), SUM(duration) FROM breaks WHERE user_id = ? GROUP BY break_type", (user_id,))
        break_stats = c.fetchall()

        break_stats_text = ""
        for break_type, count, total_duration in break_stats:
            break_type_display = {
                "meal": "ĂN CƠM", 
                "smoke": "HÚT THUỐC", 
                "wc": "WC"
            }.get(break_type, break_type)
            total_duration_str = str(timedelta(seconds=total_duration))
            break_stats_text += f"【{break_type_display}】\n次数：{count} 次\n总时间：{total_duration_str}\n"

        # Thông báo kết thúc ca
        notification = (
            f"用户：{user_name}\n"
            f"用户标识：{user_id}\n"
            f"✅ 打卡成功：下班 - {shift_end}\n"
            f"提示：本日工作时间已结算\n"
            f"今日工作总计：{total_work_time_str}\n"
            f"纯工作时间：{pure_work_time_str}\n"
            f"------------------------\n"
            f"今日累计活动总时间：{total_break_time_str}\n"
            f"{break_stats_text}"
        )

        # Gửi thông báo cho người dùng với bàn phím cố định
        await update.message.reply_text(notification, reply_markup=get_menu_keyboard())

        # Reset lại cơ sở dữ liệu cho ngày hôm sau
        c.execute("DELETE FROM breaks WHERE user_id = ?", (user_id,))
        conn.commit()

    except sqlite3.Error as e:
        logger.error(f"Error during end shift operation: {e}")
        await update.message.reply_text("Có lỗi xảy ra trong quá trình kết thúc ca làm việc.")
    finally:
        conn.close()

# Kiểm tra xem người dùng có đang nghỉ hay không
def is_in_break(user_id, break_type):
    conn = connect_db()
    if conn is None:
        return False
    try:
        c = conn.cursor()
        c.execute("SELECT break_end FROM breaks WHERE user_id = ? AND break_type = ? AND break_end IS NULL", (user_id, break_type))
        return c.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"Error checking break status: {e}")
        return False
    finally:
        conn.close()

# Lệnh nghỉ (ĂN CƠM, WC, HÚT THUỐC)
async def log_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    break_type = update.message.text.strip('/').lower()  # Lấy tên lệnh, ví dụ: 'meal', 'wc', 'smoke'
    
    # Kiểm tra xem người dùng có đang nghỉ không
    if is_in_break(user_id, break_type):
        await update.message.reply_text("Bạn cần quay lại làm việc trước khi thực hiện hoạt động này.")
        return
    
    break_start = datetime.now().strftime("%m/%d %H:%M:%S")
    
    conn = connect_db()
    if conn is None:
        await update.message.reply_text("Lỗi kết nối đến cơ sở dữ liệu.")
        return

    try:
        # Ghi vào cơ sở dữ liệu khi bắt đầu nghỉ
        c = conn.cursor()
        c.execute("INSERT INTO breaks (user_id, break_type, break_start) VALUES (?, ?, ?)", 
                  (user_id, break_type, break_start))
        conn.commit()

        # Cập nhật bảng break_stats để lưu số lần và tổng thời gian
        c.execute("SELECT count, total_duration FROM break_stats WHERE user_id = ? AND break_type = ?", (user_id, break_type))
        result = c.fetchone()
        if result:
            count, total_duration = result
            count += 1
            c.execute("UPDATE break_stats SET count = ? WHERE user_id = ? AND break_type = ?", 
                      (count, user_id, break_type))
        else:
            c.execute("INSERT INTO break_stats (user_id, break_type, count, total_duration) VALUES (?, ?, ?, ?)", 
                      (user_id, break_type, 1, 0))
        
        conn.commit()

        # Thông báo ngay lập tức sau khi người dùng bấm lệnh nghỉ
        break_type_display = {
            "meal": "ĂN CƠM", 
            "smoke": "HÚT THUỐC", 
            "wc": "WC"
        }.get(break_type, break_type)  # Hiển thị đúng tên hoạt động

        notification = (
            f"用户：{user_name}\n"
            f"用户标识：{user_id}\n"
            f"✅ 打卡成功：{break_type_display} - {break_start}\n"
            f"提示：请在完成活动后尽早回到工作岗位\n"
            f"回到工作：/back"
        )

        # Gửi thông báo cho người dùng với bàn phím cố định
        await update.message.reply_text(notification, reply_markup=get_menu_keyboard())

    except sqlite3.Error as e:
        logger.error(f"Error during break logging operation: {e}")
        await update.message.reply_text("Có lỗi xảy ra trong quá trình ghi nhận nghỉ.")

    finally:
        conn.close()

# Lệnh quay lại làm việc (回座)
async def back_to_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    break_end = datetime.now().strftime("%m/%d %H:%M:%S")

    conn = connect_db()
    if conn is None:
        await update.message.reply_text("Lỗi kết nối đến cơ sở dữ liệu.")
        return

    try:
        # Lấy thông tin nghỉ từ cơ sở dữ liệu
        c = conn.cursor()
        c.execute("""SELECT break_type, break_start FROM breaks WHERE user_id = ? AND break_end IS NULL""", (user_id,))
        break_data = c.fetchone()

        if break_data is None:
            await update.message.reply_text("Chưa có hoạt động nghỉ nào để quay lại.")
            return

        break_type = break_data[0]
        break_start_time = datetime.strptime(break_data[1], "%m/%d %H:%M:%S")
        break_end_time = datetime.strptime(break_end, "%m/%d %H:%M:%S")
        duration = (break_end_time - break_start_time).seconds

        # Cập nhật thông tin quay lại làm việc
        c.execute("UPDATE breaks SET break_end = ?, duration = ? WHERE user_id = ? AND break_end IS NULL", 
                  (break_end, duration, user_id))
        
        # Cập nhật tổng thời gian trong bảng break_stats mà **không thay đổi count**
        c.execute("SELECT count, total_duration FROM break_stats WHERE user_id = ? AND break_type = ?", 
                  (user_id, break_type))
        count, total_duration = c.fetchone()
        total_duration += duration  # Thêm thời gian vào tổng

        # Cập nhật lại bảng break_stats nhưng không thay đổi số lần (count)
        c.execute("UPDATE break_stats SET total_duration = ? WHERE user_id = ? AND break_type = ?", 
                  (total_duration, user_id, break_type))
        
        conn.commit()

        # Tính toán thời gian và gửi thông báo quay lại làm việc
        duration_str = str(timedelta(seconds=duration))

        # Thống kê số lần và thời gian trước đó
        c.execute("SELECT count, total_duration FROM break_stats WHERE user_id = ? AND break_type = ?", 
                  (user_id, break_type))
        result = c.fetchone()
        count, total_duration = result
        total_duration_str = str(timedelta(seconds=total_duration))

        break_type_display = {
            "meal": "ĂN CƠM", 
            "smoke": "HÚT THUỐC", 
            "wc": "WC"
        }.get(break_type, break_type)  # Hiển thị đúng tên hoạt động

        # Thông báo quay lại làm việc
        notification = (
            f"用户：{user_name}\n"
            f"用户标识：{user_id}\n"
            f"✅ 打卡成功：回座 - {break_end}\n"
            f"提示：您的休息已结束，回到工作岗位\n"
            f"休息类型：{break_type_display}\n"
            f"休息时长：{duration_str}\n"
            f"总计休息时间：{total_duration_str}\n"
            f"总休息次数：{count} 次\n"
            f"【继续工作】\n"
        )

        await update.message.reply_text(notification, reply_markup=get_menu_keyboard())

    except sqlite3.Error as e:
        logger.error(f"Error during back to work operation: {e}")
        await update.message.reply_text("Có lỗi xảy ra khi quay lại làm việc.")
    finally:
        conn.close()

def main():
    create_db()  # Tạo cơ sở dữ liệu nếu chưa có
    application = Application.builder().token("7351932579:AAHBQsB2mQyXBf1Whx7y5XgpaX1rsHYQT3I").build()

    # Thêm các handler cho các lệnh
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("start_shift", start_shift))
    application.add_handler(CommandHandler("end_shift", end_shift))
    application.add_handler(CommandHandler("meal", log_break))
    application.add_handler(CommandHandler("wc", log_break))
    application.add_handler(CommandHandler("smoke", log_break))
    application.add_handler(CommandHandler("back", back_to_work))

    application.run_polling()

if __name__ == '__main__':
    main()
