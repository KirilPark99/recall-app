#!/usr/bin/env python3
"""
Common helpers for Recall E2E testing suite.
"""

import atexit
import json
import os
import time
import traceback
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5173")
USERNAME = os.environ.get("E2E_USERNAME", "testadmin")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin12345")
ADMIN_USER = USERNAME
ADMIN_PASS = PASSWORD

results = []
_active_drivers = []


def _cleanup_drivers():
    for d in list(_active_drivers):
        try:
            d.quit()
        except Exception:
            pass
    _active_drivers.clear()


atexit.register(_cleanup_drivers)


def safe_quit(driver):
    try:
        if driver in _active_drivers:
            _active_drivers.remove(driver)
        driver.quit()
    except Exception:
        pass


def step(name):
    def decorator(fn):
        def wrapper(driver, *args, **kwargs):
            print(f"\n{'='*60}")
            print(f"  STEP: {name}")
            print(f"{'='*60}")
            start = time.time()
            try:
                ret = fn(driver, *args, **kwargs)
                elapsed = time.time() - start
                results.append((name, "PASS", elapsed))
                print(f"  → ✅ PASS ({elapsed:.2f}s)")
                return ret
            except Exception as e:
                elapsed = time.time() - start
                results.append((name, f"FAIL: {e}", elapsed))
                print(f"  → ❌ FAIL ({elapsed:.2f}s): {e}")
                traceback.print_exc()
                try:
                    scr_path = f"/tmp/e2e_fail_{len(results)}.png"
                    driver.save_screenshot(scr_path)
                    print(f"  Screenshot: {scr_path}")
                except:
                    pass
                raise e
        return wrapper
    return decorator


def get_driver():
    import os
    import glob
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--width=1440")
    opts.add_argument("--height=900")

    # Look for cached geckodriver first to avoid GitHub API rate limits
    cached_drivers = glob.glob(os.path.expanduser("~/.wdm/drivers/geckodriver/**/geckodriver"), recursive=True)
    executable_path = None
    for p in cached_drivers:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            executable_path = p
            break

    if executable_path:
        service = Service(executable_path=executable_path)
    else:
        try:
            service = Service(GeckoDriverManager().install())
        except Exception:
            service = Service("geckodriver")

    driver = webdriver.Firefox(service=service, options=opts)
    driver.implicitly_wait(2)
    _active_drivers.append(driver)
    return driver


def wait_for(driver, by, value, timeout=10):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def wait_clickable(driver, by, value, timeout=10):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def wait_not_present(driver, by, value, timeout=10):
    return WebDriverWait(driver, timeout).until_not(
        EC.presence_of_element_located((by, value))
    )


def js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


def js_fetch(driver, path, method="GET", body=None):
    body_js = json.dumps(body) if body else "null"
    script = f"""
        const csrf = await fetch('/api/v1/auth/csrf', {{ credentials: 'same-origin' }})
            .then(r => r.json()).then(d => d.csrf_token).catch(() => '');
        const opts = {{
            method: '{method}',
            credentials: 'same-origin',
            headers: {{ 'Content-Type': 'application/json' }}
        }};
        if (csrf) opts.headers['X-CSRF-Token'] = csrf;
        if ({body_js} !== null) opts.body = JSON.stringify({body_js});
        const res = await fetch('/api/v1{path}', opts);
        return {{ status: res.status, body: await res.json().catch(() => ({{}})) }};
    """
    return driver.execute_script(f"return (async () => {{ {script} }})()")


def set_input_text(driver, el, text):
    driver.execute_script("""
        const el = arguments[0];
        const val = arguments[1];
        const proto = (el instanceof HTMLTextAreaElement) ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        const set = Object.getOwnPropertyDescriptor(proto, 'value').set;
        set.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    """, el, text)


def login(driver, username=USERNAME, password=PASSWORD):
    driver.get(f"{BASE}/login")
    time.sleep(1)
    
    # Check if already logged in
    if "/login" not in driver.current_url:
        return
    
    user_input = wait_for(driver, By.ID, "username")
    set_input_text(driver, user_input, username)
    pass_input = wait_for(driver, By.ID, "password")
    set_input_text(driver, pass_input, password)
    js_click(driver, driver.find_element(By.CSS_SELECTOR, "button[type='submit']"))

    WebDriverWait(driver, 10).until_not(EC.url_contains("/login"))
    time.sleep(1)


def logout(driver):
    # Click logout in UI
    try:
        driver.get(f"{BASE}/")
        time.sleep(1)
        # Find logout button or trigger via API
        logout_btn = driver.find_elements(By.XPATH, "//button[contains(., 'Выйти') or contains(., 'Logout')]")
        if logout_btn:
            js_click(driver, logout_btn[0])
            WebDriverWait(driver, 5).until(EC.url_contains("/login"))
            time.sleep(1)
            return
    except Exception:
        pass
    # Fallback to API logout
    js_fetch(driver, "/auth/logout", "POST")
    driver.get(f"{BASE}/login")
    time.sleep(1)


def create_test_set(driver, title="Test Set", cards=None, description="Test Description"):
    res = js_fetch(driver, "/sets", "POST", {
        "title": title,
        "description": description,
        "folder_id": None
    })
    assert res.get("status") in (200, 201), f"Create set failed: {res}"
    set_id = res["body"]["id"]

    if cards:
        for i, card in enumerate(cards, 1):
            if isinstance(card, dict):
                term = card.get("front_text") or card.get("front") or ""
                defn = card.get("back_text") or card.get("back") or ""
            else:
                term, defn = card
            cres = js_fetch(driver, f"/sets/{set_id}/cards", "POST", {
                "front_text": term,
                "back_text": defn,
                "card_order": i
            })
            assert cres.get("status") in (200, 201), f"Card {i} failed: {cres}"

    return set_id


def delete_test_set(driver, set_id):
    if set_id:
        try:
            js_fetch(driver, f"/sets/{set_id}", "DELETE")
        except:
            pass


def print_summary():
    print(f"\n{'='*60}")
    print(f"  TEST SUITE RESULTS SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s != "PASS")
    for name, status, elapsed in results:
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {name:48} [{status}] ({elapsed:.2f}s)")
    print(f"{'='*60}")
    print(f"  Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*60}\n")
    return failed == 0
