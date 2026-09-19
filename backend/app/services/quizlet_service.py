"""Сервис парсинга и импорта карточек из Quizlet (текст, экспорт, URL, HTML, JSON)."""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import platform
import random
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.services.ezsolver import (
    do_human_click,
    ensure_xvfb,
    find_chrome,
    get_profile_dir,
    handle_challenges,
    prepare_browser_proxy,
    start_browser,
    stop_browser,
)

logger = logging.getLogger("recall.quizlet")

_ezsolver_sem = asyncio.Semaphore(1)


def _quizlet_url(text: str) -> tuple[str, str] | None:
    """Return a safe Quizlet host/path pair, never a user-controlled origin."""
    try:
        parsed = urlsplit(text.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or not (host == "quizlet.com" or host.endswith(".quizlet.com"))
        ):
            return None
    except ValueError:
        return None
    return host, parsed.path


def is_quizlet_folder_url(text: str) -> bool:
    """Проверяет, является ли строка ссылкой на папку, класс или группу Quizlet."""
    parsed = _quizlet_url(text)
    if not parsed:
        return False
    _host, t = parsed
    return bool(
        re.search(r"/(?:[a-z]{2,5}(?:-[a-z]{2,5})?/)?(?:join|class|classes|folder|folders)/", t, re.I)
        or re.search(r"/[^/]+/(?:folders|classes)/", t, re.I)
    )


def is_quizlet_url(text: str) -> bool:
    """Проверяет, является ли строка ссылкой на Quizlet или числовым ID набора."""
    return extract_quizlet_id(text) is not None or is_quizlet_folder_url(text)


def extract_quizlet_id(text: str) -> str | None:
    """Извлекает ID набора Quizlet из ссылки или строки."""
    t = text.strip()
    if re.match(r"^\d{6,14}$", t):
        return t
    parsed = _quizlet_url(t)
    if parsed:
        _host, path = parsed
        m = re.match(r"/(?:[a-z]{2,5}(?:-[a-z]{2,5})?/)*(\d+)(?:/|$)", path, re.I)
        if m:
            return m.group(1)
    return None


def canonical_quizlet_folder_url(text: str) -> str | None:
    parsed = _quizlet_url(text)
    if not parsed or not is_quizlet_folder_url(text):
        return None
    host, path = parsed
    query = urlsplit(text.strip()).query
    return urlunsplit(("https", host, path, query, ""))


def _find_chrome() -> str:
    """Определяет путь к исполняемому файлу Chrome/Chromium для EzSolver."""
    if os.environ.get("CHROME_PATH") and os.path.isfile(os.environ["CHROME_PATH"]):
        return os.environ["CHROME_PATH"]

    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
        home = os.path.expanduser("~")
        candidates.extend(sorted(glob.glob(os.path.join(home, ".cache/ms-playwright/chromium-*/chrome-linux64/chrome")), reverse=True))
        candidates.extend(sorted(glob.glob(os.path.join(home, ".cache/ms-playwright/chromium-*/chrome-linux/chrome")), reverse=True))
        candidates.extend(glob.glob(os.path.join(home, ".config/google-chrome/chrome")))

    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError("Исполняемый файл Chrome не найден на сервере.")


def _start_xvfb_if_needed(headless: bool = True) -> subprocess.Popen | None:
    """Для Linux запускает Xvfb, если DISPLAY не задан и запуск не в headless-режиме."""
    if headless:
        return None
    if platform.system() != "Linux":
        return None
    if os.environ.get("DISPLAY"):
        return None
    try:
        proc = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x900x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
        time.sleep(0.5)
        return proc
    except Exception:
        return None


async def _get_quizlet_settings(db: AsyncSession | None = None) -> tuple[str, bool]:
    """Возвращает (proxy_url, headless) из настроек сервера."""
    from app.services.settings_service import get_setting

    if db is not None:
        proxy_url = await get_setting(db, "quizlet_proxy_url", "")
        headless = await get_setting(db, "quizlet_headless", True)
        return (proxy_url or "").strip(), bool(headless)
    try:
        from app.core.db import get_sessionmaker
        sm = get_sessionmaker()
        async with sm() as session:
            proxy_url = await get_setting(session, "quizlet_proxy_url", "")
            headless = await get_setting(session, "quizlet_headless", True)
            return (proxy_url or "").strip(), bool(headless)
    except Exception:
        return "", True


def _prepare_browser_proxy(proxy_url: str) -> tuple[list[str], str | None]:
    """
    Разбирает URL прокси и готовит аргументы командной строки Chrome.
    При наличии логина/пароля создаёт временное расширение для аутентификации.
    """
    clean_proxy = (proxy_url or "").strip()
    if not clean_proxy:
        return [], None

    p = urlparse(clean_proxy)
    scheme = p.scheme or "http"
    if not p.hostname:
        return [f"--proxy-server={clean_proxy}"], None

    port_str = f":{p.port}" if p.port else ""
    server_arg = f"--proxy-server={scheme}://{p.hostname}{port_str}"

    if p.username and p.password:
        ext_dir = tempfile.mkdtemp(prefix="chrome_proxy_ext_")
        manifest = {
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Chrome Proxy Auth",
            "permissions": [
                "proxy",
                "tabs",
                "unlimitedStorage",
                "storage",
                "<all_urls>",
                "webRequest",
                "webRequestBlocking",
            ],
            "background": {"scripts": ["background.js"]},
        }
        with open(os.path.join(ext_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        bg_js = f"""
        chrome.webRequest.onAuthRequired.addListener(
            function(details) {{
                return {{
                    authCredentials: {{
                        username: {json.dumps(p.username)},
                        password: {json.dumps(p.password)}
                    }}
                }};
            }},
            {{urls: ["<all_urls>"]}},
            ["blocking"]
        );
        """
        with open(os.path.join(ext_dir, "background.js"), "w", encoding="utf-8") as f:
            f.write(bg_js)
        return [server_arg], ext_dir

    return [server_arg], None


async def _handle_challenge_step(page) -> bool:
    """
    Проверяет наличие интерактивных элементов капчи (Cloudflare Turnstile, PerimeterX)
    и совершает действия для их прохождения.
    """
    import nodriver.cdp.input_ as cdp_input

    raw = await page.evaluate(r"""JSON.stringify((() => {
        for (const f of document.querySelectorAll('iframe')) {
            const src = f.src || f.getAttribute('src') || '';
            if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                const r = f.getBoundingClientRect();
                if (r.width > 20 && r.height > 10) return {kind: 'cf_iframe', x: r.x, y: r.y, w: r.width, h: r.height};
            }
        }
        const inp = document.querySelector('[name*="turnstile"]');
        if (inp && inp.parentElement) {
            let r = inp.parentElement.getBoundingClientRect();
            if (r.width > 40 && r.height > 20) return {kind: 'cf_widget', x: r.x, y: r.y, w: r.width, h: r.height};
            const p2 = inp.parentElement.parentElement;
            if (p2) {
                r = p2.getBoundingClientRect();
                if (r.width > 40 && r.height > 20) return {kind: 'cf_widget', x: r.x, y: r.y, w: r.width, h: r.height};
            }
        }
        const pxBtn = document.querySelector('#px-captcha');
        if (pxBtn) {
            const r = pxBtn.getBoundingClientRect();
            if (r.width > 40 && r.height > 20) return {kind: 'px_btn', x: r.x, y: r.y, w: r.width, h: r.height};
        }
        return null;
    })())""")

    if not raw or raw == "null":
        return False

    try:
        data = json.loads(raw)
        kind = data.get("kind")
        if kind in ("cf_iframe", "cf_widget"):
            cx = data["x"] + 28 + random.uniform(-2, 2)
            cy = data["y"] + data["h"] / 2 + random.uniform(-2, 2)
            try:
                await page.mouse_click(cx, cy)
                return True
            except Exception:
                pass
        elif kind == "px_btn":
            cx = data["x"] + data["w"] / 2 + random.uniform(-2, 2)
            cy = data["y"] + data["h"] / 2 + random.uniform(-2, 2)
            try:
                await page.send(cdp_input.dispatch_mouse_event(type_="mouseMoved", x=cx, y=cy))
                await page.send(cdp_input.dispatch_mouse_event(
                    type_="mousePressed", x=cx, y=cy, button=cdp_input.MouseButton.LEFT, click_count=1
                ))
                await asyncio.sleep(5.0)
                await page.send(cdp_input.dispatch_mouse_event(
                    type_="mouseReleased", x=cx, y=cy, button=cdp_input.MouseButton.LEFT, click_count=1
                ))
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


async def fetch_quizlet_with_ezsolver(
    url_or_id: str,
    timeout: int = 30,
    db: AsyncSession | None = None,
    proxy_url: str | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    """
    Загружает набор Quizlet с обходом защиты Cloudflare / PerimeterX с помощью EzSolver / nodriver.
    Автоматически распознает страницы Quizlet, решает Turnstile/challenge и извлекает карточки.
    Поддерживает headless-режим и прокси.
    """
    import nodriver as uc

    cfg_proxy, cfg_headless = await _get_quizlet_settings(db)
    active_proxy = proxy_url if proxy_url is not None else cfg_proxy
    active_headless = headless if headless is not None else cfg_headless

    set_id = extract_quizlet_id(url_or_id)
    if not set_id:
        raise ApiError(422, "INVALID_URL", "Не удалось распознать ссылку на набор Quizlet.")
    target_url = f"https://quizlet.com/{set_id}/flash-cards/"

    async with _ezsolver_sem:
        browser, proxy_ext = await start_browser(
            headless=active_headless,
            proxy_url=active_proxy,
            timeout=timeout,
        )
        try:
            page = await asyncio.wait_for(browser.get(target_url), timeout=timeout)
            deadline = time.time() + timeout
            last_cf = False
            last_px = False

            while time.time() < deadline:
                await asyncio.sleep(1.0)
                title = await page.evaluate("document.title") or ""
                title_str = str(title).lower()

                is_cf = any(
                    w in title_str
                    for w in ["один момент", "just a moment", "captcha challenge", "attention required", "cloudflare"]
                )
                is_px = any(
                    w in title_str
                    for w in ["access to this page has been denied", "px-captcha"]
                )
                last_cf = is_cf
                last_px = is_px

                if not is_cf and not is_px and len(title_str) > 0:
                    content = await page.get_content()

                    # 1. Попытка извлечь из __NEXT_DATA__
                    scripts = re.findall(
                        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL | re.IGNORECASE
                    )
                    if scripts:
                        try:
                            data = json.loads(scripts[0])
                            pp = data.get("props", {}).get("pageProps", {})
                            set_title = pp.get("setTitle") or ""
                            redux = pp.get("dehydratedReduxStateKey")
                            if isinstance(redux, str):
                                redux = json.loads(redux)
                            studiable = redux.get("studyModesCommon", {}).get("studiableData", {}) if redux else {}
                            items = studiable.get("studiableItems", [])
                            if items:
                                clean_title = re.sub(
                                    r"^(Карточки|Flashcards)\s+", "", set_title, flags=re.IGNORECASE
                                ).strip()
                                rows = []
                                for idx, it in enumerate(items, start=1):
                                    f, b = "", ""
                                    for cs in it.get("cardSides", []):
                                        side_id = cs.get("sideId")
                                        label = cs.get("label") or ""
                                        txt = ""
                                        for media_item in cs.get("media", []):
                                            if media_item.get("type") == 1 and media_item.get("plainText"):
                                                txt = media_item["plainText"].strip()
                                                break
                                            elif media_item.get("type") == 2 and media_item.get("url"):
                                                txt = media_item["url"]
                                        if side_id == 0 or label == "word":
                                            f = txt
                                        elif side_id == 1 or label == "definition":
                                            b = txt
                                    if f or b:
                                        rows.append({"line": idx, "front_text": f, "back_text": b})
                                if rows:
                                    return {
                                        "title": clean_title or extract_quizlet_title(content) or title,
                                        "rows": rows,
                                        "front_language": "",
                                        "back_language": "",
                                    }
                        except Exception as e:
                            logger.debug("Failed to parse NEXT_DATA: %s", e)

                    # 2. Fallback на разбор HTML DOM
                    parsed_rows = parse_quizlet_html(content)
                    if parsed_rows:
                        return {
                            "title": extract_quizlet_title(content) or title,
                            "rows": parsed_rows,
                            "front_language": "",
                            "back_language": "",
                        }

                # Обработка интерактивной проверки Cloudflare / PerimeterX с помощью EzSolver
                if is_cf or is_px:
                    await handle_challenges(page)

            if last_px:
                raise ApiError(
                    400,
                    "QUIZLET_BLOCKED",
                    "Quizlet заблокировал доступ (PerimeterX). Настройте рабочий прокси-сервер в настройках администратора.",
                )
            if last_cf:
                raise ApiError(
                    400,
                    "QUIZLET_CLOUDFLARE_BLOCKED",
                    "Quizlet требует проверки Cloudflare Turnstile, которую не удалось пройти автоматически. Настройте прокси-сервер в настройках администратора.",
                )

            raise TimeoutError("Не удалось получить карточки из Quizlet вовремя (таймаут ответа).")
        finally:
            await stop_browser(browser)
            if proxy_ext:
                shutil.rmtree(proxy_ext, ignore_errors=True)
async def fetch_quizlet_folder_with_ezsolver(
    url: str,
    timeout: int = 45,
    download_cards: bool = True,
    selected_set_ids: list[str] | None = None,
    db: AsyncSession | None = None,
    proxy_url: str | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    """
    Загружает папку / класс / группу Quizlet с обходом Cloudflare через nodriver.
    Если download_cards=False, возвращает только список наборов и название папки (для быстрого предпросмотра).
    Если download_cards=True, скачивает карточки для всех (или выбранных) наборов.
    Поддерживает headless-режим и работу через прокси.
    """
    import nodriver as uc

    cfg_proxy, cfg_headless = await _get_quizlet_settings(db)
    active_proxy = proxy_url if proxy_url is not None else cfg_proxy
    active_headless = headless if headless is not None else cfg_headless

    target_url = canonical_quizlet_folder_url(url)
    if not target_url:
        raise ApiError(422, "INVALID_URL", "Разрешены только HTTPS-ссылки на папки Quizlet.")

    async with _ezsolver_sem:
        browser, proxy_ext = await start_browser(
            headless=active_headless,
            proxy_url=active_proxy,
            timeout=timeout,
        )
        try:
            page = await asyncio.wait_for(browser.get(target_url), timeout=timeout)
            deadline = time.time() + timeout
            last_cf = False
            last_px = False

            while time.time() < deadline:
                await asyncio.sleep(1.0)
                title = await page.evaluate("document.title") or ""
                title_str = str(title).lower()

                is_cf = any(
                    w in title_str
                    for w in ["один момент", "just a moment", "captcha challenge", "attention required", "cloudflare"]
                )
                is_px = any(
                    w in title_str
                    for w in ["access to this page has been denied", "px-captcha"]
                )
                last_cf = is_cf
                last_px = is_px

                if not is_cf and not is_px and len(title_str) > 0:
                    await asyncio.sleep(1.5)
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass

                    extract_js = r'''
                    (() => {
                        let folderTitle = '';
                        const nextData = window.__NEXT_DATA__?.props?.pageProps;
                        if (nextData?.data?.class?.title) {
                            folderTitle = nextData.data.class.title;
                        } else if (nextData?.data?.folder?.name) {
                            folderTitle = nextData.data.folder.name;
                        } else {
                            folderTitle = document.title.replace(/\|.*$/i, '').trim();
                        }
                        folderTitle = folderTitle.replace(/^(Папка|Класс|Folder|Class)\s+/i, '').trim();

                        const setMap = new Map();
                        for (const a of document.querySelectorAll('a[href]')) {
                            const href = a.href || '';
                            const m = href.match(/quizlet\.com\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?(\d{6,14})(?:\/([\w-]+))?/i);
                            if (m) {
                                const setId = m[1];
                                let title = a.innerText ? a.innerText.trim() : '';
                                if (!title && a.querySelector('span, h4, div')) {
                                    title = a.querySelector('span, h4, div').innerText.trim();
                                }
                                if (title) {
                                    title = title.replace(/^(Карточки|Flashcards)\s+/i, '').trim();
                                }
                                if (!setMap.has(setId)) {
                                    setMap.set(setId, {id: setId, title: title || ('Set ' + setId), href});
                                } else if (title && (!setMap.get(setId).title || setMap.get(setId).title.startsWith('Set '))) {
                                    setMap.get(setId).title = title;
                                }
                            }
                        }
                        return JSON.stringify({folderTitle, totalSets: setMap.size, sets: Array.from(setMap.values())});
                    })()
                    '''
                    meta_raw = await page.evaluate(extract_js)
                    meta = json.loads(meta_raw) if meta_raw else {}
                    folder_title = meta.get("folderTitle") or title
                    sets = meta.get("sets", [])

                    # Page renders set links dynamically; keep waiting if none found yet
                    if not sets:
                        continue

                    if not download_cards:
                        return {
                            "folder_title": folder_title,
                            "total_sets": len(sets),
                            "sets": sets,
                        }

                    # Скачиваем наборы
                    if selected_set_ids:
                        target_ids = [s["id"] for s in sets if s["id"] in selected_set_ids]
                    else:
                        target_ids = [s["id"] for s in sets]

                    if len(target_ids) > 100:
                        raise ApiError(422, "TOO_MANY_SETS", "За один раз можно импортировать не более 100 наборов.")

                    if not target_ids:
                        return {
                            "folder_title": folder_title,
                            "total_sets": len(sets),
                            "sets": sets,
                            "imported_sets": [],
                            "total_cards": 0,
                        }

                    fetch_js = r'''
                    (async (ids) => {
                        const results = [];
                        for (let i = 0; i < ids.length; i += 5) {
                            const chunk = ids.slice(i, i + 5);
                            const chunkRes = await Promise.all(chunk.map(async (id) => {
                                try {
                                    const r = await fetch('https://quizlet.com/' + id + '/flash-cards/');
                                    const html = await r.text();
                                    const m = html.match(/<script[^>]*id=\"__NEXT_DATA__\"[^>]*>(.*?)<\/script>/);
                                    if (!m) return {id, ok: false, error: 'no NEXT_DATA'};
                                    const data = JSON.parse(m[1]);
                                    const pp = data.props?.pageProps || {};
                                    const redux = typeof pp.dehydratedReduxStateKey === 'string' ? JSON.parse(pp.dehydratedReduxStateKey) : (pp.dehydratedReduxStateKey || {});
                                    const items = redux.studyModesCommon?.studiableData?.studiableItems || [];
                                    const rows = [];
                                    for (const it of items) {
                                        const cs = it.cardSides || [];
                                        let f = '', b = '';
                                        for (const s of cs) {
                                            let txt = '';
                                            for (const med of (s.media || [])) {
                                                if (med.type === 1 && med.plainText) { txt = med.plainText.trim(); break; }
                                            }
                                            if (s.sideId === 0 || s.label === 'word') f = txt;
                                            else if (s.sideId === 1 || s.label === 'definition') b = txt;
                                        }
                                        if (f || b) rows.push({front_text: f, back_text: b});
                                    }
                                    return {
                                        id,
                                        ok: true,
                                        title: (pp.setTitle || '').replace(/^(Карточки|Flashcards)\s+/i, '').trim(),
                                        cards: rows
                                    };
                                } catch (e) {
                                    return {id, ok: false, error: String(e)};
                                }
                            }));
                            results.push(...chunkRes);
                        }
                        return JSON.stringify(results);
                    })
                    '''
                    remaining = max(1.0, deadline - time.time())
                    res_str = await asyncio.wait_for(
                        page.evaluate(f"({fetch_js})({json.dumps(target_ids)})", await_promise=True),
                        timeout=remaining,
                    )
                    downloaded = json.loads(res_str) if res_str else []

                    id_to_meta_title = {s["id"]: s["title"] for s in sets}
                    valid_sets = []
                    total_cards = 0
                    for d in downloaded:
                        if d.get("ok"):
                            s_title = d.get("title") or id_to_meta_title.get(d["id"]) or f"Набор {d['id']}"
                            cards = d.get("cards", [])
                            valid_sets.append({
                                "id": d["id"],
                                "title": s_title,
                                "cards": cards,
                                "card_count": len(cards),
                            })
                            total_cards += len(cards)

                    return {
                        "folder_title": folder_title,
                        "total_sets": len(sets),
                        "imported_sets": valid_sets,
                        "total_cards": total_cards,
                    }

                # Обработка интерактивной проверки Cloudflare / PerimeterX
                if is_cf or is_px:
                    await handle_challenges(page)

            if last_px:
                raise ApiError(
                    400,
                    "QUIZLET_BLOCKED",
                    "Quizlet заблокировал доступ (PerimeterX). Настройте рабочий прокси-сервер в настройках администратора.",
                )
            if last_cf:
                raise ApiError(
                    400,
                    "QUIZLET_CLOUDFLARE_BLOCKED",
                    "Quizlet требует проверки Cloudflare Turnstile, которую не удалось пройти автоматически. Настройте прокси-сервер в настройках администратора.",
                )

            raise TimeoutError("Не удалось получить данные папки из Quizlet вовремя (таймаут ответа).")
        finally:
            await stop_browser(browser)
            if proxy_ext:
                shutil.rmtree(proxy_ext, ignore_errors=True)


async def fetch_quizlet_by_url(
    url_or_id: str,
    db: AsyncSession | None = None,
    proxy_url: str | None = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    """Получает метаданные и карточки набора Quizlet через EzSolver с обходом защиты Cloudflare / PerimeterX."""
    cfg_proxy, _ = await _get_quizlet_settings(db)
    active_proxy = proxy_url if proxy_url is not None else cfg_proxy

    # 1. Попытка через EzSolver (браузер nodriver с поддержкой proxy и persistent profile)
    try:
        data = await fetch_quizlet_with_ezsolver(
            url_or_id, db=db, proxy_url=active_proxy, headless=headless
        )
        if data.get("rows"):
            return data
    except ApiError as e:
        if e.code in ("QUIZLET_BLOCKED", "QUIZLET_CLOUDFLARE_BLOCKED", "INVALID_URL"):
            raise
        logger.info("EzSolver error (%s): %s. Attempting HTTP fallback.", e.code, e.message)
    except Exception as e:
        logger.info("EzSolver bypass attempt failed: %s. Falling back to HTTP.", e)

    # 2. Прямой HTTP-запрос (fallback)
    set_id = extract_quizlet_id(url_or_id)
    if not set_id:
        raise ApiError(422, "INVALID_URL", "Не удалось распознать ссылку на набор Quizlet.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=12.0,
            proxy=active_proxy if active_proxy else None,
        ) as client:
            meta_resp = await client.get(f"https://quizlet.com/webapi/3.4/sets/{set_id}")
            if meta_resp.status_code == 403:
                raise ApiError(
                    400,
                    "QUIZLET_CLOUDFLARE_BLOCKED",
                    "Quizlet защищён системой Cloudflare. Не удалось автоматически получить карточки. Укажите рабочий прокси-сервер в панели администратора.",
                    {"set_id": set_id},
                )
            if meta_resp.status_code == 404:
                raise ApiError(404, "NOT_FOUND", "Набор на Quizlet не найден или является приватным.")
            if meta_resp.status_code != 200:
                raise ApiError(400, "QUIZLET_ERROR", f"Quizlet вернул код {meta_resp.status_code}.")

            meta_json = meta_resp.json()
            set_obj = meta_json.get("responses", [{}])[0].get("models", {}).get("set", [{}])[0]
            title = set_obj.get("title", "")
            description = set_obj.get("description", "")
            word_lang = set_obj.get("wordLang", "")
            def_lang = set_obj.get("defLang", "")

            cards_resp = await client.get(
                f"https://quizlet.com/webapi/3.4/studiable-item-documents"
                f"?filters%5BstudiableContainerId%5D={set_id}&filters%5BstudiableContainerType%5D=1&perPage=100&page=1"
            )
            if cards_resp.status_code != 200:
                raise ApiError(400, "QUIZLET_ERROR", "Не удалось загрузить карточки набора из Quizlet.")

            cards_json = cards_resp.json()
            items = cards_json.get("responses", [{}])[0].get("models", {}).get("studiableItem", [])

            rows = []
            for idx, it in enumerate(items, start=1):
                sides = it.get("cardSides", [])
                front, back = "", ""
                for s in sides:
                    side_id = s.get("sideId")
                    media = s.get("media", [])
                    text_val = ""
                    for m in media:
                        if m.get("type") == 1 and m.get("plainText"):
                            text_val = m["plainText"].strip()
                            break
                    if side_id == 1 or s.get("label") == "word":
                        front = text_val
                    elif side_id == 2 or s.get("label") == "definition":
                        back = text_val
                if front or back:
                    rows.append({"line": idx, "front_text": front, "back_text": back})

            return {
                "title": title or "Импорт из Quizlet",
                "description": description or "",
                "front_language": word_lang or "",
                "back_language": def_lang or "",
                "rows": rows,
            }
    except ApiError:
        raise
    except Exception as e:
        logger.exception("Quizlet fetch failed")
        raise ApiError(
            400,
            "QUIZLET_FETCH_ERROR",
            "Не удалось получить данные с сайта Quizlet.",
            {"set_id": set_id},
        ) from e


def parse_quizlet_json(text: str) -> list[dict[str, Any]]:
    """Парсит JSON данные карточек Quizlet (из расширений, API или веб-страницы)."""
    try:
        data = json.loads(text.strip())
    except Exception:
        return []

    rows = []
    # 1. Массив объектов или пар
    if isinstance(data, list):
        for idx, item in enumerate(data, start=1):
            if isinstance(item, dict):
                f = item.get("term") or item.get("word") or item.get("front") or item.get("front_text") or ""
                b = item.get("definition") or item.get("back") or item.get("back_text") or item.get("translation") or ""
                fh = item.get("front_hint") or item.get("hint") or ""
                bh = item.get("back_hint") or ""
                if f or b:
                    rows.append({
                        "line": idx,
                        "front_text": str(f).strip()[:10000],
                        "back_text": str(b).strip()[:10000],
                        "front_hint": str(fh).strip()[:2000],
                        "back_hint": str(bh).strip()[:2000],
                    })
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                rows.append({
                    "line": idx,
                    "front_text": str(item[0]).strip()[:10000],
                    "back_text": str(item[1]).strip()[:10000],
                })
        return rows

    # 2. Объект Quizlet studiableItem или __NEXT_DATA__
    if isinstance(data, dict):
        items = data.get("responses", [{}])[0].get("models", {}).get("studiableItem", [])
        if not items and "cards" in data and isinstance(data["cards"], list):
            items = data["cards"]
        if not items:
            # поиск по ключам
            for k in ("studiableItems", "terms", "items"):
                if k in data and isinstance(data[k], list):
                    items = data[k]
                    break

        for idx, it in enumerate(items, start=1):
            if isinstance(it, dict):
                sides = it.get("cardSides", [])
                if sides:
                    f, b = "", ""
                    for s in sides:
                        txt = ""
                        for m in s.get("media", []):
                            if m.get("plainText"):
                                txt = m["plainText"].strip()
                                break
                        if not txt and s.get("label"):
                            txt = str(s.get("label")).strip()
                        if s.get("sideId") == 1 or s.get("label") == "word":
                            f = txt
                        elif s.get("sideId") == 2 or s.get("label") == "definition":
                            b = txt
                    if f or b:
                        rows.append({"line": idx, "front_text": f[:10000], "back_text": b[:10000]})
                else:
                    f = it.get("term") or it.get("front") or it.get("front_text") or it.get("word") or ""
                    b = it.get("definition") or it.get("back") or it.get("back_text") or ""
                    if f or b:
                        rows.append({"line": idx, "front_text": str(f).strip()[:10000], "back_text": str(b).strip()[:10000]})
        return rows

    return []


def parse_quizlet_html(html: str) -> list[dict[str, Any]]:
    """Извлекает карточки прямо из исходного кода страницы Quizlet (HTML)."""
    # 1. Поиск встроенного JSON с studiableItem в тегах <script>
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        s = s.strip()
        idx1 = s.find('{')
        idx2 = s.rfind('}')
        if idx1 != -1 and idx2 != -1 and idx2 > idx1:
            candidate = s[idx1:idx2+1]
            try:
                parsed = parse_quizlet_json(candidate)
                if parsed:
                    return parsed
            except Exception:
                pass

    # 2. Поиск по классам SetPageTerm-wordText и SetPageTerm-definitionText
    rows = []
    pairs = re.findall(
        r'class=["\'][^"\']*SetPageTerm-wordText[^"\']*["\'][^>]*>(.*?)<.*?class=["\'][^"\']*SetPageTerm-definitionText[^"\']*["\'][^>]*>(.*?)<',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if pairs:
        for idx, (w, d) in enumerate(pairs, start=1):
            w_clean = re.sub(r"<[^>]+>", "", w).strip()
            d_clean = re.sub(r"<[^>]+>", "", d).strip()
            if w_clean or d_clean:
                rows.append({"line": idx, "front_text": w_clean[:10000], "back_text": d_clean[:10000]})
        if rows:
            return rows

    # 3. Поиск по классам TermText
    term_texts = re.findall(r'class=["\'][^"\']*TermText[^"\']*["\'][^>]*>(.*?)<', html, re.DOTALL | re.IGNORECASE)
    if term_texts and len(term_texts) >= 2:
        cleaned = [re.sub(r"<[^>]+>", "", t).strip() for t in term_texts]
        cleaned = [t for t in cleaned if t]
        for i in range(0, len(cleaned) - 1, 2):
            rows.append({
                "line": (i // 2) + 1,
                "front_text": cleaned[i][:10000],
                "back_text": cleaned[i + 1][:10000],
            })
        if rows:
            return rows

    # 4. Если ничего не сработало, удаляем теги и отправляем в текстовый парсер
    clean_text = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r"<style.*?</style>", "", clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r"<[^>]+>", "\n", clean_text)
    return parse_quizlet_text(clean_text)


def extract_quizlet_title(text: str) -> str:
    """Пытается извлечь название набора из текста или HTML."""
    s = text.strip()
    # HTML title
    m = re.search(r"<title[^>]*>(.*?)(?:Flashcards\s*\||\s*\|\s*Quizlet|</title>)", s, re.IGNORECASE)
    if m:
        t = m.group(1).strip()
        t = re.sub(r"^(Карточки|Flashcards)\s+", "", t, flags=re.IGNORECASE).strip()
        if t:
            return t[:250]

    # Текст страницы Quizlet
    lines = [l.strip() for l in s.splitlines() if l.strip()]
    for idx, l in enumerate(lines[:15]):
        if re.search(r"terms in this set|терминов в этом модуле|карточек в этом", l, re.IGNORECASE):
            if idx > 0 and len(lines[0]) <= 200:
                clean = re.sub(r"^(Карточки|Flashcards)\s+", "", lines[0], flags=re.IGNORECASE).strip()
                return clean
            break
    return ""


# Список служебных строк интерфейса Quizlet для удаления
QUIZLET_UI_WORDS = {
    "нажмите для переворота", "click to flip", "термин", "определение",
    "term", "definition", "карточка", "flashcard", "карточки", "flashcards",
    "заучивание", "learn", "тест", "test", "подбор", "match",
    "original", "alphabetical", "по алфавиту", "сортировка",
    "сохранить и упорядочить", "save and organize", "share", "поделиться",
    "создано пользователем", "created by", "ученики также учили",
    "verified solutions", "expert solutions", "q-chat", "upgrade to remove ads",
    "about us", "help center", "privacy policy", "terms of service",
    "terms in this set", "терминов в этом модуле", "карточек в этом модуле",
}

QUIZLET_FOOTER_WORDS = (
    "other sets by this creator", "другие модули этого автора", "другие наборы",
    "leave the first review", "оставьте первый отзыв",
    "verified questions", "проверенные вопросы",
    "about us", "о нас", "help center", "центр поддержки",
    "privacy policy", "политика конфиденциальности",
    "terms of service", "условия обслуживания",
    "quizlet for teachers", "quizlet для учителей",
    "study with quizlet", "учитесь с quizlet",
)


def parse_quizlet_text(
    text: str,
    term_delimiter: str = "auto",
    card_delimiter: str = "auto",
) -> list[dict[str, Any]]:
    """
    Интеллектуальный парсер карточек Quizlet.
    Поддерживает:
    - JSON формат (из расширений, API и скриптов)
    - HTML формат (исходный код страницы Ctrl+U или элементы)
    - Стандартный экспорт Quizlet (табуляция, дефисы, двоеточия)
    - Выделение карточек со страницы Quizlet (Ctrl+A / чередующиеся строки)
    - Автоматическую очистку от служебного мусора Quizlet.
    """
    text = text.strip()
    if not text:
        return []

    # 1. Проверка на JSON
    if text.startswith("[") or text.startswith("{"):
        json_rows = parse_quizlet_json(text)
        if json_rows:
            return json_rows

    # 2. Проверка на HTML
    low_text = text.lower()
    if "<html" in low_text or "<div" in low_text or "<script" in low_text or "<!doctype" in low_text:
        html_rows = parse_quizlet_html(text)
        if html_rows:
            return html_rows

    # 3. Разбиение на строки/блоки карточек
    if card_delimiter == "newline" or (card_delimiter == "auto" and ("\n" in text or "\r\n" in text)):
        raw_lines = [line.strip() for line in text.splitlines()]
    elif card_delimiter == "double_newline" or ("\n\n" in text and card_delimiter == "auto"):
        raw_lines = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    elif card_delimiter == "semicolon":
        raw_lines = [c.strip() for c in text.split(";") if c.strip()]
    elif card_delimiter and card_delimiter != "auto":
        raw_lines = [c.strip() for c in text.split(card_delimiter) if c.strip()]
    else:
        raw_lines = [line.strip() for line in text.splitlines()]

    # Поиск маркера начала карточек (например, "Terms in this set (35)")
    start_idx = 0
    for i, l in enumerate(raw_lines[:30]):
        if re.search(r"terms in this set|терминов в этом модуле|карточек в этом", l, re.IGNORECASE):
            start_idx = i + 1
            break

    candidate_lines = raw_lines[start_idx:] if start_idx > 0 else raw_lines

    # Фильтрация стандартного мусора веб-интерфейса Quizlet
    filtered_lines: list[str] = []
    for l in candidate_lines:
        if not l:
            continue
        low = l.lower().strip()
        if any(fw in low for fw in QUIZLET_FOOTER_WORDS):
            break  # Конец списка карточек, начался подвал страницы Quizlet
        # Пропуск отдельных строк только из цифр (номера карточек 1, 2, 3...)
        if l.isdigit() and len(l) <= 5:
            continue
        # Пропуск строк вида "1 / 45" или "1 of 45"
        if re.match(r"^\d+\s*(?:/|of|из)\s*\d+$", l, re.IGNORECASE):
            continue
        if re.match(r"^\d+\s*[\./\)]\s*$", l):
            continue
        if low in QUIZLET_UI_WORDS:
            continue
        if any(low.startswith(p) for p in ("terms in this set", "терминов в этом", "карточек в этом")):
            continue

        # Удаление нумерации в начале строки вида "1. " или "1) "
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", l).strip()
        if cleaned:
            filtered_lines.append(cleaned)

    # 4. Проверка разделителя внутри строк
    has_line_delim = False
    delim_candidates = ["\t", " — ", " – ", " - ", " : ", " :: "]
    for l in filtered_lines[:25]:
        if any(d in l for d in delim_candidates):
            has_line_delim = True
            break

    # 5. Если разделителя нет или выбран alternating -> чередующиеся строки
    if (term_delimiter == "alternating" or (term_delimiter == "auto" and not has_line_delim)) and len(filtered_lines) >= 2:
        out = []
        for i in range(0, len(filtered_lines), 2):
            f = filtered_lines[i].strip()
            b = filtered_lines[i + 1].strip() if i + 1 < len(filtered_lines) else ""
            if f or b:
                out.append({
                    "line": (i // 2) + 1,
                    "front_text": f[:10000],
                    "back_text": b[:10000],
                    "front_context": "",
                    "back_context": "",
                    "front_hint": "",
                    "back_hint": "",
                    "front_explanation": "",
                    "back_explanation": "",
                    "front_example": "",
                    "back_example": "",
                    "accepted_front": [],
                    "accepted_back": [],
                })
        if out:
            return out

    # 6. Парсинг строк с разделителем
    out = []
    for idx, line in enumerate(filtered_lines, start=1):
        front, back = "", ""
        if term_delimiter == "tab" or (term_delimiter == "auto" and "\t" in line):
            parts = line.split("\t", 1)
            front, back = parts[0].strip(), parts[1].strip()
        elif term_delimiter == "dash" or (term_delimiter == "auto" and (" — " in line or " – " in line or " - " in line)):
            for d in (" — ", " – ", " - "):
                if d in line:
                    parts = line.split(d, 1)
                    front, back = parts[0].strip(), parts[1].strip()
                    break
        elif term_delimiter == "colon" or (term_delimiter == "auto" and (" :: " in line or " : " in line)):
            for d in (" :: ", " : "):
                if d in line:
                    parts = line.split(d, 1)
                    front, back = parts[0].strip(), parts[1].strip()
                    break
        elif term_delimiter == "comma" or (term_delimiter == "auto" and "," in line):
            parts = line.split(",", 1)
            front, back = parts[0].strip(), parts[1].strip()
        elif term_delimiter and term_delimiter not in ("auto", "alternating"):
            if term_delimiter in line:
                parts = line.split(term_delimiter, 1)
                front, back = parts[0].strip(), parts[1].strip()

        # Извлечение подсказок в скобках вида "слово (подсказка)"
        front_hint = ""
        back_hint = ""
        fm = re.search(r"^(.*?)\s*[\(\[]([^\)\]]+)[\)\]]$", front)
        if fm:
            front = fm.group(1).strip()
            front_hint = fm.group(2).strip()
        bm = re.search(r"^(.*?)\s*[\(\[]([^\)\]]+)[\)\]]$", back)
        if bm:
            back = bm.group(1).strip()
            back_hint = bm.group(2).strip()

        if front or back:
            out.append({
                "line": idx,
                "front_text": front[:10000],
                "back_text": back[:10000],
                "front_context": "",
                "back_context": "",
                "front_hint": front_hint[:2000],
                "back_hint": back_hint[:2000],
                "front_explanation": "",
                "back_explanation": "",
                "front_example": "",
                "back_example": "",
                "accepted_front": [],
                "accepted_back": [],
            })

    return out
