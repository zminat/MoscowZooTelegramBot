import random
from asgiref.sync import sync_to_async, async_to_sync
from django.conf import settings
from django.core.cache import cache
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, \
    MessageHandler, filters
from quiz.models import Quiz, UserQuizAnswer, Question, Animal
from urllib.parse import quote
from .bot_logger import BotLogger

CACHE_TIMEOUT = 300
TELEGRAM_BASE_URL = "https://t.me/"
CONTACT, FEEDBACK = range(2)

logger = BotLogger('bot.log')


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.log_info(f"Пользователь {user.id} запустил команду /start")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Узнать моё тотемное животное", callback_data="start_quiz")]
    ])
    text = (
        "Добро пожаловать в бот Московского Зоопарка!\n\n"
        "С помощью нашей небольшой викторины мы постараемся определить, "
        "какое животное может стать твоим тотемным.\n\n"
        "Отвечай на вопросы и по итогам узнаешь, "
        "какой зверь ближе всего по характеру именно тебе!\n\n"
        "Чтобы начать, нажми на кнопку ниже."
    )
    await update.message.reply_text(text, reply_markup=markup)


@sync_to_async
def get_active_quiz():
    cache_key = "active_quiz"
    quiz = cache.get(cache_key)
    if quiz is None:
        quiz = Quiz.objects.filter(is_active=True).first()
        cache.set(cache_key, quiz, timeout=CACHE_TIMEOUT)
    return quiz


@sync_to_async
def cleanup_user_answers(user_id, quiz_id):
    UserQuizAnswer.objects.filter(telegram_user_id=user_id, quiz_id=quiz_id).delete()


@sync_to_async
def get_first_question(quiz):
    cache_key = f"first_question_{quiz.id}"
    first_question = cache.get(cache_key)
    if first_question is None:
        qq = quiz.quiz_questions.order_by("order").first()
        first_question = qq.question if qq else None
        cache.set(cache_key, first_question, timeout=CACHE_TIMEOUT)
    return first_question


@sync_to_async
def get_answers_for_question(question):
    cache_key = f"answers_for_question_{question.id}"
    answers = cache.get(cache_key)
    if answers is None:
        answers = list(question.answers.all())
        cache.set(cache_key, answers, timeout=CACHE_TIMEOUT)
    return answers


@sync_to_async
def store_user_answer(user_id, quiz_id, question_id, answer_id):
    return UserQuizAnswer.objects.create(
        telegram_user_id=user_id,
        quiz_id=quiz_id,
        question_id=question_id,
        answer_id=answer_id
    )


@sync_to_async
def get_next_question(quiz, question):
    cache_key = f"next_question_{quiz.id}_{question.id}"
    next_question = cache.get(cache_key)
    if next_question is not None:
        return next_question

    current_qq = quiz.quiz_questions.filter(question=question).first()
    if not current_qq:
        return None

    next_qq = quiz.quiz_questions.filter(order__gt=current_qq.order).order_by("order").first()
    next_question = next_qq.question if next_qq else None
    cache.set(cache_key, next_question, timeout=CACHE_TIMEOUT)
    return next_question


@sync_to_async
def get_animal_by_id(animal_id):
    cache_key = f"animal_{animal_id}"
    animal = cache.get(cache_key)
    if animal is None:
        animal = Animal.objects.filter(id=animal_id).first()
        cache.set(cache_key, animal, timeout=CACHE_TIMEOUT)
    return animal


@sync_to_async
def calculate_result(user_id, quiz_id):
    user_answers = UserQuizAnswer.objects.filter(telegram_user_id=user_id, quiz_id=quiz_id)
    if not user_answers.exists():
        return None

    counts = {}
    for ua in user_answers:
        for animal in ua.answer.animals.all():
            counts[animal.id] = counts.get(animal.id, 0) + 1

    if not counts:
        return None

    max_count = max(counts.values())
    max_ids: list[int] = [aid for aid, cnt in counts.items() if cnt == max_count]
    chosen_id = random.choice(max_ids)
    return async_to_sync(get_animal_by_id)(chosen_id)


async def clear_current_question_message(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id: int = None):
    if message_id is None:
        message_id = context.user_data.get("current_question_message_id")
    if message_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=message_id)
        except BadRequest as e:
            error_msg = f"Ошибка при удалении сообщения: {e}"
            logger.log_error(error_msg)
            await notify_admin_error(error_msg, context)
        context.user_data["current_question_message_id"] = None


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        quiz, question, previous_message_id=None):
    if previous_message_id:
        await clear_current_question_message(update, context, previous_message_id)
    answers = await get_answers_for_question(question)
    if not answers:
        await update.effective_message.reply_text("Ошибка: у вопроса нет вариантов ответа!")
        error_msg = f"Вопрос {question.id} не содержит ответов"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
        return

    keyboard = []
    row = []
    for i, ans in enumerate(answers, start=1):
        cb_data = f"quiz:{quiz.id}|{question.id}|{ans.id}"
        button = InlineKeyboardButton(ans.text, callback_data=cb_data)
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    markup = InlineKeyboardMarkup(keyboard)

    msg = await update.effective_message.reply_text(text=question.text, reply_markup=markup)
    context.user_data["current_question_message_id"] = msg.message_id
    logger.log_debug(f"Отправлен вопрос {question.id} пользователю {update.effective_user.id}")


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_current_question_message(update, context)
    quiz = await get_active_quiz()
    if not quiz:
        await update.message.reply_text("Нет активной викторины!")
        error_msg = "Попытка начать викторину, но активной викторины не найдено"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
        return

    await cleanup_user_answers(update.effective_user.id, quiz.id)
    question = await get_first_question(quiz)
    if not question:
        await update.message.reply_text("В викторине нет вопросов.")
        error_msg = f"В викторине {quiz.id} нет вопросов"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
        return

    logger.log_info(f"Пользователь {update.effective_user.id} начал викторину {quiz.id}")
    await show_question(update, context, quiz, question)


async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_current_question_message(update, context)
    query = update.callback_query
    await query.answer()
    logger.log_debug(f"Callback start_quiz получен от пользователя {update.effective_user.id}")
    await quiz_command(update, context)


async def parse_quiz_callback_data(data: str):
    if not data.startswith("quiz:"):
        return None
    payload = data[5:]
    try:
        quiz_id_str, question_id_str, answer_id_str = payload.split("|")
    except ValueError:
        return None
    return int(quiz_id_str), int(question_id_str), int(answer_id_str)


async def build_result_markup(animal, context):
    guardianship_url = settings.GUARDIANSHIP_URL
    animal_id = animal.id
    contact_guardianship_callback_data = f"contact_guardianship:{animal_id}"
    bot_info = await context.bot.get_me()
    bot_url = f"{TELEGRAM_BASE_URL}{bot_info.username}"
    bot_url_encoded = quote(bot_url, safe='')
    share_text = f"Моё тотемное животное в Московском зоопарке – {animal.name}. Хочешь узнать своё?"
    share_text_encoded = quote(share_text, safe='')
    image_url_encoded = quote(animal.image_url, safe='')
    vk_share_url = f"https://vk.com/share.php?url={bot_url_encoded}&title={share_text_encoded}&image={image_url_encoded}"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Узнать больше", url=guardianship_url)],
        [InlineKeyboardButton("Связаться по опеке", callback_data=contact_guardianship_callback_data)],
        [InlineKeyboardButton("Поделиться в VK", url=vk_share_url)],
        [InlineKeyboardButton("Попробовать ещё раз?", callback_data="start_quiz")]
    ])
    return markup


def build_guardianship_text(include_link: bool = True):
    message_start = "Если ты хочешь помочь в сохранении биоразнообразия Земли, то прими участие в программе"
    link_text = "«Клуб друзей зоопарка»"
    if include_link:
        guardianship_url = settings.GUARDIANSHIP_URL
        link_text = f"<a href='{guardianship_url}'>{link_text}</a>"
    return f"{message_start} {link_text}."


async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, quiz_id: int):
    query = update.callback_query
    animal = await calculate_result(user_id, quiz_id)
    if not animal:
        await query.message.reply_text("Мы не смогли определить ваше животное!")
        error_msg = f"Не удалось определить тотемное животное для пользователя {user_id} в викторине {quiz_id}"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
    else:
        result_text = (
                f"Твоё тотемное животное в Московском зоопарке – <a href='{animal.page_url}'>{animal.name}</a>.\n\n" +
                build_guardianship_text(False)
        )
        markup = await build_result_markup(animal, context)
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=animal.image_url, caption=result_text,
                                         reply_markup=markup, parse_mode="HTML")
        except BadRequest as e:
            error_msg = f"Ошибка отправки фото: {e}"
            logger.log_error(error_msg)
            await notify_admin_error(error_msg, context)
            await query.message.reply_text(result_text, reply_markup=markup, parse_mode="HTML")
        logger.log_info(f"Пользователю {user_id} определено тотемное животное: {animal.name}")
    await cleanup_user_answers(user_id, quiz_id)
    await clear_current_question_message(update, context)


async def process_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              quiz_id: int, question_id: int, answer_id: int):
    user_id = update.effective_user.id
    logger.log_info(f"Пользователь {user_id} ответил на вопрос {question_id} (ответ {answer_id}) в викторине {quiz_id}")
    await store_user_answer(user_id, quiz_id, question_id, answer_id)
    quiz = await sync_to_async(Quiz.objects.get)(pk=quiz_id)
    question = await sync_to_async(Question.objects.get)(pk=question_id)
    next_q = await get_next_question(quiz, question)
    if next_q:
        msg_id = context.user_data.get("current_question_message_id")
        await show_question(update, context, quiz, next_q, previous_message_id=msg_id)
    else:
        await end_quiz(update, context, user_id, quiz_id)


async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.log_debug(f"Получен quiz callback: {data} от пользователя {update.effective_user.id}")
    parsed = await parse_quiz_callback_data(data)
    if not parsed:
        error_msg = f"Ошибка разбора callback данных: {data}"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
        return
    quiz_id, question_id, answer_id = parsed
    await process_quiz_answer(update, context, quiz_id, question_id, answer_id)


async def guardianship_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = build_guardianship_text(True)
    await update.message.reply_text(text, parse_mode="HTML")
    logger.log_info(f"Пользователь {update.effective_user.id} запросил информацию по опеке")


async def build_user_profile_link(user):
    if user.username:
        link_url = f"{TELEGRAM_BASE_URL}{user.username}"
    else:
        link_url = f"tg://user?id={user.id}"
    return f'<a href="{link_url}">{link_url}</a>'


async def contact_guardianship_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data
    if data:
        animal_id = data[21:]
        context.user_data["contact_animal_id"] = animal_id
        logger.log_info(f"Пользователь {update.effective_user.id} запросил связь по опеке для животного {animal_id}")
    else:
        context.user_data["contact_animal_id"] = None
    await update.callback_query.message.reply_text(
        "Пожалуйста, введите сообщение для сотрудника зоопарка по опеке (или /cancel для отмены):"
    )
    return CONTACT


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Пожалуйста, введите сообщение для сотрудника зоопарка (или /cancel для отмены):")
    logger.log_info(f"Пользователь {update.effective_user.id} инициировал контакт через команду /contact")
    return CONTACT


async def cancel_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Сообщение для сотрудника зоопарка отменено.")
    logger.log_info(f"Пользователь {update.effective_user.id} отменил отправку сообщения для опеки")
    return ConversationHandler.END


async def receive_contact_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_link = await build_user_profile_link(user)
    contact_message = update.message.text
    animal_info = ""
    animal_id = context.user_data.get("contact_animal_id")
    if animal_id:
        animal = await get_animal_by_id(animal_id)
        animal_info = f"\n\nТотемное животное: {animal.name}."
    message_text = f"📞 Сообщение по опеке от {user_link}:{animal_info}\n\nСообщение:\n{contact_message}"
    admin_chat_id = settings.ADMIN_CHAT_ID
    if not admin_chat_id:
        await update.message.reply_text("Обратная связь не настроена.")
        error_msg = "ADMIN_CHAT_ID не настроен, сообщение не отправлено"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
    else:
        await context.bot.send_message(chat_id=admin_chat_id, text=message_text, parse_mode="HTML")
        await update.message.reply_text("Ваше сообщение отправлено сотруднику зоопарка!")
        logger.log_info(f"Пользователь {user.id} отправил сообщение для опеки")
    return ConversationHandler.END


async def process_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE, feedback_text: str):
    user = update.effective_user
    user_link = await build_user_profile_link(user)
    message_text = f"💬 Обратная связь от {user_link}:\n{feedback_text}"
    admin_chat_id = settings.ADMIN_CHAT_ID
    if not admin_chat_id:
        await update.message.reply_text("Обратная связь не настроена.")
        error_msg = "ADMIN_CHAT_ID не настроен для обработки обратной связи"
        logger.log_error(error_msg)
        await notify_admin_error(error_msg, context)
        return
    await context.bot.send_message(chat_id=admin_chat_id, text=message_text, parse_mode="HTML")
    await update.message.reply_text("Спасибо за вашу обратную связь!")
    logger.log_info(f"Получена обратная связь от пользователя {user.id}")


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        feedback_text = " ".join(context.args)
        await process_feedback(update, context, feedback_text)
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, введите текст обратной связи (или /cancel для отмены):")
        return FEEDBACK


async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback_text = update.message.text
    await process_feedback(update, context, feedback_text)
    return ConversationHandler.END


async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Обратная связь отменена.")
    logger.log_info(f"Пользователь {update.effective_user.id} отменил отправку обратной связи")
    return ConversationHandler.END


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("quiz", "Викторина"),
        BotCommand("guardianship", "Опекунство"),
        BotCommand("contact", "Связаться по опеке"),
        BotCommand("feedback", "Обратная связь"),
    ])
    logger.log_info("Бот инициализирован: команды установлены")


async def notify_admin_error(error_message: str, context: ContextTypes.DEFAULT_TYPE):
    admin_chat_id = settings.ADMIN_CHAT_ID
    if not admin_chat_id:
        logger.log_error("ADMIN_CHAT_ID не настроен для отправки оповещений.")
        return
    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=f"❗️ Оповещение об ошибке:\n{error_message}")
    except Exception as e:
        logger.log_error(f"Ошибка отправки оповещения админу: {e}")


def run_bot():
    app = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^start_quiz$"))
    app.add_handler(CallbackQueryHandler(quiz_callback, pattern="^quiz:"))
    app.add_handler(CommandHandler("guardianship", guardianship_command))

    contact_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(contact_guardianship_callback, pattern="^contact_guardianship:"),
            CommandHandler("contact", contact_command)
        ],
        states={
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_contact_message)]
        },
        fallbacks=[CommandHandler("cancel", cancel_contact)]
    )
    app.add_handler(contact_handler)

    feedback_handler = ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_command)],
        states={
            FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)]
        },
        fallbacks=[CommandHandler("cancel", cancel_feedback)]
    )
    app.add_handler(feedback_handler)

    app.post_init = post_init

    logger.log_info("Запуск бота")
    app.run_polling()
