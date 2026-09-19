"""Unit-тесты: FSRS-адаптер."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.srs import adapter as fsrs


NOW = datetime(2026, 9, 13, 12, 0, 0)


def test_new_payload_is_new():
    p = fsrs.new_payload()
    assert fsrs.is_new(p)
    assert fsrs.state_name(p) == "learning"  # новая карта FSRS в состоянии Learning


def test_review_moves_due_forward():
    p = fsrs.new_payload()
    cfg = fsrs.SchedulerConfig()
    after = fsrs.review(p, "good", NOW, cfg)
    due = fsrs.due_at(after)
    assert due > NOW
    assert not fsrs.is_new(after)
    assert fsrs.state_name(after) in ("learning", "review", "relearning")


def test_ratings_give_different_intervals():
    p = fsrs.new_payload()
    cfg = fsrs.SchedulerConfig()
    easy = fsrs.due_at(fsrs.review(p, "easy", NOW, cfg))
    again = fsrs.due_at(fsrs.review(p, "again", NOW, cfg))
    assert easy > again


def test_again_after_review_is_short():
    p = fsrs.new_payload()
    cfg = fsrs.SchedulerConfig()
    after_good = fsrs.review(p, "good", NOW, cfg)
    after_again = fsrs.review(after_good, "again", NOW + timedelta(days=10), cfg)
    assert fsrs.due_at(after_again) < NOW + timedelta(days=10) + timedelta(days=1)


def test_payload_roundtrip():
    p = fsrs.new_payload()
    cfg = fsrs.SchedulerConfig()
    after = fsrs.review(p, "hard", NOW, cfg)
    # Сериализация/десериализация сохраняет смысл
    import json

    restored = json.loads(json.dumps(after))
    due1 = fsrs.due_at(after)
    due2 = fsrs.due_at(restored)
    assert due1 == due2


def test_preview_does_not_mutate():
    p = fsrs.new_payload()
    cfg = fsrs.SchedulerConfig()
    before = fsrs.due_at(p)
    intervals = fsrs.preview_intervals(p, cfg)
    assert set(intervals.keys()) == {"again", "hard", "good", "easy"}
    assert fsrs.due_at(p) == before
