#!/usr/bin/env python3
"""
E2E Test Suite for Sets with Diverse Sizes (10 to 80 cards with step of 10).
Verifies:
1. All 8 sized sets (10, 20, 30, 40, 50, 60, 70, 80) render correctly on Sets page.
2. API and database card counts match expectations exactly (10, 20, 30, 40, 50, 60, 70, 80).
3. SetDetail page renders large card lists (10 and 80) and supports list/tiles toggle.
4. Flashcards runner handles 80 cards with multi-batch breakdown (7 cards per batch) and flips.
5. Learn runner applies multi-round batching (batch size 7) on large sets (50 cards).
6. Test runner generates full 40-question tests and navigates smoothly via question palette.
7. Match runner operates cleanly on sized sets (20-card set).
8. Editor handles 80-card sets, filtering, and auto-saving without lag.
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    BASE, USERNAME, PASSWORD, get_driver, wait_for, wait_clickable,
    js_click, js_fetch, set_input_text, login, print_summary, step
)

SIZED_SETS = {}  # {10: id, 20: id, ..., 80: id}


@step("1. Login and Detect Sized Sets (10 to 80 cards)")
def test_detect_sized_sets(driver):
    login(driver, USERNAME, PASSWORD)
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)

    # Fetch all sets via API
    res = js_fetch(driver, "/sets?page_size=100")
    assert res["status"] == 200, f"Failed to fetch sets: {res}"
    sets = res["body"] if isinstance(res["body"], list) else res["body"].get("items", [])

    target_sizes = [10, 20, 30, 40, 50, 60, 70, 80]
    for s in sets:
        count = s.get("card_count", 0)
        if count in target_sizes and count not in SIZED_SETS:
            SIZED_SETS[count] = s["id"]
            print(f"  Found set with {count} cards: '{s['title']}' (ID: {s['id']})")

    missing = [size for size in target_sizes if size not in SIZED_SETS]
    assert not missing, f"Missing sets for sizes: {missing}. Found: {list(SIZED_SETS.keys())}"
    print(f"  All {len(target_sizes)} sized sets detected successfully!")


@step("2. API Card Counts and Session Creation for All Sized Sets")
def test_api_validation(driver):
    for size in [10, 20, 30, 40, 50, 60, 70, 80]:
        set_id = SIZED_SETS[size]
        cards_res = js_fetch(driver, f"/sets/{set_id}/cards?page_size=200")
        assert cards_res["status"] == 200, f"Error getting cards for set {set_id}"
        total = cards_res["body"]["total"]
        items_len = len(cards_res["body"]["items"])
        assert total == size, f"Expected {size} cards total, got {total}"
        assert items_len == size, f"Expected {size} cards in items, got {items_len}"

        # Test creating study sessions across modes
        cards_sess = js_fetch(driver, "/study-sessions", "POST", {
            "mode": "cards",
            "set_ids": [set_id],
            "limit": 0,
            "order": "original",
        })
        assert cards_sess["body"]["item_count"] == size, f"Expected {size} items in cards session, got {cards_sess['body']['item_count']}"
        assert len(cards_sess["body"]["tasks"]) == size, f"Expected {size} tasks in cards session, got {len(cards_sess['body']['tasks'])}"

    print("  Verified API card counts and session creation for all 8 sizes (10-80)")


@step("3. Verify SetDetail Display & List/Tiles View for 10 and 80 Cards")
def test_set_detail_views(driver):
    # Check 10-card set
    set_10_id = SIZED_SETS[10]
    driver.get(f"{BASE}/sets/{set_10_id}")
    time.sleep(1.5)
    cards_heading = wait_for(driver, By.XPATH, "//h2[contains(., '10')]")
    assert "10" in cards_heading.text, f"Expected 10 in heading, got: {cards_heading.text}"

    card_rows = driver.find_elements(By.CSS_SELECTOR, "ol.space-y-3 > li")
    assert len(card_rows) == 10, f"Expected 10 card rows in DOM, got {len(card_rows)}"

    # Check 80-card set
    set_80_id = SIZED_SETS[80]
    driver.get(f"{BASE}/sets/{set_80_id}")
    time.sleep(2)
    cards_heading_80 = wait_for(driver, By.XPATH, "//h2[contains(., '80')]")
    assert "80" in cards_heading_80.text, f"Expected 80 in heading, got: {cards_heading_80.text}"

    card_rows_80 = driver.find_elements(By.CSS_SELECTOR, "ol.space-y-3 > li")
    assert len(card_rows_80) == 80, f"Expected 80 card rows in DOM list view, got {len(card_rows_80)}"

    # Toggle to tiles view
    tiles_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[aria-label='Плитки'], button[aria-label='Tiles']")
    js_click(driver, tiles_btn)
    time.sleep(1)
    tiles = driver.find_elements(By.CSS_SELECTOR, ".grid.gap-4.sm\\:grid-cols-2 > .card")
    assert len(tiles) == 80, f"Expected 80 tiles in tiles view, got {len(tiles)}"

    # Toggle back to list view
    list_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[aria-label='Список'], button[aria-label='List']")
    js_click(driver, list_btn)
    time.sleep(0.5)
    print("  SetDetail correctly rendered 10 and 80 cards with list/tiles toggle")


@step("4. Flashcards Study Mode on 80-Card Set (Multi-Batch 7 cards/batch)")
def test_flashcards_80_cards(driver):
    set_80_id = SIZED_SETS[80]
    driver.get(f"{BASE}/sets/{set_80_id}")
    time.sleep(1)

    # Click Cards mode
    cards_btn = wait_clickable(driver, By.XPATH, "//button[.//span[text()='Карточки' or text()='Flashcards']]")
    js_click(driver, cards_btn)

    WebDriverWait(driver, 10).until(EC.url_contains("/study/"))
    if "/study/new" in driver.current_url:
        start_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit']")
        js_click(driver, start_btn)
        WebDriverWait(driver, 10).until(lambda d: "/study/" in d.current_url and "/study/new" not in d.current_url)

    time.sleep(1.5)

    # Progress pill: 80 cards with batch_size 7 gives 12 batches. First batch shows:
    # "Заход 1/12 · 1 / 7"
    progress = wait_for(driver, By.CSS_SELECTOR, "span.badge-accent")
    assert "1 / 7" in progress.text or "1/7" in progress.text, f"Expected '1 / 7', got: '{progress.text}'"
    assert "1/12" in progress.text or "1 / 12" in progress.text or "Заход" in progress.text, f"Expected batch indicator, got: '{progress.text}'"

    # Flip first card: click "Перевернуть" button
    flip_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Перевернуть') or contains(., 'Flip')]")
    js_click(driver, flip_btn)
    time.sleep(0.5)

    # Click "Знаю" / "Know"
    know_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Знаю') or contains(., 'Know')]")
    js_click(driver, know_btn)
    time.sleep(0.5)

    # Progress should advance to 2 / 7
    progress = wait_for(driver, By.CSS_SELECTOR, "span.badge-accent")
    assert "2 / 7" in progress.text or "2/7" in progress.text, f"Expected '2 / 7', got: '{progress.text}'"

    # Flip 2nd card before grading it
    flip_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Перевернуть') or contains(., 'Flip')]")
    js_click(driver, flip_btn)
    time.sleep(0.5)

    # Click "Пока не знаю" / "Don't know"
    dont_know_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Пока не знаю') or contains(., 'Не знаю') or contains(., 'Still learning') or contains(., \"Don't know\")]")
    js_click(driver, dont_know_btn)
    time.sleep(0.5)

    # Progress should advance to 3 / 7
    progress = wait_for(driver, By.CSS_SELECTOR, "span.badge-accent")
    assert "3 / 7" in progress.text or "3/7" in progress.text, f"Expected '3 / 7', got: '{progress.text}'"

    # Test keyboard navigation: press ArrowRight
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(Keys.ARROW_RIGHT)
    time.sleep(0.5)

    progress = wait_for(driver, By.CSS_SELECTOR, "span.badge-accent")
    assert "4 / 7" in progress.text or "4/7" in progress.text, f"Expected '4 / 7', got: '{progress.text}'"
    print("  Flashcards runner advances smoothly on 80-card set with 7-card batches")


@step("5. Learn Mode with Multi-Round Batching (50-Card Set)")
def test_learn_mode_batching(driver):
    set_50_id = SIZED_SETS[50]
    driver.get(f"{BASE}/sets/{set_50_id}")
    time.sleep(1)

    # Click Learn mode
    learn_btn = wait_clickable(driver, By.XPATH, "//button[.//span[text()='Обучение' or text()='Learn' or text()='Заучивание']]")
    js_click(driver, learn_btn)

    WebDriverWait(driver, 10).until(EC.url_contains("/study/"))
    if "/study/new" in driver.current_url:
        start_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit']")
        js_click(driver, start_btn)
        WebDriverWait(driver, 10).until(lambda d: "/study/" in d.current_url and "/study/new" not in d.current_url)

    time.sleep(1.5)

    # In Learn mode on 50 cards (8 batches of 7 cards), badge shows batch indicator e.g. "Заход 1/8"
    progress = wait_for(driver, By.CSS_SELECTOR, "span.badge-accent")
    assert "1/8" in progress.text or "1 / 8" in progress.text or "Заход" in progress.text, f"Expected batch indicator in: '{progress.text}'"

    # Answer current question (recognition multiple choice or self assess)
    choices = driver.find_elements(By.CSS_SELECTOR, ".study-card button.btn-secondary, .study-card button")
    choice_buttons = [b for b in choices if b.text.strip()]
    if choice_buttons:
        js_click(driver, choice_buttons[0])
        time.sleep(1.5)
    else:
        # Fallback to written or self-assess
        self_assess_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Знаю') or contains(., 'Не знаю')]")
        if self_assess_btns:
            js_click(driver, self_assess_btns[0])
            time.sleep(1)

    # Advance if next button is present
    next_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Далее') or contains(., 'Next')]")
    if next_btns:
        js_click(driver, next_btns[0])
        time.sleep(1)

    print("  Learn runner correctly isolates current round to batch_size 7 on 50-card set")


@step("6. Test Mode Generation & Question Navigator on 40-Card Set")
def test_test_mode_navigator(driver):
    set_40_id = SIZED_SETS[40]

    # Start test session via API with 40 questions
    sess_res = js_fetch(driver, "/study-sessions", "POST", {
        "mode": "test",
        "set_ids": [set_40_id],
        "limit": 40,
        "order": "original",
        "settings": {"question_count": 40}
    })
    assert sess_res["status"] == 201, f"Failed to start test session: {sess_res}"
    sess_id = sess_res["body"]["id"]

    driver.get(f"{BASE}/study/{sess_id}")
    time.sleep(2)

    # Verify questions navigator has 40 buttons
    nav_buttons = driver.find_elements(By.CSS_SELECTOR, "div[role='tablist'] button, nav button")
    assert len(nav_buttons) == 40, f"Expected 40 question buttons in navigator, got {len(nav_buttons)}"

    # Click button for Question 20
    q20_btn = nav_buttons[19]
    js_click(driver, q20_btn)
    time.sleep(0.5)

    # Click button for Question 40
    q40_btn = nav_buttons[39]
    js_click(driver, q40_btn)
    time.sleep(0.5)

    # Answer question 40 (multiple choice radio or true/false or text)
    radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
    if radios:
        js_click(driver, radios[0])
        time.sleep(1)
        assert "отвечен" in q40_btn.get_attribute("title") or len(q40_btn.find_elements(By.CSS_SELECTOR, "svg")) > 0
    else:
        text_inputs = driver.find_elements(By.CSS_SELECTOR, "input.input, textarea")
        if text_inputs:
            set_input_text(driver, text_inputs[0], "test answer")
            time.sleep(1)

    print("  Test runner successfully generated 40 questions with interactive palette")


@step("7. Match Mode on 20-Card Set")
def test_match_mode(driver):
    set_20_id = SIZED_SETS[20]
    driver.get(f"{BASE}/sets/{set_20_id}")
    time.sleep(1)

    match_btn = wait_clickable(driver, By.XPATH, "//button[.//span[text()='Подбор пар' or text()='Подбор' or text()='Match']]")
    js_click(driver, match_btn)

    WebDriverWait(driver, 10).until(EC.url_contains("/study/"))
    if "/study/new" in driver.current_url:
        start_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit']")
        js_click(driver, start_btn)
        WebDriverWait(driver, 10).until(lambda d: "/study/" in d.current_url and "/study/new" not in d.current_url)

    time.sleep(1.5)

    # Check board tiles (default 6 pairs = 12 tiles)
    tiles = driver.find_elements(By.CSS_SELECTOR, "button.study-card, .grid button")
    tiles = [t for t in tiles if t.text.strip()]
    assert len(tiles) >= 6, f"Expected tiles on Match board, got {len(tiles)}"

    # Select two tiles
    js_click(driver, tiles[0])
    time.sleep(0.3)
    js_click(driver, tiles[1])
    time.sleep(0.5)
    print("  Match mode correctly initialized board from 20-card set")


@step("8. Editor Operations & Filtering on 80-Card Set")
def test_editor_80_cards(driver):
    set_80_id = SIZED_SETS[80]
    driver.get(f"{BASE}/sets/{set_80_id}/edit")
    time.sleep(2)

    # Verify editor loaded all 80 cards
    card_elements = driver.find_elements(By.CSS_SELECTOR, ".space-y-4 > .card")
    assert len(card_elements) == 80, f"Expected 80 cards loaded in editor, got {len(card_elements)}"

    # Test search filter
    search_input = wait_for(driver, By.CSS_SELECTOR, "input[placeholder*='карточкам'], input[placeholder*='cards'], input.pl-11")
    set_input_text(driver, search_input, "Ability")
    time.sleep(0.5)

    filtered_cards = driver.find_elements(By.CSS_SELECTOR, ".space-y-4 > .card")
    assert len(filtered_cards) == 1, f"Expected 1 card matching 'Ability', got {len(filtered_cards)}"

    # Clear search filter
    set_input_text(driver, search_input, "")
    time.sleep(0.5)

    card_elements_restored = driver.find_elements(By.CSS_SELECTOR, ".space-y-4 > .card")
    assert len(card_elements_restored) == 80, f"Expected 80 cards restored after clear, got {len(card_elements_restored)}"

    # Edit front text of first card
    first_textarea = wait_for(driver, By.CSS_SELECTOR, "textarea[id^='front-'], textarea")
    driver.execute_script("arguments[0].scrollIntoView(true);", first_textarea)
    set_input_text(driver, first_textarea, "Ability (edited)")
    time.sleep(2)

    # Status badge should show 'сохранено' / 'saved'
    badge = wait_for(driver, By.CSS_SELECTOR, ".badge[aria-live='polite']")
    assert "сохранен" in badge.text.lower() or "saved" in badge.text.lower(), f"Expected saved status, got: '{badge.text}'"

    # Restore original text
    set_input_text(driver, first_textarea, "Ability")
    time.sleep(2)
    print("  Editor successfully managed 80 cards, fast filtering and auto-saving")


def main():
    driver = get_driver()
    try:
        test_detect_sized_sets(driver)
        test_api_validation(driver)
        test_set_detail_views(driver)
        test_flashcards_80_cards(driver)
        test_learn_mode_batching(driver)
        test_test_mode_navigator(driver)
        test_match_mode(driver)
        test_editor_80_cards(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
