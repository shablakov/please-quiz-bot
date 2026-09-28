import asyncio
import json
import logging
import os
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

TEAM_NAME = 'Леди и Жиробасы'
FEEDBACK_FILE = 'feedback.json'

def load_questions():
    if os.path.exists('questions.json'):
        with open('questions.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            cleaned_data = []
            for q in data:
                cleaned_q = {}
                for k, v in q.items():
                    clean_k = k.strip()
                    if isinstance(v, str):
                        cleaned_q[clean_k] = v.strip()
                    else:
                        cleaned_q[clean_k] = v
                cleaned_data.append(cleaned_q)
            return cleaned_data
    return []

def load_feedback():
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_feedback(data):
    with open(FEEDBACK_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

QUESTIONS_DB = load_questions()
games = {}

def get_categories():
    categories = set(q.get('category', 'Разнобой') for q in QUESTIONS_DB)
    return sorted(list(categories))

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f'👋 Привет, команда «{TEAM_NAME}»!\n\n'
        f'Я идеальный тренажер для Please Quiz.\n'
        f'📊 В базе: {len(QUESTIONS_DB)} вопросов (включая аудио и картинки!).\n\n'
        '📌 **Команды:**\n'
        '• `/quiz` — начать новую тренировку\n'
        '• `/stop` — остановить игру\n'
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🚀 Запустить тренировку", callback_data="init_game")]]
    await update.message.reply_text(
        f"🎯 Команда «{TEAM_NAME}», готовы к тренировке?\n\n"
        f"Нажмите кнопку ниже, чтобы начать!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def init_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    initiator = user.full_name
    
    categories = get_categories()
    keyboard = [[InlineKeyboardButton('🎲 Все категории (Микс)', callback_data='cat_ALL')]]
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(f'📁 {cat}', callback_data=f'cat_{cat}'))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        f"👤 **Игру запустил:** {initiator}\n\n"
        f"🎯 Выберите тематику:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    cat_data = query.data.replace('cat_', '')
    initiator_name = query.from_user.full_name

    if cat_data == 'ALL':
        selected_questions = QUESTIONS_DB.copy()
        cat_name = 'Все категории (Микс)'
    else:
        selected_questions = [q for q in QUESTIONS_DB if q.get('category') == cat_data]
        cat_name = cat_data

    if not selected_questions:
        await query.edit_message_text('❌ В этой категории пока нет вопросов!')
        return

    random.shuffle(selected_questions)
    games[chat_id] = {
        'status': 'active',
        'category': cat_name,
        'questions': selected_questions,
        'current_idx': 0,
        'score': 0,
        'state': 'waiting_answer',
        'timer_task': None,
        'initiator': initiator_name
    }

    await query.edit_message_text(
        f'✅ **Тематика:** {cat_name}\n'
        f'📊 **Вопросов:** {len(selected_questions)}\n\n'
        '🚀 Начинаем через 2 секунды...',
        parse_mode='Markdown',
    )
    await asyncio.sleep(2)
    await send_question(chat_id, context)

async def send_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = games.get(chat_id)
    if not game or game['status'] != 'active':
        return

    idx = game['current_idx']
    total = len(game['questions'])
    if idx >= total:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f'🏁 **Тренировка окончена!**\n\n'
                f'👤 **Капитан игры:** {game.get("initiator", "Неизвестен")}\n'
                f'🏆 Команда «{TEAM_NAME}» набрала: **{game["score"]}** из {total}!\n'
                'Запустить новую: `/quiz`'
            ),
            parse_mode='Markdown',
        )
        game['status'] = 'idle'
        return

    q = game['questions'][idx]
    game['state'] = 'waiting_answer'

    keyboard = []
    if q.get('type') == 'closed' and 'options' in q:
        opt_row = []
        for opt in q['options']:
            opt_letter = opt.split(')')[0].strip()
            opt_row.append(InlineKeyboardButton(opt, callback_data=f'opt_{opt_letter}'))
            if len(opt_row) == 2:
                keyboard.append(opt_row)
                opt_row = []
        if opt_row:
            keyboard.append(opt_row)

    keyboard.append([
        InlineKeyboardButton('💡 Подсказка', callback_data='action_hint'),
        InlineKeyboardButton('🔔 Вскрыть', callback_data='action_reveal'),
    ])

    q_type_badge = '🔘 Закрытый' if q.get('type') == 'closed' else '💬 Открытый'
    options_text = '\n\n' + '\n'.join(q['options']) if q.get('options') else ''

    msg_text = (
        f'❓ **Вопрос №{idx + 1} / {total}**\n'
        f'📂 [{q.get("category", "Разнобой")}] • {q_type_badge}\n\n'
        f'{q["question"]}'
        f'{options_text}\n\n'
        f'⏱ **Время:** {q.get("time_limit", 45)} сек'
    )

    # 🖼 Отправка картинки
    if q.get('image_url'):
        try:
            await context.bot.send_photo(chat_id=chat_id, photo=q['image_url'])
        except Exception as e:
            logging.warning(f"Не удалось загрузить картинку: {e}")
            
    # 🎧 Отправка аудио
    if q.get('audio_url'):
        try:
            await context.bot.send_audio(
                chat_id=chat_id, 
                audio=q['audio_url'], 
                title="🎧 Аудио-вопрос",
                caption="🎧 Включаем аудио!"
            )
        except Exception as e:
            logging.warning(f"Не удалось загрузить аудио: {e}")

    await context.bot.send_message(
        chat_id=chat_id,
        text=msg_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown',
    )

    if game.get('timer_task'):
        game['timer_task'].cancel()
    game['timer_task'] = asyncio.create_task(
        question_timer(chat_id, context, q.get('time_limit', 45), idx)
    )

async def question_timer(chat_id: int, context: ContextTypes.DEFAULT_TYPE, seconds: int, q_idx: int):
    try:
        if seconds > 10:
            await asyncio.sleep(seconds - 10)
            game = games.get(chat_id)
            if game and game['status'] == 'active' and game['current_idx'] == q_idx and game['state'] == 'waiting_answer':
                await context.bot.send_message(chat_id=chat_id, text='⏳ Осталось 10 секунд!')
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(seconds)
            
        game = games.get(chat_id)
        if game and game['status'] == 'active' and game['current_idx'] == q_idx and game['state'] == 'waiting_answer':
            await context.bot.send_message(chat_id=chat_id, text='🔔 **Время вышло!**')
            await reveal_answer(chat_id, context)
    except asyncio.CancelledError:
        pass

async def reveal_answer(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = games.get(chat_id)
    if not game or game['status'] == 'idle':
        return

    game['state'] = 'showing_answer'
    q = game['questions'][game['current_idx']]
    q_id = str(q.get('id', 'unknown'))
    
    keyboard = [
        [
            InlineKeyboardButton('✅ Засчитать (+1)', callback_data='score_yes'),
            InlineKeyboardButton('❌ Не взяли (0)', callback_data='score_no'),
        ],
        [
            InlineKeyboardButton('👍 Огонь!', callback_data=f'rate_{q_id}_up'),
            InlineKeyboardButton('👎 Выкинуть', callback_data=f'rate_{q_id}_down')
        ],
        [InlineKeyboardButton('➡️ Следующий вопрос', callback_data='action_next')],
    ]
    
    accepts_text = ""
    if q.get("accepts"):
        accepts_text = f"\n✅ **Зачёт:** {', '.join(q['accepts'])}"

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f'💡 **Правильный ответ:**\n**{q["answer"]}**'
            f'{accepts_text}\n\n'
            f'📝 **Пояснение:** {q.get("explanation", "—")}\n\n'
            f'Засчитать очко команде «{TEAM_NAME}»?'
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown',
    )

async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    game = games.get(chat_id)
    data = query.data

    # Обработка лайков/дизлайков
    if data.startswith('rate_'):
        parts = data.split('_')
        if len(parts) == 3:
            q_id = parts[1]
            rating = parts[2]
            user_name = update.effective_user.full_name
            
            feedback = load_feedback()
            if q_id not in feedback:
                feedback[q_id] = {'up': 0, 'down': 0, 'voters': []}
                
            if user_name not in feedback[q_id]['voters']:
                feedback[q_id][rating] += 1
                feedback[q_id]['voters'].append(user_name)
                save_feedback(feedback)
                
                msg = "👍 Спасибо! Вопрос огонь!" if rating == 'up' else "👎 Понял! Выкинем этот бред."
                await query.answer(msg, show_alert=True)
            else:
                await query.answer("Вы уже оценили этот вопрос 😉", show_alert=True)
        return

    if not game or game['status'] != 'active':
        return

    if data.startswith('opt_'):
        chosen_letter = data.replace('opt_', '')
        q = game['questions'][game['current_idx']]
        correct_ans = q['answer']
        if chosen_letter in correct_ans:
            game['score'] += 1
            await query.edit_message_text(f'🎯 **Верно!** Текущий счёт: **{game["score"]}**')
        else:
            await query.edit_message_text(f'❌ **Неверно!** Правильный ответ: **{correct_ans}**')
        if game.get('timer_task'): game['timer_task'].cancel()
        game['current_idx'] += 1
        await asyncio.sleep(2)
        await send_question(chat_id, context)

    elif data == 'action_hint':
        q = game['questions'][game['current_idx']]
        hint = q.get('hint', 'Подсказка отсутствует.')
        await context.bot.send_message(chat_id=chat_id, text=f'💡 **Подсказка:**\n_{hint}_', parse_mode='Markdown')

    elif data == 'action_reveal':
        if game.get('timer_task'): game['timer_task'].cancel()
        await reveal_answer(chat_id, context)

    elif data == 'score_yes':
        game['score'] += 1
        await query.edit_message_text(f'✅ Засчитано! Счёт: **{game["score"]}**')
        game['current_idx'] += 1
        await asyncio.sleep(1)
        await send_question(chat_id, context)

    elif data == 'score_no':
        await query.edit_message_text(f'❌ Не взяли. Счёт: **{game["score"]}**')
        game['current_idx'] += 1
        await asyncio.sleep(1)
        await send_question(chat_id, context)

    elif data == 'action_next':
        game['current_idx'] += 1
        await send_question(chat_id, context)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if game and game['status'] == 'active':
        if game.get('timer_task'): game['timer_task'].cancel()
        game['status'] = 'idle'
        await update.message.reply_text('⛔️ Тренировка остановлена.')
    else:
        await update.message.reply_text('Активных игр нет.')

if __name__ == '__main__':
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler('start', start_cmd))
    app.add_handler(CommandHandler('quiz', quiz_cmd))
    app.add_handler(CommandHandler('stop', stop_cmd))
    app.add_handler(CallbackQueryHandler(init_game_callback, pattern='^init_game$'))
    app.add_handler(CallbackQueryHandler(category_callback, pattern='^cat_'))
    app.add_handler(CallbackQueryHandler(action_callback, pattern='^(action_|score_|opt_|rate_)'))
    
    print(f'🤖 Бот запущен! База: {len(QUESTIONS_DB)} вопросов.')
    app.run_polling()