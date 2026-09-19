# Тестирование

## Запуск

```bash
# Backend: unit + интеграционные (временный файл SQLite, без production-базы)
.venv/bin/python -m pytest backend/app/tests -q

# Frontend: строгий typecheck и сборка
cd frontend && npx tsc -b --noEmit && npm run build

# Всё вместе
./scripts/check.sh
```

## Уровни

| Уровень | Что проверяет | Примеры |
| --- | --- | --- |
| Unit (`test_checkers.py`) | нормализация, AnswerChecker, допустимые ответы, distractors | C≠C++, resume≠résumé, кириллическая/латинская «a», alias-коллизии |
| Unit (`test_learn.py`) | алгоритм Learn | порции по 10, освоение = 2 успеха (≥1 письменный), assisted не считается, лимит 4 предъявлений |
| Unit (`test_fsrs_adapter.py`) | адаптер FSRS | новая единица, интервалы оценок, payload round-trip, предпросмотр без мутации |
| Integration (`test_integration.py`) | API-сценарии на временной базе | доступ (owner/reader/carol), 409 версий, идемпотентность ответов и SRS-review, undo, share-link redeem/revoke, импорт/экспорт, блокировка с отзывом сессий, JSON 404 на неизвестный API |

## Ключевые regression-проверки

- по API теста не отдаётся ключ ответа до завершения (`answer_key` отсутствует в DTO);
- повторное завершение теста не удваивает результат (идемпотентный complete);
- частичный PATCH карточки не стирает текст (учёт `model_fields_set`);
- `GET /auth/csrf` не разлогинивает и не ломает параллельные вкладки
  (детерминированный CSRF-токен сессии);
- неизвестный API-маршрут возвращает JSON 404, а не HTML SPA;
- SRS: раздельные состояния направлений, конфликт версии состояния, undo
  только последнего review.

## Принципы

- Инъекция времени: FSRS-адаптер принимает `now` параметром; системные часы не меняются.
- Тесты используют временный файл SQLite (не in-memory), созданный `alembic upgrade head`.
- Rate limiter очищается между тестами (`clear_rate_limits`).
- TTS transport в pytest замокан; реальные голоса и аудиовыход проверяются вручную.
