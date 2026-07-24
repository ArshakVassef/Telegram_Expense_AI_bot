import os
from dotenv import load_dotenv
from telebot import TeleBot
import sqlite3

load_dotenv()
TOKEN = os.getenv("TOKEN")
bot = TeleBot(token=TOKEN)



connection = sqlite3.connect('gang.db', check_same_thread=False)
cursor = connection.cursor()

create_table_query = """
CREATE TABLE IF NOT EXISTS gang(
    id integer primary key,
    first_name text,
    last_name text,
    nickname text,
    card_number text
);
"""

cursor.execute(create_table_query)
connection.commit()

def save(chat_id):
    
    insert_query = """
    INSERT OR REPLACE INTO gang (id, first_name, last_name, nickname, card_number)
    VALUES (?, ?, ?, ?, ?)
    """
    cursor.execute(insert_query, (
        chat_id,
        gang['first_name'],
        gang['last_name'],
        gang['nickname'],
        gang['card_number']
    ))
    connection.commit()




gang = {}

@bot.message_handler(func=lambda message: message.text.startswith('/'))
def cancel_command(message):
    command = message.text.split()[0]
    
    gang.clear()
    
    bot.clear_step_handler_by_chat_id(message.chat.id)

    if command == '/start':
        welcome(message)





@bot.message_handler(commands=['start'])
def welcome(message):
    gang['id'] = message.chat.id
    
    msg = bot.send_message(message.chat.id, 'نام(فارسی):')
    bot.register_next_step_handler(msg, get_first_name)

def get_first_name(message):
    gang['first_name'] = message.text

    msg = bot.send_message(message.chat.id, 'نام خانوادگی(فارسی):')
    bot.register_next_step_handler(msg, get_last_name)

def get_last_name(message):
    gang['last_name'] = message.text

    msg = bot.send_message(message.chat.id, 'ملقب به(فارسی):')
    bot.register_next_step_handler(msg, get_nickname)

def get_nickname(message):
    gang['nickname'] = message.text

    msg = bot.send_message(message.chat.id, 'شماره کارت(انگلیسی):')
    bot.register_next_step_handler(msg, get_card_number)

def get_card_number(message):
    text = message.text.strip()

    if text.startswith('/'):
        bot.send_message(message.chat.id, "❌ عملیات لغو شد")
        return

    if not text.isdigit():
        msg = bot.send_message(message.chat.id, "❌ شماره کارت فقط باید عدد باشه. دوباره بفرست:")
        bot.register_next_step_handler(msg, get_card_number)
        return

    if len(text) != 16:
        msg = bot.send_message(message.chat.id, "❌ شماره کارت باید ۱۶ رقم باشه. دوباره بفرست:")
        bot.register_next_step_handler(msg, get_card_number)
        return

    gang['card_number'] = message.text

    save(message.chat.id)
    
    bot.send_message(message.chat.id, 
f"""
✅ اطلاعات ثبت شد:
نام: {gang['first_name']}
نام خانوادگی: {gang['last_name']}
لقب: {gang['nickname']}
شماره کارت: {gang['card_number']}
"""
    )

    print(gang)



bot.infinity_polling(timeout=10, long_polling_timeout=5)




