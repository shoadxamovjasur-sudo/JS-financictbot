# Келес Курилиш — Бот учёта расходов

## Деплой на Railway.app (бесплатно, 24/7)

1. Зарегистрируйся на https://railway.app
2. Нажми "New Project" → "Deploy from GitHub"
3. Загрузи эту папку на GitHub (или используй Railway CLI)
4. В настройках проекта добавь переменные окружения:
   - TELEGRAM_TOKEN = токен от BotFather
   - ANTHROPIC_API_KEY = ключ от Anthropic
5. Railway автоматически запустит бота

## Локальный запуск (Mac)

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN="ваш_токен"
export ANTHROPIC_API_KEY="ваш_ключ"
python bot.py
```

## Команды бота

- Просто пиши расходы в любом формате
- /отчет — отчёт за текущий месяц  
- /отчет 5 2025 — отчёт за май 2025
- /список — последние 10 расходов
- /помощь — справка
