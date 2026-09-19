#!/usr/bin/env python3
"""
E2E Test: Test mode (Exam flow, question types, submission, result page, answer correction, stats)
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from helpers import (
    BASE, step, get_driver, login, js_click, js_fetch,
    wait_for, wait_clickable, create_test_set, delete_test_set, print_summary
)

SET_ID = None
SESSION_ID = None
CARDS = [
    ("Capital of France", "Paris"),
    ("Capital of Germany", "Berlin"),
    ("Capital of Italy", "Rome"),
    ("Capital of Spain", "Madrid"),
    ("Capital of Japan", "Tokyo"),
    ("Capital of Canada", "Ottawa"),
]


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Setup test set with 6 geography cards")
def test_setup_set(driver):
    global SET_ID
    SET_ID = create_test_set(driver, title="Geography Capitals Test Set", cards=CARDS)
    print(f"  Created test set: {SET_ID}")


@step("3. Start Test study session")
def test_start_session(driver):
    global SESSION_ID
    res = js_fetch(driver, "/study-sessions", "POST", {
        "set_ids": [SET_ID],
        "mode": "test"
    })
    assert res.get("status") in (200, 201), f"Failed to create test session: {res}"
    SESSION_ID = res["body"]["id"]
    print(f"  Created Test session: {SESSION_ID}")


@step("4. Navigate to test runner and verify questions navigator")
def test_navigate_test(driver):
    driver.get(f"{BASE}/study/{SESSION_ID}")
    time.sleep(2)

    # Check that questions navigator tabs are present
    tabs = driver.find_elements(By.CSS_SELECTOR, "div[role='tablist'] button[role='tab']")
    assert len(tabs) > 0, "No question tabs found in test runner"
    print(f"  Found {len(tabs)} questions in test")


@step("5. Answer all test questions across all types")
def test_answer_questions(driver):
    tabs = driver.find_elements(By.CSS_SELECTOR, "div[role='tablist'] button[role='tab']")
    total = len(tabs)

    for i in range(total):
        # Click question tab i
        tab_btns = driver.find_elements(By.CSS_SELECTOR, "div[role='tablist'] button[role='tab']")
        js_click(driver, tab_btns[i])
        time.sleep(0.5)

        # Check question type and answer
        # 1. Multiple choice (test_mc)
        radio_choices = driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][name]")
        written_input = driver.find_elements(By.CSS_SELECTOR, "input.input[aria-label]")
        tf_radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][name^='tf-']")
        match_btns = driver.find_elements(By.CSS_SELECTOR, ".grid-cols-2 button")

        if tf_radios:
            # True/False question: click first option (Верно)
            js_click(driver, tf_radios[0])
            print(f"  Question {i+1}: answered True/False")
        elif radio_choices:
            # MC question: select first choice
            js_click(driver, radio_choices[0])
            print(f"  Question {i+1}: answered Multiple Choice")
        elif written_input:
            # Written question: enter answer
            inp = written_input[0]
            inp.clear()
            inp.send_keys("Paris")
            print(f"  Question {i+1}: answered Written input")
        elif match_btns:
            # Match question: click first left then first right
            js_click(driver, match_btns[0])
            time.sleep(0.3)
            # Find right side button
            rights = driver.find_elements(By.CSS_SELECTOR, ".grid-cols-2 > div:last-child button")
            if rights:
                js_click(driver, rights[0])
            print(f"  Question {i+1}: answered Match pairs")

        time.sleep(0.5)


@step("6. Submit test and confirm completion")
def test_submit_test(driver):
    # Click "Завершить тест"
    finish_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Завершить тест') or contains(., 'Finish')]")
    assert len(finish_btns) > 0, "Finish test button not found"
    js_click(driver, finish_btns[0])
    time.sleep(0.5)

    # In confirm modal, click "Подтвердить" / "Confirm"
    confirm_btn = wait_clickable(driver, By.XPATH, "//div[@role='alertdialog']//button[contains(@class, 'btn-primary')]")
    js_click(driver, confirm_btn)
    time.sleep(2)

    # Wait for result page
    assert "/result" in driver.current_url, f"Expected /result URL, got {driver.current_url}"
    print(f"  Landed on Result page: {driver.current_url}")


@step("7. Verify score and result statistics")
def test_verify_result(driver):
    # Verify page title
    wait_for(driver, By.XPATH, "//h1[contains(., 'завершено') or contains(., 'complete') or contains(., 'Result')]")

    # Verify score stats cards
    score_els = wait_for(driver, By.CSS_SELECTOR, ".card .text-xl.font-bold")
    assert score_els is not None, "Score element not displayed on result page"

    all_stats = driver.find_elements(By.CSS_SELECTOR, ".card .text-xl.font-bold")
    stats_text = [el.text for el in all_stats]
    print(f"  Result stats displayed: {stats_text}")


@step("8. Verify questions review breakdown on result page")
def test_answer_correction(driver):
    # Verify detail breakdown is rendered
    question_cards = driver.find_elements(By.XPATH, "//section//div[contains(@class, 'card')]")
    assert len(question_cards) > 0, "Question detail cards not displayed on result page"
    print(f"  Found {len(question_cards)} questions reviewed in result breakdown")


@step("9. Verify test history on Stats page")
def test_verify_stats(driver):
    driver.get(f"{BASE}/stats")
    time.sleep(1.5)

    # Verify "История попыток" section has rows
    test_rows = driver.find_elements(
        By.XPATH,
        "//section[contains(., 'История попыток') or contains(., 'Attempt history') or contains(., 'История тестов')]//li"
    )
    assert len(test_rows) > 0, "No test history rows found on Stats page"
    print(f"  Stats page reflects completed test: {test_rows[0].text}")


@step("10. Cleanup")
def test_cleanup(driver):
    global SET_ID
    if SET_ID:
        delete_test_set(driver, SET_ID)
        print("  Cleaned up test set")


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_setup_set(driver)
        test_start_session(driver)
        test_navigate_test(driver)
        test_answer_questions(driver)
        test_submit_test(driver)
        test_verify_result(driver)
        test_answer_correction(driver)
        test_verify_stats(driver)
        test_cleanup(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
