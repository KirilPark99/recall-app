# Архитектура Recall

Модульный монолит: FastAPI (backend) + React/Vite (frontend) + SQLite. Production — один Uvicorn worker раздаёт API и собранный frontend под одним origin; dev — Vite proxy `/api/v1`.

## Backend (`backend/app/`)

```
api/        HTTP-роутеры (auth, me, sets, cards, folders, tags, media, imports,
            exports, discover, sharing, study, srs, stats, admin) — только HTTP + валидация
core/       config (pydantic-settings), db (async engine + pragmas), security (argon2, токены),
            errors (единый формат ошибок), ratelimit
db/         base.py
models/     SQLAlchemy 2.x модели (см. Доменную модель)
schemas/    Pydantic 2.x DTO: request/response models, ошибки
services/   бизнес-логика: access, normalization/checker, questions, learn,
            study_service, results_service, srs_service, media_service,
            sets_service/cards_service, share_service, search, quizlet_service
srs/        adapter.py — единственная точка вызова библиотеки fsrs
cli.py      create-admin, seed-demo; cli_backup.py — backup и maintenance
tests/      unit + integration (pytest, pytest-asyncio, временный SQLite-файл)
```

Ключевые правила:

- Сервер — источник истины: проверка ответа, оценка, расписание FSRS вычисляются на backend; клиент не присылает доверенные поля (`is_correct`, `score`, `next_due`).
- Авторизация: серверные сессии — непрозрачный токен в HttpOnly cookie, хеш + метаданные в БД; kind = `pre_auth` | `authenticated`. CSRF bootstrap через `GET /auth/csrf` (pre-auth сессия). Cookie SameSite=Lax; CSRF-проверка на всех mutating запросах через header `X-CSRF-Token`.
- Каждая транзакция короткая; SQLite: WAL, foreign_keys=ON, busy_timeout=5000.
- Все даты — UTC ISO 8601; локальные даты пользователя считаются по IANA timezone.

## Доменная модель (основное)

`users`, `sessions`, `sets`, `cards` (+`accepted_answers`), `user_preferences`,
`library_entries`, `user_card_flags`, `srs_enrollments`, `srs_settings`,
`tags`/`set_tags`, `folders`/`folder_sets`, `set_permissions`, `share_links`,
`media`/`card_media`, `study_sessions`/`study_session_items`/`study_answers`,
`srs_states`/`srs_reviews`, `daily_goals`, `activity_events`, `test_attempts`,
`match_records`, `import_jobs`, `audit_events`.

Единица памяти SRS — `(user_id, card_id, direction)`. Состояния хранят полный
`scheduler_payload` библиотеки FSRS + `due_at/last_review_at/state_name/version`;
журнал `srs_reviews` хранит before/after payload. Отмена — только последнего review.

Занятие фиксирует снимок использованных карточек (текст, ответы, версии), seed и
порядок; результаты относятся к снимку. `study_answers` — уникальность
`(user_id, client_event_id)` (идемпотентность retry).

Версии: `sets.content_version` (optimistic concurrency, 409 при конфликте),
`cards.content_version`, `srs_states.version` (conditional update).

## Frontend (`frontend/src/`)

React 18 + TypeScript (strict) + Vite + Tailwind CSS 4 (токены через CSS-переменные,
dark через класс). React Router, TanStack Query (один QueryClient, инвалидация по
scope пользователя). Иконки lucide-react. Собственный i18n-модуль (`ru`/`en`
словари + pluralization для русского). Графики — маленькие SVG-компоненты.

```
api/        типизированный клиент fetch (CSRF, 401→login, ошибки)
i18n/       словари ru/en, t(), plural
pages/      Login, Home, Sets, SetDetail, Editor, Study/*, Review, Stats,
            Settings, Discover, Admin, Share
components/ общие UI (диалоги, тоасты, скелетоны, empty states)
state/      auth-контекст, тема, локаль
```

Занятия и редактор хранят состояние в памяти + сервер; localStorage не используется
для материала и секретов.

## Доступ

- `set.visibility`: `private` (владелец + прямые разрешения), `server_public` (все вошедшие), `link` (секретная ссылка, redeem → разрешение `source=share_link`).
- Токены ссылок: случайные, хранится только SHA-256; redeem по `POST /share-links/redeem` (fragment `#token=...`).
- Отзыв ссылки отключает производные разрешения; прямые разрешения независимы.
- Проверка прав — единый `services/access.py`, применяется до пагинации/подсчёта.

## Импорт/экспорт

Preview (staging + fingerprint) → подтверждение одной атомарной транзакцией;
идемпотентно. Экспорт: CSV/TSV/JSON/ZIP (schema_version, manifest, media) и
«для таблиц» с защитой от formula injection. Backup сервера — отдельная админская
операция (SQLite backup API + manifest + media).

## Ошибки

Единый формат `{"error": {code, message, details, request_id}}`; без stack trace,
SQL и секретов. request_id в каждом ответе и логах.
