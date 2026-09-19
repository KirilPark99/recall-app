"""Оригинальные демонстрационные наборы (запускается только явно через CLI)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sets_service import create_set_with_cards


DEMO_SETS = [
    {
        "title": "[Демо] Английский: базовые фразы",
        "description": "Небольшой оригинальный набор повседневных фраз. Демо-материал Recall.",
        "front_language": "en",
        "back_language": "ru",
        "tags": ["demo", "english"],
        "cards": [
            {"front_text": "Good morning!", "back_text": "Доброе утро!"},
            {"front_text": "How much does it cost?", "back_text": "Сколько это стоит?"},
            {"front_text": "Where is the nearest station?", "back_text": "Где ближайшая станция?"},
            {"front_text": "I would like a coffee, please.", "back_text": "Я хотел бы кофе, пожалуйста.", "front_hint": "вежливая просьба"},
            {"front_text": "See you tomorrow", "back_text": "До встречи завтра"},
            {"front_text": "It does not matter", "back_text": "Не имеет значения", "front_hint": "неважно"},
        ],
    },
    {
        "title": "[Демо] Программирование: C и C++",
        "description": "Термины с чувствительностью к регистру и техническими различиями.",
        "front_language": "ru",
        "back_language": "en",
        "tags": ["demo", "programming"],
        "cards": [
            {
                "front_text": "Какой язык появился раньше?",
                "back_text": "C",
                "front_context": "Два языка из 1970-х и 1980-х",
                "front_explanation": "C (1972) старше C++ (1985). Регистр ответа важен: строчная `c` не считается.",
            },
            {"front_text": "Расширение файла исходного кода C++", "back_text": "cpp", "front_hint": "три буквы"},
            {"front_text": "Функция входа в программу на C", "back_text": "main"},
            {"front_text": "Заголовок для ввода-вывода в C", "back_text": "stdio.h"},
            {"front_text": "Ключевое слово для константы в C++", "back_text": "const"},
        ],
    },
    {
        "title": "[Демо] Определения с вариантами ответа",
        "description": "Длинные определения с допустимыми вариантами (aliases) и пояснениями.",
        "front_language": "ru",
        "back_language": "ru",
        "tags": ["demo", "definitions"],
        "cards": [
            {
                "front_text": "Алгоритм, который разбивает задачу на подзадачи и комбинирует их решения",
                "back_text": "разделяй и властвуй",
                "back_explanation": "Типичные примеры: сортировка слиянием, быстрое возведение в степень.",
            },
            {
                "front_text": "Структура данных «первым пришёл — первым вышел»",
                "back_text": "очередь",
            },
            {
                "front_text": "Метод проверки, что элемент находится в отсортированном массиве за O(log n)",
                "back_text": "двоичный поиск",
                "back_explanation": "Также называется «бинарный поиск».",
            },
        ],
    },
]


async def seed_demo_sets(db: AsyncSession, user) -> int:
    created = 0
    for spec in DEMO_SETS:
        await create_set_with_cards(db, owner_id=user.id, **spec)
        created += 1
    await db.commit()
    return created
