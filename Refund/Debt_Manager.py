import sqlite3
import threading
import time
import json
import os
import uuid
import traceback
from datetime import datetime, timedelta
from telebot import types
from ollama import Client
from dotenv import load_dotenv
 
load_dotenv()
 
# ################################################################# 
# ####                     setting                              ###
# #################################################################
 
ADMIN_TELEGRAM_ID = os.getenv('ADMIN_TELEGRAM_ID')  # ارشاک
 
DEFAULT_REMINDER_HOUR = 10
DEFAULT_REMINDER_MINUTE = 0
DEFAULT_REMINDER_TEXT = (
    "⏰ یادآوری روزانه\n\n"
    "سلام {first_name}! هنوز بدهی داری:\n\n"
    "{debt_list}\n"
    "💰 مجموع: {total:,} تومان\n\n"
    "برای تسویه /pay رو بزن و رسید پرداختت رو بفرست."
)
 
reminder_config = {
    "hour": DEFAULT_REMINDER_HOUR,
    "minute": DEFAULT_REMINDER_MINUTE,
    "text": DEFAULT_REMINDER_TEXT,
    "enabled": True
}
 
 
# ################################################################# 
# ####                setting up the database                   ###
# #################################################################
 
def init_db(connection):
    cursor = connection.cursor()
 
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            debtor_name TEXT NOT NULL,
            debtor_chat_id INTEGER,
            creditor_name TEXT NOT NULL,
            creditor_card TEXT,
            amount INTEGER NOT NULL,
            paid INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
 
    try:
        cursor.execute("ALTER TABLE gang ADD COLUMN chat_id INTEGER")
    except Exception:
        pass
 
    connection.commit()
    print("[DB] Tables ready.")
 
 
# ################################################################# 
# ####            database handling helper fuctions             ###
# #################################################################
 
def get_member_by_name(cursor, full_name):
    parts = full_name.strip().split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    cursor.execute(
        "SELECT id, first_name, last_name, card_number, chat_id FROM gang WHERE first_name=? AND last_name=?",
        (first, last)
    )
    return cursor.fetchone()
 
 
def get_member_by_chat_id(cursor, chat_id):
    cursor.execute(
        "SELECT id, first_name, last_name, card_number FROM gang WHERE chat_id=?",
        (chat_id,)
    )
    return cursor.fetchone()
 
 
def get_unpaid_debts_by_name(cursor, full_name):
    cursor.execute(
        "SELECT id, creditor_name, creditor_card, amount FROM debts WHERE debtor_name=? AND paid=0",
        (full_name,)
    )
    return cursor.fetchall()
 
 
def get_unpaid_debts_by_chat_id(cursor, chat_id):
    member = get_member_by_chat_id(cursor, chat_id)
    if not member:
        return [], None
    full_name = f"{member[1]} {member[2]}"
    debts = get_unpaid_debts_by_name(cursor, full_name)
    return debts, full_name
 
 
def save_debts_to_db(cursor, connection, session_id, settlement_plan):
    cursor.execute("DELETE FROM debts WHERE session_id=?", (session_id,))
 
    for step in settlement_plan:
        debtor_name = step["from"]
        creditor_name = step["to"]
        amount = step["amount"]
 
        debtor = get_member_by_name(cursor, debtor_name)
        debtor_chat_id = debtor[4] if debtor else None
 
        creditor = get_member_by_name(cursor, creditor_name)
        creditor_card = creditor[3] if creditor else None
 
        cursor.execute('''
            INSERT INTO debts (session_id, debtor_name, debtor_chat_id, creditor_name, creditor_card, amount, paid)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (session_id, debtor_name, debtor_chat_id, creditor_name, creditor_card, amount))
 
    connection.commit()
    return len(settlement_plan)
 
 
# ################################################################# 
# ####                   getting LLM results                    ###
# #################################################################
 
def extract_payment_info(text):
    API_KEY = os.getenv("OLLAMA_API_KEY")
    client = Client(
        host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),  # FIX: use env var
        headers={"Authorization": f"Bearer {API_KEY}"}
    )
 
    prompt = f"""
    Extract payment receipt information from this Persian bank SMS or receipt text.
    Text: "{text}"
 
    Respond ONLY with a raw JSON object with these keys:
    - amount (integer): the amount paid in Toman. 0 if not found.
    - card_last4 (string): first 4 digits and last 4 digits of the DESTINATION card number. "" if not found.
    - is_receipt (boolean): true if this looks like a payment receipt/transaction SMS.
 
    Example: {{"amount": 500000, "card_last4": "1234,####,####,1234", "is_receipt": true}}
    """
 
    raw = ""
    try:
        response = client.chat(
            model=os.getenv("OLLAMA_GPT_MODEL"),
            messages=[
                {"role": "system", "content": "You are a JSON-only response bot. Never write anything except valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        raw = response.message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return {"amount": 0, "card_last4": "", "is_receipt": False}
        return json.loads(raw[start:end])
    except Exception as e:
        print(f"[extract_payment_info] Error: {e} | raw: {repr(raw)}")
        return {"amount": 0, "card_last4": "", "is_receipt": False}
 
 
# ################################################################# 
# ####                      reminder                            ###
# #################################################################
 
def send_daily_reminders(bot, connection):
    while True:
        try:
            now = datetime.now()
            next_run = now.replace(
                hour=reminder_config["hour"],
                minute=reminder_config["minute"],
                second=0,
                microsecond=0
            )
            if now >= next_run:
                next_run += timedelta(days=1)
 
            sleep_secs = (next_run - now).total_seconds()
            print(f"[Reminder] Next run at {next_run.strftime('%H:%M')} — sleeping {sleep_secs/3600:.1f}h")
            time.sleep(sleep_secs)
 
            if not reminder_config["enabled"]:
                print("[Reminder] Disabled, skipping.")
                continue

            local_cursor = connection.cursor()
            local_cursor.execute("""
                SELECT d.debtor_name, d.creditor_name, d.amount, g.chat_id
                FROM debts d
                LEFT JOIN gang g ON g.first_name || ' ' || g.last_name = d.debtor_name
                WHERE d.paid = 0
            """)
            unpaid = local_cursor.fetchall()
 
            debtor_map = {}
            for debtor_name, creditor_name, amount, chat_id in unpaid:
                if debtor_name not in debtor_map:
                    debtor_map[debtor_name] = {"chat_id": chat_id, "debts": []}
                debtor_map[debtor_name]["debts"].append({"creditor": creditor_name, "amount": amount})
 
            for debtor_name, data in debtor_map.items():
                chat_id = data["chat_id"]
                if not chat_id:
                    print(f"[Reminder] No chat_id for {debtor_name}, skipped.")
                    continue
 
                debt_list = "\n".join(
                    [f"🔴 {d['amount']:,} تومان به {d['creditor']}" for d in data["debts"]]
                )
                total = sum(d["amount"] for d in data["debts"])
                first_name = debtor_name.split()[0]

                msg = reminder_config["text"].format(
                    first_name=first_name,
                    debt_list=debt_list,
                    total=total
                )
 
                try:
                    bot.send_message(chat_id, msg)
                    print(f"[Reminder] ✅ Sent to {debtor_name} ({chat_id})")
                except Exception as e:
                    print(f"[Reminder] ❌ Failed for {debtor_name}: {e}")
 
        except Exception as e:
            print(f"[Reminder] Thread error: {e}")
            traceback.print_exc()
            time.sleep(60)
 
 
def start_reminder_thread(bot, connection):
    t = threading.Thread(target=send_daily_reminders, args=(bot, connection), daemon=True)
    t.start()
    print("[Reminder] Thread started.")
 
 
# ################################################################# 
# ####                     bot handlers                         ###
# #################################################################
 
def register_debt_handlers(bot, connection, cursor):
 
    sessions = {}
 
    def get_session(chat_id):
        if chat_id not in sessions:
            sessions[chat_id] = {}
        return sessions[chat_id]

    def fresh_cursor():
        return connection.cursor()

# ─────────────────────────────────────────
#  /register 
# ─────────────────────────────────────────
    user_data = {}
    
    @bot.message_handler(commands=['register'])
    def start_registration(message):
        chat_id = message.chat.id
        user_data[chat_id] = {}
        msg = bot.send_message(chat_id, "لطفاً نام خود را وارد کنید:")
        bot.register_next_step_handler(msg, get_first_name)

    def get_first_name(message):
        chat_id = message.chat.id
        if not message.text:
            msg = bot.send_message(chat_id, "لطفاً نام خود را به صورت متن وارد کنید:")
            bot.register_next_step_handler(msg, get_first_name)
            return
        user_data[chat_id]["first_name"] = message.text.strip()
        msg = bot.send_message(chat_id, "لطفاً نام خانوادگی خود را وارد کنید:")
        bot.register_next_step_handler(msg, get_last_name)

    def get_last_name(message):
        chat_id = message.chat.id
        if not message.text:
            msg = bot.send_message(chat_id, "لطفاً نام خانوادگی خود را به صورت متن وارد کنید:")
            bot.register_next_step_handler(msg, get_last_name)
            return
        user_data[chat_id]["last_name"] = message.text.strip()

        markup = types.InlineKeyboardMarkup()
        confirm_btn = types.InlineKeyboardButton("تایید و ثبت نهایی", callback_data="confirm_reg")
        cancel_btn = types.InlineKeyboardButton("لغو", callback_data="cancel_reg")
        markup.add(confirm_btn, cancel_btn)

        f_name = user_data[chat_id]["first_name"]
        l_name = user_data[chat_id]["last_name"]

        bot.send_message(
            chat_id,
            f"اطلاعات وارد شده:\n\n👤 نام: {f_name}\n👤 نام خانوادگی: {l_name}\n\nآیا این اطلاعات مورد تایید است؟",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data in ["confirm_reg", "cancel_reg"])
    def callback_verification(call):
        chat_id = call.message.chat.id

        if chat_id not in user_data:
            bot.answer_callback_query(call.id, "❌ نشست شما منقضی شده است. مجدد تلاش کنید.")
            return

        if call.data == "confirm_reg":
            final_first_name = user_data[chat_id].get("first_name", "")
            final_last_name = user_data[chat_id].get("last_name", "")

            c = fresh_cursor()
            c.execute(
                "SELECT id FROM gang WHERE first_name=? AND last_name=?",
                (final_first_name, final_last_name)
            )
            member = c.fetchone()

            if member:
                c.execute("UPDATE gang SET chat_id=? WHERE id=?", (chat_id, member[0]))
                connection.commit()
                
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"✅ {final_first_name} {final_last_name} عزیز، اطلاعات شما تایید و ثبت شد!\nاز این به بعد یادآوری بدهی‌ها براتون ارسال میشه.\nبرای تسویه می‌توانید از دستور /pay استفاده کنید."
                )
            else:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"❌ نام «{final_first_name} {final_last_name}» در لیست اعضای گروه پیدا نشد.\nلطفاً با ادمین هماهنگ کنید."
                )

            del user_data[chat_id]

        elif call.data == "cancel_reg":
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ ثبت نام لغو شد. می‌توانید مجدداً با دستور /register شروع کنید.",
            )
            if chat_id in user_data:
                del user_data[chat_id]

    # ─────────────────────────────────────────
    #  /pay 
    # ─────────────────────────────────────────
    @bot.message_handler(commands=['pay'])
    def request_receipt(message):
        session = get_session(message.chat.id)
        c = fresh_cursor()
        debts, full_name = get_unpaid_debts_by_chat_id(c, message.chat.id)
 
        if not debts:
            bot.send_message(message.chat.id, "✅ هیچ بدهی فعالی نداری!")
            return
 
        session['pending_debts'] = [
            {"id": d[0], "creditor": d[1], "card": d[2], "amount": d[3]}
            for d in debts
        ]
 
        debt_text = "💳 بدهی‌های فعال تو:\n\n"
        for d in debts:
            card_hint = f"(کارت: ...{d[2][-4:]})" if d[2] else ""
            debt_text += f"🔴 {d[3]:,} تومان به {d[1]} {card_hint}\n"
        debt_text += "\n📄 متن پیامک بانکی رسید پرداختت رو بفرست:"
 
        msg = bot.send_message(message.chat.id, debt_text)
        bot.register_next_step_handler(msg, process_receipt, session)
 
    def process_receipt(message, session):
        chat_id = message.chat.id

        if not message.text:
            bot.send_message(chat_id, "❌ لطفاً متن پیامک بانکی را بفرستید.")
            return

        text = message.text
        if text.startswith('/'):
            bot.send_message(chat_id, "عملیات لغو شد.")
            return
 
        status = bot.send_message(chat_id, "🔍 در حال بررسی رسید...")
        receipt_info = extract_payment_info(text)
 
        if not receipt_info.get('is_receipt'):
            bot.edit_message_text(
                "❌ این متن شبیه رسید پرداخت نیست.\nلطفاً متن پیامک بانکی رو بفرست.",
                chat_id, status.message_id
            )
            return
 
        receipt_amount = receipt_info.get('amount', 0)
        receipt_card = receipt_info.get('card_last4', '')
        pending_debts = session.get('pending_debts', [])
        matched_debt = None
 
        for debt in pending_debts:
            amount_ok = abs(receipt_amount - debt['amount']) <= debt['amount'] * 0.05
            card_ok = (
                not debt['card'] or
                not receipt_card or
                str(debt['card']).endswith(receipt_card)
            )
            if amount_ok and card_ok:
                matched_debt = debt
                break
 
        if not matched_debt:
            debts_list = [f"{d['amount']:,}" for d in pending_debts]
            debts_str = ", ".join(debts_list) if debts_list else "هیچ بدهی فعالی وجود ندارد"

            bot.edit_message_text(
                chat_id=chat_id,
                message_id=status.message_id,
                text=(
                    f"❌ رسید تطابق نداشت.\n\n"
                    f"💵 مبلغ رسید پردازش شده: {receipt_amount:,} تومان\n"
                    f"⏳ بدهی‌های فعال شما: {debts_str} تومان\n\n"
                    f"⚠️ مطمئن شو مبلغ و شماره کارت مقصد کاملاً درست باشه."
                )
            )
            return

        c = fresh_cursor()
        c.execute("UPDATE debts SET paid=1 WHERE id=?", (matched_debt['id'],))
        connection.commit()
 
        bot.edit_message_text(
            f"✅ پرداخت تایید شد!\n\n"
            f"💰 مبلغ: {receipt_amount:,} تومان\n"
            f"👤 به: {matched_debt['creditor']}\n\n"
            f"بدهیت صاف شد! 🎉",
            chat_id, status.message_id
        )
 
        remaining_debts, _ = get_unpaid_debts_by_chat_id(fresh_cursor(), chat_id)
        if remaining_debts:
            bot.send_message(
                chat_id,
                f"⚠️ هنوز {len(remaining_debts)} بدهی دیگه داری.\n/pay رو بزن برای تسویه."
            )
 
    # ─────────────────────────────────────────
    #  /mydebt
    # ─────────────────────────────────────────
    @bot.message_handler(commands=['mydebt'])
    def my_debt(message):
        debts, full_name = get_unpaid_debts_by_chat_id(fresh_cursor(), message.chat.id)
        if not debts:
            bot.send_message(message.chat.id, "✅ بدهی فعالی نداری!")
            return
        text = f"💰 بدهی‌های فعال {full_name}:\n\n"
        for d in debts:
            card_hint = f"(کارت: ...{d[2][-4:]})" if d[2] else ""
            text += f"🔴 {d[3]:,} تومان به {d[1]} {card_hint}\n"
        text += "\nبرای تسویه /pay رو بزن."
        bot.send_message(message.chat.id, text)
 
    # ─────────────────────────────────────────
    #  /admin 
    # ─────────────────────────────────────────
    def is_admin(message):
        return message.from_user.id == int(ADMIN_TELEGRAM_ID)
 
    def admin_main_panel(chat_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⏰ تغییر زمان ارسال", callback_data="adm_time"))
        markup.add(types.InlineKeyboardButton("✏️ تغییر متن یادآوری", callback_data="adm_text"))
        markup.add(types.InlineKeyboardButton("📋 لیست بدهی‌های فعال", callback_data="adm_list"))
        markup.add(types.InlineKeyboardButton("✅ تایید دستی پرداخت", callback_data="adm_manual_pay"))
        markup.add(types.InlineKeyboardButton(
            f"{'🔴 غیرفعال کردن' if reminder_config['enabled'] else '🟢 فعال کردن'} یادآوری",
            callback_data="adm_toggle"
        ))
        markup.add(types.InlineKeyboardButton("📤 ارسال یادآوری همین الان", callback_data="adm_send_now"))
 
        status_text = "🟢 فعال" if reminder_config["enabled"] else "🔴 غیرفعال"
        text = (
            f"🛠 پنل مدیریت ارشاک\n\n"
            f"⏰ زمان ارسال: {reminder_config['hour']:02d}:{reminder_config['minute']:02d}\n"
            f"📡 وضعیت یادآوری: {status_text}"
        )
        bot.send_message(chat_id, text, reply_markup=markup)
 
    @bot.message_handler(commands=['admin'])
    def admin_panel(message):
        if not is_admin(message):
            bot.send_message(message.chat.id, "⛔️ دسترسی ندارید.")
            return
        admin_main_panel(message.chat.id)
 
    @bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
    def admin_callbacks(call):
        if call.from_user.id != int(ADMIN_TELEGRAM_ID):
            bot.answer_callback_query(call.id, "⛔️ دسترسی ندارید.")
            return
 
        chat_id = call.message.chat.id
        session = get_session(chat_id)
 
        if call.data == "adm_time":
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            msg = bot.send_message(
                chat_id,
                f"⏰ زمان فعلی: {reminder_config['hour']:02d}:{reminder_config['minute']:02d}\n\n"
                f"زمان جدید رو به فرمت HH:MM بفرست (مثلاً 09:30):"
            )
            bot.register_next_step_handler(msg, admin_set_time, session)
 
        elif call.data == "adm_text":
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            msg = bot.send_message(
                chat_id,
                f"✏️ متن فعلی یادآوری:\n\n{reminder_config['text']}\n\n"
                f"───────────────\n"
                f"متغیرهای قابل استفاده:\n"
                f"{{first_name}} — اسم بدهکار\n"
                f"{{debt_list}} — لیست بدهی‌ها\n"
                f"{{total}} — مجموع بدهی\n\n"
                f"متن جدید رو بفرست:"
            )
            bot.register_next_step_handler(msg, admin_set_text, session)
 
        elif call.data == "adm_list":
            c = fresh_cursor()
            c.execute("""
                SELECT debtor_name, creditor_name, amount, created_at
                FROM debts WHERE paid=0
                ORDER BY debtor_name
            """)
            debts = c.fetchall()
 
            if not debts:
                bot.answer_callback_query(call.id, "✅ هیچ بدهی فعالی وجود نداره!")
                return
 
            text = "📋 بدهی‌های فعال:\n\n"
            for d in debts:
                text += f"🔴 {d[0]} ← {d[2]:,} تومان ← {d[1]}\n"
            bot.send_message(chat_id, text)
 
        elif call.data == "adm_toggle":
            reminder_config["enabled"] = not reminder_config["enabled"]
            status = "فعال ✅" if reminder_config["enabled"] else "غیرفعال 🔴"
            bot.answer_callback_query(call.id, f"یادآوری {status}")
            admin_main_panel(chat_id)
 
        elif call.data == "adm_send_now":
            bot.answer_callback_query(call.id, "در حال ارسال...")
            threading.Thread(
                target=_force_send_reminders,
                args=(bot, connection, chat_id),
                daemon=True
            ).start()
 
        elif call.data == "adm_manual_pay":
            c = fresh_cursor()
            c.execute("""
                SELECT id, debtor_name, creditor_name, amount
                FROM debts WHERE paid=0
                ORDER BY debtor_name
            """)
            debts = c.fetchall()
 
            if not debts:
                bot.answer_callback_query(call.id, "✅ بدهی فعالی نیست!")
                return
 
            markup = types.InlineKeyboardMarkup()
            for d in debts:
                label = f"{d[1]} ← {d[3]:,} → {d[2]}"
                markup.add(types.InlineKeyboardButton(label, callback_data=f"adm_pay_{d[0]}"))
            markup.add(types.InlineKeyboardButton("🔙 برگشت", callback_data="adm_back"))
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            bot.send_message(chat_id, "کدوم بدهی رو میخوای دستی تایید کنی؟", reply_markup=markup)
 
        elif call.data.startswith("adm_pay_"):
            try:
                debt_id = int(call.data[len("adm_pay_"):])
            except ValueError:
                bot.answer_callback_query(call.id, "❌ شناسه بدهی نامعتبر است.")
                return
            c = fresh_cursor()
            c.execute("UPDATE debts SET paid=1 WHERE id=?", (debt_id,))
            connection.commit()
            bot.answer_callback_query(call.id, "✅ بدهی تایید شد!")
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            bot.send_message(chat_id, "✅ بدهی با موفقیت دستی تایید شد.")
 
        elif call.data == "adm_back":
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            admin_main_panel(chat_id)
 
    def admin_set_time(message, session):
        chat_id = message.chat.id
        if not message.text:
            bot.send_message(chat_id, "❌ لطفاً زمان را به فرمت HH:MM بفرستید.")
            admin_main_panel(chat_id)
            return
        text = message.text.strip()
        try:
            h, m = text.split(":")
            h, m = int(h), int(m)
            assert 0 <= h <= 23 and 0 <= m <= 59
            reminder_config["hour"] = h
            reminder_config["minute"] = m
            bot.send_message(chat_id, f"✅ زمان ارسال به {h:02d}:{m:02d} تغییر کرد.")
        except Exception:
            bot.send_message(chat_id, "❌ فرمت اشتباه. مثال: 09:30")
        admin_main_panel(chat_id)
 
    def admin_set_text(message, session):
        chat_id = message.chat.id
        if not message.text:
            bot.send_message(chat_id, "❌ لطفاً متن را به صورت متن بفرستید.")
            admin_main_panel(chat_id)
            return
        new_text = message.text.strip()

        try:
            new_text.format(first_name="تست", debt_list="تست", total=1000)
            reminder_config["text"] = new_text
            bot.send_message(chat_id, f"✅ متن یادآوری آپدیت شد:\n\n{new_text}")
        except KeyError as e:
            bot.send_message(
                chat_id,
                f"❌ متغیر اشتباه: {e}\n"
                f"فقط از {{first_name}}, {{debt_list}}, {{total}} استفاده کن."
            )
        admin_main_panel(chat_id)
 
 
def _force_send_reminders(bot, connection, admin_chat_id):
    try:
        local_cursor = connection.cursor()
        local_cursor.execute("""
            SELECT d.debtor_name, d.creditor_name, d.amount, g.chat_id
            FROM debts d
            LEFT JOIN gang g ON g.first_name || ' ' || g.last_name = d.debtor_name
            WHERE d.paid = 0
        """)
        unpaid = local_cursor.fetchall()
 
        debtor_map = {}
        for debtor_name, creditor_name, amount, chat_id in unpaid:
            if debtor_name not in debtor_map:
                debtor_map[debtor_name] = {"chat_id": chat_id, "debts": []}
            debtor_map[debtor_name]["debts"].append({"creditor": creditor_name, "amount": amount})
 
        sent = 0
        skipped = 0
        for debtor_name, data in debtor_map.items():
            cid = data["chat_id"]
            if not cid:
                skipped += 1
                continue
            debt_list = "\n".join(
                [f"🔴 {d['amount']:,} تومان به {d['creditor']}" for d in data["debts"]]
            )
            total = sum(d["amount"] for d in data["debts"])
            first_name = debtor_name.split()[0]
            msg = reminder_config["text"].format(
                first_name=first_name,
                debt_list=debt_list,
                total=total
            )
            try:
                bot.send_message(cid, msg)
                sent += 1
            except Exception as e:
                print(f"[ForceReminder] Failed for {debtor_name}: {e}")
                skipped += 1
 
        bot.send_message(
            admin_chat_id,
            f"📤 یادآوری ارسال شد.\n✅ موفق: {sent} نفر\n⚠️ بدون chat_id: {skipped} نفر"
        )
    except Exception as e:
        bot.send_message(admin_chat_id, f"❌ خطا: {e}")
        traceback.print_exc()