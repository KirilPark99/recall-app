"""Механизм занятий: создание с снимком материала, проверка ответов, результаты.

Сервер — источник истины: клиент не присылает is_correct/score/next_due.
Ответы идемпотентны по (user_id, client_event_id).
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ApiError
from app.db.base import new_uuid, utcnow
from app.models import (
    ActivityEvent, Card, CardMedia, Media, SnapshotMedia, StudyAnswer,
    StudySession, StudySessionItem, TestAttempt, User, UserCardFlag,
)
from app.schemas.sets import MediaOut
from app.services import learn as learn_algo
from app.services import questions as qgen
from app.services.card_dto import load_set_cards
from app.services.local_dates import local_date_for
from app.services.normalization import DEFAULT_POLICY, check_answer, normalize
from app.services.questions import PoolEntry, build_pool_entry, eligible_pairs

DIRECTIONS = ("front_to_back", "back_to_front")


def _pool_key(entry: PoolEntry) -> str:
    return f"{entry.card_id}:{entry.direction}"


async def resolve_source_sets(
    db: AsyncSession, user: User, set_ids: list[str] | None, folder_id: str | None
) -> list:
    from app.models import Folder, FolderSet
    from app.services.access import get_set_access

    if not set_ids and not folder_id:
        raise ApiError(422, "VALIDATION_ERROR", "Укажите источник: наборы или папку.")
    if folder_id:
        folder = (
            await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id))
        ).scalar_one_or_none()
        if folder is None:
            raise ApiError(404, "NOT_FOUND", "Папка не найдена.")
        rows = (
            await db.execute(select(FolderSet.set_id).where(FolderSet.folder_id == folder.id))
        ).scalars().all()
        set_ids = list(rows)
    sets = []
    for sid in set_ids or []:
        access = await get_set_access(db, user, sid)
        if access.set.archived:
            raise ApiError(409, "SET_ARCHIVED", f"Набор «{access.set.title}» в архиве; занятия по нему недоступны.")
        sets.append(access.set)
    if not sets:
        raise ApiError(422, "EMPTY_SOURCE", "В источнике нет доступных наборов.")
    return sets


async def build_pool(
    db: AsyncSession, user: User, sets: list, direction: str, card_filter: str
) -> list[PoolEntry]:
    """Снимок материала: карточки + допустимые ответы + медиа + звёздочки."""
    pool: list[PoolEntry] = []
    for st in sets:
        cards = await load_set_cards(db, st.id)
        if not cards:
            continue
        card_ids = [c.id for c in cards]
        media_rows = (
            await db.execute(
                select(CardMedia, Media)
                .join(Media, Media.id == CardMedia.media_id)
                .where(CardMedia.card_id.in_(card_ids), Media.deleted_at.is_(None))
                .order_by(CardMedia.position)
            )
        ).all()
        media_by_card: dict[str, dict[str, list[dict]]] = {}
        for cm, m in media_rows:
            dto = {
                "id": m.id, "media_type": m.media_type, "mime_type": m.mime_type,
                "original_name": m.original_name, "description": m.description,
                "width": m.width, "height": m.height, "duration_ms": m.duration_ms,
            }
            media_by_card.setdefault(cm.card_id, {"front": [], "back": []})[cm.side].append(dto)
        starred_ids = set(
            (
                await db.execute(
                    select(UserCardFlag.card_id).where(
                        UserCardFlag.user_id == user.id,
                        UserCardFlag.card_id.in_(card_ids),
                        UserCardFlag.is_starred.is_(True),
                    )
                )
            ).scalars()
        )
        for card in cards:
            if not card.front_text.strip() or not card.back_text.strip():
                continue  # черновики без текста стороны не изучаются
            directions = DIRECTIONS if direction == "both" else [direction]
            for d in directions:
                if d == "front_to_back" and not card.enabled_front_to_back:
                    continue
                if d == "back_to_front" and not card.enabled_back_to_front:
                    continue
                acc_front = [a.answer for a in card.accepted_answers if a.side == "front"]
                acc_back = [a.answer for a in card.accepted_answers if a.side == "back"]
                entry = build_pool_entry(
                    card, d, acc_front, acc_back,
                    starred=card.id in starred_ids,
                    media_front=media_by_card.get(card.id, {}).get("front", []),
                    media_back=media_by_card.get(card.id, {}).get("back", []),
                )
                if card_filter == "starred" and not entry.starred:
                    continue
                pool.append(entry)
    return pool


def serialize_entry(e: PoolEntry) -> dict:
    return {
        "card_id": e.card_id, "direction": e.direction, "content_version": e.content_version,
        "question_text": e.question_text, "question_context": e.question_context,
        "answer_text": e.answer_text, "answer_context": e.answer_context,
        "hint": e.hint, "explanation": e.explanation, "example": e.example,
        "language": e.language, "written_check": e.written_check,
        "accepted": e.accepted, "starred": e.starred,
        "media_question": e.media_question, "media_answer": e.media_answer,
    }


def deserialize_entry(d: dict) -> PoolEntry:
    return PoolEntry(**d)


def snapshot_public(entry: PoolEntry, mode: str) -> dict:
    return {
        "question_text": entry.question_text,
        "question_context": entry.question_context,
        "hint": entry.hint,
        "explanation": entry.explanation,
        "example": entry.example,
        "language": entry.language,
        "media_question": entry.media_question or [],
        "media_answer": entry.media_answer or [],
    }


class StudyService:
    def __init__(self, db: AsyncSession, user: User):
        self.db = db
        self.user = user

    # ---------- создание ----------

    async def create_session(
        self,
        mode: str,
        set_ids: list[str] | None,
        folder_id: str | None,
        direction: str,
        card_filter: str,
        limit: int,
        order: str,
        settings_payload: dict,
    ) -> StudySession:
        if mode not in ("cards", "learn", "write", "spell", "test", "match"):
            raise ApiError(422, "VALIDATION_ERROR", "Неизвестный режим занятия.")
        if direction not in ("front_to_back", "back_to_front", "both"):
            raise ApiError(422, "VALIDATION_ERROR", "Неизвестное направление.")
        sets = await resolve_source_sets(self.db, self.user, set_ids, folder_id)
        pool = await build_pool(self.db, self.user, sets, direction, card_filter)
        if direction == "both":
            pool = [e for e in pool if e.question_text.strip() and e.answer_text.strip()]
        # Один card_id не повторяется в пределах одного направления.
        seen: set[tuple[str, str]] = set()
        deduped = []
        for e in pool:
            key = (e.card_id, e.direction)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        pool = deduped
        rng = qgen.seeded_rng(seed:= (utcnow().microsecond * 100000 + len(pool)))
        seed = settings_payload.pop("_seed", None) or seed
        rng = qgen.seeded_rng(seed)
        if order != "original":
            rng.shuffle(pool)
        if limit and limit > 0:
            if mode == "match":
                # Для Match берём кратное размеру доски число пар.
                board = int(settings_payload.get("board_size") or 6)
                limit = min(limit or board, board)
            pool = pool[:limit]
        if not pool:
            raise ApiError(422, "EMPTY_SOURCE", "В выбранном материале нет пригодных карточек для этого режима.")
        settings_payload = dict(settings_payload or {})

        session = StudySession(
            user_id=self.user.id,
            mode=mode,
            settings_json=json.dumps(settings_payload, ensure_ascii=False),
            sources_json=json.dumps([s.id for s in sets]),
            seed=seed,
            pool_json=json.dumps([serialize_entry(e) for e in pool], ensure_ascii=False),
        )
        if mode == "test":
            await self._validate_test(pool, settings_payload)
            timer = int(settings_payload.get("timer_seconds") or 0)
            if timer > 0:
                session.deadline_at = utcnow() + timedelta(seconds=timer)
        if mode == "match":
            board = int(settings_payload.get("board_size") or 6)
            if board not in (6, 8, 12) and not (2 <= board <= 5):
                raise ApiError(422, "VALIDATION_ERROR", "Размер доски: 6, 8 или 12 пар.")
            if len(pool) < board:
                if len(pool) == 1:
                    raise ApiError(422, "NOT_ENOUGH_CARDS", "Режиму «Подбор пар» нужны минимум две пары.")
                if len(pool) < 2:
                    raise ApiError(422, "NOT_ENOUGH_CARDS", "Недостаточно карточек.")
                settings_payload["board_size"] = len(pool)
                session.settings_json = json.dumps(settings_payload, ensure_ascii=False)
        self.db.add(session)
        await self.db.flush()

        media_ids = set()
        for e in pool:
            for m in (e.media_question or []) + (e.media_answer or []):
                media_ids.add(m["id"])
        for mid in media_ids:
            self.db.add(SnapshotMedia(study_session_id=session.id, media_id=mid))

        if mode in ("cards", "write", "spell"):
            for pos, e in enumerate(pool):
                # Ключ ответа хранится на сервере; DTO отдаёт только tts_text для диктанта.
                key = {
                    "accepted": e.accepted,
                    "correct_text": e.answer_text,
                    "explanation": e.explanation,
                    "example": e.example,
                    "answer_context": e.answer_context,
                }
                self.db.add(
                    StudySessionItem(
                        session_id=session.id, item_uid=new_uuid(), position=pos,
                        card_id=e.card_id, direction=e.direction, content_version=e.content_version,
                        task_type="card" if mode == "cards" else ("spell" if mode == "spell" else "written"),
                        snapshot_json=json.dumps(snapshot_public(e, mode), ensure_ascii=False),
                        answer_key_json=json.dumps(key, ensure_ascii=False),
                    )
                )
        elif mode == "test":
            await self._create_test_items(session, pool, settings_payload, rng)
        elif mode == "match":
            await self._create_match_items(session, pool, settings_payload, rng)
        elif mode == "learn":
            learn_algo.init_state(session, pool)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def _validate_test(self, pool: list[PoolEntry], settings_payload: dict) -> None:
        types = settings_payload.get("question_types") or ["mc", "written"]
        direction = settings_payload.get("direction", "front_to_back")
        entries = eligible_pairs(pool, direction)
        if not entries:
            raise ApiError(422, "EMPTY_SOURCE", "Нет пригодных карточек для теста.")
        n = int(settings_payload.get("question_count") or len(entries))
        n = min(max(n, 1), settings.max_test_questions)
        if "mc" in types and len(entries) < 2:
            types = [t for t in types if t != "mc"]
        if not types:
            raise ApiError(422, "NOT_ENOUGH_CARDS", "Недостаточно материала для выбранных типов вопросов.")
        if n > len(entries) * len(types):
            n = len(entries) * len(types)
        settings_payload["question_count"] = n

    async def _create_test_items(
        self, session: StudySession, pool: list[PoolEntry], sp: dict, rng
    ) -> None:
        types = sp.get("question_types") or ["mc", "written"]
        direction = sp.get("direction", "front_to_back")
        entries = eligible_pairs(pool, direction)
        if direction == "both":
            entries = [e for e in pool]
        # Не ставим встречные вопросы, где один раскрывает ответ на другой.
        entries = _avoid_counterparts(entries, rng)
        n = int(sp.get("question_count") or len(entries))
        plan = []
        cycle = [t for t in ("mc", "written", "tf", "match") if t in types]
        if "match" in cycle and len(entries) < 4:
            cycle = [t for t in cycle if t != "match"]
        if "mc" in cycle and len(entries) < 2:
            cycle = [t for t in cycle if t != "mc"]
        if not cycle:
            raise ApiError(422, "NOT_ENOUGH_CARDS", "Недостаточно материала для выбранных типов вопросов.")
        i = 0
        used: set[str] = set()
        while len(plan) < n and i < len(entries) * 4:
            e = entries[i % len(entries)]
            key = _pool_key(e)
            if key not in used:
                t = cycle[len(plan) % len(cycle)]
                if t == "mc" and qgen.build_choices(e, pool, rng) is None:
                    t = "written"
                if t == "match":
                    if len(entries) - len(plan) < 4:
                        t = "written"
                    else:
                        # Сопоставление занимает 4 карточки.
                        group = []
                        for j in range(i, len(entries)):
                            k2 = _pool_key(entries[j])
                            if k2 not in used:
                                group.append(entries[j])
                                used.add(k2)
                            if len(group) == 4:
                                break
                        plan.append(("match", group))
                        i += 4
                        continue
                used.add(key)
                plan.append((t, e))
            i += 1
        if not plan:
            raise ApiError(422, "NOT_ENOUGH_CARDS", "Не удалось составить тест из этого материала.")
        for pos, (t, payload) in enumerate(plan):
            if t == "match":
                await self._create_match_question(session, pos, payload, rng)
                continue
            e = payload
            choices = None
            if t == "mc":
                built = qgen.build_choices(e, pool, rng)
                if built is None:
                    t = "written"
                else:
                    choices, correct_index = built
            key_json = {
                "accepted": e.accepted,
                "correct_text": e.answer_text,
                "explanation": e.explanation,
                "example": e.example,
                "answer_context": e.answer_context,
            }
            if t == "tf":
                wrong_pool = qgen.make_distractors(e, pool, rng, desired=1)
                statement, is_true = (e.answer_text, True)
                if wrong_pool and rng.random() < 0.5:
                    statement, is_true = wrong_pool[0], False
                key_json["is_true"] = is_true
                snapshot = snapshot_public(e, "test")
                snapshot["statement"] = statement
                snapshot["question_text"] = e.question_text
                item_type = "test_tf"
            elif t == "mc":
                snapshot = snapshot_public(e, "test")
                item_type = "test_mc"
                key_json["choices"] = choices
            else:
                snapshot = snapshot_public(e, "test")
                item_type = "test_written"
            self.db.add(
                StudySessionItem(
                    session_id=session.id, item_uid=new_uuid(), position=pos,
                    card_id=e.card_id, direction=e.direction, content_version=e.content_version,
                    task_type=item_type,
                    snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                    choices_json=json.dumps(choices) if choices else None,
                    answer_key_json=json.dumps(key_json, ensure_ascii=False),
                )
            )

    async def _create_match_question(self, session: StudySession, pos: int, group: list[PoolEntry], rng) -> None:
        lefts = [{"id": g.card_id, "text": g.question_text} for g in group]
        rights = [{"id": g.card_id, "text": g.answer_text} for g in group]
        rng.shuffle(lefts)
        rng.shuffle(rights)
        pairs = [{"left": g.card_id, "right": g.card_id} for g in group]
        key_json = {"pairs": pairs, "lefts": lefts, "rights": rights}
        snapshot = {"match_lefts": lefts, "match_rights": rights, "question_text": ""}
        self.db.add(
            StudySessionItem(
                session_id=session.id, item_uid=new_uuid(), position=pos,
                card_id=group[0].card_id, direction=group[0].direction,
                content_version=group[0].content_version,
                task_type="test_match",
                snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                answer_key_json=json.dumps(key_json, ensure_ascii=False),
            )
        )

    async def _create_match_items(self, session: StudySession, pool: list[PoolEntry], sp: dict, rng) -> None:
        board = int(sp.get("board_size") or 6)
        entries = [e for e in pool if e.question_text.strip() and e.answer_text.strip()]
        entries = _distinct_pairs(entries, board)
        if len(entries) < board:
            board = len(entries)
        entries = entries[:board]
        for pos, e in enumerate(entries):
            snap = snapshot_public(e, "match")
            snap["match_right_text"] = e.answer_text
            self.db.add(
                StudySessionItem(
                    session_id=session.id, item_uid=new_uuid(), position=pos,
                    card_id=e.card_id, direction=e.direction, content_version=e.content_version,
                    task_type="match_pair",
                    snapshot_json=json.dumps(snap, ensure_ascii=False),
                )
            )
        state = json.loads(session.state_json or "{}")
        state["match"] = {"matched": [], "mistakes": 0, "board_size": board}
        session.state_json = json.dumps(state, ensure_ascii=False)

    # ---------- получение ----------

    async def get_session(self, session_id: str) -> StudySession:
        st = (
            await self.db.execute(
                select(StudySession).where(StudySession.id == session_id, StudySession.user_id == self.user.id)
            )
        ).scalar_one_or_none()
        if st is None:
            raise ApiError(404, "NOT_FOUND", "Занятие не найдено.")
        return st

    async def get_item(self, session: StudySession, item_id: str) -> StudySessionItem:
        item = (
            await self.db.execute(
                select(StudySessionItem).where(
                    StudySessionItem.id == item_id, StudySessionItem.session_id == session.id
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise ApiError(404, "NOT_FOUND", "Задание не найдено в этом занятии.")
        return item

    def _check_deadline(self, session: StudySession) -> bool:
        return session.deadline_at is not None and session.deadline_at <= utcnow()

    async def require_active(self, session: StudySession) -> None:
        if session.status in ("completed", "abandoned", "voided"):
            raise ApiError(409, "SESSION_FINISHED", "Занятие уже завершено.")
        if self._check_deadline(session):
            raise ApiError(409, "TEST_DEADLINE_EXCEEDED", "Время теста истекло; завершите тест.")

    # ---------- ответы ----------

    async def submit_answer(
        self, session: StudySession, item_id: str, client_event_id: str,
        answer: dict, latency_ms: int | None,
    ) -> dict:
        # Идемпотентность: тот же client_event_id возвращает сохранённый результат.
        existing = (
            await self.db.execute(
                select(StudyAnswer).where(
                    StudyAnswer.user_id == self.user.id,
                    StudyAnswer.client_event_id == client_event_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.session_id != session.id:
                raise ApiError(409, "EVENT_CONFLICT", "Событие с этим ID относится к другому занятию.")
            item = await self.get_item(session, existing.item_id)
            return await self._feedback(session, item, existing.raw_answer or "", existing)

        item = await self.get_item(session, item_id)
        await self.require_active(session)
        pool_entry = await self._entry_for_item(session, item)
        feedback = self._grade(session, item, pool_entry, answer)
        assisted = bool(answer.get("used_hint")) or item.revealed
        attempt_no = (
            await self.db.execute(
                select(StudyAnswer.attempt_no)
                .where(StudyAnswer.session_id == session.id, StudyAnswer.item_id == item.id)
                .order_by(StudyAnswer.attempt_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or 0
        answer_type = feedback.pop("answer_type", "auto")
        raw = feedback.pop("raw_answer", None)
        rec_id = None
        rec = StudyAnswer(
            session_id=session.id,
            item_id=item.id,
            user_id=self.user.id,
            client_event_id=client_event_id,
            attempt_no=attempt_no + 1,
            raw_answer=raw if isinstance(raw, str) else (json.dumps(raw, ensure_ascii=False) if raw is not None else None),
            normalized_answer=feedback.pop("normalized_answer", None),
            machine_correct=feedback["correct"] if answer_type in ("auto", "self_assess") else feedback["correct"],
            final_correct=feedback["correct"],
            assisted=assisted,
            answer_type=answer_type,
            latency_ms=min(int(latency_ms or 0), 10 * 60 * 1000) or None,
            fingerprint=f"{item.id}:{item.content_version}:{feedback['correct']}",
        )
        try:
            self.db.add(rec)
            await self.db.flush()
            rec_id = rec.id
        except IntegrityError:
            await self.db.rollback()
            latest_ans = (
                await self.db.execute(
                    select(StudyAnswer)
                    .where(StudyAnswer.session_id == session.id, StudyAnswer.item_id == item.id)
                    .order_by(StudyAnswer.attempt_no.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest_ans is not None:
                item = await self.get_item(session, item_id)
                return await self._feedback(session, item, latest_ans.raw_answer or "", latest_ans)
            raise
        item.status = "answered"
        item.draft_answer = None
        session.last_activity_at = utcnow()
        session.current_index = max(session.current_index, item.position + 1)
        # learn: обновление состояния алгоритма; статус освоения — в feedback
        if session.mode == "learn":
            res = learn_algo.on_answer(session, item, pool_entry, feedback, assisted)
            feedback.update(res)
        await self.db.commit()
        feedback["answer_id"] = rec_id
        return feedback

    async def _entry_for_item(self, session: StudySession, item: StudySessionItem) -> PoolEntry | None:
        """Полный вход пула для grading (включая accepted)."""
        pool = json.loads(session.pool_json)
        for d in pool:
            if d["card_id"] == item.card_id and d["direction"] == item.direction:
                return deserialize_entry(d)
        return None

    def _grade(self, session: StudySession, item: StudySessionItem, entry: PoolEntry | None, answer: dict) -> dict:
        t = item.task_type
        policy = DEFAULT_POLICY
        base = {"assisted": bool(answer.get("used_hint")) or item.revealed}
        if t in ("written", "spell", "recognition", "test_written", "test_mc"):
            if t in ("recognition", "test_mc"):
                chosen = str(answer.get("choice") or "")
                key = json.loads(item.answer_key_json or "{}") if item.answer_key_json else None
                correct_text = (key or {}).get("correct_text", entry.answer_text if entry else "")
                ok = bool(chosen) and normalize(chosen) == normalize(correct_text)
                return {**base, "correct": ok, "answer_type": "auto", "raw_answer": chosen,
                        "correct_text": correct_text, "explanation": (key or {}).get("explanation", ""),
                        "example": (key or {}).get("example", "")}
            raw = str(answer.get("text") or "")
            accepted = (json.loads(item.answer_key_json or "{}").get("accepted") if item.answer_key_json else None) or (entry.accepted if entry else [entry.answer_text if entry else ""])
            res = check_answer(raw, accepted, policy)
            key = json.loads(item.answer_key_json or "{}") if item.answer_key_json else {}
            fb = {**base, "correct": res.correct, "answer_type": "auto", "raw_answer": raw,
                  "normalized_answer": res.normalized_answer, "possible_typo": res.possible_typo,
                  "correct_text": key.get("correct_text", entry.answer_text if entry else ""),
                  "explanation": key.get("explanation", entry.explanation if entry else ""),
                  "example": key.get("example", entry.example if entry else ""),
                  "answer_context": key.get("answer_context", "")}
            return fb
        if t == "self_assess" or t == "card":
            known = bool(answer.get("known"))
            return {**base, "correct": known, "answer_type": "self_assess",
                    "raw_answer": "known" if known else "unknown",
                    "correct_text": entry.answer_text if entry else "", "explanation": entry.explanation if entry else ""}
        if t == "test_tf":
            key = json.loads(item.answer_key_json or "{}")
            is_true = bool(answer.get("is_true"))
            return {**base, "correct": is_true == key.get("is_true"), "answer_type": "auto",
                    "raw_answer": "true" if is_true else "false",
                    "correct_text": key.get("correct_text"), "statement": item_snapshot(item).get("statement"),
                    "explanation": key.get("explanation", "")}
        if t == "test_match":
            key = json.loads(item.answer_key_json or "{}")
            mapping = answer.get("mapping") or {}
            pair_results = [
                {"left": p["left"], "correct": mapping.get(p["left"]) == p["right"]}
                for p in key["pairs"]
            ]
            return {**base, "correct": all(p["correct"] for p in pair_results), "answer_type": "auto",
                    "raw_answer": json.dumps(mapping, ensure_ascii=False),
                    "pair_results": pair_results, "pairs": key["pairs"]}
        raise ApiError(422, "VALIDATION_ERROR", "Неподдерживаемый тип задания.")

    async def _feedback(self, session: StudySession, item: StudySessionItem, raw: str | None, rec: StudyAnswer) -> dict:
        """Повторная выдача сохранённого ответа (retry после потери сети)."""
        entry = await self._entry_for_item(session, item)
        if rec.answer_type == "self_assess":
            answer = {"known": raw == "known", "used_hint": rec.assisted}
        else:
            answer = {"text": raw or "", "choice": raw or "", "used_hint": rec.assisted}
        try:
            parsed = json.loads(raw) if raw and raw.startswith("{") else None
            if isinstance(parsed, dict):
                answer = {**answer, **parsed}
        except Exception:
            pass
        fb = self._grade(session, item, entry, answer)
        fb["replayed"] = True
        return fb


def item_snapshot(item: StudySessionItem) -> dict:
    return json.loads(item.snapshot_json or "{}")


def _avoid_counterparts(entries: list[PoolEntry], rng) -> list[PoolEntry]:
    """Для both: не ставим рядом f2b и b2f одной карточки (вопрос раскрыл бы ответ)."""
    out: list[PoolEntry] = []
    recent: dict[str, int] = {}
    for i, e in enumerate(entries):
        if e.direction == "back_to_front" and recent.get(e.card_id) == i - 1:
            entries.append(e)  # откладываем в конец
            continue
        out.append(e)
        recent[e.card_id] = i
    return out


def _distinct_pairs(entries: list[PoolEntry], board: int) -> list[PoolEntry]:
    """Только визуально различимые пары: уникальные question/answer после нормализации."""
    seen_q: set[str] = {}
    seen_a: set[str] = set()
    out = []
    for e in entries:
        nq, na = normalize(e.question_text), normalize(e.answer_text)
        if nq in seen_a or na in seen_a:
            continue
        if nq in seen_q and seen_q.get(nq) != e.card_id:
            continue
        seen_q[nq] = e.card_id
        seen_a.add(na)
        out.append(e)
        if len(out) >= board:
            break
    return out
