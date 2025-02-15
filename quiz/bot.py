import random
from asgiref.sync import sync_to_async
from django.conf import settings
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from quiz.models import Quiz, UserQuizAnswer, Question, Animal
from urllib.parse import quote


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Узнать моё тотемное животное", callback_data="start_quiz")]])
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
    return Quiz.objects.filter(is_active=True).first()


@sync_to_async
def cleanup_user_answers(user_id, quiz_id):
    UserQuizAnswer.objects.filter(telegram_user_id=user_id, quiz_id=quiz_id).delete()


@sync_to_async
def get_first_question(quiz):
    qq = quiz.quiz_questions.order_by("order").first()
    return qq.question if qq else None


@sync_to_async
def get_answers_for_question(question):
    return list(question.answers.all())


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
    current_qq = quiz.quiz_questions.filter(question=question).first()
    if not current_qq:
        return None

    next_qq = quiz.quiz_questions.filter(order__gt=current_qq.order).order_by("order").first()
    return next_qq.question if next_qq else None


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
    return Animal.objects.filter(id=chosen_id).first()


async def clear_current_question_message(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id: int = None):
    if message_id is None:
        message_id = context.user_data.get("current_question_message_id")
    if message_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=message_id)
        except BadRequest:
            pass
        context.user_data["current_question_message_id"] = None


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        quiz, question, previous_message_id=None):
    if previous_message_id:
        await clear_current_question_message(update, context, previous_message_id)
    answers = await get_answers_for_question(question)
    if not answers:
        await update.effective_message.reply_text("Ошибка: у вопроса нет вариантов ответа!")
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


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_current_question_message(update, context)
    quiz = await get_active_quiz()
    if not quiz:
        await update.message.reply_text("Нет активной викторины!")
        return

    await cleanup_user_answers(update.effective_user.id, quiz.id)
    question = await get_first_question(quiz)
    if not question:
        await update.message.reply_text("В викторине нет вопросов.")
        return

    await show_question(update, context, quiz, question)


async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clear_current_question_message(update, context)
    query = update.callback_query
    await query.answer()
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


async def get_result_markup(animal, context):
    bot_info = await context.bot.get_me()
    bot_url = f"https://t.me/{bot_info.username}"
    bot_url_encoded = quote(bot_url, safe='')
    share_text = f"Моё тотемное животное в Московском зоопарке – {animal.name}. Хочешь узнать своё?"
    share_text_encoded = quote(share_text, safe='')
    image_url_encoded = quote(animal.image_url, safe='')
    vk_share_url = f"https://vk.com/share.php?url={bot_url_encoded}&title={share_text_encoded}&image={image_url_encoded}"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Поделиться в VK", url=vk_share_url)],
        [InlineKeyboardButton("Попробовать ещё раз?", callback_data="start_quiz")]
    ])
    return markup


async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, quiz_id: int):
    query = update.callback_query
    animal = await calculate_result(user_id, quiz_id)
    if not animal:
        await query.message.reply_text("Мы не смогли определить ваше животное!")
    else:
        result_text = f"Твоё тотемное животное в Московском зоопарке – {animal.name}"
        markup = await get_result_markup(animal, context)
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=animal.image_url,
                                         caption=result_text, reply_markup=markup)
        except BadRequest:
            await query.message.reply_text(result_text, reply_markup=markup)
    await cleanup_user_answers(user_id, quiz_id)
    await clear_current_question_message(update, context)


async def process_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              quiz_id: int, question_id: int, answer_id: int):
    user_id = update.effective_user.id
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
    parsed = await parse_quiz_callback_data(data)
    if not parsed:
        return
    quiz_id, question_id, answer_id = parsed
    await process_quiz_answer(update, context, quiz_id, question_id, answer_id)


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("quiz", "Викторина"),
    ])


def run_bot():
    app = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^start_quiz$"))
    app.add_handler(CallbackQueryHandler(quiz_callback, pattern="^quiz:"))

    app.post_init = post_init

    app.run_polling()
