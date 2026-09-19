"""Генератор заданий и distractors: воспроизводимость по seed, отсев конфликтов."""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.services.normalization import DEFAULT_POLICY, normalize


@dataclass
class PoolEntry:
    """Элемент снимка материала: одна карточка в одном направлении."""

    card_id: str
    direction: str
    content_version: int
    question_text: str
    question_context: str
    answer_text: str
    answer_context: str
    hint: str
    explanation: str
    example: str
    language: str
    written_check: bool
    accepted: list[str]
    starred: bool = False
    media_answer: list[dict] | None = None
    media_question: list[dict] | None = None


def build_pool_entry(card, direction: str, accepted_front: list[str], accepted_back: list[str], starred: bool, media_front: list[dict], media_back: list[dict]) -> PoolEntry:
    if direction == "front_to_back":
        return PoolEntry(
            card_id=card.id,
            direction=direction,
            content_version=card.content_version,
            question_text=card.front_text,
            question_context=card.front_context,
            answer_text=card.back_text,
            answer_context=card.back_context,
            hint=card.front_hint,
            explanation=card.back_explanation,
            example=card.back_example,
            language=card.back_language or "",
            written_check=card.written_check_back,
            accepted=accepted_back + [card.back_text],
            starred=starred,
            media_answer=media_back,
            media_question=media_front,
        )
    return PoolEntry(
        card_id=card.id,
        direction=direction,
        content_version=card.content_version,
        question_text=card.back_text,
        question_context=card.back_context,
        answer_text=card.front_text,
        answer_context=card.front_context,
        hint=card.back_hint,
        explanation=card.front_explanation,
        example=card.front_example,
        language=card.front_language or "",
        written_check=card.written_check_front,
        accepted=accepted_front + [card.front_text],
        starred=starred,
        media_answer=media_front,
        media_question=media_back,
    )


def eligible_pairs(pool: list[PoolEntry], direction: str, starred_only: bool = False) -> list[PoolEntry]:
    """Пригодные единицы: непустой вопрос и ответ, разрешённое направление."""
    out = []
    for e in pool:
        if e.direction != direction and direction != "both":
            continue
        if not e.question_text.strip() or not e.answer_text.strip():
            continue
        if starred_only and not e.starred:
            continue
        out.append(e)
    return out


def dedupe_by_card(entries: list[PoolEntry], rng: random.Random, both_directions: bool) -> list[PoolEntry]:
    """Один card_id не повторяется в пределах одного направления;
    для both — одна запись на направление, перемешанных между собой."""
    seen: set[tuple[str, str]] = set()
    out = []
    for e in entries:
        key = (e.card_id, e.direction)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def make_distractors(
    target: PoolEntry,
    pool: list[PoolEntry],
    rng: random.Random,
    desired: int = 4,
) -> list[str]:
    """Неправильные варианты из того же материала: уникальные после нормализации,
    не совпадающие с допустимыми ответами вопроса."""
    target_norms = {normalize(a) for a in target.accepted if a.strip()}
    seen = {normalize(t) for t in target_norms}
    candidates: list[str] = []
    for e in pool:
        if e.card_id == target.card_id and e.direction == target.direction:
            continue
        text = e.answer_text
        norm = normalize(text)
        if not norm or norm in seen:
            continue
        # Вариант не должен пересекаться с допустимыми ответами вопроса.
        if norm in target_norms:
            continue
        seen.add(norm)
        candidates.append(text)
    rng.shuffle(candidates)
    return candidates[: max(desired - 1, 0)]


def build_choices(
    target: PoolEntry, pool: list[PoolEntry], rng: random.Random
) -> tuple[list[str], int] | None:
    """Варианты для распознавания: до 4 уникальных; возвращают (варианты, индекс верного).
    None — если меньше двух уникальных вариантов (однозначный вопрос невозможен)."""
    distractors = make_distractors(target, pool, rng, desired=4)
    if not distractors:
        return None
    choices = [target.answer_text] + distractors
    order = list(range(len(choices)))
    rng.shuffle(order)
    shuffled = [choices[i] for i in order]
    correct_index = order.index(0)
    return shuffled, correct_index


def seeded_rng(seed: int) -> random.Random:
    return random.Random(seed)


def source_fingerprint(entries: list[PoolEntry], direction: str, board_size: int) -> str:
    """Отпечаток состава доски для сопоставимости рекордов Match."""
    import hashlib

    parts = [f"{e.card_id}:{e.content_version}:{e.direction}" for e in sorted(entries, key=lambda x: (x.card_id, x.direction))[:board_size]]
    h = hashlib.sha256(("|".join(parts) + f"#{direction}#{board_size}").encode()).hexdigest()
    return h
