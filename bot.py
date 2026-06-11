import os
import re
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import anthropic
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import io

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN_HERE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_KEY")
ADMIN_ID = 1885883892

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
expenses = []

settings = {
    "categories": [
        "мясо", "напитки", "кола", "сырьё", "оплата за газ", "рис", "ФОТ",
        "электроэнергия", "налог", "доход", "соленые тилла", "телефония",
        "хлеб", "фрукты", "благоустройство", "эхсон", "масло", "рыба",
        "долг", "савзи", "мфй", "посуда", "налог ежемесячный",
        "транспорт", "такси", "дебит кредит", "70%", "30%", "прочее"
    ],
    "custom_rules": {}
}

# Ожидающие подтверждения расходы: {uuid: {expense_data, chat_id, message_id}}
pending_expenses = {}

WAIT_NEW_CATEGORY = 1
WAIT_RULE_EXAMPLE = 2

EMOJI_MAP = {
    "мясо": "🥩", "напитки": "🥤", "кола": "🥤", "сырьё": "🛒",
    "оплата за газ": "🔥", "рис": "🍚", "ФОТ": "👷",
    "электроэнергия": "⚡", "налог": "📋", "доход": "💰",
    "телефония": "📱", "хлеб": "🍞", "фрукты": "🍎",
    "благоустройство": "🌿", "масло": "🫙", "рыба": "🐟",
    "савзи": "🥕", "транспорт": "🚗", "такси": "🚕",
    "дебит кредит": "🏦", "70%": "💼", "30%": "💼",
    "прочее": "📌", "эхсон": "📌", "мфй": "📌", "посуда": "🍽️"
}

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────

def main_keyboard(user_id=None):
    keyboard = [
        [KeyboardButton("📊 Отчёт за день"), KeyboardButton("📈 Отчёт за неделю")],
        [KeyboardButton("📅 Отчёт за месяц"), KeyboardButton("📋 Последние записи")],
        [KeyboardButton("📥 Скачать Excel"), KeyboardButton("ℹ️ Помощь")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("⚙️ Настройки администратора")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

def admin_keyboard():
    keyboard = [
        [KeyboardButton("➕ Добавить категорию")],
        [KeyboardButton("🔧 Добавить правило (пример → категория)")],
        [KeyboardButton("📋 Список правил и категорий")],
        [KeyboardButton("🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def category_inline_keyboard(pending_id):
    cats = settings["categories"]
    keyboard = []
    row = []
    for cat in cats:
        row.append(InlineKeyboardButton(cat, callback_data=f"assign:{pending_id}:{cat}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🗑 Пропустить", callback_data=f"skip:{pending_id}")])
    return InlineKeyboardMarkup(keyboard)

# ─── EXCEL ────────────────────────────────────────────────────────────────────

def generate_excel(chat_expenses):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Расходы"

        headers = ["Дата", "Категория", "Сумма (сум)", "Описание", "Кто добавил"]
        hf = PatternFill("solid", start_color="C00000", end_color="C00000")
        hfont = Font(bold=True, color="FFFFFF", name="Arial", size=10)
        thin = Side(style='thin', color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.fill = hf; cell.font = hfont
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border

        ws.row_dimensions[1].height = 25
        for i, w in enumerate([14, 20, 18, 50, 18], 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        af = PatternFill("solid", start_color="FFF2CC", end_color="FFF2CC")
        df_style = Font(name="Arial", size=9)

        for r, e in enumerate(sorted(chat_expenses, key=lambda x: x['date']), 2):
            fill = af if r % 2 == 0 else PatternFill("solid", start_color="FFFFFF", end_color="FFFFFF")
            vals = [e['date'], e['category'], e['amount'], e['description'], e.get('user', '—')]
            alns = ["center", "left", "right", "left", "center"]
            for c, (val, aln) in enumerate(zip(vals, alns), 1):
                cell = ws.cell(row=r, column=c, value=val)
                cell.font = df_style; cell.fill = fill
                cell.alignment = Alignment(horizontal=aln, vertical="center")
                cell.border = border
                if c == 3: cell.number_format = '#,##0'

        ws2 = wb.create_sheet("Итоги по категориям")
        by_cat = defaultdict(float)
        for e in chat_expenses:
            by_cat[e['category']] += e['amount']
        total = sum(by_cat.values())

        for col, h in enumerate(["Категория", "Сумма", "%"], 1):
            ws2.cell(row=1, column=col, value=h).font = Font(bold=True)
        ws2.column_dimensions['A'].width = 25
        ws2.column_dimensions['B'].width = 18
        ws2.column_dimensions['C'].width = 10

        for r, (cat, amt) in enumerate(sorted(by_cat.items(), key=lambda x: x[1], reverse=True), 2):
            ws2.cell(row=r, column=1, value=cat)
            c = ws2.cell(row=r, column=2, value=amt)
            c.number_format = '#,##0'
            ws2.cell(row=r, column=3, value=round(amt/total*100, 1) if total else 0)

        tr = len(by_cat) + 3
        ws2.cell(row=tr, column=1, value="ИТОГО").font = Font(bold=True)
        tc = ws2.cell(row=tr, column=2, value=total)
        tc.font = Font(bold=True); tc.number_format = '#,##0'

        buf = io.BytesIO()
        wb.save(buf); buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Excel error: {e}")
        return None

# ─── AI ПАРСИНГ ───────────────────────────────────────────────────────────────

def parse_expense_with_ai(text):
    try:
        categories_str = ", ".join(settings["categories"])
        custom_rules_str = "\n".join([f"- '{k}' → {v}" for k, v in settings["custom_rules"].items()])
        today = datetime.now().strftime("%d.%m.%Y")
        custom_section = f"\nПользовательские правила (приоритет над всем!):\n{custom_rules_str}" if custom_rules_str else ""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": f"""Ты помощник учёта расходов ресторана. Текст на русском или узбекском.

Сегодня: {today}{custom_section}

Извлеки ВСЕ расходы. Верни ТОЛЬКО JSON массив:
[{{"amount": число, "category": "категория или null если не уверен", "description": "описание", "date": "ДД.ММ.ГГГГ", "found": true, "uncertain": false}}]

Если не уверен в категории — поставь "uncertain": true и category: null.

Категории: {categories_str}

Правила:
- Имена людей → ФОТ (кроме пользовательских правил выше)
- Шохрух → 70%
- Такси → такси | Транспорт, бензин → транспорт
- Кампод такси → сырьё | Алиса → телефония
- Гўшт, мясо → мясо | Сут → сырьё | Нон → хлеб | Кола → кола
- Формулы "2*50=100" → берём 100 | Точки = тысячи: 50.000=50000
- Дата из текста если есть, иначе {today}
- Пустые суммы — пропусти

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

# ─── ОТЧЁТЫ ───────────────────────────────────────────────────────────────────

def format_report(title, chat_expenses, date_from, date_to):
    filtered = [e for e in chat_expenses if date_from <= datetime.strptime(e['date'], "%d.%m.%Y") <= date_to]
    if not filtered:
        return "📭 Нет данных за указанный период"
    by_cat = defaultdict(float)
    for e in filtered: by_cat[e['category']] += e['amount']
    total = sum(v for k, v in by_cat.items() if k != "доход")
    lines = [f"📊 *{title}*\n"]
    for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
        emoji = EMOJI_MAP.get(cat, "📌")
        pct = (amt/total*100) if total > 0 and cat != "доход" else 0
        lines.append(f"{emoji} *{cat}*: {amt:,.0f} сум ({pct:.1f}%)")
    lines += [f"\n━━━━━━━━━━━━━━━",
              f"💰 *ИТОГО: {total:,.0f} сум*",
              f"📝 Записей: {len(filtered)}",
              f"📆 {date_from.strftime('%d.%m')} — {date_to.strftime('%d.%m.%Y')}"]
    return "\n".join(lines)

# ─── ХЕНДЛЕРЫ ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        "☪️ *Ассаламу алейкум!*\n\n"
        "Я — *профессиональный бот-финансист* 🤖💼\n\n"
        "Создан специально для группы *Суром* с целью автоматизации учёта расходов. "
        "Больше не нужно вручную вносить данные в таблицы — просто пишите расходы "
        "в любом формате, и я мгновенно распределю их по категориям!\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🧠 *Что я умею:*\n"
        "• Понимаю русский и узбекский язык\n"
        "• Распознаю суммы в любом формате\n"
        "• Автоматически определяю категории\n"
        "• Учитываю даты из текста сообщений\n"
        "• Отчёты за день, неделю и месяц\n"
        "• Выгрузка в Excel файл\n"
        "• Спрашиваю у администратора если не уверен\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📝 *Просто пишите расходы:*\n"
        "`Гўшт 50.000`\n"
        "`Аброр 350.000`\n"
        "`Такси бозор 30.000`\n\n"
        "Используйте кнопки ниже 👇",
        parse_mode="Markdown", reply_markup=main_keyboard(uid))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    if not text or update.message.from_user.is_bot:
        return

    # Кнопки меню
    if text == "📊 Отчёт за день": await report_day(update, context); return
    elif text == "📈 Отчёт за неделю": await report_week(update, context); return
    elif text == "📅 Отчёт за месяц": await report_month(update, context); return
    elif text == "📋 Последние записи": await cmd_list(update, context); return
    elif text == "📥 Скачать Excel": await download_excel(update, context); return
    elif text == "ℹ️ Помощь": await cmd_help(update, context); return
    elif text == "🔙 Назад":
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard(uid)); return
    elif text == "⚙️ Настройки администратора":
        if uid != ADMIN_ID: await update.message.reply_text("⛔ Только для администратора."); return
        await update.message.reply_text("⚙️ *Панель администратора*", parse_mode="Markdown", reply_markup=admin_keyboard()); return
    elif text == "➕ Добавить категорию":
        if uid != ADMIN_ID: return
        context.user_data['state'] = WAIT_NEW_CATEGORY
        await update.message.reply_text("Введите название новой категории:"); return
    elif text == "🔧 Добавить правило (пример → категория)":
        if uid != ADMIN_ID: return
        context.user_data['state'] = WAIT_RULE_EXAMPLE
        await update.message.reply_text("Введите ключевое слово или имя:\n_(например: `Мадина`)_", parse_mode="Markdown"); return
    elif text == "📋 Список правил и категорий":
        if uid != ADMIN_ID: return
        cats = "\n".join([f"• {c}" for c in settings["categories"]])
        rules = "\n".join([f"• `{k}` → *{v}*" for k, v in settings["custom_rules"].items()]) or "_(пусто)_"
        await update.message.reply_text(f"📋 *Категории:*\n{cats}\n\n🔧 *Правила:*\n{rules}",
            parse_mode="Markdown", reply_markup=admin_keyboard()); return

    # Состояния диалога (только для админа)
    state = context.user_data.get('state')
    if state == WAIT_NEW_CATEGORY and uid == ADMIN_ID:
        new_cat = text.strip()
        if new_cat not in settings["categories"]:
            settings["categories"].append(new_cat)
            await update.message.reply_text(f"✅ Категория *{new_cat}* добавлена!", parse_mode="Markdown", reply_markup=admin_keyboard())
        else:
            await update.message.reply_text(f"⚠️ Уже существует.", reply_markup=admin_keyboard())
        context.user_data['state'] = None; return

    elif state == WAIT_RULE_EXAMPLE and uid == ADMIN_ID:
        context.user_data['rule_example'] = text.strip().lower()
        cats = settings["categories"]
        keyboard = []
        row = []
        for cat in cats:
            row.append(InlineKeyboardButton(cat, callback_data=f"setcat:{cat}"))
            if len(row) == 3: keyboard.append(row); row = []
        if row: keyboard.append(row)
        await update.message.reply_text(f"Выберите категорию для *{text.strip()}*:",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if text.startswith('/'): return

    # ─── Обработка расходов ───
    items = parse_expense_with_ai(text)
    if not items: return

    saved = []
    uncertain_items = []

    for item in items:
        if not item.get('found') or not item.get('amount'): continue
        item_date = item.get('date', datetime.now().strftime("%d.%m.%Y"))
        try: datetime.strptime(item_date, "%d.%m.%Y")
        except: item_date = datetime.now().strftime("%d.%m.%Y")

        expense = {
            'date': item_date,
            'amount': float(item['amount']),
            'category': item.get('category') or 'прочее',
            'description': item.get('description', '')[:100],
            'user': update.message.from_user.first_name or "—",
            'chat_id': update.effective_chat.id
        }

        if item.get('uncertain') or not item.get('category'):
            uncertain_items.append(expense)
        else:
            expenses.append(expense)
            saved.append(expense)

    # Сохранённые — подтвердить
    if saved:
        if len(saved) == 1:
            e = saved[0]
            emoji = EMOJI_MAP.get(e['category'], "📌")
            await update.message.reply_text(
                f"✅ *Записано!*\n{emoji} *{e['category']}*\n💵 {e['amount']:,.0f} сум\n📝 {e['description']}\n📆 {e['date']}",
                parse_mode="Markdown")
        else:
            total = sum(e['amount'] for e in saved)
            lines = [f"✅ *Записано {len(saved)} позиций:*\n"]
            for e in saved:
                emoji = EMOJI_MAP.get(e['category'], "📌")
                lines.append(f"{emoji} {e['description']}: {e['amount']:,.0f} → *{e['category']}* ({e['date']})")
            lines.append(f"\n💰 *Итого: {total:,.0f} сум*")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # Непонятные — спросить у админа в личке
    for exp in uncertain_items:
        import uuid
        pid = str(uuid.uuid4())[:8]
        pending_expenses[pid] = exp

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❓ *Не понял категорию!*\n\n"
                     f"📝 *Описание:* {exp['description']}\n"
                     f"💵 *Сумма:* {exp['amount']:,.0f} сум\n"
                     f"📆 *Дата:* {exp['date']}\n"
                     f"👤 *Кто отправил:* {exp['user']}\n\n"
                     f"Выберите категорию:",
                parse_mode="Markdown",
                reply_markup=category_inline_keyboard(pid)
            )
        except Exception as e:
            logger.error(f"Cant send to admin: {e}")
            exp['category'] = 'прочее'
            expenses.append(exp)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("setcat:"):
        # Правило от админа
        cat = data.replace("setcat:", "")
        example = context.user_data.get('rule_example', '')
        if example:
            settings["custom_rules"][example] = cat
            await query.edit_message_text(
                f"✅ Правило добавлено!\n`{example}` → *{cat}*",
                parse_mode="Markdown")
        context.user_data['state'] = None
        context.user_data['rule_example'] = None

    elif data.startswith("assign:"):
        # Назначение категории для непонятного расхода
        parts = data.split(":", 2)
        pid = parts[1]
        cat = parts[2]
        if pid in pending_expenses:
            exp = pending_expenses.pop(pid)
            exp['category'] = cat
            expenses.append(exp)
            emoji = EMOJI_MAP.get(cat, "📌")
            await query.edit_message_text(
                f"✅ Записано!\n{emoji} *{cat}*\n💵 {exp['amount']:,.0f} сум\n📝 {exp['description']}",
                parse_mode="Markdown")

    elif data.startswith("skip:"):
        pid = data.replace("skip:", "")
        if pid in pending_expenses:
            pending_expenses.pop(pid)
            await query.edit_message_text("🗑 Пропущено.")

async def download_excel(update, context):
    chat_expenses = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    if not chat_expenses:
        await update.message.reply_text("📭 Нет данных для выгрузки.")
        return
    await update.message.reply_text("⏳ Генерирую Excel...")
    buf = generate_excel(chat_expenses)
    if buf:
        filename = f"расходы_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
        await update.message.reply_document(document=buf, filename=filename,
            caption=f"📊 Отчёт — {len(chat_expenses)} записей")
    else:
        await update.message.reply_text("❌ Ошибка при создании файла.")

async def report_day(update, context):
    now = datetime.now()
    ce = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    await update.message.reply_text(format_report(f"Отчёт за {now.strftime('%d.%m.%Y')}", ce,
        now.replace(hour=0,minute=0,second=0), now.replace(hour=23,minute=59,second=59)), parse_mode="Markdown")

async def report_week(update, context):
    now = datetime.now()
    ce = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    await update.message.reply_text(format_report("Отчёт за 7 дней", ce,
        (now-timedelta(days=7)).replace(hour=0,minute=0,second=0), now.replace(hour=23,minute=59,second=59)), parse_mode="Markdown")

async def report_month(update, context):
    now = datetime.now()
    months = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
              7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
    ce = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    await update.message.reply_text(format_report(f"Отчёт за {months[now.month]} {now.year}", ce,
        now.replace(day=1,hour=0,minute=0,second=0), now.replace(hour=23,minute=59,second=59)), parse_mode="Markdown")

async def cmd_list(update, context):
    ce = [e for e in expenses if e['chat_id'] == update.effective_chat.id]
    recent = sorted(ce, key=lambda x: x['date'], reverse=True)[:10]
    if not recent:
        await update.message.reply_text("📭 Нет записей."); return
    lines = ["📋 *Последние записи:*\n"]
    for e in recent:
        emoji = EMOJI_MAP.get(e['category'], "📌")
        lines.append(f"{emoji} {e['date']} | *{e['category']}* | {e['amount']:,.0f} | {e['description'][:30]}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_help(update, context):
    await update.message.reply_text(
        "📖 *Инструкция*\n\n"
        "Пишите расходы в любом формате:\n"
        "```\n13 май\nГўшт 50.000\nАброр 350.000\nТакси 30.000\n```\n\n"
        "• Бот сам определит категорию\n"
        "• Если не уверен — спросит у администратора\n"
        "• 📥 Скачать Excel — выгрузка всех данных\n"
        "• ⚙️ Настройки — только для администратора",
        parse_mode="Markdown", reply_markup=main_keyboard(update.effective_user.id))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
