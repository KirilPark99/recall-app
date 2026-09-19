# Эксплуатация

## Процессы

Production — один процесс Uvicorn (API + собранный SPA). Не запускайте
несколько writer-процессов против одной SQLite-базы. Раздельные каталоги
`DATA_DIR` для базы, медиа и backup.

## Здоровье

- `GET /api/v1/health` — процесс жив (базу не трогает).
- `GET /api/v1/ready` — миграции применены, база отвечает.

## Регулярное обслуживание

| Задача | Команда | Частота |
| --- | --- | --- |
| Backup | `python -m app.cli backup create --output data/backups/…` | ежедневно |
| Проверка backup | `python -m app.cli backup verify PATH` | еженедельно |
| Очистка сессий | `python -m app.cli maintenance cleanup-sessions` | еженедельно |
| Мусорные медиа | `python -m app.cli maintenance cleanup-media --dry-run` | по необходимости |
| WAL checkpoint | `python -m app.cli maintenance sqlite-checkpoint` | автоматически; вручную при переносе |

## Логи

Структурированные строки: метод, путь, статус, длительность, request_id.
Не логируются: пароли, cookie, CSRF, share-токены, тексты карточек, ответы.
`request_id` возвращается в `X-Request-ID` и в теле ошибки — сверяйте при разборе.

## Обновление версии

1. `backup create`.
2. Остановить приложение.
3. Обновить код, `pip install -e './backend[dev]'` (или `requirements.lock`), `npm ci && npm run build`.
4. `alembic upgrade head` — повторный запуск ничего не меняет.
5. Запустить, проверить `ready` и smoke-сценарий.

Откат: остановить, восстановить код предыдущей версии и каталог данных
(`data.rollback-*` или backup), при необходимости `alembic downgrade` там, где
он безопасен (описан в миграциях).

## Смена секрета / отзыв сессий

Сессии хранятся хешами, отдельного подписывающего секрета нет. Отзыв всех
сессий пользователя: админка → сброс пароля, либо `auth/logout-all`. Массовый
отзыв: `maintenance cleanup-sessions` не трогает активные; для «выйти у всех»
остановите приложение и выполните `UPDATE sessions SET revoked_at=…`.

## Аварийное восстановление

1. Остановить приложение и workers.
2. `backup restore PATH --confirm` — проверит формат, integrity_check,
   foreign_key_check, распакует во временный каталог, отзовёт старые
   сессии/ссылки и заменит `DATA_DIR`, сохранив прежний как `data.rollback-*`.
3. Запустить, проверить `ready`, войти, открыть набор и SRS-обзор.
4. Не удаляйте единственный предыдущий каталог данных до успешной проверки.
