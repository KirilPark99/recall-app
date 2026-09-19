"""Тесты для высококачественного нейросетевого TTS."""
import pytest
from pathlib import Path

from app.services.tts_service import format_rate, resolve_voice


def test_format_rate():
    assert format_rate(1.0) == "+0%"
    assert format_rate(1.25) == "+25%"
    assert format_rate(0.8) == "-20%"
    assert format_rate(0.1) == "-50%"  # Clamped to 0.5
    assert format_rate(3.0) == "+100%"  # Clamped to 2.0


def test_resolve_voice():
    # Russian Cyrillic
    assert resolve_voice("Привет мир") == "ru-RU-SvetlanaNeural"
    assert resolve_voice("Привет мир", gender="male") == "ru-RU-DmitryNeural"

    # English text
    assert resolve_voice("Hello world", lang="en") == "en-US-AvaNeural"
    assert resolve_voice("Hello world", lang="en", gender="male") == "en-US-AndrewNeural"

    # German text
    assert resolve_voice("Guten Tag", lang="de") == "de-DE-KatjaNeural"

    # Script mismatch: Cyrillic text with lang='en' should resolve to Russian
    assert resolve_voice("Яблоко", lang="en") == "ru-RU-SvetlanaNeural"

    # Explicit voice request
    assert resolve_voice("Hello", requested_voice="custom-voice") == "custom-voice"


@pytest.mark.asyncio
async def test_tts_voices_endpoint(alice):
    resp = await alice.get("/tts/voices")
    assert resp.status_code == 200
    data = resp.json()
    assert "voices" in data
    assert len(data["voices"]) > 0
    langs = {v["language"] for v in data["voices"]}
    assert "ru" in langs
    assert "en" in langs


@pytest.mark.asyncio
async def test_tts_endpoint_validation(alice):
    resp = await alice.get("/tts")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tts_synthesis_is_mocked(alice, monkeypatch, tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake-mp3")

    async def fake_synthesize(**_kwargs) -> Path:
        return audio

    monkeypatch.setattr("app.api.tts.synthesize_speech", fake_synthesize)
    resp = await alice.get("/tts", params={"text": "Hello test", "lang": "en"})
    assert resp.status_code == 200
    assert resp.content == b"fake-mp3"
