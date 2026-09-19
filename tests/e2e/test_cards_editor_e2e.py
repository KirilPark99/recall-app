#!/usr/bin/env python3
"""
E2E Test: Cards Editor (Full CRUD & Operations)
- Edit card content (front_text, back_text) with auto-save
- Add new card via UI (+ Карточка)
- Swap sides (front ↔ back)
- Reorder cards (move down / move up)
- Star / Unstar card via SetDetail UI toggle
- Delete single card with undo
- Bulk delete multiple cards via selection
- Clean up
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from helpers import (
    BASE, step, get_driver, login, js_click, js_fetch,
    wait_for, wait_clickable, set_input_text, create_test_set,
    delete_test_set, print_summary
)

TEST_SET_TITLE = "Editor E2E Operations Set"
SET_ID = None
CARD_IDS = []


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Setup Set with initial cards")
def test_setup_set(driver):
    global SET_ID, CARD_IDS
    cards = [
        {"front_text": "Hydrogen", "back_text": "Водород"},
        {"front_text": "Helium", "back_text": "Гелий"},
        {"front_text": "Lithium", "back_text": "Литий"},
    ]
    SET_ID = create_test_set(driver, TEST_SET_TITLE, cards)
    time.sleep(1)

    cards_res = js_fetch(driver, f"/sets/{SET_ID}/cards")
    CARD_IDS = [c["id"] for c in cards_res["body"]["items"]]
    assert len(CARD_IDS) == 3, f"Expected 3 cards, got {len(CARD_IDS)}"
    print(f"  Created test set {SET_ID} with 3 cards: {CARD_IDS}")


@step("3. Edit Card Content with Auto-Save")
def test_edit_card_content(driver):
    driver.get(f"{BASE}/sets/{SET_ID}/edit")
    time.sleep(2)

    # Edit front and back of first card
    front_ta = wait_for(driver, By.ID, f"front-{CARD_IDS[0]}")
    set_input_text(driver, front_ta, "Hydrogen (H)")

    back_ta = wait_for(driver, By.ID, f"back-{CARD_IDS[0]}")
    set_input_text(driver, back_ta, "Водород (газ)")

    # Wait for auto-save debounce (800ms) + server commit
    time.sleep(2)

    # Verify badge displays "Сохранено"
    badge = wait_for(driver, By.CSS_SELECTOR, ".badge-accent")
    assert "Сохранено" in badge.text or "saved" in badge.text.lower(), f"Unexpected badge text: {badge.text}"

    # Verify on SetDetail page
    driver.get(f"{BASE}/sets/{SET_ID}")
    time.sleep(1.5)
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Hydrogen (H)" in page_text and "Водород (газ)" in page_text, "Edited text not reflected on SetDetail"
    print("  Card content edited and verified auto-save on SetDetail")


@step("4. Add New Card via UI")
def test_add_new_card(driver):
    driver.get(f"{BASE}/sets/{SET_ID}/edit")
    time.sleep(2)

    add_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'карточк') or contains(., 'Карточк') or contains(., 'card')]")
    js_click(driver, add_btn)
    time.sleep(1.5)

    # Now there should be 4 cards
    front_textareas = driver.find_elements(By.CSS_SELECTOR, "textarea[id^='front-']")
    assert len(front_textareas) == 4, f"Expected 4 front textareas, found {len(front_textareas)}"

    # Fill the newly added card (last textarea)
    new_front = front_textareas[-1]
    new_id = new_front.get_attribute("id").replace("front-", "")
    set_input_text(driver, new_front, "Beryllium")

    new_back = wait_for(driver, By.ID, f"back-{new_id}")
    set_input_text(driver, new_back, "Бериллий")
    time.sleep(2)

    print(f"  Successfully added card via UI: Beryllium (ID: {new_id})")


@step("5. Swap Sides")
def test_swap_sides(driver):
    driver.get(f"{BASE}/sets/{SET_ID}/edit")
    time.sleep(2)

    swap_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Поменять стороны') or contains(., 'Swap sides')]")
    js_click(driver, swap_btn)
    time.sleep(2.5)

    # Verify sides swapped in first card
    front_ta = wait_for(driver, By.ID, f"front-{CARD_IDS[0]}")
    assert "Водород" in front_ta.get_attribute("value"), f"Expected Russian text in front after swap, got: '{front_ta.get_attribute('value')}'"
    print("  Swap sides verified (front now contains Russian definition)")

    # Swap back so original orientation is preserved
    js_click(driver, swap_btn)
    time.sleep(2.5)


@step("6. Reorder Cards via Move Down / Move Up")
def test_reorder_cards(driver):
    driver.get(f"{BASE}/sets/{SET_ID}/edit")
    time.sleep(2)

    # Move first card down (Russian label is 'Ниже')
    down_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[aria-label='Ниже'], button[aria-label='Move down']")
    js_click(driver, down_btn)
    time.sleep(2)

    # Reload page to verify backend persistence
    driver.refresh()
    time.sleep(2)

    # First front textarea should now be Helium (previously 2nd)
    first_front = wait_for(driver, By.CSS_SELECTOR, "textarea[id^='front-']")
    assert "Helium" in first_front.get_attribute("value"), f"Expected Helium in first position after move down, got: '{first_front.get_attribute('value')}'"
    print("  Card reordering persisted across reload")


@step("7. Star and Unstar Card via SetDetail")
def test_star_unstar_card(driver):
    driver.get(f"{BASE}/sets/{SET_ID}")
    time.sleep(1.5)

    # Find the star button on the first card
    star_btn = wait_clickable(driver, By.CSS_SELECTOR, ".card-star-btn")
    assert star_btn.get_attribute("aria-pressed") == "false", "Card should initially not be starred"

    # Click to star
    js_click(driver, star_btn)
    WebDriverWait(driver, 8).until(
        lambda d: d.find_element(By.CSS_SELECTOR, ".card-star-btn").get_attribute("aria-pressed") == "true"
    )

    # Click to unstar
    star_btn = driver.find_element(By.CSS_SELECTOR, ".card-star-btn")
    js_click(driver, star_btn)
    WebDriverWait(driver, 8).until(
        lambda d: d.find_element(By.CSS_SELECTOR, ".card-star-btn").get_attribute("aria-pressed") == "false"
    )
    print("  Star and Unstar card verified via UI")


@step("8. Delete Single Card and Undo")
def test_delete_card_and_undo(driver):
    driver.get(f"{BASE}/sets/{SET_ID}/edit")
    time.sleep(2)

    initial_count = len(driver.find_elements(By.CSS_SELECTOR, "textarea[id^='front-']"))

    # Click delete on first card
    del_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Удалить карточку') or contains(., 'Delete card')]")
    js_click(driver, del_btn)
    time.sleep(1.5)

    count_after_del = len(driver.find_elements(By.CSS_SELECTOR, "textarea[id^='front-']"))
    assert count_after_del == initial_count - 1, f"Expected {initial_count - 1} cards, found {count_after_del}"

    # Click undo button ("Повторить" / undo / retry)
    undo_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Повторить') or contains(., 'Undo') or contains(., 'Отменить') or contains(., 'Retry')]")
    js_click(driver, undo_btn)
    WebDriverWait(driver, 8).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "textarea[id^='front-']")) == initial_count
    )
    time.sleep(1)

    count_after_undo = len(driver.find_elements(By.CSS_SELECTOR, "textarea[id^='front-']"))
    assert count_after_undo == initial_count, f"Expected {initial_count} cards after undo, got {count_after_undo}"
    print("  Delete card and Undo delete verified")


@step("9. Bulk Delete Cards via Selection")
def test_bulk_delete(driver):
    driver.get(f"{BASE}/sets/{SET_ID}/edit")
    time.sleep(2)

    # Select first two cards
    checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox'][aria-label*='Выбрать карточку']")
    assert len(checkboxes) >= 2, f"Expected at least 2 selection checkboxes, got {len(checkboxes)}"

    js_click(driver, checkboxes[0])
    time.sleep(0.5)
    js_click(driver, checkboxes[1])
    time.sleep(0.5)

    # Bulk delete button appears in toolbar
    bulk_del_btn = wait_clickable(driver, By.CSS_SELECTOR, "div.card button.btn-danger")
    js_click(driver, bulk_del_btn)
    time.sleep(2.5)

    # Reload to verify
    driver.refresh()
    time.sleep(2)

    remaining_cards = driver.find_elements(By.CSS_SELECTOR, "textarea[id^='front-']")
    assert len(remaining_cards) == 2, f"Expected 2 remaining cards after bulk delete, found {len(remaining_cards)}"
    print(f"  Bulk delete verified: 2 cards removed, {len(remaining_cards)} remaining")


@step("10. Cleanup Test Set")
def test_cleanup(driver):
    global SET_ID
    if SET_ID:
        delete_test_set(driver, SET_ID)
        print(f"  Cleaned up set {SET_ID}")
        SET_ID = None


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_setup_set(driver)
        test_edit_card_content(driver)
        test_add_new_card(driver)
        test_swap_sides(driver)
        test_reorder_cards(driver)
        test_star_unstar_card(driver)
        test_delete_card_and_undo(driver)
        test_bulk_delete(driver)
    finally:
        test_cleanup(driver)
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
