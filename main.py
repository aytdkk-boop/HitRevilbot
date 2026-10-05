# main.py
import asyncio
import logging
import traceback

import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, API_HOST, API_PORT
from handlers import router
from database import init_db, get_expired_keys_not_notified, mark_key_notified
from keyboards import close_inline

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("hitrevil")


# ===== ФОНОВАЯ ЗАДАЧА: УВЕДОМЛЕНИЕ ОБ ИСТЕЧЕНИИ =====
async def check_expired_keys(bot: Bot):
    """
    Каждые 10 секунд проверяем, не истёк ли у кого-то ключ.
    Отправляем уведомление ровно в момент истечения.
    """
    logger.info("🔍 Фоновая задача проверки ключей запущена")

    while True:
        try:
            await asyncio.sleep(10)

            try:
                expired = get_expired_keys_not_notified()
            except Exception as e:
                logger.error(f"❌ Ошибка в get_expired_keys_not_notified: {e}")
                traceback.print_exc()
                continue

            logger.info(f"🔍 Проверка ключей: найдено {len(expired)} истёкших")

            for item in expired:
                try:
                    key_value = item["key"]
                    logger.info(f"📤 Отправляем уведомление: chat_id={item['telegram_id']} key={key_value}")

                    text = (
                        f"<b>❗Ваш ключ {key_value} истек, "
                        f"для использования HITREVIL, необходимо получить ключ!</b>"
                    )

                    await bot.send_message(
                        chat_id=item["telegram_id"],
                        text=text,
                        reply_markup=close_inline(),
                        parse_mode="HTML",
                    )

                    mark_key_notified(item["id"])
                    logger.info(f"✅ Уведомление отправлено: chat_id={item['telegram_id']}")
                except Exception as e:
                    logger.error(f"⚠️ Не удалось уведомить {item['telegram_id']}: {e}")
                    traceback.print_exc()
                    mark_key_notified(item["id"])
        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой задаче: {e}")
            traceback.print_exc()


# ===== ЗАПУСК БОТА =====
async def run_bot():
    logger.info("🚀 Запуск бота...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Обёртка для безопасного запуска фоновой задачи
    async def safe_expired_checker():
        try:
            await check_expired_keys(bot)
        except Exception as e:
            logger.error(f"❌ check_expired_keys упала: {e}")
            traceback.print_exc()

    asyncio.create_task(safe_expired_checker())
    logger.info("✅ Фоновая задача создана")

    # Удаляем webhook на всякий случай
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook удалён")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось удалить webhook: {e}")

    logger.info("🤖 Бот начал polling")
    await dp.start_polling(bot)


# ===== ЗАПУСК API =====
async def run_api():
    logger.info(f"🌐 Запуск API на http://{API_HOST}:{API_PORT}")

    config = uvicorn.Config(
        "server:app",
        host=API_HOST,
        port=API_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


# ===== ГЛАВНАЯ =====
async def main():
    logger.info("=== HITREVIL bot starting ===")
    init_db()
    logger.info("✅ БД инициализирована")

    await asyncio.gather(
        run_bot(),
        run_api(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Остановлено")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        traceback.print_exc()