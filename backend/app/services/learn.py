"""Алгоритм режима «Обучение»: детерминированный, порции до 10, освоение = 2 успеха подряд."""
from __future__ import annotations

import json

from app.services.questions import PoolEntry

MAX_PRESENTATIONS_PER_ROUND = 4


def init_state(session, pool: list[PoolEntry]) -> None:
    """Разбивка на порции и начальное состояние очереди."""
    sp = json.loads(getattr(session, "settings_json", None) or "{}")
    batch_size = int(sp.get("batch_size") or 7)
    keys = [f"{e.card_id}:{e.direction}" for e in pool]
    batches = [keys[i : i + batch_size] for i in range(0, len(keys), batch_size)]
    state = json.loads(session.state_json or "{}")
    state["learn"] = {
        "batches": batches,
        "batch_index": 0,
        "batch_phase": "choice",
        "queue": [],
        "card": {},
        "mastered": [],
        "round_failed": [],
        "hints_used": 0,
        "repeat_batch": None,
    }
    session.state_json = json.dumps(state, ensure_ascii=False)


def _lstate(session) -> dict:
    return json.loads(session.state_json)["learn"]


def _save(session, ls: dict) -> None:
    state = json.loads(session.state_json)
    state["learn"] = ls
    session.state_json = json.dumps(state, ensure_ascii=False)


def _card_state(ls: dict, key: str) -> dict:
    return ls["card"].setdefault(
        key, {
            "successes": 0,
            "written_success": False,
            "recognition_success": False,
            "presentations": 0,
            "types_done": [],
            "revealed": False,
        }
    )


def _written_available(pool_by_key: dict, key: str) -> bool:
    e = pool_by_key.get(key)
    return bool(e and e.written_check)


def _recognition_possible(pool_by_key: dict, key: str, pool: list[PoolEntry]) -> bool:
    e = pool_by_key.get(key)
    if e is None:
        return False
    from app.services.questions import make_distractors
    import random

    return len(make_distractors(e, pool, random.Random(0), desired=2)) >= 1


def on_answer(session, item, entry, feedback: dict, assisted: bool) -> dict:
    """Обновляет состояние Learn по принятому ответу. Возвращает статус карточки."""
    ls = _lstate(session)
    key = f"{item.card_id}:{item.direction}"
    cs = _card_state(ls, key)
    cs["presentations"] += 1
    if assisted and feedback.get("answer_type") != "self_assess":
        feedback["assisted"] = True
    correct = bool(feedback.get("correct"))
    pool_dict = session_pool_by_key(session)
    written_available = _written_available(pool_dict, key)
    rec_possible = _recognition_possible(pool_dict, key, list(pool_dict.values()))

    if item.task_type == "written":
        cs["types_done"] = sorted(set(cs["types_done"]) | {"written"})
    if item.task_type == "recognition":
        cs["types_done"] = sorted(set(cs["types_done"]) | {"recognition"})

    if correct and not assisted:
        cs["successes"] += 1
        if item.task_type == "written":
            cs["written_success"] = True
        if item.task_type == "recognition":
            cs["recognition_success"] = True

        independent_ok = False
        if cs["written_success"] and (cs["recognition_success"] or not rec_possible or cs["successes"] >= 2):
            independent_ok = True
        elif not written_available and cs["successes"] >= 2:
            independent_ok = True
        elif not rec_possible and (cs["written_success"] or cs["successes"] >= 1):
            independent_ok = True

        if independent_ok:
            _mark_mastered(ls, key)
            _save(session, ls)
            return {"mastered": True}
        else:
            # Успех на этапе выбора — убираем карточку из текущей очереди фазы выбора,
            # чтобы перейти к следующим карточкам порции
            if key in ls["queue"]:
                ls["queue"].remove(key)
    elif not correct:
        # Ошибка: возврат карточки в конец очереди текущей фазы
        if key in ls["queue"]:
            ls["queue"].remove(key)
        ls["queue"].append(key)
    else:
        # Успех с подсказкой/раскрытием: не самостоятельный, требуется ещё попытка
        if key in ls["queue"]:
            ls["queue"].remove(key)
        ls["queue"].append(key)

    if cs["presentations"] >= MAX_PRESENTATIONS_PER_ROUND and key not in ls["mastered"]:
        if key in ls["queue"]:
            ls["queue"].remove(key)
        if key not in ls["round_failed"]:
            ls["round_failed"].append(key)

    _save(session, ls)
    return {"mastered": key in ls["mastered"], "round_failed": key in ls["round_failed"]}


def session_pool_by_key(session) -> dict[str, PoolEntry]:
    from app.services.study_service import deserialize_entry

    return {f"{d['card_id']}:{d['direction']}": deserialize_entry(d) for d in json.loads(session.pool_json)}


def _mark_mastered(ls: dict, key: str) -> None:
    if key not in ls["mastered"]:
        ls["mastered"].append(key)
    if key in ls["queue"]:
        ls["queue"].remove(key)


def next_task(session, pool_by_key: dict[str, PoolEntry], pool: list[PoolEntry]):
    """Возвращает (key, task_type) следующего задания или (None, status)."""
    ls = _lstate(session)

    while True:
        # 1. Если текущая очередь пуста:
        if not ls["queue"]:
            phase = ls.get("batch_phase", "choice")
            if ls["batch_index"] == 0 and not ls.get("repeat_batch"):
                # Начинаем первую порцию
                batch = ls["batches"][0]
                ls["batch_index"] = 1
                ls["batch_phase"] = "choice"
                ls["queue"] = [
                    k for k in batch
                    if k not in ls["mastered"] and k not in ls["round_failed"]
                ]
            elif phase == "choice":
                # Завершена фаза выбора (recognition) текущей порции!
                # Переходим к фазе написания (written) для этой же порции
                current_batch = ls.get("repeat_batch") or ls["batches"][ls["batch_index"] - 1]
                written_candidates = [
                    k for k in current_batch
                    if k not in ls["mastered"] and k not in ls["round_failed"]
                ]
                if written_candidates:
                    ls["batch_phase"] = "written"
                    ls["queue"] = written_candidates
                else:
                    ls["batch_phase"] = "round_done"
                    if ls.get("repeat_batch"):
                        ls["repeat_batch"] = None
                    _save(session, ls)
                    if ls["batch_index"] >= len(ls["batches"]):
                        return None, "pool_complete"
                    return None, "round_complete"
            elif phase == "written":
                # Завершена фаза написания текущей порции!
                ls["batch_phase"] = "round_done"
                if ls.get("repeat_batch"):
                    ls["repeat_batch"] = None
                _save(session, ls)
                if ls["batch_index"] >= len(ls["batches"]):
                    return None, "pool_complete"
                return None, "round_complete"
            elif phase == "round_done":
                # Пользователь перешел к следующей порции (next_batch)
                if ls.get("repeat_batch"):
                    ls["repeat_batch"] = None
                if ls["batch_index"] < len(ls["batches"]):
                    batch = ls["batches"][ls["batch_index"]]
                    ls["batch_index"] += 1
                    ls["batch_phase"] = "choice"
                    ls["queue"] = [
                        k for k in batch
                        if k not in ls["mastered"] and k not in ls["round_failed"]
                    ]
                else:
                    _save(session, ls)
                    return None, "pool_complete"

        # 2. Выбираем следующую карточку из очереди
        while ls["queue"]:
            key = ls["queue"][0]
            cs = _card_state(ls, key)
            if cs["presentations"] >= MAX_PRESENTATIONS_PER_ROUND:
                ls["queue"].pop(0)
                if key not in ls["round_failed"]:
                    ls["round_failed"].append(key)
                continue
            if key not in pool_by_key:
                # Карточка удалена: пропускаем
                ls["queue"].pop(0)
                continue
            task_type = _pick_task_type(ls, key, pool_by_key, pool)
            if task_type is None:
                ls["queue"].pop(0)
                continue
            _save(session, ls)
            return key, task_type


def _pick_task_type(ls: dict, key: str, pool_by_key: dict, pool: list[PoolEntry]) -> str | None:
    cs = _card_state(ls, key)
    written_ok = _written_available(pool_by_key, key)
    recognition_ok = _recognition_possible(pool_by_key, key, pool)
    phase = ls.get("batch_phase", "choice")

    if phase == "choice":
        if recognition_ok and not cs.get("recognition_success"):
            return "recognition"
        if written_ok:
            return "written"
        if recognition_ok:
            return "recognition"
        return "self_assess"
    else:  # "written"
        if written_ok and not cs.get("written_success"):
            return "written"
        if recognition_ok:
            return "recognition"
        if written_ok:
            return "written"
        return "self_assess"


def round_summary(session) -> dict:
    ls = _lstate(session)
    pool_keys = list(session_pool_by_key(session).keys())
    return {
        "mastered": ls["mastered"],
        "round_failed": ls["round_failed"],
        "hints_used": ls["hints_used"],
        "remaining": [k for k in pool_keys if k not in ls["mastered"] and k not in ls["round_failed"]],
        "batch_index": ls["batch_index"],
        "total_batches": len(ls["batches"]),
    }


def start_repeat_failed_round(session) -> dict:
    """«Повторить ошибки»: неудачные карточки снова в очереди той же порции."""
    ls = _lstate(session)
    failed = list(ls["round_failed"])
    ls["round_failed"] = []
    ls["repeat_batch"] = list(failed)
    ls["batch_phase"] = "choice"
    ls["queue"] = list(failed)
    for key in failed:
        cs = _card_state(ls, key)
        cs["presentations"] = 0
        cs["written_success"] = False
        cs["recognition_success"] = False
        cs["successes"] = 0
        cs["types_done"] = []
    _save(session, ls)
    return {"requeued": failed}


def on_reveal(session, key: str) -> None:
    ls = _lstate(session)
    cs = _card_state(ls, key)
    cs["revealed"] = True
    ls["hints_used"] += 1
    _save(session, ls)
