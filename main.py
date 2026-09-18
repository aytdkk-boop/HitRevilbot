# run_all.py
import asyncio
import logging
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.markdown import bold

from config import BOT_TOKEN, API_HOST, API_PORT
from handlers import router
from database import init_db, get_expired_keys_not_notified, mark_key_notified
from keyboards import close_inline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def run_bot():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    asyncio.create_task(check_expired_keys(bot))

    print("🤖 Бот запущен")
    await dp.start_polling(bot)


async def run_api():
    config = uvicorn.Config(
        "server:app",
        host=API_HOST,
        port=API_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    print(f"🌐 API запущен на http://{API_HOST}:{API_PORT}")
    await server.serve()


async def check_expired_keys(bot: Bot):
    while True:
        try:
            await asyncio.sleep(60)
            expired = get_expired_keys_not_notified()
            for item in expired:
                try:
                    text = bold(f"❗ Ваш ключ {item['key']} больше недействителен!")
                    await bot.send_message(
                        chat_id=item["telegram_id"],
                        text=text,
                        reply_markup=close_inline(),
                        parse_mode="HTML",
                    )
                    mark_key_notified(item["id"])
                except Exception as e:
                    print(f"⚠️ Не удалось уведомить {item['telegram_id']}: {e}")
                    mark_key_notified(item["id"])
        except Exception as e:
            print(f"Ошибка в фоновой задаче: {e}")


async def main():
    init_db()
    await asyncio.gather(run_bot(), run_api())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 Остановлено")