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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN_HERE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
expenses = []

# ─── БАЗА ЗНАНИЙ ──────────────────────────────────────────────────────────────

KNOWN_NAMES_FOT = [
    "комолиддин", "аброр", "фахридин", "ойбек", "шавкат", "жохонгир", "тохир",
    "сагдина", "мохи", "самандар", "зиевуддин", "сунат", "даврон",
    "зухрат", "муслима", "султон мурод", "султон", "мурод", "бозор", "тогара",
    "мойка", "уборка", "тозалаш"
]
KNOWN_NAMES_70 = ["шохрух"]
KNOWN_NAMES_30 = []

COMBO_RULES = {
    "кампод такси": "сырьё", "кампот такси": "сырьё",
    "такси бозор": "аренда", "такси мева": "аренда",
    "сув 10л": "сырьё", "мойка уборка": "ФОТ",
}

KEYWORD_CATEGORY_MAP = {
    "мясо": "мясо", "гўшт": "мясо", "гушт": "мясо", "қази": "мясо", "кази": "мясо", "тузлама": "мясо",
    "сырьё": "сырьё", "сырье": "сырьё",
    "сут": "сырьё", "молоко": "сырьё", "сув": "сырьё", "вода": "сырьё",
    "когоз": "сырьё", "купия": "сырьё", "кампод": "сырьё", "кампот": "сырьё",
    "ун": "сырьё", "мука": "сырьё", "туз": "сырьё", "соль": "сырьё",
    "қанд": "сырьё", "канд": "сырьё", "сахар": "сырьё",
    "картошка": "сырьё", "картофель": "сырьё", "помидор": "сырьё",
    "бодринг": "сырьё", "пиёз": "сырьё", "лук": "сырьё",
    "рис": "рис", "guruch": "рис",
    "ёғ": "масло", "ег": "масло", "масло": "масло", "yog": "масло",
    "мева": "фрукты", "урик": "фрукты", "тарвуз": "фрукты", "гулос": "фрукты",
    "савзи": "савзи", "морковь": "савзи",
    "нон": "хлеб", "хлеб": "хлеб", "лаваш": "хлеб",
    "чой": "напитки", "чай": "напитки", "кола": "кола", "напитки": "напитки",
    "такси": "аренда", "транспорт": "аренда", "транспортировка": "аренда", "тахи": "аренда",
    "машина": "аренда", "бензин": "аренда",
    "алиса": "телефония", "программа": "телефония", "интернет": "телефония", "телефон": "телефония",
    "газ": "оплата за газ",
    "электр": "электроэнергия", "свет": "электроэнергия",
    "налог": "налог", "ндс": "налог", "солик": "налог",
    "аренда": "аренда", "ижара": "аренда",
    "банк": "дебит кредит", "комиссия": "дебит кредит",
    "благоустройство": "благоустройство", "эхсон": "эхсон",
}

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

# ─── ЛОГИКА ───────────────────────────────────────────────────────────────────

def parse_expense_with_ai(text):
    try:
        categories_str = ", ".join(CATEGORIES)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": f"""Ты помощник учёта расходов ресторана. Текст на русском или узбекском.

Извлеки ВСЕ расходы из сообщения. Верни ТОЛЬКО JSON массив:
[{{"amount": число, "category": "категория", "description": "описание", "found": true}}]

Категории: {categories_str}

Правила:
- Имена людей (Аброр, Шавкат, Сагдина, Султон Мурод и др.) → ФОТ
- Шохрух → 70%
- Такси, транспорт, тахи → аренда
- Кампод такси, Кампот → сырьё  
- Алиса программа → телефония
- Гўшт, мясо, қази → мясо
- Сут, молоко → сырьё
- Нон, хлеб → хлеб
- Фрукты, мева, урик, тарвуз, гулос → фрукты
- Формулы "2*50.000=100.000" → берём 100000
- Точки в числах — разделитель тысяч: 50.000 = 50000
- Если сумма не указана (прочерк, пусто) — пропусти
- Заголовки, итоги, остатки — пропусти

Сообщение:
{text}"""}]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'```json|```', '', raw).strip()
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception as e:
        logger.error(f"AI error: {e}")
        return []

def format_report(month, year, chat_expenses):
    filtered = [e for e in chat_expenses if e['date'].month == month and e['date'].year == year]
    if not filtered:
        return f"📭 Нет данных за {month:02d}.{year}"

    by_category = defaultdict(float)
    for e in filtered:
        by_category[e['category']] += e['amount']

    total = sum(v for k, v in by_category.items() if k != "доход")
    month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
                   7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}

    lines = [f"📊 *{month_names.get(month, month)} {year}*\n"]
    for cat, amount in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
        emoji = EMOJI_MAP.get(cat, "📌")
        pct = (amount / total * 100) if total > 0 and cat != "доход" else 0
        lines.append(f"{emoji} *{cat}*: {amount:,.0f} сум ({pct:.1f}%)")
    lines.append(f"\n━━━━━━━━━━━━━━━")
    lines.append(f"💰 *ИТОГО: {total:,.0f} сум*")
    lines.append(f"📝 Записей: {len(filtered)}")
    return "\n".join(lines)

# ─── ХЕНДЛЕРЫ ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Привет! Бот учёта расходов*\n\n"
        "Отправляйте отчёты на русском или узбекском:\n"
        "```\nГўшт 50.000\nАброр 350.000\nТакси 30.000\n```\n\n"
        "*/report* — отчёт за месяц\n"
        "*/report 5 2025* — май 2025\n"
        "*/list* — последние записи",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text or text.startswith('/') or update.message.from_user.is_bot:
        return

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
            f"✅ {emoji} *{e['category']}*\n💵 {e['amount']:,.0f} сум\n📝 {e['description']}",
            parse_mode="Markdown"
        )
    else:
        total = sum(e['amount'] for e in saved)
        lines = [f"✅ *Записано {len(saved)} позиций:*\n"]
        for e in saved:
            emoji = EMOJI_MAP.get(e['category'], "📌")
            lines.append(f"{emoji} {e['description']}: {e['amount']:,.0f} → *{e['category']}*")
        lines.append(f"\n💰 *Итого: {total:,.0f} сум*")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    month, year = now.month, now.year
    if context.args:
        try:
            if len(context.args) >= 1: month = int(context.args[0])
            if len(context.args) >= 2: year = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Формат: /report 5 2025")
            return
    chat_expenses = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    await update.message.reply_text(format_report(month, year, chat_expenses), parse_mode="Markdown")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_expenses = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    recent = sorted(chat_expenses, key=lambda x: x['date'], reverse=True)[:10]
    if not recent:
        await update.message.reply_text("📭 Нет записей.")
        return
    lines = ["📋 *Последние записи:*\n"]
    for e in recent:
        emoji = EMOJI_MAP.get(e['category'], "📌")
        lines.append(f"{emoji} {e['date'].strftime('%d.%m')} | *{e['category']}* | {e['amount']:,.0f} | {e['description'][:35]}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Справка*\n\n"
        "Пишите расходы в любом формате:\n"
        "```\nГўшт 50.000\nНон 5*4500=20.000\nАброр 350.000\n```\n\n"
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
