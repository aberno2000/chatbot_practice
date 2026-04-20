import asyncio
from aiogram import Bot, Dispatcher

from config import API_TOKEN
from database import create_tables
from handlers import register_handlers

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

async def main():
    await create_tables()
    register_handlers(dp)
    print("Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
