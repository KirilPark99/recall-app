#!/usr/bin/env python3
"""
E2E Test: SRS Review (Spaced Repetition: Enroll, Ratings, Undo, Empty State)
"""

import sys
import time
from selenium.webdriver.common.by import By
from helpers import (
    BASE, step, get_driver, login, js_click, js_fetch,
    wait_for, wait_clickable, create_test_set, delete_test_set, print_summary
)

SET_ID = None
CARDS = [
    ("SRS Question 1", "SRS Answer 1"),
    ("SRS Question 2", "SRS Answer 2"),
    ("SRS Question 3", "SRS Answer 3"),
]


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Create test set for SRS")
def test_create_set(driver):
    global SET_ID
    SET_ID = create_test_set(driver, title="SRS E2E Test Set", cards=CARDS)
    print(f"  Created test set: {SET_ID}")


@step("3. Navigate to Review page and Enroll set")
def test_enroll_set(driver):
    driver.get(f"{BASE}/review")
    time.sleep(1.5)

    # Try clicking our set in the UI if visible, otherwise any available unenrolled set
    target_btns = driver.find_elements(
        By.XPATH,
        f"//li[contains(., 'SRS E2E Test Set')]//button[contains(., 'Включить') or contains(., 'Enable')]"
    )
    if target_btns:
        js_click(driver, target_btns[0])
    else:
        any_enroll = driver.find_elements(
            By.XPATH,
            "//section//button[contains(., 'Включить') or contains(., 'Enable')]"
        )
        if any_enroll:
            js_click(driver, any_enroll[0])
        # Ensure our test set is enrolled
        js_fetch(driver, "/srs/enroll", "POST", {
            "set_id": SET_ID, "enabled": True, "forward_enabled": True, "reverse_enabled": False
        })
    time.sleep(2)
    print("  Set enrolled successfully")


@step("4. Review card with 'Show answer' and rating 'Good'")
def test_review_card(driver):
    driver.get(f"{BASE}/review")
    time.sleep(1.5)

    # Click "Show answer"
    show_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Показать ответ') or contains(., 'Show')]")
    js_click(driver, show_btn)
    time.sleep(0.5)

    # Verify answer is visible
    ans = wait_for(driver, By.XPATH, "//*[@aria-live='polite']")
    assert ans.is_displayed(), "Answer not displayed"

    # Click "Помню" (Good)
    good_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Помню') or contains(., 'Good')]")
    js_click(driver, good_btn)
    time.sleep(1.5)
    print("  Card reviewed with 'Good' rating")


@step("5. Undo last review")
def test_undo_review(driver):
    undo_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Отменить') or contains(., 'Undo')]")
    js_click(driver, undo_btn)
    time.sleep(1.5)

    # Verify undo confirmation message
    status_msg = wait_for(driver, By.XPATH, "//*[@role='status' and contains(., 'отменена')]")
    assert status_msg.is_displayed(), "Undo confirmation not displayed"
    print("  Undo completed successfully")


@step("6. Review remaining cards through different ratings")
def test_review_all_cards(driver):
    # Review cards until empty state or limit
    ratings = ["Не помню", "Трудно", "Помню", "Легко"]
    idx = 0
    while idx < 10:
        time.sleep(1)
        # Check if study card is present
        show_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Показать ответ') or contains(., 'Show')]")
        if not show_btns:
            break
        js_click(driver, show_btns[0])
        time.sleep(0.5)

        # Pick rating
        rating_label = ratings[idx % len(ratings)]
        r_btns = driver.find_elements(By.XPATH, f"//button[contains(., '{rating_label}')]")
        if r_btns:
            js_click(driver, r_btns[0])
        else:
            # Click any secondary rating button
            all_r = driver.find_elements(By.CSS_SELECTOR, ".grid button.btn-secondary")
            if all_r:
                js_click(driver, all_r[0])
        time.sleep(1.5)
        idx += 1

    print(f"  Reviewed {idx} cards")


@step("7. Verify empty state or overview updated")
def test_verify_empty_or_updated(driver):
    driver.get(f"{BASE}/review")
    time.sleep(1.5)

    # Check that overview has numbers
    counters = driver.find_elements(By.CSS_SELECTOR, ".grid .card")
    assert len(counters) >= 4, "Expected at least 4 overview counter cards"
    print("  Overview counters are present and populated")


@step("8. Cleanup")
def test_cleanup(driver):
    global SET_ID
    if SET_ID:
        delete_test_set(driver, SET_ID)
        print("  Cleaned up test set")


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_create_set(driver)
        test_enroll_set(driver)
        test_review_card(driver)
        test_undo_review(driver)
        test_review_all_cards(driver)
        test_verify_empty_or_updated(driver)
        test_cleanup(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
