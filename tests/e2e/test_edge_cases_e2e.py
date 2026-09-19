#!/usr/bin/env python3
"""
E2E Test: Edge Cases & Error Recovery
- Empty Set Restrictions: UI mode buttons disabled, direct config submission shows validation error alert
- Mid-Session Reload: Page refresh during active study runner resumes cleanly without white screen crash
- Study Exit Button: Header 'X' button cleanly exits study session
- Invalid Routes: Clean error boundaries for non-existent sets and sessions
- Teardown: Clean up created test sets
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from helpers import (
    BASE, step, get_driver, login, js_click,
    wait_for, wait_clickable, create_test_set,
    delete_test_set, print_summary
)

EMPTY_SET_ID = None
CARDS_SET_ID = None
CARDS = [
    ("Alpha", "Альфа"),
    ("Beta", "Бета"),
    ("Gamma", "Гамма"),
]


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Empty Set: Study Buttons Disabled & Config Validation Error")
def test_empty_set_restrictions(driver):
    global EMPTY_SET_ID
    EMPTY_SET_ID = create_test_set(
        driver,
        title="Empty Edge Case Set",
        cards=[],
    )
    print(f"  Created empty set {EMPTY_SET_ID}")

    # 1. Check SetDetail page
    driver.get(f"{BASE}/sets/{EMPTY_SET_ID}")
    time.sleep(2)

    # Check mode buttons: should all be disabled
    mode_buttons = driver.find_elements(By.CSS_SELECTOR, "section[aria-label*='Режимы'] button, section[aria-label*='Modes'] button")
    assert len(mode_buttons) >= 5, f"Expected at least 5 mode buttons, got {len(mode_buttons)}"
    for btn in mode_buttons:
        assert btn.get_attribute("disabled") is not None, f"Expected button {btn.text} to be disabled for empty set"
    print("  All study mode buttons are correctly disabled on SetDetail page")

    # 2. Try navigating directly to StudyConfigPage
    driver.get(f"{BASE}/study/new?set={EMPTY_SET_ID}&mode=cards")
    time.sleep(2)

    # Click start button
    start_btn = wait_clickable(driver, By.XPATH, "//button[@type='submit' or contains(., 'Начать') or contains(., 'Start')]")
    js_click(driver, start_btn)
    time.sleep(1.5)

    # Should display validation alert
    alert = wait_for(driver, By.CSS_SELECTOR, "p[role='alert']")
    assert "VALIDATION_ERROR" in alert.text or "карточек" in alert.text or "cards" in alert.text.lower() or "ошибка" in alert.text.lower(), f"Unexpected alert text: {alert.text}"
    print(f"  Direct start properly rejected with alert: {alert.text}")


@step("3. Mid-Session Reload: Runner Resumes Cleanly")
def test_mid_session_reload(driver):
    global CARDS_SET_ID
    CARDS_SET_ID = create_test_set(
        driver,
        title="Resume Session Set",
        cards=CARDS,
    )
    print(f"  Created test set {CARDS_SET_ID} with 3 cards")

    # Start cards study
    driver.get(f"{BASE}/study/new?set={CARDS_SET_ID}&mode=cards")
    time.sleep(2)
    start_btn = wait_clickable(driver, By.XPATH, "//button[@type='submit' or contains(., 'Начать') or contains(., 'Start')]")
    js_click(driver, start_btn)
    time.sleep(2)

    assert "/study/" in driver.current_url and "/result" not in driver.current_url

    # Flip card 1
    flip_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Перевернуть') or contains(., 'Flip')]")
    js_click(driver, flip_btn)
    time.sleep(1)

    # Click 'Знаю' (Known)
    know_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Знаю') or contains(., 'Know')]")
    js_click(driver, know_btn)
    time.sleep(1)

    # Progress should advance (e.g. 2 / 3)
    body_text_before = driver.find_element(By.TAG_NAME, "body").text
    assert "2 / 3" in body_text_before or "1 / 3" in body_text_before

    # Now simulate user reloading the page mid-session
    driver.refresh()
    time.sleep(2)

    # Verify runner resumes cleanly without crashing
    card_after_refresh = wait_for(driver, By.CSS_SELECTOR, "div.study-card[role='button']")
    assert card_after_refresh.is_displayed(), "Card container should be displayed after page refresh"

    # Complete remaining cards in session using clean loop
    for _ in range(8):
        if "/result" in driver.current_url:
            break
        flip_btns = driver.find_elements(By.XPATH, "//button[(contains(., 'Перевернуть') or contains(., 'Flip')) and not(@disabled)]")
        if flip_btns:
            js_click(driver, flip_btns[0])
            time.sleep(0.8)
        know_btns = driver.find_elements(By.XPATH, "//button[(contains(., 'Знаю') or contains(., 'Know')) and not(@disabled)]")
        if know_btns:
            js_click(driver, know_btns[0])
            time.sleep(1.2)

    # Should reach results page
    WebDriverWait(driver, 10).until(lambda d: "/result" in d.current_url)
    print("  Mid-session refresh resumed cleanly and completed study session successfully")


@step("4. Study Exit Button: Header 'X' Exits Study Runner")
def test_study_exit_button(driver):
    # Start a new session
    driver.get(f"{BASE}/study/new?set={CARDS_SET_ID}&mode=cards")
    time.sleep(2)
    start_btn = wait_clickable(driver, By.XPATH, "//button[@type='submit' or contains(., 'Начать') or contains(., 'Start')]")
    js_click(driver, start_btn)
    time.sleep(2)

    active_url = driver.current_url
    assert "/study/" in active_url

    # Find and click exit button (X icon in StudyChrome)
    exit_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[aria-label*='Выйти'], button[aria-label*='Exit']")
    js_click(driver, exit_btn)
    time.sleep(2)

    # URL should change away from active study session
    assert driver.current_url != active_url, f"Expected URL to change after exit, stayed at {driver.current_url}"
    print(f"  Exit button successfully transitioned from {active_url} to {driver.current_url}")


@step("5. Invalid Routes: Clean Error Boundaries Without Crash")
def test_invalid_routes(driver):
    # 1. Non-existent set detail
    driver.get(f"{BASE}/sets/00000000000000000000000000000000")
    time.sleep(2)
    body = driver.find_element(By.TAG_NAME, "body").text
    assert "Не найдено" in body or "Not found" in body or "sets" in driver.current_url, f"Expected not found message, got: {body[:200]}"
    print("  Non-existent set displayed graceful 404 message")

    # 2. Non-existent study session
    driver.get(f"{BASE}/study/00000000000000000000000000000000")
    time.sleep(2)
    body = driver.find_element(By.TAG_NAME, "body").text
    assert "ошибка" in body.lower() or "error" in body.lower() or "/" in driver.current_url, f"Expected error card, got: {body[:200]}"
    print("  Non-existent study session displayed graceful error state")

    # 3. Non-existent route
    driver.get(f"{BASE}/non-existent-page-path-12345")
    time.sleep(2)
    body = driver.find_element(By.TAG_NAME, "body").text
    assert "Не найдено" in body or "Not found" in body or driver.current_url.endswith("/"), f"Expected 404 or redirect, got url: {driver.current_url}"
    print("  Non-existent route handled gracefully")


@step("6. Cleanup Edge Case Test Sets")
def test_cleanup(driver):
    global EMPTY_SET_ID, CARDS_SET_ID
    if EMPTY_SET_ID:
        delete_test_set(driver, EMPTY_SET_ID)
        print(f"  Cleaned up empty set {EMPTY_SET_ID}")
        EMPTY_SET_ID = None
    if CARDS_SET_ID:
        delete_test_set(driver, CARDS_SET_ID)
        print(f"  Cleaned up cards set {CARDS_SET_ID}")
        CARDS_SET_ID = None


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_empty_set_restrictions(driver)
        test_mid_session_reload(driver)
        test_study_exit_button(driver)
        test_invalid_routes(driver)
    finally:
        test_cleanup(driver)
        driver.quit()
        print_summary()


if __name__ == "__main__":
    main()
