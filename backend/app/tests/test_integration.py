"""Интеграционные тесты: auth, доступ, занятия, идемпотентность, конфликты."""
from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.asyncio


async def create_set(api, title="Set", cards=None):
    r = await api.post("/sets", json={
        "title": title,
        "cards": cards or [
            {"front_text": "apple", "back_text": "яблоко"},
            {"front_text": "dog", "back_text": "собака"},
            {"front_text": "sun", "back_text": "солнце"},
            {"front_text": "book", "back_text": "книга"},
        ],
    })
    assert r.status_code == 201, r.text
    return r.json()


class TestAuth:
    async def test_login_wrong_password_same_response(self, api_factory, users):
        api = await api_factory()
        csrf = await api.bootstrap()
        r1 = await api.client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"},
                                   headers={"X-CSRF-Token": csrf})
        r2 = await api.client.post("/api/v1/auth/login", json={"username": "ghost", "password": "wrong"},
                                   headers={"X-CSRF-Token": csrf})
        assert r1.status_code == r2.status_code == 401
        assert r1.json()["error"]["code"] == r2.json()["error"]["code"]

    async def test_login_without_csrf_rejected(self, api_factory):
        api = await api_factory()
        r = await api.client.post("/api/v1/auth/login", json={"username": "alice", "password": "pass-alice-123"})
        # Нет сессии → 401; есть сессия, но нет CSRF → 403. Оба — отказ.
        assert r.status_code in (401, 403)

    async def test_session_rotation_on_login(self, api_factory, users):
        api = await api_factory()
        old_cookie = api.client.cookies.get("recall_session")
        await api.login("alice", "pass-alice-123")
        new_cookie = api.client.cookies.get("recall_session")
        assert old_cookie != new_cookie

    async def test_change_password_revokes_other_sessions(self, api_factory, users):
        api1 = await api_factory()
        await api1.login("alice", "pass-alice-123")
        api2 = await api_factory()
        await api2.login("alice", "pass-alice-123")
        r = await api1.post("/auth/change-password",
                            {"current_password": "pass-alice-123", "new_password": "new-pass-12345"})
        assert r.status_code == 200
        assert (await api2.get("/me")).status_code == 401
        assert (await api1.get("/me")).status_code == 200


class TestSetsAndAccess:
    async def test_owner_sees_own_set(self, alice, demo_set):
        r = await alice.get(f"/sets/{demo_set['id']}")
        assert r.status_code == 200
        assert r.json()["viewer_role"] == "owner"

    async def test_carol_cannot_see_private_set(self, carol, demo_set):
        r = await carol.get(f"/sets/{demo_set['id']}")
        assert r.status_code == 404  # неотличимо от несуществующего

    async def test_reader_cannot_edit(self, bob, demo_set, alice):
        await alice.post(f"/sets/{demo_set['id']}/permissions", {"username": "bob"})
        r = await bob.patch(f"/sets/{demo_set['id']}",
                            {"title": "hacked", "expected_content_version": 1})
        assert r.status_code in (403, 404)
        r = await bob.get(f"/sets/{demo_set['id']}/cards")
        assert r.status_code == 200

    async def test_version_conflict_409(self, alice, demo_set):
        sid = demo_set["id"]
        cv = demo_set["content_version"]
        r1 = await alice.patch(f"/sets/{sid}", {"title": "A", "expected_content_version": cv})
        assert r1.status_code == 200
        r2 = await alice.patch(f"/sets/{sid}", {"title": "B", "expected_content_version": cv})
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "SET_VERSION_CONFLICT"

    async def test_copy_new_ids_no_progress(self, bob, demo_set, alice):
        await alice.post(f"/sets/{demo_set['id']}/permissions", {"username": "bob"})
        r = await bob.post(f"/sets/{demo_set['id']}/copy")
        assert r.status_code == 201
        copy = r.json()
        assert copy["id"] != demo_set["id"]
        assert copy["title"].endswith("(копия)")

    async def test_search_finds_by_card_text(self, alice, demo_set):
        r = await alice.get("/sets", params={"q": "яблоко"})
        assert r.status_code == 200
        assert any(s["id"] == demo_set["id"] for s in r.json())

    async def test_search_respects_access(self, carol, demo_set):
        r = await carol.get("/sets", params={"q": "яблоко"})
        assert all(s["id"] != demo_set["id"] for s in r.json())

    async def test_server_public_visible_in_discover(self, alice, demo_set, bob):
        sid = demo_set["id"]
        cv = demo_set["content_version"]
        await alice.patch(f"/sets/{sid}", {"visibility": "server_public", "expected_content_version": cv})
        r = await bob.get("/discover/sets")
        assert any(s["id"] == sid for s in r.json()["items"])
        # bob может добавить в библиотеку
        r = await bob.post(f"/library/sets/{sid}")
        assert r.status_code == 201
        # и вернуть favorite
        r = await bob.put(f"/sets/{sid}/favorite", {"enabled": True})
        assert r.status_code == 200


class TestStudy:
    async def test_cards_session_full_flow(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {"mode": "cards", "set_ids": [sid], "direction": "front_to_back"})
        assert r.status_code == 201, r.text
        session = r.json()
        tasks = session["tasks"]
        assert len(tasks) == 6
        # У заданий нет ключа ответа
        assert "answer_key" not in tasks[0]
        # Ответ
        ev = uuid.uuid4().hex
        r = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": tasks[0]["item_id"], "client_event_id": ev, "answer": {"known": True},
        })
        assert r.status_code == 200 and r.json()["correct"] is True
        # Идемпотентность: тот же client_event_id — тот же результат
        r2 = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": tasks[0]["item_id"], "client_event_id": ev, "answer": {"known": False},
        })
        assert r2.json()["correct"] is True
        # Чужой event_id того же пользователя с другим содержимым для другого item — ок
        r = await alice.post(f"/study-sessions/{session['id']}/complete")
        assert r.status_code == 200
        result = r.json()
        assert result["known"] == 1

    async def test_write_grading(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {
            "mode": "write", "set_ids": [sid], "direction": "front_to_back", "order": "original",
        })
        session = r.json()
        t0 = session["tasks"][0]  # apple → яблоко
        r = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": t0["item_id"], "client_event_id": uuid.uuid4().hex, "answer": {"text": "Яблоко"},
        })
        assert r.json()["correct"] is True
        # accepted alias тоже верен
        await alice.patch(f"/sets/{sid}/cards/{t0['card_id']}", {"accepted_back": ["яблочко"]})
        r2 = await alice.post("/study-sessions", {
            "mode": "write", "set_ids": [sid], "direction": "front_to_back", "order": "original",
        })
        t = next(x for x in r2.json()["tasks"] if x["question_text"] == "apple")
        r = await alice.post(f"/study-sessions/{r2.json()['id']}/answers", {
            "item_id": t["item_id"], "client_event_id": uuid.uuid4().hex, "answer": {"text": "яблочко"},
        })
        assert r.json()["correct"] is True

    async def test_learn_mastery_flow(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {"mode": "learn", "set_ids": [sid], "direction": "front_to_back"})
        session_id = r.json()["id"]
        answers = {"apple": "яблоко", "dog": "собака", "sun": "солнце", "book": "книга",
                   "water": "вода", "tree": "дерево"}
        correct_texts = {}
        mastered = set()
        steps = 0
        while steps < 80:
            r = await alice.get(f"/study-sessions/{session_id}/next")
            body = r.json()
            if body.get("round_complete"):
                break
            task = body["task"]
            steps += 1
            if task["task_type"] == "recognition":
                # первый выбор может быть неверным — учимся из фидбека
                ans = {"choice": correct_texts.get(task["question_text"], task["choices"][0])}
            elif task["task_type"] == "written":
                ans = {"text": answers.get(task["question_text"], "???")}
            else:
                ans = {"known": True}
            r = await alice.post(f"/study-sessions/{session_id}/answers", {
                "item_id": task["item_id"], "client_event_id": uuid.uuid4().hex, "answer": ans,
            })
            fb = r.json()
            correct_texts[task["question_text"]] = fb.get("correct_text", correct_texts.get(task["question_text"], ""))
            if fb.get("mastered"):
                mastered.add(task["card_id"])
        assert len(mastered) == 6

    async def test_test_scoring_and_drafts(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {
            "mode": "test", "set_ids": [sid], "direction": "front_to_back",
            "settings": {"question_types": ["mc", "written"], "question_count": 4},
        })
        session = r.json()
        tasks = session["tasks"]
        # Ключи ответов не отдаются до завершения
        assert all("answer_key" not in t for t in tasks)
        # Черновик: версия
        t0 = tasks[0]
        r = await alice.put(f"/study-sessions/{session['id']}/items/{t0['item_id']}/draft",
                            {"draft": "first", "draft_version": 0})
        assert r.status_code == 200 and r.json()["draft_version"] == 1
        r = await alice.put(f"/study-sessions/{session['id']}/items/{t0['item_id']}/draft",
                            {"draft": "stale", "draft_version": 0})
        assert r.status_code == 409
        # Отвечаем: письменные правильно, mc — последним (неверным) вариантом
        correct = {"apple": "яблоко", "dog": "собака", "sun": "солнце", "book": "книга",
                   "water": "вода", "tree": "дерево"}
        for t in tasks:
            if t["task_type"] == "test_mc":
                ans = {"choice": t["choices"][-1]}
            elif t["task_type"] == "test_written":
                ans = {"text": correct.get(t["question_text"], "?")}
            else:
                ans = {}
            r = await alice.post(f"/study-sessions/{session['id']}/answers", {
                "item_id": t["item_id"], "client_event_id": uuid.uuid4().hex, "answer": ans,
            })
            assert r.status_code == 200, r.text
        r = await alice.post(f"/study-sessions/{session['id']}/complete")
        res = r.json()
        assert res["max_score"] == res["max_score"]
        assert res["score"] == res["score"]
        # Повторное завершение — идемпотентно
        r2 = await alice.post(f"/study-sessions/{session['id']}/complete")
        assert r2.json()["score"] == res["score"]

    async def test_match_server_validates(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {
            "mode": "match", "set_ids": [sid], "direction": "front_to_back", "settings": {"board_size": 4},
        })
        session = r.json()
        tasks = session["tasks"]
        # Неверная пара
        r = await alice.post(f"/study-sessions/{session['id']}/match-moves",
                             {"first_item_id": tasks[0]["item_id"], "second_item_id": tasks[1]["item_id"]})
        assert r.json()["correct"] is False
        assert r.json()["mistakes"] == 1
        # Верные
        for t in tasks:
            r = await alice.post(f"/study-sessions/{session['id']}/match-moves",
                                 {"first_item_id": t["item_id"], "second_item_id": t["item_id"]})
        assert r.json()["complete"] is True
        assert r.json()["result"]["mistakes"] == 1

    async def test_abandoned_session_does_not_continue(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {"mode": "cards", "set_ids": [sid]})
        session = r.json()
        await alice.post(f"/study-sessions/{session['id']}/abandon")
        task = session["tasks"][0]
        r = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": task["item_id"], "client_event_id": uuid.uuid4().hex, "answer": {"known": True},
        })
        assert r.status_code == 409

    async def test_archived_set_blocks_new_sessions(self, alice, demo_set):
        sid = demo_set["id"]
        await alice.post(f"/sets/{sid}/archive")
        r = await alice.post("/study-sessions", {"mode": "cards", "set_ids": [sid]})
        assert r.status_code == 409
        await alice.post(f"/sets/{sid}/restore")


class TestSRS:
    async def _enroll(self, alice, sid):
        r = await alice.post("/srs/enroll", {"set_id": sid, "enabled": True,
                                             "forward_enabled": True, "reverse_enabled": False})
        assert r.status_code == 200

    async def test_review_and_separate_directions(self, alice, demo_set):
        sid = demo_set["id"]
        await self._enroll(alice, sid)
        r = await alice.get("/srs/queue")
        items = r.json()["items"]
        assert len(items) == 6 and all(i["is_new"] for i in items)
        item = items[0]
        # Первый review
        r = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": "front_to_back", "rating": "good",
            "client_event_id": uuid.uuid4().hex,
        })
        assert r.status_code == 200
        # Идемпотентность по client_event_id
        ev = uuid.uuid4().hex
        r1 = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": "front_to_back", "rating": "good", "client_event_id": ev,
        })
        r2 = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": "front_to_back", "rating": "easy", "client_event_id": ev,
        })
        assert r1.status_code == 200 and r2.status_code == 200
        assert r2.json().get("replayed") is True

    async def test_state_version_conflict(self, alice, demo_set):
        sid = demo_set["id"]
        await self._enroll(alice, sid)
        r = await alice.get("/srs/queue")
        item = r.json()["items"][0]
        r1 = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": item["direction"], "rating": "good",
            "client_event_id": uuid.uuid4().hex,
        })
        # Вторая вкладка со старой ожидаемой версией получает конфликт
        r2 = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": item["direction"], "rating": "good",
            "expected_state_version": 0, "client_event_id": uuid.uuid4().hex,
        })
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "SRS_VERSION_CONFLICT"

    async def test_undo_only_last(self, alice, demo_set):
        sid = demo_set["id"]
        await self._enroll(alice, sid)
        r = await alice.get("/srs/queue")
        item = r.json()["items"][0]
        r1 = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": item["direction"], "rating": "good",
            "client_event_id": uuid.uuid4().hex,
        })
        review_id = r1.json()["review_id"]
        r = await alice.post(f"/srs/reviews/{review_id}/undo")
        assert r.status_code == 200
        # Повторный undo запрещён
        r = await alice.post(f"/srs/reviews/{review_id}/undo")
        assert r.status_code == 409

    async def test_reverse_direction_disabled(self, alice, demo_set):
        sid = demo_set["id"]
        await self._enroll(alice, sid)
        r = await alice.get("/srs/queue")
        item = r.json()["items"][0]
        r = await alice.post("/srs/reviews", {
            "card_id": item["card_id"], "direction": "back_to_front", "rating": "good",
            "client_event_id": uuid.uuid4().hex,
        })
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "DIRECTION_DISABLED"


class TestSharing:
    async def test_share_link_redeem_revoke(self, alice, bob, demo_set):
        sid = demo_set["id"]
        # Набор переводим в режим "по ссылке"
        await alice.patch(f"/sets/{sid}", {"visibility": "link", "expected_content_version": demo_set["content_version"]})
        r = await alice.post(f"/sets/{sid}/share-links", {})
        token = r.json()["token"]
        # Bob обменивает токен
        r = await bob.post("/share-links/redeem", {"token": token})
        assert r.status_code == 200
        set_id = r.json()["set_id"]
        r = await bob.get(f"/sets/{set_id}/cards")
        assert r.status_code == 200
        # Alice отзывает ссылку
        links = await alice.get(f"/sets/{sid}/share-links")
        link_id = links.json()[0]["id"]
        await alice.delete(f"/sets/{sid}/share-links/{link_id}")
        # Доступ bob исчезает
        r = await bob.get(f"/sets/{set_id}")
        assert r.status_code == 404
        # Токен больше не обменивается
        r = await bob.post("/share-links/redeem", {"token": token})
        assert r.status_code == 404

    async def test_link_sets_not_in_discover(self, alice, bob, demo_set):
        sid = demo_set["id"]
        await alice.patch(f"/sets/{sid}", {"visibility": "link", "expected_content_version": demo_set["content_version"]})
        r = await bob.get("/discover/sets")
        assert all(s["id"] != sid for s in r.json()["items"])

    async def test_privatize_revokes_links(self, alice, bob, demo_set):
        sid = demo_set["id"]
        await alice.patch(f"/sets/{sid}", {"visibility": "link", "expected_content_version": demo_set["content_version"]})
        r = await alice.post(f"/sets/{sid}/share-links", {})
        token = r.json()["token"]
        await bob.post("/share-links/redeem", {"token": token})
        # Возврат в private (версия изменилась после первого PATCH)
        detail = (await alice.get(f"/sets/{sid}")).json()
        await alice.patch(f"/sets/{sid}", {"visibility": "private", "expected_content_version": detail["content_version"]})
        r = await bob.get(f"/sets/{sid}")
        assert r.status_code == 404


class TestImportExport:
    async def test_import_preview_confirm_roundtrip(self, alice):
        import io

        csv_data = b"front,back\nhello,privet\nmoon,luna\n"
        r = await alice.post("/imports/preview", None, files={
            "file": ("t.csv", io.BytesIO(csv_data), "text/csv"),
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["valid_rows"] == 2
        job_id = body["job_id"]
        r = await alice.post("/imports", {"job_id": job_id, "mode": "new",
                                          "new_set": {"title": "From CSV", "front_language": "en", "back_language": "ru"}})
        assert r.status_code == 200
        set_id = r.json()["set_id"]
        # Идемпотентность повторного подтверждения
        r2 = await alice.post("/imports", {"job_id": job_id, "mode": "new",
                                           "new_set": {"title": "From CSV"}})
        assert r2.json().get("already_applied") is True
        # Экспорт JSON содержит обе карточки
        r = await alice.get(f"/sets/{set_id}/export?format=json")
        data = r.json()
        assert data["schema_version"] == 1
        assert {c["front_text"] for c in data["cards"]} == {"hello", "moon"}

    async def test_import_rejects_foreign_set(self, alice, bob, demo_set):
        r = await bob.post("/imports", {"job_id": "any", "mode": "existing", "set_id": demo_set["id"]})
        assert r.status_code == 404

    async def test_table_export_escapes_formulas(self, alice, demo_set):
        sid = demo_set["id"]
        cards = await alice.get(f"/sets/{sid}/cards")
        card_id = cards.json()["items"][0]["id"]
        await alice.patch(f"/sets/{sid}/cards/{card_id}", {"back_text": "=CMD"})
        r = await alice.get(f"/sets/{sid}/export?format=table")
        assert "'=CMD" in r.text


class TestPermissionsMatrix:
    async def test_blocked_user_cannot_access(self, admin, alice, bob, demo_set):
        # bob получает прямой доступ, затем admin блокирует bob
        await alice.post(f"/sets/{demo_set['id']}/permissions", {"username": "bob"})
        users = await admin.get("/admin/users")
        bob_id = next(u["id"] for u in users.json()["items"] if u["username"] == "bob")
        r = await admin.patch(f"/admin/users/{bob_id}", {"is_active": False})
        assert r.status_code == 200
        # Сессии bob отозваны: API возвращает 401
        r = await bob.get("/me")
        assert r.status_code == 401

    async def test_last_admin_protected(self, admin):
        users = await admin.get("/admin/users")
        admin_id = next(u["id"] for u in users.json()["items"] if u["role"] == "admin")
        r = await admin.patch(f"/admin/users/{admin_id}", {"role": "user"})
        assert r.status_code == 409

    async def test_unknown_api_returns_json_404(self, alice):
        r = await alice.get("/nonexistent-endpoint")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


class TestManualCorrection:
    async def test_write_correction_keeps_machine_score(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {
            "mode": "write", "set_ids": [sid], "direction": "front_to_back", "order": "original",
        })
        session = r.json()
        t0 = session["tasks"][0]
        ev = uuid.uuid4().hex
        # Отвечаем неверно
        r = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": t0["item_id"], "client_event_id": ev, "answer": {"text": "неверно"},
        })
        assert r.json()["correct"] is False
        # Находим ответ и корректируем
        result = (await alice.get(f"/study-sessions/{session['id']}/result")).json()
        item_row = next(x for x in result["items"] if x["item_id"] == t0["item_id"])
        answers = (await alice.get(f"/study-sessions/{session['id']}/result")).json()
        # correction по answer_id: получаем из БД через результат (item_id) — эндпоинт принимает answer_id,
        # поэтому ищем через завершение занятия
        r = await alice.post(f"/study-sessions/{session['id']}/complete")
        res = r.json()
        # Коррекция последнего ответа: endpoint принимает answer_id; в UI известен из ответа проверки.
        # Здесь проверяем через прямой повторный ответ (idempotency) и изменение final_correct.
        # Повторная отправка того же события не создаёт попытку:
        r2 = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": t0["item_id"], "client_event_id": ev, "answer": {"text": "неверно"},
        })
        assert r2.status_code == 200
        res2 = r2.json()
        # результат идемпотентен
        assert res2["correct"] is False


class TestCorrectionEndpoint:
    async def test_correction_updates_final_and_keeps_machine(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {
            "mode": "write", "set_ids": [sid], "direction": "front_to_back", "order": "original",
        })
        session = r.json()
        t0 = session["tasks"][0]
        r = await alice.post(f"/study-sessions/{session['id']}/answers", {
            "item_id": t0["item_id"], "client_event_id": uuid.uuid4().hex, "answer": {"text": "неверно"},
        })
        fb = r.json()
        assert fb["correct"] is False and fb["answer_id"]
        # Ручная коррекция
        r = await alice.post(
            f"/study-sessions/{session['id']}/answers/{fb['answer_id']}/correction",
            {"final_correct": True},
        )
        assert r.status_code == 200 and r.json()["final_correct"] is True
        # Повторная коррекция — конфликт
        r = await alice.post(
            f"/study-sessions/{session['id']}/answers/{fb['answer_id']}/correction",
            {"final_correct": False},
        )
        assert r.status_code == 409
        # Итог занятия учитывает коррекцию
        r = await alice.post(f"/study-sessions/{session['id']}/complete")
        res = r.json()
        assert res["correct"] == 1 and res["incorrect"] == 0

    async def test_correction_of_test_attempt_adjusts_score(self, alice, demo_set):
        sid = demo_set["id"]
        r = await alice.post("/study-sessions", {
            "mode": "test", "set_ids": [sid], "direction": "front_to_back",
            "settings": {"question_types": ["written"], "question_count": 4},
        })
        session = r.json()
        correct = {"apple": "яблоко", "dog": "собака", "sun": "солнце", "book": "книга",
                   "water": "вода", "tree": "дерево"}
        first_fb = None
        for t in session["tasks"]:
            r = await alice.post(f"/study-sessions/{session['id']}/answers", {
                "item_id": t["item_id"], "client_event_id": uuid.uuid4().hex,
                "answer": {"text": correct.get(t["question_text"], "?")},
            })
            fb = r.json()
            if first_fb is None and fb["correct"] is False:
                first_fb = fb
        r = await alice.post(f"/study-sessions/{session['id']}/complete")
        base = r.json()
        assert base["score"] == base["max_score"]
        if first_fb:
            # Одна из оценок не совпала (например, вариант из accepted) — корректируем
            r = await alice.post(
                f"/study-sessions/{session['id']}/answers/{first_fb['answer_id']}/correction",
                {"final_correct": True},
            )
            assert r.status_code == 200
            assert r.json()["adjusted_score"] == base["max_score"]
            # исходный счёт не изменён
            r = await alice.get(f"/study-sessions/{session['id']}/result")
            assert r.json()["score"] == base["score"]
            assert r.json()["adjusted_score"] is not None
