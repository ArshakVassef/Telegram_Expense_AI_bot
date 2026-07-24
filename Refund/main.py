from debt_manager import register_debt_handlers, init_db, start_reminder_thread, save_debts_to_db
import os
import uuid
import requests
import sqlite3
from telebot import TeleBot, types
from ollama import Client
from dotenv import load_dotenv
from ddgs import DDGS

load_dotenv()

# waking up the bot
bot = TeleBot(token=os.getenv("TOKEN"))

#waking up the database
connection = sqlite3.connect('gang.db', check_same_thread=False)
cursor = connection.cursor()

init_db(connection)
register_debt_handlers(bot, connection, cursor)

# 🧠 Session Storage to allow multiple groups to use the bot concurrently
sessions = {}

def get_session(chat_id):
    if chat_id not in sessions:
        sessions[chat_id] = {
            'language': 'English',
            'user_selections': [],
            'all_expenses': [],
            'current_expense': {}
        }
    return sessions[chat_id]

def main():
    en_button = types.InlineKeyboardButton(text="English", callback_data="en_button")
    fas_button = types.InlineKeyboardButton(text="Farsi", callback_data="far_button")
    inline_keyboard = types.InlineKeyboardMarkup()
    inline_keyboard.add(en_button, fas_button)
    return inline_keyboard

################################################################# 
####                         Start                            ###
################################################################# 

@bot.message_handler(commands=['start'])
def starter(message):
    chat_id = message.chat.id
    c = connection.cursor()
    c.execute("SELECT first_name, last_name FROM gang WHERE chat_id=?", (chat_id,))
    member = c.fetchone()

    if member:
        bot.send_message(chat_id, f"✅ خوش اومدی {member[0]}! یادآوری بدهی‌هات فعاله.")
    else:
        bot.send_message(chat_id, "⚠️ حسابت ثبت نشده. از /register استفاده کن.")

    bot.send_message(chat_id, 'choose a language: :زبان را انتخاب کن', reply_markup=main())
    
@bot.callback_query_handler(func=lambda call: call.data in ['en_button', 'far_button'])
def check_button(call):
    session = get_session(call.message.chat.id)
    if call.data == 'en_button':
        session['language'] = 'English'
        bot.answer_callback_query(call.id, "English")
        bot.edit_message_text("language is set on <b>English</b>", 
                              call.message.chat.id, call.message.message_id, 
                              reply_markup=None, parse_mode="HTML")
        bot.send_message(call.message.chat.id, 'Hello👋. How may I help you today?')
    elif call.data == 'far_button':
        session['language'] = 'Farsi'
        bot.answer_callback_query(call.id, "Farsi")
        bot.edit_message_text("زبان <b>فارسی</b> انتخاب شد", 
                              call.message.chat.id, call.message.message_id, 
                              reply_markup=None, parse_mode="HTML")
        bot.send_message(call.message.chat.id, 'سلام👋. امروز چه کمکی ازم ساختس؟')

################################################################# 
####                         Search                           ###
################################################################# 

@bot.message_handler(commands=['search'])
def searcher(message):
    session = get_session(message.chat.id)
    msg = bot.send_message(message.chat.id, translate('Tell me what you want to know: ', 'English', session['language']))
    bot.register_next_step_handler(msg, process_LLM)
    
def process_LLM(message):
    session = get_session(message.chat.id)
    if not message.text:
        bot.send_message(message.chat.id, translate('Please send a text message.', 'English', session['language']))
        return
    if message.text.startswith('/'):
        bot.send_message(message.chat.id, translate('Process Terminated!!!', 'English', session['language']))
        return
    LLM(message, session['language']) 

################################################################# 
####                 personalized translator                  ###
################################################################# 

def translate(text, from_language='English', to_language='Farsi'):
    if from_language == to_language:
        return text
    API_KEY = os.getenv("OLLAMA_API_KEY")
    TranslatorModel = os.getenv("OLLAMA_DEEPSEEK_MODEL")

    client = Client(
        host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        headers={"Authorization": f"Bearer {API_KEY}"}
    )
    response = client.chat(
        model=TranslatorModel,
        messages=[
            {
                "role": "system", 
                "content" : f"You are a professional translator who translates {from_language} to fluent {to_language}. Use natural, clear translation with proper punctuation."
            },
            {
                "role":"user", 
                "content" : f"Translate this text to {to_language}:\n\n{text}"
            }
        ]
    )

    return response.message.content

################################################################# 
####                          mammad                          ###
################################################################# 

def get_all_members():
    cursor.execute("SELECT id, nickname, first_name, last_name FROM gang")
    return cursor.fetchall()

def get_name_by_id(m_id):
    cursor.execute("SELECT first_name, last_name FROM gang WHERE id=?", (m_id,))
    info = cursor.fetchone()
    return f"{info[0]} {info[1]}" if info else "Unknown"

def create_selection_markup(chat_id, selected_ids, is_for_all):
    session = get_session(chat_id)
    markup = types.InlineKeyboardMarkup()
    if is_for_all:
        members = get_all_members()
        id_fullname_list = [(str(m[0]), f"{m[2]} {m[3]}") for m in members]
    else:
        id_fullname_list = [(str(m_id), get_name_by_id(m_id)) for m_id in session['user_selections']]

    for m_id, full_name in id_fullname_list:
        status = " ✅" if str(m_id) in selected_ids else ""
        markup.add(types.InlineKeyboardButton(text=f"{full_name}{status}", callback_data=f"toggle_{m_id}"))
    
    label = "✅ تایید نهایی لیست" if not is_for_all else "📥 ثبت لیست اعضای کل"
    callback = "confirm_participants" if not is_for_all else "final_submit"
    markup.add(types.InlineKeyboardButton(text=label, callback_data=callback))
    return markup

def create_individual_markup(chat_id, individual_data):
    session = get_session(chat_id)
    markup = types.InlineKeyboardMarkup()
    total = sum(individual_data.values())
    for m_id in session['user_selections']:
        full_name = get_name_by_id(m_id)
        amount = individual_data.get(str(m_id), 0)
        status = f" 💰 {amount:,}" if amount > 0 else " ➖"
        markup.add(types.InlineKeyboardButton(text=f"{full_name}{status}", callback_data=f"set_indiv_{m_id}"))
    
    markup.add(types.InlineKeyboardButton(text=f"✅ مرحله بعد (مجموع: {total:,})", callback_data="confirm_individual_total"))
    return markup

def create_payer_markup(chat_id):
    session = get_session(chat_id)
    markup = types.InlineKeyboardMarkup()
    for m_id in session['user_selections']:
        full_name = get_name_by_id(m_id)
        markup.add(types.InlineKeyboardButton(text=f"👤 {full_name}", callback_data=f"set_payer_{m_id}"))
    return markup

def main_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="➕ اضافه کردن خرج جدید", callback_data="add_spender"))
    markup.add(types.InlineKeyboardButton(text="🔚 اتمام و محاسبه دنگ‌ها", callback_data="calculate_total"))
    return markup

_DEBT_MANAGER_CALLBACKS = {'confirm_reg', 'cancel_reg'}
_DEBT_MANAGER_PREFIXES = ('adm_',)

@bot.callback_query_handler(func=lambda call: (
    call.data not in ['en_button', 'far_button'] and
    call.data not in _DEBT_MANAGER_CALLBACKS and
    not any(call.data.startswith(p) for p in _DEBT_MANAGER_PREFIXES)
))
def callback_query(call):
    chat_id = call.message.chat.id
    session = get_session(chat_id)

    if call.data.startswith("toggle_"):
        m_id = call.data.split("_")[1]
        if "حضور دارند" in call.message.text:
            if m_id in session['user_selections']: 
                session['user_selections'].remove(m_id)
            else: 
                session['user_selections'].append(m_id)
            markup = create_selection_markup(chat_id, session['user_selections'], is_for_all=True)
        else: 
            if 'temp_participants' not in session['current_expense']: 
                session['current_expense']['temp_participants'] = []
            if m_id in session['current_expense']['temp_participants']: 
                session['current_expense']['temp_participants'].remove(m_id)
            else: 
                session['current_expense']['temp_participants'].append(m_id)
            markup = create_selection_markup(chat_id, session['current_expense']['temp_participants'], is_for_all=False)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)

    elif call.data == "final_submit":
        if not session['user_selections']:
            bot.answer_callback_query(call.id, "❌ کسی انتخاب نشده!")
            return
        bot.edit_message_text(f"📍 حاضرین ({len(session['user_selections'])} نفر) تایید شدند.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "حالا خرج‌ها را وارد کنید:", reply_markup=main_menu())

    elif call.data == "add_spender":
        session['current_expense'] = {'description': '', 'type': '', 'amount': 0, 'individual_amounts': {}, 'temp_participants': []}
        msg = bot.send_message(chat_id, "📝 بابت چیه؟ (مثلاً رستوران)")
        bot.register_next_step_handler(msg, get_description)

    elif call.data == "type_group":
        session['current_expense']['type'] = 'group'
        msg = bot.send_message(chat_id, "💰 مبلغ کل هزینه:")
        bot.register_next_step_handler(msg, get_amount_group)

    elif call.data == "type_individual":
        session['current_expense']['type'] = 'individual'
        bot.send_message(chat_id, "سهم هر نفر را وارد کنید (مبلغ فاکتور):", reply_markup=create_individual_markup(chat_id, {}))

    elif call.data.startswith("set_indiv_"):
        u_id = call.data.split("_")[2]
        q_msg = bot.send_message(chat_id, f"سهم {get_name_by_id(u_id)}:")
        bot.register_next_step_handler(q_msg, save_individual_amount, u_id, call.message.message_id, q_msg.message_id)

    elif call.data == "confirm_individual_total":
        session['current_expense']['amount'] = sum(session['current_expense']['individual_amounts'].values())
        bot.send_message(chat_id, "👤 چه کسی پرداخت کرده؟", reply_markup=create_payer_markup(chat_id))

    elif call.data.startswith("set_payer_"):
        session['current_expense']['payer_id'] = call.data.split("_")[2]
        if session['current_expense']['type'] == 'group':
            bot.send_message(chat_id, f"چه کسانی در {session['current_expense']['description']} سهم دارند؟", reply_markup=create_selection_markup(chat_id, [], False))
        else:
            session['current_expense']['participants'] = list(session['current_expense']['individual_amounts'].keys())
            session['all_expenses'].append(session['current_expense'].copy())
            bot.send_message(chat_id, f"✅ هزینه '{session['current_expense']['description']}' ثبت شد.", reply_markup=main_menu())

    elif call.data == "confirm_participants":
        if not session['current_expense'].get('temp_participants'):
            bot.answer_callback_query(call.id, "❌ حداقل یک نفر را انتخاب کنید")
            return
        session['current_expense']['participants'] = list(session['current_expense']['temp_participants'])
        session['all_expenses'].append(session['current_expense'].copy())
        bot.send_message(chat_id, f"✅ هزینه '{session['current_expense']['description']}' ثبت شد.", reply_markup=main_menu())

    elif call.data == "calculate_total":
        show_final_results(chat_id)
        
    elif call.data == "smart_add":
        msg = bot.send_message(chat_id, "📝 هزینه بعدی را بنویس:")
        bot.register_next_step_handler(msg, process_smart_expense)

    elif call.data == "smart_calculate":
        process_smart_calculate(chat_id, call.message.message_id)

@bot.message_handler(commands=['mammad'])
def start_process(message):
    session = get_session(message.chat.id)
    session['user_selections'], session['all_expenses'] = [], []
    bot.send_message(message.chat.id, "چه کسانی حضور دارند؟ 👥", reply_markup=create_selection_markup(message.chat.id, [], True))

def get_description(message):
    session = get_session(message.chat.id)
    if not message.text:
        bot.send_message(message.chat.id, "لطفاً متن بفرستید.")
        return
    session['current_expense']['description'] = message.text
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👥 جمعی (تقسیم مساوی)", callback_data="type_group"), 
               types.InlineKeyboardButton("👤 تکی (هرکس سهم خودش)", callback_data="type_individual"))
    bot.send_message(message.chat.id, "نوع تقسیم هزینه:", reply_markup=markup)

def get_amount_group(message):
    session = get_session(message.chat.id)
    try:
        amount = int(message.text.replace(',', '').strip())
        if amount <= 0:
            raise ValueError("Amount must be positive")
        session['current_expense']['amount'] = amount
        bot.send_message(message.chat.id, "👤 چه کسی پرداخت کرده؟", reply_markup=create_payer_markup(message.chat.id))
    except (ValueError, AttributeError):
        bot.send_message(message.chat.id, "❌ عدد معتبر وارد کنید (مثلاً: 150000)")
        msg = bot.send_message(message.chat.id, "💰 مبلغ کل هزینه:")
        bot.register_next_step_handler(msg, get_amount_group)
    
def save_individual_amount(message, u_id, list_msg_id, q_id):
    session = get_session(message.chat.id)
    try: bot.delete_message(message.chat.id, q_id)
    except: pass
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    
    try:
        amount = int(message.text.replace(',', '').strip())
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        session['current_expense']['individual_amounts'][u_id] = amount
        bot.edit_message_reply_markup(message.chat.id, list_msg_id, reply_markup=create_individual_markup(message.chat.id, session['current_expense']['individual_amounts']))
    except (ValueError, AttributeError):
        err_msg = bot.send_message(message.chat.id, f"❌ عدد معتبر وارد کنید. سهم {get_name_by_id(u_id)}:")
        bot.register_next_step_handler(err_msg, save_individual_amount, u_id, list_msg_id, err_msg.message_id)

def show_final_results(chat_id):
    session = get_session(chat_id)
    balances = {get_name_by_id(m_id): 0 for m_id in session['user_selections']}
    report = "📊 **جزئیات هزینه‌ها:**\n"
    
    for exp in session['all_expenses']:
        payer_name = get_name_by_id(exp['payer_id'])
        net_total = exp['amount']
        balances[payer_name] = balances.get(payer_name, 0) + net_total
        
        if exp['type'] == 'group':
            p_ids = exp['participants']
            if not p_ids:
                continue
            share_per_person = net_total / len(p_ids)
            for p_id in p_ids:
                name = get_name_by_id(p_id)
                balances[name] = balances.get(name, 0) - share_per_person
            report += f"🔹 {exp['description']}: {net_total:,} (پرداخت: {payer_name})\n"
        else:
            indiv_list = []
            for u_id, u_amt in exp['individual_amounts'].items():
                name = get_name_by_id(u_id)
                balances[name] = balances.get(name, 0) - u_amt
                indiv_list.append(f"{name}: {int(u_amt):,}")
            report += f"🔸 {exp['description']}: {net_total:,} (پرداخت: {payer_name})\n   [ { ' | '.join(indiv_list) } ]\n"

    report += "\n💰 **وضعیت نهایی (طلب/بدهی):**\n"
    for p, b in balances.items():
        emoji = "🟢 " if b > 1 else "🔴 " if b < -1 else "⚪️ "
        report += f"{emoji}{p}: {abs(int(b)):,}\n"

    debtors = [{'name': p, 'amount': abs(b)} for p, b in balances.items() if b < -1]
    creditors = [{'name': p, 'amount': b} for p, b in balances.items() if b > 1]

    # Sort for fewer transactions
    debtors.sort(key=lambda x: x['amount'], reverse=True)
    creditors.sort(key=lambda x: x['amount'], reverse=True)
    
    plan = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        settle = min(debtors[i]['amount'], creditors[j]['amount'])
        # FIX Bug 1: debtor pays creditor (was reversed)
        plan.append(f"👤 {debtors[i]['name']} ➡️ {int(settle):,} تومان ➡️ {creditors[j]['name']}")
        debtors[i]['amount'] -= settle
        creditors[j]['amount'] -= settle
        if debtors[i]['amount'] <= 1: i += 1
        if creditors[j]['amount'] <= 1: j += 1

    bot.send_message(chat_id, report + "\n🏁 **نحوه تسویه حساب:**\n" + ("\n".join(plan) if plan else "همه حساب‌ها صاف است! ✅"), parse_mode="Markdown")

################################################################# 
####                          LLM                             ###
################################################################# 

def LLM(tel_message, language='English'):
    API_KEY = os.getenv("OLLAMA_API_KEY")
    SummarizerModel = os.getenv("OLLAMA_GPT_MODEL")
    TranslatorModel = os.getenv("OLLAMA_DEEPSEEK_MODEL")

    client = Client(
        host=os.getenv("OLLAMA_HOST", "http://localhost:11434"), 
        headers={"Authorization": f"Bearer {API_KEY}"}
    )

    status = bot.send_message(tel_message.chat.id, '🔎 searching...')
    
    def search(topic, num_results=3):
        results = []
        with DDGS() as ddgs:
            for out in ddgs.text(topic, max_results=num_results):
                results.append(f"Title: {out['title']}\nURL: {out['href']}\nSnippet: {out['body']}\n")
        bot.edit_message_text("📝 Summarizing...", tel_message.chat.id, status.message_id)
        return "\n".join(results)

    def summarize(text):
        response = client.chat(
            model=SummarizerModel,
            messages=[
                {"role": "system", "content": "You are a professional summarizer. Summarize text clearly in fluent English under 150 words."},
                {"role": "user", "content": f"Please summarize the following texts:\n\n{text}"}
            ]
        )
        print('summarize done')
        return response.message.content

    def translate_summary(english_text):
        bot.edit_message_text("💬 Translating...", tel_message.chat.id, status.message_id)
        response = client.chat(
            model=TranslatorModel,
            messages=[
                {"role": "system", "content": "You are a professional translator who translates English to fluent Persian. Limit to 150 words."},
                {"role": "user", "content": f"Translate this text to Persian:\n\n{english_text}"}
            ]
        )
        return response.message.content

    topic = tel_message.text
    search_results = search(topic)
    summary = summarize(search_results)
    
    output = translate_summary(summary) if language == 'Farsi' else summary
    bot.edit_message_text(output, tel_message.chat.id, status.message_id)



################################################################# 
####                 AI Smart Spender (API Client)            ###
################################################################# 

def smart_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ افزودن هزینه جدید", callback_data="smart_add"))
    markup.add(types.InlineKeyboardButton("🏁 محاسبه و تسویه نهایی", callback_data="smart_calculate"))
    return markup

@bot.message_handler(commands=['smart'])
def smart_expense_starter(message):
    session = get_session(message.chat.id)
    session['smart_expenses'] = []
    session['smart_members'] = []

    members = get_all_members()
    session['smart_members'] = [f"{m[2]} {m[3]}" for m in members]

    bot.send_message(
        message.chat.id,
        "🤖 حالت هوشمند فعال شد!\nهزینه اول را به زبان ساده بنویس:",
    )
    msg = bot.send_message(message.chat.id, "📝 مثال: دیشب 2 میلیون تومن پول شهربازیرو ارشاک حساب کرد، ارشاک و بهراد و نیما و رهام بودیم")
    bot.register_next_step_handler(msg, process_smart_expense)


def process_smart_expense(message):
    chat_id = message.chat.id
    session = get_session(chat_id)

    # FIX Bug 5: guard non-text
    if not message.text:
        bot.send_message(chat_id, "لطفاً متن بفرستید.")
        return

    text = message.text
    if text.startswith('/'):
        bot.send_message(chat_id, "عملیات لغو شد.")
        return

    status = bot.send_message(chat_id, "🧠 در حال تحلیل متن...")

    payload = {
        "text": text,
        "available_members": session['smart_members']
    }

    try:
        api_response = requests.post(
            "http://127.0.0.1:8000/api/v1/extract-expense", json=payload, timeout=30
        )

        if api_response.status_code == 200:
            expense_data = api_response.json()
            session['smart_expenses'].append(expense_data)

            result_msg = (
                f"✅ هزینه شماره {len(session['smart_expenses'])} ثبت شد:\n\n"
                f"📝 بابت: {expense_data.get('description')}\n"
                f"💰 مبلغ: {expense_data.get('total_amount', 0):,} تومان\n"
                f"👤 پرداخت‌کننده: {expense_data.get('payer')}\n"
                f"👥 سهام‌داران: {', '.join(expense_data.get('participants', []))}\n"
            )
            bot.edit_message_text(result_msg, chat_id, status.message_id)
            bot.send_message(chat_id, "چیکار کنیم؟", reply_markup=smart_menu())

        else:
            bot.edit_message_text(
                f"❌ خطا از سرور: {api_response.status_code}\n{api_response.text}",
                chat_id, status.message_id
            )

    except requests.exceptions.ConnectionError:
        bot.edit_message_text(
            "🔌 سرور FastAPI خاموش است! لطفا ابتدا سرور را روشن کنید.",
            chat_id, status.message_id
        )
    except requests.exceptions.Timeout:
        bot.edit_message_text("⏱ سرور پاسخ نداد. دوباره تلاش کنید.", chat_id, status.message_id)


def process_smart_calculate(chat_id, edit_msg_id=None):
    session = get_session(chat_id)

    if not session.get('smart_expenses'):
        bot.send_message(chat_id, "❌ هیچ هزینه‌ای ثبت نشده!")
        return

    status = bot.send_message(chat_id, "⚙️ در حال محاسبه...")

    payload = {
        "expenses": session['smart_expenses'],
        "all_members": session['smart_members']
    }

    try:
        api_response = requests.post(
            "http://127.0.0.1:8000/api/v1/calculate", json=payload, timeout=30
        )

        if api_response.status_code == 200:
            result = api_response.json()

            report = "📊 *جزئیات هزینه‌ها:*\n"
            for line in result.get("report", []):
                report += f"{line}\n"

            report += "\n💰 *وضعیت نهایی (طلب/بدهی):*\n"
            for name, balance in result["balances"].items():
                if balance > 1:
                    emoji = "🟢"
                elif balance < -1:
                    emoji = "🔴"
                else:
                    emoji = "⚪️"
                report += f"{emoji} {name}: {abs(balance):,}\n"

            report += "\n🏁 *نحوه تسویه حساب:*\n"
            plan = result.get("settlement_plan", [])
            if plan:
                for step in plan:
                    report += f"👤 {step['to']} ➡️ {step['amount']:,} تومان ➡️ {step['from']}\n"
            else:
                report += "همه حساب‌ها صاف است! ✅"

            bot.edit_message_text(
                report,
                chat_id,
                status.message_id,
                parse_mode="Markdown"
            )

            session_id = str(uuid.uuid4())
            save_debts_to_db(cursor, connection, session_id, result.get("settlement_plan", []))
            bot.send_message(chat_id, "💾 بدهی‌ها ذخیره شدن.\nهر بدهکار باید /register بزنه تا یادآوری دریافت کنه.")

        else:
            bot.edit_message_text(
                f"❌ خطا: {api_response.status_code}\n{api_response.text}",
                chat_id,
                status.message_id
            )

    except requests.exceptions.ConnectionError:
        bot.edit_message_text(
            "🔌 سرور FastAPI خاموش است!", chat_id, status.message_id
        )
    except requests.exceptions.Timeout:
        bot.edit_message_text("⏱ سرور پاسخ نداد. دوباره تلاش کنید.", chat_id, status.message_id)


start_reminder_thread(bot, connection)

bot.infinity_polling(timeout=10, long_polling_timeout=5)