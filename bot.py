import os
import re
import json
import logging
from datetime import datetime
from collections import defaultdict
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from knowledge import (
    KNOWN_NAMES_FOT, KNOWN_NAMES_70, KNOWN_NAMES_30,
    KEYWORD_CATEGORY_MAP, COMBO_RULES
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN_HERE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

expenses = []  # {date, amount, category, description, user, chat_id}

CATEGORIES = [
    "мясо", "напитки", "сырьё", "оплата за газ", "рис", "ФОТ",
    "электроэнергия", "налог", "доход", "соленые тилла", "телефония",
    "хлеб", "фрукты", "благоустройство", "эхсон", "масло", "рыба",
    "долг", "савзи", "мфй", "посуда", "налог ежемесячный",
    "аренда", "кола", "дебит кредит", "70%", "30%", "прочее"
]

EMOJI_MAP = {
    "мясо": "🥩", "напитки": "🥤", "сырьё": "🛒", "оплата за газ": "🔥",
    "рис": "🍚", "ФОТ": "👷", "электроэнергия": "⚡", "налог": "📋",
    "доход": "💰", "телефония": "📱", "хлеб": "🍞", "фрукты": "🍎",
    "благоустройство": "🌿", "масло": "🫙", "рыба": "🐟",
    "савзи": "🥕", "аренда": "🚗", "кола": "🥤",
    "дебит кредит": "🏦", "70%": "💼", "30%": "💼", "прочее": "📌",
    "эхсон": "📌", "мфй": "📌", "посуда": "🍽️"
}

def extract_amount(text):
    """Extract number from text like '50.000', '2*50.000=100.000', '1 800 000'"""
    # Formula like 2*50.000=100.000 — take the result after =
    eq_match = re.search(r'=\s*([\d\s.,]+)', text)
    if eq_match:
        num = eq_match.group(1).replace(' ', '').replace('.', '').replace(',', '')
        try:
            return float(num)
        except:
            pass
    # Regular numbers with dots/spaces as thousands separators
    numbers = re.findall(r'\d[\d\s.,]*\d|\d+', text)
    for n in reversed(numbers):
        cleaned = n.replace(' ', '').replace('.', '').replace(',', '')
        try:
            val = float(cleaned)
            if val > 100:  # Skip small numbers like quantity
                return val
        except:
            pass
    return None

def categorize_local(text):
    """Try to categorize using local knowledge base first."""
    text_lower = text.lower().strip()

    # Check combo rules first
    for combo, cat in COMBO_RULES.items():
        if combo in text_lower:
            return cat

    # Check known names for 70%
    for name in KNOWN_NAMES_70:
        if name in text_lower:
            return "70%"

    # Check known names for 30%
    for name in KNOWN_NAMES_30:
        if name in text_lower:
            return "30%"

    # Check known FOT names
    for name in KNOWN_NAMES_FOT:
        if name in text_lower:
            return "ФОТ"

    # Check keyword map
    for keyword, cat in KEYWORD_CATEGORY_MAP.items():
        if keyword.lower() in text_lower:
            return cat

    return None

def parse_expense_with_ai(text):
    """Use Claude AI to parse expense — supports Russian and Uzbek."""
    try:
        categories_str = ", ".join(CATEGORIES)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""Ты помощник для учёта расходов ресторана. Текст может быть на русском или узбекском языке.

Извлеки ВСЕ расходы из этого сообщения. Каждая строка может быть отдельным расходом.
Верни ТОЛЬКО JSON массив без комментариев и markdown:
[
  {{"amount": число, "category": "категория", "description": "описание", "found": true}},
  ...
]

Категории: {categories_str}

Правила:
- Имена людей (Аброр, Шавкат, Сагдина и др.) → ФОТ
- Шохрух → 70%
- Такси, транспорт, тахи → аренда
- Кампод такси, Кампот → сырьё
- Алиса программа → телефония
- Гўшт, мясо, қази → мясо
- Сут, молоко → сырьё
- Нон, хлеб → хлеб
- Фрукты, мева, урик, тарвуз → фрукты
- Формулы типа "2*50.000=100.000" — берём итоговую сумму 100000
- Точки в числах — разделитель тысяч: 50.000 = 50000
- Если сумма не указана (прочерк или пусто) — пропусти эту строку
- Если это не расход (заголовок, итог, остаток) — пропусти

Сообщение:
{text}"""
            }]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'```json|```', '', raw).strip()
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        return []
    except Exception as e:
        logger.error(f"AI parse error: {e}")
        return []

def format_report(month, year, chat_expenses):
    filtered = [e for e in chat_expenses
                if e['date'].month == month and e['date'].year == year]

    if not filtered:
        return f"📭 Нет данных за {month:02d}.{year}"

    by_category = defaultdict(float)
    for e in filtered:
        by_category[e['category']] += e['amount']

    total = sum(v for k, v in by_category.items() if k != "доход")

    month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
                   7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}

    lines = [f"📊 *{month_names.get(month, month)} {year}*\n"]
    sorted_cats = sorted(by_category.items(), key=lambda x: x[1], reverse=True)

    for cat, amount in sorted_cats:
        emoji = EMOJI_MAP.get(cat, "📌")
        pct = (amount / total * 100) if total > 0 and cat != "доход" else 0
        lines.append(f"{emoji} *{cat}*: {amount:,.0f} сум ({pct:.1f}%)")

    lines.append(f"\n━━━━━━━━━━━━━━━")
    lines.append(f"💰 *ИТОГО расходов: {total:,.0f} сум*")
    lines.append(f"📝 Записей: {len(filtered)}")
    return "\n".join(lines)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Привет! Я бот учёта расходов*\n\n"
        "Отправляйте отчёты в любом формате — на русском или узбекском:\n\n"
        "```\nГўшт 50.000\nАброр 350.000\nТакси 30.000\nАлиса программа 615.000\n```\n\n"
        "Я сам распознаю категории!\n\n"
        "📌 *Команды:*\n"
        "/report — отчёт за текущий месяц\n"
        "/report 5 2025 — отчёт за май 2025\n"
        "/list — последние 10 записей\n"
        "/help — справка",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text or text.startswith('/'):
        return
    if update.message.from_user.is_bot:
        return

    # Try AI parsing for full report blocks
    items = parse_expense_with_ai(text)

    if not items:
        return

    saved = []
    for item in items:
        if not item.get('found') or not item.get('amount'):
            continue
        expense = {
            'date': datetime.now(),
            'amount': float(item['amount']),
            'category': item.get('category', 'прочее'),
            'description': item.get('description', '')[:100],
            'user': update.message.from_user.first_name or "—",
            'chat_id': update.effective_chat.id
        }
        expenses.append(expense)
        saved.append(expense)

    if not saved:
        return

    if len(saved) == 1:
        e = saved[0]
        emoji = EMOJI_MAP.get(e['category'], "📌")
        await update.message.reply_text(
            f"✅ *Записано!*\n{emoji} {e['category']}\n💵 {e['amount']:,.0f} сум\n📝 {e['description']}",
            parse_mode="Markdown"
        )
    else:
        total = sum(e['amount'] for e in saved)
        lines = [f"✅ *Записано {len(saved)} позиций:*\n"]
        for e in saved:
            emoji = EMOJI_MAP.get(e['category'], "📌")
            lines.append(f"{emoji} {e['description']}: {e['amount']:,.0f} сум → *{e['category']}*")
        lines.append(f"\n💰 Итого: *{total:,.0f} сум*")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

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
            await update.message.reply_text("❌ Формат: /report 5 2025")
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
    lines = ["📋 *Последние записи:*\n"]
    for e in recent:
        emoji = EMOJI_MAP.get(e['category'], "📌")
        lines.append(f"{emoji} {e['date'].strftime('%d.%m')} | *{e['category']}* | {e['amount']:,.0f} сум | {e['description'][:40]}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Справка*\n\n"
        "Бот понимает русский и узбекский язык.\n"
        "Просто отправьте отчёт — бот сам разберёт:\n\n"
        "```\nГўшт 50.000\nНон 5*4500=20.000\nАброр 350.000\nТакси 30.000\n```\n\n"
        "*/report* — текущий месяц\n"
        "*/report 6 2025* — июнь 2025\n"
        "*/list* — последние записи",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
