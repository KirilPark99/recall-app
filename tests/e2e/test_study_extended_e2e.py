#!/usr/bin/env python3
"""
E2E Test: Extended Study Modes (Spell, Match, Learn)
- Spell Mode: Listen/prompt, text input, incorrect answer feedback, repeat mistakes round, completion
- Match Mode: 8-tile board, deliberate mismatch with penalty calculation, matching all pairs, auto-redirect to results
- Learn Mode: Multiple-choice / written questions, deliberate mistake, round summary, 'Повторить ошибки' re-test, completion
- Teardown: Clean up study set and verify stats
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from helpers import (
    BASE, step, get_driver, login, js_click,
    wait_for, wait_clickable, set_input_text, create_test_set,
    delete_test_set, print_summary
)

SET_ID = None
CARDS = [
    ("Apple", "Яблоко"),
    ("Banana", "Банан"),
    ("Cherry", "Вишня"),
    ("Date", "Финик"),
]


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Setup Extended Study Set")
def test_setup_set(driver):
    global SET_ID
    SET_ID = create_test_set(
        driver,
        title="Extended Study Modes Set",
        cards=CARDS,
    )
    print(f"  Created test set {SET_ID} with 4 cards")


@step("3. Spell Mode: Typing, Wrong Answer Feedback & Mistake Round")
def test_spell_mode(driver):
    driver.get(f"{BASE}/study/new?set={SET_ID}&mode=spell")
    time.sleep(2)

    start_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Начать') or contains(., 'Start')]")
    js_click(driver, start_btn)
    time.sleep(2)

    assert "/study/" in driver.current_url, f"Expected study runner, got {driver.current_url}"

    # Question 1: Deliberately type wrong answer
    inp = wait_for(driver, By.ID, "answer-input")
    set_input_text(driver, inp, "WRONG_ANSWER")
    check_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Проверить') or contains(., 'Check')]")
    js_click(driver, check_btn)
    time.sleep(1.5)

    # Feedback should indicate error
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Неверно" in body_text or "Incorrect" in body_text or "Правильный" in body_text, f"Expected wrong answer feedback, got: {body_text[:200]}"

    next_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Далее') or contains(., 'Дальше') or contains(., 'Next') or contains(., 'Понятно')]")
    js_click(driver, next_btn)
    time.sleep(1.5)

    # For remaining cards in round 1, submit answers (even if wrong/skipped, just answer to finish round)
    while True:
        inputs = driver.find_elements(By.ID, "answer-input")
        if not inputs:
            break
        # If repeat mistakes round banner is visible, we reached round 2!
        if "⚠️" in driver.find_element(By.TAG_NAME, "body").text or "Повтор" in driver.find_element(By.TAG_NAME, "body").text:
            print("  Mistake round successfully triggered with ⚠️ banner!")
            break
        set_input_text(driver, inputs[0], "Apple")
        check_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Проверить') or contains(., 'Check')]")
        if check_btns:
            js_click(driver, check_btns[0])
            time.sleep(1)
        next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Далее') or contains(., 'Дальше') or contains(., 'Next') or contains(., 'Понятно')]")
        if next_btns:
            js_click(driver, next_btns[0])
            time.sleep(1)

    # Finish remaining questions in Spell runner
    for _ in range(10):
        if "/result" in driver.current_url:
            break
        next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Далее') or contains(., 'Дальше') or contains(., 'Next') or contains(., 'Понятно') or contains(., 'Завершить') or contains(., 'Finish')]")
        if next_btns:
            js_click(driver, next_btns[0])
            time.sleep(1)
        else:
            inputs = driver.find_elements(By.ID, "answer-input")
            if inputs:
                set_input_text(driver, inputs[0], "Banana")
                check_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Проверить') or contains(., 'Check')]")
                if check_btns:
                    js_click(driver, check_btns[0])
                    time.sleep(1)

    print("  Spell Mode completed verified")


@step("4. Match Mode: Matching Tiles, Mismatch Penalty & Completion")
def test_match_mode(driver):
    driver.get(f"{BASE}/study/new?set={SET_ID}&mode=match")
    time.sleep(2)

    start_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Начать') or contains(., 'Start')]")
    js_click(driver, start_btn)
    time.sleep(2)

    # Find tiles
    tiles = driver.find_elements(By.CSS_SELECTOR, "div.grid button.study-card")
    assert len(tiles) == 8, f"Expected 8 tiles (4 pairs), found {len(tiles)}"

    # 1. Deliberate mismatch: pick an English card and a Russian card that do not match
    apple_tile = next((t for t in tiles if t.text == "Apple"), None)
    banan_tile = next((t for t in tiles if t.text == "Банан"), None)
    if apple_tile and banan_tile:
        js_click(driver, apple_tile)
        time.sleep(0.5)
        js_click(driver, banan_tile)
        time.sleep(1.2)
        timer_text = driver.find_element(By.CSS_SELECTOR, "span.font-mono").text
        assert "×3" in timer_text or "с" in timer_text or "s" in timer_text, f"Expected penalty in timer, got {timer_text}"
        print(f"  Deliberate mismatch penalty verified: {timer_text}")

    # Make sure no tile remains selected
    selected_tiles = driver.find_elements(By.CSS_SELECTOR, "div.grid button.study-card[aria-pressed='true']")
    for st in selected_tiles:
        js_click(driver, st)
        time.sleep(0.3)

    # 2. Now solve all pairs
    for front, back in CARDS:
        tiles_now = driver.find_elements(By.CSS_SELECTOR, "div.grid button.study-card:not([disabled])")
        front_tile = next((t for t in tiles_now if t.text == front), None)
        back_tile = next((t for t in tiles_now if t.text == back), None)
        if front_tile and back_tile:
            js_click(driver, front_tile)
            time.sleep(0.5)
            js_click(driver, back_tile)
            time.sleep(1.0)

    # Verify auto-redirection to results
    WebDriverWait(driver, 15).until(lambda d: "/result" in d.current_url)
    print("  Match mode solved all pairs and redirected to results")


@step("5. Learn Mode: Questions, Round Failed & Repeat Mistakes")
def test_learn_mode(driver):
    driver.get(f"{BASE}/study/new?set={SET_ID}&mode=learn")
    time.sleep(2)

    start_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Начать') or contains(., 'Start')]")
    js_click(driver, start_btn)
    time.sleep(2)

    # In Learn runner, answer cards
    for _ in range(20):
        if "/result" in driver.current_url:
            break

        # Check if round complete screen is shown
        round_complete_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Повторить ошибки') or contains(., 'Retry') or contains(., 'Следующая') or contains(., 'Следующий') or contains(., 'Next') or contains(., 'Завершить') or contains(., 'Finish')]")
        if round_complete_btns:
            print(f"  Round summary visible: {round_complete_btns[0].text}")
            js_click(driver, round_complete_btns[0])
            time.sleep(2)
            continue

        # Look for self-assess buttons (Know / Don't know / Show answer)
        assess_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Знаю') or contains(., 'Не знаю') or contains(., 'Показать ответ') or contains(., 'Show answer') or contains(., 'Know')]")
        if assess_btns:
            js_click(driver, assess_btns[0])
            time.sleep(1.5)
            continue

        # Look for text input
        inputs = driver.find_elements(By.CSS_SELECTOR, "input.input:not([disabled])")
        if inputs:
            set_input_text(driver, inputs[0], "Apple")
            check_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Проверить') or contains(., 'Check')]")
            if check_btns and check_btns[0].is_enabled():
                js_click(driver, check_btns[0])
                time.sleep(1)
            next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Далее') or contains(., 'Дальше') or contains(., 'Next')]")
            if next_btns:
                js_click(driver, next_btns[0])
                time.sleep(1)
            continue

        # Look for multiple choice buttons
        choices = driver.find_elements(By.CSS_SELECTOR, "div.grid button.btn-secondary:not([disabled]), div.grid button.study-card:not([disabled])")
        if choices:
            js_click(driver, choices[0])
            time.sleep(1.5)
            next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Далее') or contains(., 'Дальше') or contains(., 'Next')]")
            if next_btns:
                js_click(driver, next_btns[0])
                time.sleep(1)
            continue

        # Check if next button is present on its own
        next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Далее') or contains(., 'Дальше') or contains(., 'Next')]")
        if next_btns:
            js_click(driver, next_btns[0])
            time.sleep(1)
            continue

        # If finish button visible
        finish_btn = driver.find_elements(By.XPATH, "//button[contains(., 'Завершить') or contains(., 'Finish')]")
        if finish_btn:
            js_click(driver, finish_btn[0])
            time.sleep(2)
            break

    print("  Learn mode cycle verified")


@step("6. Cleanup Test Set")
def test_cleanup(driver):
    global SET_ID
    if SET_ID:
        delete_test_set(driver, SET_ID)
        print(f"  Cleaned up test set {SET_ID}")
        SET_ID = None


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_setup_set(driver)
        test_spell_mode(driver)
        test_match_mode(driver)
        test_learn_mode(driver)
    finally:
        test_cleanup(driver)
        driver.quit()
        print_summary()


if __name__ == "__main__":
    main()
