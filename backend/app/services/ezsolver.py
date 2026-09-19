"""EzSolver — Cloudflare Turnstile & challenge solver via real Chrome browser.

Based on https://github.com/ismoiloffS/EzSolver by ismoiloffS.
Uses nodriver with persistent Chrome profile, human-like mouse movement,
and automatic Xvfb virtual display on Linux servers.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import platform
import random
import subprocess
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import nodriver as uc

logger = logging.getLogger("recall.ezsolver")

_xvfb_process: Optional[subprocess.Popen] = None
_solver_lock = asyncio.Lock()


def find_chrome() -> str:
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

    raise FileNotFoundError(
        "Chrome/Chromium не найден в стандартных путях системы. "
        "Укажите путь через переменную окружения CHROME_PATH."
    )


def get_profile_dir() -> str:
    """Возвращает постоянную директорию профиля Chrome (persistent profile).

    EzSolver требует постоянный профиль, чтобы сохранялись cookies,
    токены доверия Cloudflare/PerimeterX и кэш.
    """
    if os.environ.get("TS_PROFILE_DIR"):
        return os.environ["TS_PROFILE_DIR"]
    try:
        from app.core.config import settings
        p = Path(settings.data_dir_path) / "quizlet_chrome_profile"
        p.mkdir(parents=True, exist_ok=True)
        return str(p)
    except Exception:
        pass

    if platform.system() == "Windows":
        base = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Temp"
        p = os.path.join(base, "ts_profile")
    else:
        p = os.path.expanduser("~/.cache/recall/ts_profile")
    os.makedirs(p, exist_ok=True)
    return p


def clean_stale_profile_locks(profile_dir: str) -> None:
    """Удаляет устаревшие файлы блокировки Singleton*, оставшиеся после сбоя Chrome."""
    import glob

    for link in glob.glob(os.path.join(profile_dir, "Singleton*")):
        try:
            if link.endswith("SingletonLock") and os.path.islink(link):
                target = os.readlink(link)
                parts = target.rsplit("-", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    pid = int(parts[1])
                    try:
                        os.kill(pid, 0)
                        continue  # Процесс ещё жив
                    except OSError:
                        pass
            os.unlink(link)
        except OSError:
            pass


def ensure_xvfb(display_num: int = 99) -> Optional[subprocess.Popen]:
    """Запускает виртуальный дисплей Xvfb на Linux сервере при необходимости.

    Позволяет Chrome работать в полнофункциональном режиме (headless=False)
    без отображения окна на мониторе пользователя.
    Корректно обрабатывает устаревшие lock-файлы.
    """
    global _xvfb_process
    if platform.system() != "Linux":
        return None

    lock_file = f"/tmp/.X{display_num}-lock"
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            # Сервер Xvfb на этом дисплее действительно активен
            os.environ["DISPLAY"] = f":{display_num}"
            return None
        except (OSError, ValueError):
            # Процесс завершился, остался «висячий» lock
            logger.info("Удаление устаревшего lock-файла Xvfb: %s", lock_file)
            try:
                os.unlink(lock_file)
            except OSError:
                pass
            socket_file = f"/tmp/.X11-unix/X{display_num}"
            if os.path.exists(socket_file):
                try:
                    os.unlink(socket_file)
                except OSError:
                    pass

    try:
        proc = subprocess.Popen(
            ["Xvfb", f":{display_num}", "-screen", "0", "1920x1080x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        os.environ["DISPLAY"] = f":{display_num}"
        _xvfb_process = proc
        logger.info("Запущен виртуальный дисплей Xvfb на :%d (PID %d)", display_num, proc.pid)
        return proc
    except FileNotFoundError:
        logger.warning("Xvfb не установлен в системе. Установите: sudo apt install xvfb")
        return None
    except Exception as e:
        logger.warning("Не удалось запустить Xvfb на :%d: %s", display_num, e)
        return None


def prepare_browser_proxy(proxy_url: str) -> tuple[list[str], str | None]:
    """Разбирает URL прокси и готовит аргументы командной строки Chrome.

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
        import tempfile
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


async def do_human_click(page: Any, rect: Optional[dict[str, Any]]) -> None:
    """Кликает по виджету с плавным движением мыши (как в EzSolver)."""
    if rect:
        cx = rect["x"] + 28 + random.uniform(-3, 3)
        cy = rect["y"] + rect["h"] / 2 + random.uniform(-3, 3)
        logger.debug("EzSolver: клик по Cloudflare iframe (%0.1f, %0.1f)", cx, cy)
    else:
        cx = 20 + 28 + random.uniform(-3, 3)
        cy = 20 + 32 + random.uniform(-3, 3)
        logger.debug("EzSolver: клик по фиксированной позиции (%0.1f, %0.1f)", cx, cy)

    try:
        # 1. Плавный подход мыши с задержками
        await page.mouse_move(cx - 80, cy - 20)
        await asyncio.sleep(random.uniform(0.15, 0.25))
        await page.mouse_move(cx, cy)
        await asyncio.sleep(random.uniform(0.08, 0.15))
        await page.mouse_click(cx, cy)
    except Exception as e:
        logger.debug("EzSolver: ошибка при движении мыши: %s", e)


async def handle_challenges(page: Any) -> bool:
    """Обнаруживает и пытается решить проверки Cloudflare Turnstile и PerimeterX.

    Возвращает True, если было совершено интерактивное действие.
    """
    raw = await page.evaluate(r"""JSON.stringify((() => {
        // 1. Cloudflare Turnstile iframe
        for (const f of document.querySelectorAll('iframe')) {
            const src = f.src || f.getAttribute('src') || '';
            if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                const r = f.getBoundingClientRect();
                if (r.width > 30 && r.height > 10) return {kind: 'cf_iframe', x: r.x, y: r.y, w: r.width, h: r.height};
            }
        }
        // 2. Cloudflare Turnstile widget контейнер
        const inp = document.querySelector('[name*="turnstile"], [name="cf-turnstile-response"]');
        if (inp && inp.parentElement) {
            let r = inp.parentElement.getBoundingClientRect();
            if (r.width > 40 && r.height > 20) return {kind: 'cf_widget', x: r.x, y: r.y, w: r.width, h: r.height};
            const p2 = inp.parentElement.parentElement;
            if (p2) {
                r = p2.getBoundingClientRect();
                if (r.width > 40 && r.height > 20) return {kind: 'cf_widget', x: r.x, y: r.y, w: r.width, h: r.height};
            }
        }
        // 3. PerimeterX press & hold кнопка
        const pxBtn = document.querySelector('#px-captcha, [id*="px-captcha"]');
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
            await do_human_click(page, data)
            return True

        if kind == "px_btn":
            import nodriver.cdp.input_ as cdp_input

            cx = data["x"] + data["w"] / 2 + random.uniform(-2, 2)
            cy = data["y"] + data["h"] / 2 + random.uniform(-2, 2)
            logger.info("EzSolver: удержание кнопки PerimeterX (%0.1f, %0.1f)", cx, cy)

            await page.mouse_move(cx - 50, cy - 20)
            await asyncio.sleep(random.uniform(0.15, 0.25))
            await page.send(cdp_input.dispatch_mouse_event(type_="mouseMoved", x=cx, y=cy))
            await page.send(
                cdp_input.dispatch_mouse_event(
                    type_="mousePressed", x=cx, y=cy, button=cdp_input.MouseButton.LEFT, click_count=1
                )
            )
            # PerimeterX требует удерживать кнопку 5-6 секунд
            await asyncio.sleep(random.uniform(5.5, 6.5))
            await page.send(
                cdp_input.dispatch_mouse_event(
                    type_="mouseReleased", x=cx, y=cy, button=cdp_input.MouseButton.LEFT, click_count=1
                )
            )
            return True

    except Exception as e:
        logger.debug("EzSolver: ошибка при обработке проверки: %s", e)

    return False


async def start_browser(
    headless: bool = True,
    proxy_url: Optional[str] = None,
    timeout: int = 30,
) -> tuple[Any, Optional[str]]:
    """Запускает Chrome через nodriver с архитектурой EzSolver.

    - Если headless=True на Linux, используется Xvfb на :99, чтобы Chrome работал
      в полнофункциональном режиме без видимого окна (не детектируется Cloudflare).
    - Использует постоянный профиль (persistent profile) для сохранения доверия.
    - Возвращает (browser, proxy_extension_dir).
    """
    chrome_bin = find_chrome()
    profile_dir = get_profile_dir()

    # Если на Linux запрашивается headless-режим (или сервер без монитора),
    # используем Xvfb, а Chrome запускаем с headless=False.
    # Это ключевой принцип EzSolver: реальный браузер в виртуальном экране.
    actual_headless = False
    if platform.system() == "Linux":
        if headless or not os.environ.get("DISPLAY"):
            ensure_xvfb(99)
            actual_headless = False
        else:
            actual_headless = False
    else:
        actual_headless = headless

    proxy_args, proxy_ext = prepare_browser_proxy(proxy_url or "")

    browser_args = [
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if proxy_args:
        browser_args.extend(proxy_args)

    config = uc.Config(
        browser_executable_path=chrome_bin,
        headless=actual_headless,
        user_data_dir=profile_dir,
        browser_args=browser_args,
    )
    if proxy_ext:
        config.add_extension(proxy_ext)
    clean_stale_profile_locks(profile_dir)

    browser = await asyncio.wait_for(uc.start(config), timeout=timeout)
    return browser, proxy_ext


async def stop_browser(browser: Any) -> None:
    """Останавливает браузер nodriver и гарантированно ожидает завершения процесса Chrome."""
    if not browser:
        return
    proc = getattr(browser, "_process", None)
    pid = getattr(browser, "_process_pid", None) or (proc.pid if proc else None)
    try:
        browser.stop()
    except Exception as e:
        logger.debug("EzSolver: ошибка при остановке браузера: %s", e)

    if proc:
        try:
            if hasattr(proc, "wait"):
                import inspect
                if inspect.iscoroutinefunction(proc.wait):
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                    except (asyncio.TimeoutError, Exception):
                        pass
                else:
                    for _ in range(30):
                        if proc.poll() is not None:
                            break
                        await asyncio.sleep(0.1)
        except Exception:
            pass

    if pid:
        for _ in range(30):
            try:
                os.kill(pid, 0)
                await asyncio.sleep(0.1)
            except OSError:
                break
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
            await asyncio.sleep(0.1)

    profile_dir = get_profile_dir()
    clean_stale_profile_locks(profile_dir)


async def solve_turnstile(sitekey: str, siteurl: str, timeout: int = 45) -> str:
    """Реализация EzSolver _solve() из оригинального https://github.com/ismoiloffS/EzSolver.

    Инжектирует виджет Turnstile в страницу и возвращает токен.
    """
    browser, proxy_ext = await start_browser(headless=True, timeout=timeout)
    try:
        page = await browser.get(siteurl)
        await asyncio.sleep(random.uniform(2.0, 3.0))

        # Инжектируем виджет в live DOM
        await page.evaluate(f"""
            (() => {{
                if (document.getElementById('_ts_box')) return;
                window._tsToken = null;
                const wrap = document.createElement('div');
                wrap.id = '_ts_box';
                wrap.style = 'position:fixed;top:20px;left:20px;z-index:2147483647;';
                document.body.appendChild(wrap);
                window._tsLoad = function () {{
                    turnstile.render('#_ts_box', {{
                        sitekey: '{sitekey}',
                        callback: function(token) {{ window._tsToken = token; }}
                    }});
                }};
                const s = document.createElement('script');
                s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=_tsLoad&render=explicit';
                s.async = true;
                document.head.appendChild(s);
            }})();
        """)

        await asyncio.sleep(5.0)

        async def get_token() -> Optional[str]:
            return await page.evaluate("""
                (() => {
                    if (window._tsToken) return window._tsToken;
                    const inp = document.querySelector('#_ts_box [name="cf-turnstile-response"]');
                    return (inp && inp.value) ? inp.value : null;
                })()
            """)

        async def get_cf_iframe_rect() -> Optional[dict]:
            raw = await page.evaluate("""
                JSON.stringify((() => {
                    for (const f of document.querySelectorAll('iframe')) {
                        const src = f.src || f.getAttribute('src') || '';
                        if (!src.includes('challenges.cloudflare.com')) continue;
                        const r = f.getBoundingClientRect();
                        if (r.width > 50 && r.height > 20) return {x:r.x, y:r.y, w:r.width, h:r.height};
                    }
                    return null;
                })())
            """)
            if raw and raw != "null":
                return json.loads(raw)
            return None

        # Проверяем, не решился ли автоматически (invisible mode)
        token = await get_token()
        if token:
            return token

        # Ожидаем появления чекбокса
        rect = None
        for _ in range(20):
            rect = await get_cf_iframe_rect()
            if rect:
                break
            await asyncio.sleep(0.5)

        deadline = asyncio.get_event_loop().time() + timeout
        click_count = 0
        last_click = 0.0

        while asyncio.get_event_loop().time() < deadline:
            token = await get_token()
            if token:
                break

            now = asyncio.get_event_loop().time()
            if click_count == 0 or (not token and now - last_click > 8):
                if click_count >= 3:
                    await asyncio.sleep(0.3)
                    continue
                await do_human_click(page, rect)
                last_click = asyncio.get_event_loop().time()
                click_count += 1
                await asyncio.sleep(1.0)
                rect = await get_cf_iframe_rect() or rect
                continue

            await asyncio.sleep(0.3)

        if not token:
            raise TimeoutError(f"Turnstile token not obtained within {timeout}s")
        return token
    finally:
        await stop_browser(browser)
        if proxy_ext:
            import shutil
            shutil.rmtree(proxy_ext, ignore_errors=True)
