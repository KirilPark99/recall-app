"""Unit-тесты: алгоритм Learn (порции, освоение, assisted, лимит предъявлений)."""
from __future__ import annotations

import json

from app.services import learn
from app.services.questions import PoolEntry


def entry(card_id: str, direction: str = "front_to_back", written: bool = True) -> PoolEntry:
    return PoolEntry(
        card_id=card_id, direction=direction, content_version=1,
        question_text=f"q-{card_id}", question_context="", answer_text=f"a-{card_id}",
        answer_context="", hint="", explanation="", example="", language="ru",
        written_check=written, accepted=[f"a-{card_id}"], starred=False,
        media_question=None, media_answer=None,
    )


class FakeSession:
    def __init__(self, pool, settings_json: str = "{}"):
        self.pool_json = json.dumps([{**p.__dict__} for p in pool], ensure_ascii=False)
        self.state_json = "{}"
        self.settings_json = settings_json


def make(session_pool, n=6, settings_json: str = "{}"):
    pool = [entry(f"c{i}") for i in range(n)]
    session = FakeSession(pool, settings_json=settings_json)
    learn.init_state(session, pool)
    return session, pool, {f"c{i}:front_to_back": p for i, p in enumerate(pool)}


def test_init_creates_batches_of_ten():
    session, _, _ = make(None, n=25, settings_json=json.dumps({"batch_size": 10}))
    ls = json.loads(session.state_json)["learn"]
    assert len(ls["batches"]) == 3
    assert len(ls["batches"][0]) == 10

    # Default batch size is 7
    session7, _, _ = make(None, n=21)
    ls7 = json.loads(session7.state_json)["learn"]
    assert len(ls7["batches"]) == 3
    assert len(ls7["batches"][0]) == 7


def test_recognition_first_then_written():
    session, pool, by_key = make(None)
    key, task_type = learn.next_task(session, by_key, pool)
    assert task_type == "recognition"


def test_mastery_requires_two_successes_one_written():
    session, pool, by_key = make(None, n=3)
    key, task_type = learn.next_task(session, by_key, pool)
    item = SimpleItem("c0", "front_to_back", "recognition")
    # Первый успех (распознавание) — не освоено.
    res = learn.on_answer(session, item, by_key[key], {"correct": True}, assisted=False)
    assert not res["mastered"]
    # Ошибка → возврат в очередь.
    res = learn.on_answer(session, item, by_key[key], {"correct": False}, assisted=False)
    assert not res["mastered"]
    ls = json.loads(session.state_json)["learn"]
    assert "c0:front_to_back" in ls["queue"]


def test_written_success_completes_mastery():
    session, pool, by_key = make(None, n=2)
    item_rec = SimpleItem("c0", "front_to_back", "recognition")
    learn.on_answer(session, item_rec, by_key["c0:front_to_back"], {"correct": True}, assisted=False)
    item_w = SimpleItem("c0", "front_to_back", "written")
    res = learn.on_answer(session, item_w, by_key["c0:front_to_back"], {"correct": True}, assisted=False)
    assert res["mastered"]
    ls = json.loads(session.state_json)["learn"]
    assert "c0:front_to_back" in ls["mastered"]


def test_assisted_success_does_not_count():
    session, pool, by_key = make(None, n=2)
    item_w = SimpleItem("c0", "front_to_back", "written")
    res = learn.on_answer(session, item_w, by_key["c0:front_to_back"], {"correct": True}, assisted=True)
    assert not res["mastered"]
    ls = json.loads(session.state_json)["learn"]
    # Карточка возвращается в очередь
    assert "c0:front_to_back" in ls["queue"]


def test_presentation_cap_moves_to_failed():
    session, pool, by_key = make(None, n=2)
    item = SimpleItem("c0", "front_to_back", "written")
    for _ in range(learn.MAX_PRESENTATIONS_PER_ROUND):
        learn.on_answer(session, item, by_key["c0:front_to_back"], {"correct": False}, assisted=False)
    ls = json.loads(session.state_json)["learn"]
    assert "c0:front_to_back" in ls["round_failed"]
    assert "c0:front_to_back" not in ls["queue"]


def test_no_written_check_uses_recognition_twice():
    pool = [entry("c0", written=False), entry("c1", written=False)]
    session = FakeSession(pool)
    learn.init_state(session, pool)
    by_key = {"c0:front_to_back": pool[0], "c1:front_to_back": pool[1]}
    key, task_type = learn.next_task(session, by_key, pool)
    # recognition возможен (2+ карточки) → первый тип recognition
    assert task_type == "recognition"
    item = SimpleItem("c0", "front_to_back", "recognition")
    learn.on_answer(session, item, by_key[key], {"correct": True}, assisted=False)
    learn.on_answer(session, item, by_key[key], {"correct": True}, assisted=False)
    ls = json.loads(session.state_json)["learn"]
    assert "c0:front_to_back" in ls["mastered"]


def test_deleted_card_skipped_in_queue():
    session, pool, by_key = make(None, n=2)
    del by_key["c0:front_to_back"]
    key, task_type = learn.next_task(session, by_key, pool)
    # Удалённая карточка пропускается, выдаётся следующая.
    assert key == "c1:front_to_back"


def test_full_batch_recognition_then_written():
    session, pool, by_key = make(None, n=3, settings_json=json.dumps({"batch_size": 3}))

    # Phase 1: All cards must be served as recognition first
    # Card 0
    k0, t0 = learn.next_task(session, by_key, pool)
    assert t0 == "recognition"
    item0 = SimpleItem("c0", "front_to_back", t0)
    res0 = learn.on_answer(session, item0, by_key[k0], {"correct": True}, assisted=False)
    assert not res0["mastered"]

    # Card 1 - error on first try
    k1, t1 = learn.next_task(session, by_key, pool)
    assert t1 == "recognition"
    assert k1 == "c1:front_to_back"
    item1 = SimpleItem("c1", "front_to_back", t1)
    res1 = learn.on_answer(session, item1, by_key[k1], {"correct": False}, assisted=False)
    assert not res1["mastered"]

    # Card 2
    k2, t2 = learn.next_task(session, by_key, pool)
    assert t2 == "recognition"
    assert k2 == "c2:front_to_back"
    item2 = SimpleItem("c2", "front_to_back", t2)
    res2 = learn.on_answer(session, item2, by_key[k2], {"correct": True}, assisted=False)
    assert not res2["mastered"]

    # Card 1 again (since it had an error) - must still be recognition!
    k1_retry, t1_retry = learn.next_task(session, by_key, pool)
    assert k1_retry == "c1:front_to_back"
    assert t1_retry == "recognition"
    res1_retry = learn.on_answer(session, item1, by_key[k1_retry], {"correct": True}, assisted=False)
    assert not res1_retry["mastered"]

    # All 3 cards completed recognition phase. Next tasks must be written!
    written_cards = []
    for _ in range(3):
        kw, tw = learn.next_task(session, by_key, pool)
        assert tw == "written"
        written_cards.append(kw)
        item_w = SimpleItem(kw.split(":")[0], "front_to_back", tw)
        res_w = learn.on_answer(session, item_w, by_key[kw], {"correct": True}, assisted=False)
        assert res_w["mastered"]

    assert set(written_cards) == {"c0:front_to_back", "c1:front_to_back", "c2:front_to_back"}

    # Now all cards mastered in this batch, next_task returns completion
    k_end, status = learn.next_task(session, by_key, pool)
    assert k_end is None
    assert status in ("round_complete", "pool_complete")


class SimpleItem:
    def __init__(self, card_id: str, direction: str, task_type: str):
        self.card_id = card_id
        self.direction = direction
        self.task_type = task_type

