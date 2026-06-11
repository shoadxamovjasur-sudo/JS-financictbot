import os
import re
import json
import logging
from datetime import datetime
from collections import defaultdict
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8723508444:AAGeM1osSk5FFOlOcaLLTVRZJyHf6faMvVQ")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR ANTROPIC KEY")

# In-memory storage (replace with DB for production)
expenses = []  # list of dicts: {date, amount, category, description, user, chat_id}

CATEGORIES = [
    "ЗП", "Снабжение", "Банковские расходы", "Налог",
    "Транспорт", "Питание", "Котлаван", "Бетон", "Арматура",
    "Опалубка", "Электроснабжение", "Прочее", "Перемещение"
]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def parse_expense_with_ai(text: str) -> dict | None:
    """Use Claude to extract expense info from any free-form text."""
    try:
        categories_str = ", ".join(CATEGORIES)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": f"""Извлеки информацию о расходе из этого сообщения. 
Верни ТОЛЬКО JSON без комментариев:
{{"amount": число, "category": "категория", "description": "описание", "found": true/false}}

Категории: {categories_str}

Если сумма не найдена, верни {{"found": false}}

Сообщение: {text}"""
            }]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'```json|```', '', raw).strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"AI parse error: {e}")
        return None

def format_report(month: int, year: int, chat_expenses: list) -> str:
    """Generate monthly report."""
    filtered = [e for e in chat_expenses 
                if e['date'].month == month and e['date'].year == year]
    
    if not filtered:
        return f"📭 Нет данных за {month:02d}.{year}"
    
    by_category = defaultdict(float)
    for e in filtered:
        by_category[e['category']] += e['amount']
    
    total = sum(by_category.values())
    month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
                   7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
    
    lines = [f"📊 *{month_names[month]} {year}*\n"]
    sorted_cats = sorted(by_category.items(), key=lambda x: x[1], reverse=True)
    
    for cat, amount in sorted_cats:
        pct = (amount / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 5)
        lines.append(f"*{cat}*\n{bar} {amount:,.0f} сум ({pct:.1f}%)\n")
    
    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"💰 *ИТОГО: {total:,.0f} сум*")
    lines.append(f"📝 Транзакций: {len(filtered)}")
    return "\n".join(lines)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Привет! Я бот учёта расходов Келес Курилиш*\n\n"
        "Просто пишите расходы в любом формате:\n"
        "• `ЗП Ахмад 500 000`\n"
        "• `Купили арматуру 2 500 000 сум`\n"
        "• `Бетон за июль 15 млн`\n\n"
        "📌 *Команды:*\n"
        "/отчет — отчёт за текущий месяц\n"
        "/отчет 5 2025 — отчёт за май 2025\n"
        "/список — последние 10 расходов\n"
        "/помощь — справка",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text or text.startswith('/'):
        return
    
    # Skip bot messages
    if update.message.from_user.is_bot:
        return

    result = parse_expense_with_ai(text)
    
    if not result or not result.get('found'):
        return  # Ignore non-expense messages silently in groups
    
    expense = {
        'date': datetime.now(),
        'amount': float(result.get('amount', 0)),
        'category': result.get('category', 'Прочее'),
        'description': result.get('description', text[:100]),
        'user': update.message.from_user.first_name or "Неизвестно",
        'chat_id': update.effective_chat.id
    }
    expenses.append(expense)
    
    emoji_map = {
        "ЗП": "👷", "Снабжение": "🏗️", "Банковские расходы": "🏦",
        "Налог": "📋", "Транспорт": "🚛", "Питание": "🍽️",
        "Котлаван": "⛏️", "Бетон": "🧱", "Арматура": "🔩",
        "Опалубка": "🪵", "Электроснабжение": "⚡", "Перемещение": "🔄", "Прочее": "📌"
    }
    emoji = emoji_map.get(expense['category'], "📌")
    
    await update.message.reply_text(
        f"✅ *Записано!*\n"
        f"{emoji} {expense['category']}\n"
        f"💵 {expense['amount']:,.0f} сум\n"
        f"📝 {expense['description']}",
        parse_mode="Markdown"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    month, year = now.month, now.year
    
    if context.args:
        try:
            if len(context.args) >= 1:
                month = int(context.args[0])
            if len(context.args) >= 2:
                year = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Формат: /отчет 5 2025")
            return
    
    chat_expenses = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    report = format_report(month, year, chat_expenses)
    await update.message.reply_text(report, parse_mode="Markdown")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_expenses = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    recent = sorted(chat_expenses, key=lambda x: x['date'], reverse=True)[:10]
    
    if not recent:
        await update.message.reply_text("📭 Нет записанных расходов.")
        return
    
    lines = ["📋 *Последние 10 расходов:*\n"]
    for e in recent:
        lines.append(f"• {e['date'].strftime('%d.%m')} | *{e['category']}* | {e['amount']:,.0f} сум | {e['description'][:40]}")
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Справка*\n\n"
        "*Как записывать расходы:*\n"
        "Просто пишите в любом формате, бот сам поймёт:\n"
        "`ЗП рабочим 3 500 000`\n"
        "`арматура 12мм — 8 млн`\n"
        "`такси на объект 150к`\n\n"
        "*Команды:*\n"
        "/отчет — текущий месяц\n"
        "/отчет 6 2025 — июнь 2025\n"
        "/список — последние записи\n",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("отчет", cmd_report))
    app.add_handler(CommandHandler("список", cmd_list))
    app.add_handler(CommandHandler("помощь", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
