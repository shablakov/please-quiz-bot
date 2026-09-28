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

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

# Название команды
TEAM_NAME = 'Леди и жиробасы'


def load_questions():
  if os.path.exists('questions.json'):
    with open('questions.json', 'r', encoding='utf-8') as f:
      return json.load(f)
  return []


QUESTIONS_DB = load_questions()

# games[chat_id] = {
#     "status": "active" | "idle",
#     "category": "...",
#     "questions": [...],
#     "current_idx": 0,
#     "score": 0,
#     "state": "waiting_answer" | "showing_answer",
#     "timer_task": None
# }
games = {}


def get_categories():
  categories = set(q.get('category', 'Разнобой') for q in QUESTIONS_DB)
  return sorted(list(categories))


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  msg = (
      f'👋 Привет, команда **«{TEAM_NAME}»**!\n\n'
      'Я тренировочный бот для игр **Please Quiz** с большой базой из 50+'
      ' вопросов.\n\n'
      '📌 **Команды:**\n'
      '• `/quiz` — начать новую тренировку\n'
      '• `/stop` — остановить игру\n'
      '• `/help` — справка'
  )
  await update.message.reply_text(msg, parse_mode='Markdown')


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  categories = get_categories()
  keyboard = [[
      InlineKeyboardButton(
          '🎲 Все категории (Микс 50 вопросов)', callback_data='cat_ALL'
      )
  ]]

  row = []
  for cat in categories:
    row.append(InlineKeyboardButton(f'📁 {cat}', callback_data=f'cat_{cat}'))
    if len(row) == 2:
      keyboard.append(row)
      row = []
  if row:
    keyboard.append(row)

  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text(
      f'🎯 **Команда «{TEAM_NAME}», выберите тематику:**',
      reply_markup=reply_markup,
      parse_mode='Markdown',
  )


async def category_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  await query.answer()

  chat_id = query.message.chat_id
  cat_data = query.data.replace('cat_', '')

  if cat_data == 'ALL':
    selected_questions = QUESTIONS_DB.copy()
    cat_name = 'Все категории (Микс)'
  else:
    selected_questions = [
        q for q in QUESTIONS_DB if q.get('category') == cat_data
    ]
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
  }

  await query.edit_message_text(
      f'✅ **Тематика:** {cat_name}\n'
      f'📊 Вопросов в пакете: **{len(selected_questions)}**\n\n'
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
            '🏁 **Тренировка окончена!**\n\n'
            f'🏆 Команда **«{TEAM_NAME}»** набрала: **{game["score"]} из'
            f' {total}** правильных ответов!\nЗапустить новую: `/quiz`.'
        ),
        parse_mode='Markdown',
    )
    game['status'] = 'idle'
    return

  q = game['questions'][idx]
  game['state'] = 'waiting_answer'

  # Формируем клавиатуру в зависимости от типа вопроса (открытый / закрытый с вариантами)
  keyboard = []
  if q.get('type') == 'closed' and 'options' in q:
    opt_row = []
    for opt in q['options']:
      opt_letter = opt.split(')')[0].strip()
      opt_row.append(
          InlineKeyboardButton(opt, callback_data=f'opt_{opt_letter}')
      )
      if len(opt_row) == 2:
        keyboard.append(opt_row)
        opt_row = []
    if opt_row:
      keyboard.append(opt_row)

  keyboard.append([
      InlineKeyboardButton('💡 Подсказка', callback_data='action_hint'),
      InlineKeyboardButton('🔔 Вскрыть ответ', callback_data='action_reveal'),
  ])
  reply_markup = InlineKeyboardMarkup(keyboard)

  q_type_badge = (
      '🔘 Закрытый вопрос'
      if q.get('type') == 'closed'
      else '💬 Открытый вопрос (обсуждение)'
  )

  options_text = ''
  if q.get('options'):
    options_text = '\n\n' + '\n'.join(q['options'])

  msg_text = (
      f'❓ **Вопрос №{idx + 1} / {total}** [{q.get("category", "Разнобой")}]\n'
      f'_{q_type_badge}_\n\n'
      f'**{q["question"]}**'
      f'{options_text}\n\n'
      f'⏱ Время: **{q.get("time_limit", 45)} сек**'
  )

  await context.bot.send_message(
      chat_id=chat_id,
      text=msg_text,
      reply_markup=reply_markup,
      parse_mode='Markdown',
  )

  if game.get('timer_task'):
    game['timer_task'].cancel()

  game['timer_task'] = asyncio.create_task(
      question_timer(chat_id, context, q.get('time_limit', 45), idx)
  )


async def question_timer(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE, seconds: int, q_idx: int
):
  if seconds > 15:
    await asyncio.sleep(seconds - 10)
    game = games.get(chat_id)
    if (
        game
        and game['status'] == 'active'
        and game['current_idx'] == q_idx
        and game['state'] == 'waiting_answer'
    ):
      await context.bot.send_message(
          chat_id=chat_id, text='⏳ **Осталось 10 секунд!**'
      )
      await asyncio.sleep(10)
  else:
    await asyncio.sleep(seconds)

  game = games.get(chat_id)
  if (
      game
      and game['status'] == 'active'
      and game['current_idx'] == q_idx
      and game['state'] == 'waiting_answer'
  ):
    await context.bot.send_message(
        chat_id=chat_id, text='🔔 **Время вышло!** Вскрываем ответ.'
    )
    await reveal_answer(chat_id, context)


async def reveal_answer(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
  game = games.get(chat_id)
  if not game or game['status'] == 'idle':
    return

  game['state'] = 'showing_answer'
  q = game['questions'][game['current_idx']]

  keyboard = [
      [
          InlineKeyboardButton('✅ Засчитать (+1)', callback_data='score_yes'),
          InlineKeyboardButton('❌ Не взяли (0)', callback_data='score_no'),
      ],
      [InlineKeyboardButton('➡️ Следующий вопрос', callback_data='action_next')],
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)

  await context.bot.send_message(
      chat_id=chat_id,
      text=(
          f'💡 **Правильный ответ:**\n\n**{q["answer"]}**\n\n📝'
          f' *Пояснение:* {q.get("explanation", "—")}\n\nЗасчитать очко команде'
          f' **«{TEAM_NAME}»**?'
      ),
      reply_markup=reply_markup,
      parse_mode='Markdown',
  )


async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  await query.answer()

  chat_id = query.message.chat_id
  game = games.get(chat_id)
  if not game or game['status'] != 'active':
    return

  data = query.data

  if data.startswith('opt_'):
    chosen_letter = data.replace('opt_', '')
    q = game['questions'][game['current_idx']]
    correct_ans = q['answer']

    if chosen_letter in correct_ans:
      game['score'] += 1
      await query.edit_message_text(
          f'🎯 **Верно!** Вариант {chosen_letter} правильный.\nТекущий счёт:'
          f' **{game["score"]}**'
      )
    else:
      await query.edit_message_text(
          f'❌ **Неверно!** Правильный ответ: **{correct_ans}**'
      )

    if game.get('timer_task'):
      game['timer_task'].cancel()

    game['current_idx'] += 1
    await asyncio.sleep(2)
    await send_question(chat_id, context)

  elif data == 'action_hint':
    q = game['questions'][game['current_idx']]
    hint = q.get('hint', 'Подсказка отсутствует.')
    await context.bot.send_message(
        chat_id=chat_id, text=f'💡 **Подсказка:** _{hint}_', parse_mode='Markdown'
    )

  elif data == 'action_reveal':
    if game.get('timer_task'):
      game['timer_task'].cancel()
    await reveal_answer(chat_id, context)

  elif data == 'score_yes':
    game['score'] += 1
    await query.edit_message_text(
        f'✅ **Засчитано!** Счёт: **{game["score"]}**'
    )
    game['current_idx'] += 1
    await asyncio.sleep(1)
    await send_question(chat_id, context)

  elif data == 'score_no':
    await query.edit_message_text(f'❌ **Не взяли.** Счёт: **{game["score"]}**')
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
    if game.get('timer_task'):
      game['timer_task'].cancel()
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
  app.add_handler(CallbackQueryHandler(category_callback, pattern='^cat_'))
  app.add_handler(
      CallbackQueryHandler(action_callback, pattern='^(action_|score_|opt_)')
  )

  print('🤖 Бот запущен с расширенной базой 50 вопросов!')
  app.run_polling()