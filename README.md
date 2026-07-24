# Telegram Expense & Debt Management Bot

An advanced, AI-powered Telegram bot and FastAPI backend built for groups to track shared expenses, split bills intelligently, process bank receipt SMS notifications, and automate debt reminders.

---

## Features

* **🤖 AI-Powered Natural Language Processing:** Powered by Ollama models to parse natural language text into structured expense data.
* **⚡ FastAPI Backend:** Handles calculations, API endpoints, and expense tracking logic.
* **💳 Bank Receipt Verification:** Automatically reads and matches Persian bank SMS and receipt texts to verify payments.
* **⏰ Automated Debt Reminders:** Customizable daily reminder system that notifies users of unpaid balances via Telegram.
* **👥 Multi-User Group Support:** Tracks participants, handles group splits versus individual splits, and computes optimized settlement plans.
* **🌐 Multilingual Support:** Interactive language selection supporting English and Farsi.

---

## Project Structure

```text
Telegram_Expense_AI_bot/
├── Recruitment/
│   └── Gang.py               # User registration and member database management
├── Refund/
│   ├── API.py                # FastAPI backend service for AI expense extraction and settlement calculation
│   ├── Debt_Manager.py       # Debt tracking, payment verification, reminders, and database handlers
│   └── main.py               # Main Telegram bot initialization, handlers, and dispatchers
├── Test/
│   └── Test.py               # A small test
├── .gitignore
├── LICENSE
├── README.md                  # Project documentation and setup guide
└── requirements.txt           # Project dependencies
```

---

## Prerequisites & Installation


1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   Create a `.env` file in the Refund directory with the following keys:
   ```env
   TOKEN=your_telegram_bot_token
   ADMIN_TELEGRAM_ID=your_admin_telegram_id
   OLLAMA_API_KEY=your_ollama_api_key
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_GPT_MODEL=your_gpt_model_name
   OLLAMA_DEEPSEEK_MODEL=your_deepseek_model_name
   ```

3. **Create the gang:**
   run Recruitment/gang.py, add members on telegram and when done, move the gang.db to Refund/
---

## Running the Application

1. **Start the FastAPI Backend Server:**
   ```bash
   fastapi dev api.py
   ```

2. **Run the Telegram Bot:**
   ```bash
   python main.py
   ```
