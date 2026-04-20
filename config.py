import os
from dotenv import load_dotenv
import logging

load_dotenv()

API_TOKEN = str(os.getenv("BOT_TOKEN"))
DB_NAME = "quiz_bot.db"

logging.basicConfig(level=logging.DEBUG)
