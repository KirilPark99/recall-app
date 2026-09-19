"""Адаптер FSRS (py-fsrs 6.x). Единственная точка вызова библиотеки."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, ReviewLog, Scheduler, State

ALGORITHM_NAME = "fsrs"
ALGORITHM_VERSION = "6.3.2"

RATING_MAP = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}
RATING_NAMES = {1: "again", 2: "hard", 3: "good", 4: "easy"}
STATE_MAP = {int(State.Learning): "learning", int(State.Review): "review", int(State.Relearning): "relearning"}


@dataclass
class SchedulerConfig:
    desired_retention: float = 0.9
    enable_fuzzing: bool = False  # предпросмотр не должен расходиться с принятой оценкой

    def to_params(self) -> dict:
        return {"desired_retention": self.desired_retention, "enable_fuzzing": self.enable_fuzzing}


def make_scheduler(cfg: SchedulerConfig) -> Scheduler:
    return Scheduler(desired_retention=cfg.desired_retention, enable_fuzzing=cfg.enable_fuzzing)


def new_payload() -> dict:
    """Полный сериализуемый payload новой единицы."""
    return {"scheduler": make_scheduler(SchedulerConfig()).to_dict(), "card": Card().to_dict()}


def parse_payload(payload: dict) -> tuple[Scheduler, Card]:
    scheduler = Scheduler.from_dict(payload["scheduler"])
    card = Card.from_dict(payload["card"])
    return scheduler, card


def serialize(scheduler: Scheduler, card: Card) -> dict:
    return {"scheduler": scheduler.to_dict(), "card": card.to_dict()}


def review(payload: dict, rating_name: str, now_utc: datetime, cfg: SchedulerConfig) -> dict:
    """Применяет оценку; возвращает новый payload + производные поля."""
    scheduler, card = parse_payload(payload)
    rating = RATING_MAP[rating_name]
    review_at = now_utc.replace(tzinfo=timezone.utc)
    card, _log = scheduler.review_card(card, rating, review_at)
    return serialize(scheduler, card)


def preview_intervals(payload: dict, cfg: SchedulerConfig) -> dict:
    """Приблизительные интервалы для кнопок оценок (без изменения состояния)."""
    scheduler, card = parse_payload(payload)
    review_at = datetime.now(timezone.utc)
    out = {}
    for name, rating in RATING_MAP.items():
        next_card, _ = scheduler.review_card(card, rating, review_at)
        delta = next_card.due - review_at
        out[name] = _human_interval(delta)
    return out


def _human_interval(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() / 60)
    if minutes < 1:
        return "<1 мин"
    if minutes < 60:
        return f"{minutes} мин"
    hours = int(minutes / 60)
    if hours < 24:
        return f"{hours} ч"
    days = round(delta.total_seconds() / 86400)
    if days < 30:
        return f"{days} дн"
    months = round(days / 30)
    if months < 12:
        return f"{months} мес"
    return f"{round(days / 365)} г"


def state_name(payload: dict) -> str:
    card = Card.from_dict(payload["card"])
    return STATE_MAP.get(int(card.state), "learning")


def due_at(payload: dict) -> datetime:
    card = Card.from_dict(payload["card"])
    return card.due.replace(tzinfo=None)


def is_new(payload: dict) -> bool:
    """Новая = ещё не было принятого SRS review (у состояния нет last_review)."""
    return payload["card"].get("last_review") is None


def stability(payload: dict) -> float | None:
    return payload["card"].get("stability")
