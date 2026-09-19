# Прогресс

## Статус: ядро завершено, все обязательные сценарии реализованы и проверены

Backend: unit- и интеграционные pytest-тесты; интеграционная схема создаётся Alembic-миграциями.
Frontend: tsc strict без ошибок, production build собирается.
Браузерная проверка: вход, наборы, Cards, Test (с финализацией), результат,
SRS-страница, настройки ru/en + темы, мобильный вид 360 px, светлая/тёмная тема.

## Компоненты

### Backend (`backend/app/`)
- core/: config (pydantic-settings), db (WAL, FK, busy_timeout), security
  (Argon2id, токены, детерминированный CSRF-токен сессии), errors (единый формат
  + request_id), ratelimit (in-memory окно).
- models/: 33 таблицы + FTS5 `search_fts` (миграция 69c4151aa633, downgrade→upgrade проверен).
- api/: auth, me, sets, cards (+media attach, star, swap), folders+tags, media,
  imports, exports, discover, sharing (links/redeem/permissions), study (создание,
  ответы, skip/reveal/draft, complete, learn/next, match-moves, correction),
  srs (overview/queue/enroll/settings/reviews/undo/reset/history), stats,
  admin (users/settings/status/audit/backups).
- services/: access, checker/normalization, questions, learn, study_service,
  results, srs_service (FSRS через app/srs/adapter), share, media, sets/cards.
- cli.py + cli_backup.py: create-admin, seed-demo, backup create/verify/restore,
  maintenance cleanup-sessions/cleanup-media/sqlite-checkpoint.

### Frontend (`frontend/src/`)
- Каркас: React 18 + TS strict + Vite 6 + Tailwind 4 (CSS-токены light/dark),
  TanStack Query, React Router, lucide-react, собственный i18n ru/en с
  плюрализацией.
- Страницы: Login, Home, Sets, SetDetail, Editor (автосохранение, 409-диалог,
  DnD + кнопки/позиция, медиа, поиск, массовые операции, предпросмотр),
  StudyConfig, Study (Cards/Write/Spell runners, LearnRunner, TestRunner с
  черновиками/таймером/навигатором, MatchRunner), Result, Review (SRS), Stats,
  Settings, Folders, Discover, Share (redeem через fragment), Admin.

## Исправленные дефекты (root cause)
1. `GET /auth/csrf` перезаписывал авторизованную сессию pre-auth → разлогин на
   каждый F5. Решение: csrf-токен детерминирован от сессии (HMAC), /auth/csrf
   переиспользует живую сессию и мигрирует старые csrf_hash.
2. Частичный PATCH карточки применял пустые дефолты (риск стирания текста).
   Решение: apply только полей из `model_fields_set`.
3. SRS-обзор использовал несуществующий `func.case` → TypeError.
4. Второй review одной единицы падал (payload не десериализовывался из TEXT).
5. Коррекция ответа нарушала уникальность (session, item, attempt_no) →
   отдельный диапазон номеров + проверка по correction_of_id.
6. TestRunner UI не отправлял финальные ответы — сервер считал 0 из 0 ответов.
   Решение: финализация сначала POST /answers для каждого отвеченного вопроса.
7. `/study/new` не имел маршрута → StudyPage пытался открыть занятие "new".

## Запуск
- Backend: `.venv/bin/uvicorn app.main:app --port 8000` (из backend/; пакет
  установлен editable в venv). Тестовый admin: testadmin/testpass123 (dev-база).
- Frontend dev: `cd frontend && npm run dev`; production build уже в frontend/dist
  и раздаётся backend'ом (SPA fallback, JSON 404 на /api/v1/*).
- Проверки: `./scripts/check.sh`.

## NOT VERIFIED
- Реальное звучание TTS (нет аудиовыхода в среде) — Web Speech API и fallback
  сообщения проверены.
- HTTPS reverse proxy — описан в README, не прогонялся с реальным TLS.
