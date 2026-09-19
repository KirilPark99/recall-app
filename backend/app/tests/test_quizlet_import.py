"""Tests for Quizlet parsing, preview, and import workflows."""
from __future__ import annotations

import pytest
from app.services.quizlet_service import (
    is_quizlet_url,
    extract_quizlet_id,
    parse_quizlet_text,
)



class TestQuizletServiceUnit:
    """Unit tests for Quizlet text parser and URL extractor."""

    def test_parse_tab_separated(self):
        text = "cat\tкот\ndog\tсобака\nfish\tрыба"
        cards = parse_quizlet_text(text)
        assert len(cards) == 3
        assert cards[0]["front_text"] == "cat"
        assert cards[0]["back_text"] == "кот"
        assert cards[1]["front_text"] == "dog"
        assert cards[1]["back_text"] == "собака"
        assert cards[2]["front_text"] == "fish"
        assert cards[2]["back_text"] == "рыба"

    def test_parse_dash_separated(self):
        text = "hello - привет\nworld — мир\ngoodbye – пока"
        cards = parse_quizlet_text(text)
        assert len(cards) == 3
        assert cards[0]["front_text"] == "hello"
        assert cards[0]["back_text"] == "привет"
        assert cards[1]["front_text"] == "world"
        assert cards[1]["back_text"] == "мир"
        assert cards[2]["front_text"] == "goodbye"
        assert cards[2]["back_text"] == "пока"

    def test_parse_colon_separated(self):
        text = "sun : солнце\nmoon :: луна"
        cards = parse_quizlet_text(text)
        assert len(cards) == 2
        assert cards[0]["front_text"] == "sun"
        assert cards[0]["back_text"] == "солнце"
        assert cards[1]["front_text"] == "moon"
        assert cards[1]["back_text"] == "луна"

    def test_parse_alternating_lines(self):
        text = "apple\nяблоко\nbanana\nбанан\norange\nапельсин"
        cards = parse_quizlet_text(text, term_delimiter="alternating")
        assert len(cards) == 3
        assert cards[0]["front_text"] == "apple"
        assert cards[0]["back_text"] == "яблоко"
        assert cards[1]["front_text"] == "banana"
        assert cards[1]["back_text"] == "банан"
        assert cards[2]["front_text"] == "orange"
        assert cards[2]["back_text"] == "апельсин"

    def test_parse_double_newline_card_delimiter(self):
        text = "one\tодин\n\ntwo\tдва\n\nthree\tтри"
        cards = parse_quizlet_text(text, card_delimiter="double_newline")
        assert len(cards) == 3
        assert cards[0]["front_text"] == "one"
        assert cards[1]["front_text"] == "two"
        assert cards[2]["front_text"] == "three"

    def test_filters_quizlet_ui_artifacts(self):
        text = """1
cat\tкот
Click card to see definition
dog\tсобака
42
fish\tрыба"""
        cards = parse_quizlet_text(text)
        assert len(cards) == 3
        terms = [c["front_text"] for c in cards]
        assert "cat" in terms
        assert "dog" in terms
        assert "fish" in terms
        assert not any(t.isdigit() for t in terms)
        assert not any("Click card" in t for t in terms)

    def test_url_detection(self):
        assert is_quizlet_url("https://quizlet.com/12345678/biology-flash-cards/")
        assert not is_quizlet_url("http://quizlet.com/ru/999999/test-set/")
        assert is_quizlet_url("https://www.quizlet.com/456789")
        assert is_quizlet_url("123456789")
        assert not is_quizlet_url("https://google.com")
        assert not is_quizlet_url("random text without url")
        for unsafe in (
            "http://127.0.0.1:8123/?quizlet.com/123456",
            "https://localhost/quizlet.com/123456",
            "https://quizlet.com.evil.test/123456",
            "https://evil.test/?quizlet.com/123456",
            "https://user:pass@quizlet.com/123456",
            "https://quizlet.com:8443/123456",
        ):
            assert not is_quizlet_url(unsafe)

    def test_url_id_extraction(self):
        assert extract_quizlet_id("https://quizlet.com/987654321/spanish-verbs-flash-cards/") == "987654321"
        assert extract_quizlet_id("https://quizlet.com/ru/123456/test/") == "123456"
        assert extract_quizlet_id("555444333") == "555444333"

    def test_parse_json_format(self):
        json_text = '[{"term": "casa", "definition": "дом"}, {"term": "sol", "definition": "солнце"}]'
        cards = parse_quizlet_text(json_text)
        assert len(cards) == 2
        assert cards[0]["front_text"] == "casa"
        assert cards[0]["back_text"] == "дом"
        assert cards[1]["front_text"] == "sol"
        assert cards[1]["back_text"] == "солнце"

    def test_parse_html_format(self):
        html_text = '''
        <html><body>
          <div class="SetPageTerms-term">
            <span class="SetPageTerm-wordText">hola</span>
            <span class="SetPageTerm-definitionText">привет</span>
          </div>
          <div class="SetPageTerms-term">
            <span class="SetPageTerm-wordText">amigo</span>
            <span class="SetPageTerm-definitionText">друг</span>
          </div>
        </body></html>
        '''
        cards = parse_quizlet_text(html_text)
        assert len(cards) == 2
        assert cards[0]["front_text"] == "hola"
        assert cards[0]["back_text"] == "привет"
        assert cards[1]["front_text"] == "amigo"
        assert cards[1]["back_text"] == "друг"

    def test_parse_html_with_embedded_json(self):
        html_text = '''
        <!DOCTYPE html><html><head><title>Spanish 101 Flashcards | Quizlet</title></head><body>
        <script>
        {"responses":[{"models":{"studiableItem":[{"cardSides":[{"sideId":1,"label":"word","media":[{"type":1,"plainText":"perro"}]},{"sideId":2,"label":"definition","media":[{"type":1,"plainText":"собака"}]}]}]}}]}
        </script>
        </body></html>
        '''
        cards = parse_quizlet_text(html_text)
        assert len(cards) == 1
        assert cards[0]["front_text"] == "perro"
        assert cards[0]["back_text"] == "собака"

    def test_parse_page_copy_with_headers_and_odd_lines(self):
        page_copy = '''
        Spanish Level A1
        Terms in this set (3)
        1 / 3
        gato
        кот
        2 / 3
        perro
        собака
        3 / 3
        pájaro
        птица
        Other sets by this creator
        Leave the first review
        '''
        cards = parse_quizlet_text(page_copy)
        assert len(cards) == 3
        terms = [c["front_text"] for c in cards]
        defs = [c["back_text"] for c in cards]
        assert "gato" in terms and "кот" in defs
        assert "perro" in terms and "собака" in defs
        assert "pájaro" in terms and "птица" in defs


class TestQuizletApiEndpoints:
    """Integration tests for Quizlet API endpoints."""
    pytestmark = pytest.mark.asyncio

    async def test_quizlet_parse_endpoint(self, alice):
        r = await alice.post("/imports/quizlet/parse", json={
            "text": "red\tкрасный\ngreen\tзеленый\nblue\tсиний",
            "term_delimiter": "tab",
            "card_delimiter": "newline",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["total_rows"] == 3
        assert data["valid_rows"] == 3
        assert len(data["cards"]) == 3
        assert data["cards"][0]["front_text"] == "red"
        assert data["cards"][0]["back_text"] == "красный"

    async def test_quizlet_parse_alternating(self, alice):
        r = await alice.post("/imports/quizlet/parse", json={
            "text": "Monday\nПонедельник\nTuesday\nВторник",
            "term_delimiter": "alternating",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["cards"]) == 2
        assert data["cards"][0]["front_text"] == "Monday"
        assert data["cards"][0]["back_text"] == "Понедельник"

    async def test_quizlet_parse_empty_returns_422(self, alice):
        r = await alice.post("/imports/quizlet/parse", json={
            "text": "   ",
        })
        assert r.status_code in (400, 422)

    async def test_import_preview_with_quizlet_format(self, alice):
        # multipart/form-data preview
        data = {
            "format": "quizlet",
            "text": "water\tвода\nfire\tогонь\nearth\tземля\nair\tвоздух",
            "term_delimiter": "tab",
            "card_delimiter": "newline",
        }
        csrf = await alice.bootstrap()
        r = await alice.client.post(
            "/api/v1/imports/preview",
            data=data,
            headers={"X-CSRF-Token": csrf},
            cookies=alice.client.cookies,
        )
        assert r.status_code == 200
        res = r.json()
        assert "job_id" in res
        assert res["total_rows"] == 4
        assert res["valid_rows"] == 4
        assert len(res["sample"]) == 4

        # Now confirm the import to create a new set
        job_id = res["job_id"]
        confirm_r = await alice.post("/imports", json={
            "job_id": job_id,
            "mode": "new",
            "new_set": {
                "title": "Elements from Quizlet",
                "front_language": "en",
                "back_language": "ru",
            },
        })
        assert confirm_r.status_code == 200
        created = confirm_r.json()
        set_id = created["set_id"]
        assert set_id is not None

        # Verify cards were created in the new set
        cards_r = await alice.get(f"/sets/{set_id}/cards")
        assert cards_r.status_code == 200
        cards_data = cards_r.json()
        assert cards_data["total"] == 4
        terms = [c["front_text"] for c in cards_data["items"]]
        assert "water" in terms and "fire" in terms and "earth" in terms and "air" in terms

    async def test_import_confirm_with_sparse_quizlet_rows(self, alice, test_db, users):
        """Проверяет импорт набора, когда строки содержат только front_text и back_text (без front_context и т.д.)."""
        import json
        from app.models import ImportJob
        from app.db.base import utcnow

        staging = json.dumps([
            {"line": 1, "front_text": "apple", "back_text": "яблоко"},
            {"line": 2, "front_text": "banana", "back_text": "банан"},
        ])
        job = ImportJob(
            user_id=users["alice"],
            status="ready",
            source_format="quizlet",
            fingerprint="test_fp_sparse",
            preview_json=json.dumps({"format": "quizlet", "valid_rows": 2}),
            staging_json=staging,
            errors_json="[]",
            finished_at=utcnow(),
        )
        async with test_db() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        confirm_r = await alice.post("/imports", json={
            "job_id": job_id,
            "mode": "new",
            "new_set": {
                "title": "Sparse Quizlet Set",
            },
        })
        assert confirm_r.status_code == 200
        res = confirm_r.json()
        assert res["ok"] is True
        assert res["set_id"] is not None
        assert res["applied"] == 2

    async def test_batch_card_addition_for_editor(self, alice):
        # 1. Create an empty set
        set_res = await alice.post("/sets", json={
            "title": "Batch Add Test",
            "description": "Testing editor Quizlet batch add",
        })
        assert set_res.status_code == 201
        set_id = set_res.json()["id"]

        # 2. Simulate Quizlet cards batch added from Editor
        batch_cards = [
            {"front_text": "run", "back_text": "бежать", "front_hint": "verb", "back_hint": "глагол"},
            {"front_text": "fast", "back_text": "быстро", "front_hint": "adv", "back_hint": "наречие"},
            {"front_text": "jump", "back_text": "прыгать", "front_hint": "", "back_hint": ""},
        ]
        batch_r = await alice.post(f"/sets/{set_id}/cards/batch", json={
            "cards": batch_cards,
        })
        assert batch_r.status_code == 201
        applied = batch_r.json()["applied"]
        assert applied == 3

        # 3. Verify cards in set
        cards_r = await alice.get(f"/sets/{set_id}/cards")
        assert cards_r.status_code == 200
        items = cards_r.json()["items"]
        assert len(items) == 3
        assert items[0]["front_text"] == "run"
        assert items[0]["front_hint"] == "verb"
        assert items[1]["front_text"] == "fast"
        assert items[2]["front_text"] == "jump"

    async def test_quizlet_folder_url_detection(self):
        from app.services.quizlet_service import is_quizlet_folder_url, is_quizlet_url
        assert is_quizlet_folder_url("https://quizlet.com/join/TESTCODE") is True
        assert is_quizlet_folder_url("https://quizlet.com/class/31816981/") is True
        assert is_quizlet_folder_url("https://quizlet.com/example_user/folders/sample-folder") is True
        assert is_quizlet_folder_url("https://quizlet.com/folders/31816981") is True
        assert is_quizlet_folder_url("https://quizlet.com/000000000/flash-cards/") is False
        assert is_quizlet_folder_url("https://quizlet.com/000000000/") is False
        assert is_quizlet_url("https://quizlet.com/join/TESTCODE") is True

    async def test_quizlet_folder_import_endpoint(self, alice, monkeypatch):
        from unittest.mock import AsyncMock
        import app.api.imports_api as imp_api

        mock_folder_data = {
            "folder_title": "Example Quizlet Class",
            "total_sets": 2,
            "imported_sets": [
                {
                    "id": "1001",
                    "title": "Unit 1 Greetings",
                    "cards": [
                        {"front_text": "Hello", "back_text": "Привет"},
                        {"front_text": "Goodbye", "back_text": "Пока"},
                    ],
                },
                {
                    "id": "1002",
                    "title": "Unit 2 Numbers",
                    "cards": [
                        {"front_text": "One", "back_text": "Один"},
                        {"front_text": "Two", "back_text": "Два"},
                    ],
                },
            ],
            "total_cards": 4,
        }

        monkeypatch.setattr(
            imp_api,
            "fetch_quizlet_folder_with_ezsolver",
            AsyncMock(return_value=mock_folder_data),
        )

        res = await alice.post("/imports/quizlet/folder/import", json={
            "url": "https://quizlet.com/join/TESTCODE",
            "folder_name": "Example Quizlet Class",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["folder_name"] == "Example Quizlet Class"
        assert data["imported_sets_count"] == 2
        assert data["total_cards_count"] == 4
        folder_id = data["folder_id"]
        assert folder_id is not None

        # Verify folder exists in /folders
        folders_res = await alice.get("/folders")
        assert folders_res.status_code == 200
        folders = folders_res.json()
        target_folder = next((f for f in folders if f["id"] == folder_id), None)
        assert target_folder is not None
        assert target_folder["name"] == "Example Quizlet Class"
        assert target_folder["set_count"] == 2


class TestQuizletProxyAndHeadlessSettings:
    """Тесты настроек прокси и headless-режима в админ-панели и quizlet_service."""

    def test_prepare_browser_proxy_empty(self):
        from app.services.quizlet_service import _prepare_browser_proxy
        args, ext = _prepare_browser_proxy("")
        assert args == []
        assert ext is None

    def test_prepare_browser_proxy_without_auth(self):
        from app.services.quizlet_service import _prepare_browser_proxy
        args, ext = _prepare_browser_proxy("http://127.0.0.1:8080")
        assert args == ["--proxy-server=http://127.0.0.1:8080"]
        assert ext is None

    def test_prepare_browser_proxy_with_auth(self):
        import os, json, shutil
        from app.services.quizlet_service import _prepare_browser_proxy
        args, ext = _prepare_browser_proxy("http://testuser:secretpass@127.0.0.1:8080")
        assert args == ["--proxy-server=http://127.0.0.1:8080"]
        assert ext is not None
        assert os.path.isdir(ext)
        manifest_path = os.path.join(ext, "manifest.json")
        bg_path = os.path.join(ext, "background.js")
        assert os.path.isfile(manifest_path)
        assert os.path.isfile(bg_path)
        with open(bg_path, encoding="utf-8") as f:
            bg_code = f.read()
            assert "testuser" in bg_code
            assert "secretpass" in bg_code
        shutil.rmtree(ext, ignore_errors=True)

    async def test_admin_quizlet_settings_get_and_patch(self, admin):
        # 1. GET settings
        get_res = await admin.get("/admin/settings")
        assert get_res.status_code == 200
        data = get_res.json()
        assert "quizlet_proxy_url" in data
        assert "quizlet_headless" in data
        assert data["quizlet_headless"] is True

        # 2. PATCH settings
        patch_res = await admin.patch("/admin/settings", json={
            "quizlet_proxy_url": "http://user:pass@proxy.example.com:3128",
            "quizlet_headless": False,
        })
        assert patch_res.status_code == 200
        pdata = patch_res.json()
        assert pdata["quizlet_proxy_url"] == "http://user:pass@proxy.example.com:3128"
        assert pdata["quizlet_headless"] is False

        # 3. Verify persistence with another GET
        get_res2 = await admin.get("/admin/settings")
        assert get_res2.status_code == 200
        assert get_res2.json()["quizlet_proxy_url"] == "http://user:pass@proxy.example.com:3128"
        assert get_res2.json()["quizlet_headless"] is False

    async def test_admin_proxy_test_validation(self, admin):
        # Empty proxy test should fail with 400
        empty_res = await admin.post("/admin/proxy/test", json={"proxy_url": ""})
        # If no saved proxy, 400 NO_PROXY_SPECIFIED
        assert empty_res.status_code in (400, 200)

        # Invalid scheme
        bad_scheme = await admin.post("/admin/proxy/test", json={"proxy_url": "ftp://proxy.com:21"})
        assert bad_scheme.status_code == 400
        assert bad_scheme.json()["error"]["code"] == "INVALID_PROXY_SCHEME"
