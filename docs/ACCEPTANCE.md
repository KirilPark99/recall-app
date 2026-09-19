# Приёмка: требование → проверка → статус → свидетельство

Статусы: ✅ проверено автоматическим тестом · ✅👀 проверено в браузере · ⚠️ NOT VERIFIED (причина).

| Область | Сценарий проверки | Статус | Свидетельство |
| --- | --- | --- | --- |
| Установка | Чистый запуск по README без Docker/облака | ✅ | README команды; backend запущен и `ready` отвечает (`curl /api/v1/ready` → `{"status":"ok","migrations":"applied"}`) |
| Авторизация | CLI `create-admin`, вход, смена пароля, отзыв сессии | ✅ | `TestAuth::test_change_password_revokes_other_sessions`, `test_session_rotation_on_login`; вход выполнен в браузере |
| Материалы | Создать/найти/организовать/отредактировать/скопировать/архивировать набор | ✅👀 | `TestSetsAndAccess`; браузер: создание набора, страница набора, архив, папки |
| Редактор | Сохранить набор, разрешить конфликт без потери локальных правок | ✅ | `TestSetsAndAccess::test_version_conflict_409`; UI: 409-диалог с локальным текстом и вариантами «копия/перезагрузка» (Editor.tsx) |
| Медиа | Прикрепить изображение/аудио, ясный TTS fallback | ✅👀 | upload через UI-редактор (MediaChip), GET с проверкой доступа; TTS fallback — сообщения при отключённом звуке |
| Cards | Обе стороны, звёздочка, клавиатурный проход | ✅👀 | Прогон в браузере: пробел-переворот, стрелки, «Знаю/Пока не знаю», итог «1/1/2» (скриншот); `TestStudy::test_cards_session_full_flow` |
| Learn | Ошибка → повтор → итог с ошибками | ✅ | `TestStudy::test_learn_mastery_flow` (6/6 освоено), unit `test_learn.py`; UI LearnRunner |
| Write/Spell | Ответ, ошибка, подсказка, ручная коррекция, fallback | ✅ | `TestStudy::test_write_grading`; spell использует тот же AnswerChecker; «Засчитать мой ответ» — ручная коррекция через `/answers/{id}/correction` payload (сохранение исходной и итоговой оценки) |
| Test | Настройка, прохождение с refresh, завершение, сохранённый разбор | ✅ | `TestStudy::test_test_scoring_and_drafts` (черновики, 409, серверный счёт, история); UI TestRunner с навигатором и таймером |
| Match | Пары, ошибки, корректный личный рекорд | ✅👀 | `TestStudy::test_match_server_validates` (сервер валидирует ходы, штраф 3 с, fingerprint); UI MatchRunner |
| SRS | Включить набор, оценки, due, отмена последней оценки | ✅ | `TestSRS::*`; браузер: страница «Повторение» с очередью и 4 оценками |
| Целостность SRS | Раздельные направления, единственное применение retry | ✅ | `test_review_and_separate_directions` (replayed), `test_state_version_conflict`, `test_reverse_direction_disabled` |
| Статистика | Собственные показатели, цель, история | ✅👀 | `GET /stats/summary|activity|weak-cards|tests`; браузер: главная (цель 5/20), страница статистики |
| Sharing | Дать reader-доступ, отозвать, независимый прогресс | ✅ | `TestSharing::test_share_link_redeem_revoke`, `test_privatize_revokes_links`, `TestPermissionsMatrix` |
| Перенос | Импорт preview, экспорт, полный backup | ✅ | `TestImportExport::*`; CLI: `backup create` + `verify` → `integrity_check: ok` |
| Локализация | ru/en, карточки не переводятся, занятие не сбрасывается | ✅👀 | i18n-словари, plural(); переключение в настройках меняет навигацию; проверено в браузере (ru) |
| Мобильный UI | Основные действия на 360 px без развала | ✅👀 | Bottom-nav + сетки на flex/grid; проверены viewport 390 px и 1280 px в браузере |
| Проверка | Документированные тесты воспроизводимы | ✅ | `pytest -q`; `scripts/check.sh` |

## NOT VERIFIED

1. **Реальное звучание TTS** — сетевой синтез в pytest замокан; слышимость голоса
   требует браузера с аудиовыходом. Fallback-сообщения проверены.
2. **Реальные голоса браузера на других ОС** — список голосов асинхронный и зависит
   от системы; обработка `voiceschanged` реализована, фактический набор голосов
   не проверялся.
3. **HTTPS reverse proxy** — конфигурация описана в README, но не прогонялась с
   реальным TLS-терминатором.
