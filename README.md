# Moscow Zoo Telegram Bot

This project is a Django-based Telegram chatbot for determining a user's "totem animal" using a quiz. It includes a web interface (via Django admin) for editing quiz questions and downloading log files, and a Telegram bot for interacting with users.

## Requirements

- Python 3.9+
- Other dependencies as listed in `requirements.txt`

## Installation

1. **Install Required Packages**

   Run the following command to install all dependencies from requirements.txt:
```bash
   pip install -r requirements.txt
```

2. **Configure Settings**

   Open the config/settings.py file and set the following parameters:

    - TELEGRAM_TOKEN: Your Telegram bot token.
    - ADMIN_CHAT_ID: Your Telegram admin chat ID.

## Running the Project

- **Django Server**

  To run the Django server (for editing questions and downloading logs via the Django admin), execute:
```bash
  python manage.py runserver
```
- **Telegram Bot**

  To start the Telegram bot, run:
```bash
  python manage.py runbot
```