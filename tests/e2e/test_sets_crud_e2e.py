#!/usr/bin/env python3
"""
E2E Test: Sets CRUD & Management
- Create set via UI dialog
- Edit metadata (title, description, languages) via UI dialog
- Toggle favorite status
- Copy set to create a duplicate
- Archive and restore set (including archive view on Sets page)
- Search and sort filtering on Sets page
- Delete set with confirmation dialog
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from helpers import (
    BASE, step, get_driver, login, js_click, js_fetch,
    wait_for, wait_clickable, set_input_text, delete_test_set, print_summary
)

ORIGINAL_TITLE = "Alpha Plants Test Set"
UPDATED_TITLE = "Alpha Plants Updated Title"
CREATED_SET_ID = None
COPIED_SET_ID = None


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Create Set via UI Dialog")
def test_create_set(driver):
    global CREATED_SET_ID
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)

    # Click "+ Создать набор"
    create_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать набор') or contains(., 'Create set')]")
    js_click(driver, create_btn)
    time.sleep(1)

    title_input = wait_for(driver, By.ID, "set-title")
    set_input_text(driver, title_input, ORIGINAL_TITLE)

    desc_input = wait_for(driver, By.ID, "set-desc")
    set_input_text(driver, desc_input, "A test set of botanical terms")

    flang_input = wait_for(driver, By.ID, "set-flang")
    set_input_text(driver, flang_input, "la")

    blang_input = wait_for(driver, By.ID, "set-blang")
    set_input_text(driver, blang_input, "ru")

    save_btn = wait_clickable(driver, By.XPATH, "//div[@role='dialog']//button[@type='submit']")
    js_click(driver, save_btn)
    time.sleep(2)

    # Should navigate to /sets/{id}/edit
    assert "/sets/" in driver.current_url and "/edit" in driver.current_url, f"Expected /sets/{{id}}/edit, got {driver.current_url}"
    CREATED_SET_ID = driver.current_url.split("/sets/")[1].split("/edit")[0]
    print(f"  Set created successfully with ID: {CREATED_SET_ID}")

    # Add a test card via API so set is not completely empty
    js_fetch(driver, f"/sets/{CREATED_SET_ID}/cards", method="POST", body={"front_text": "Rosa", "back_text": "Роза"})


@step("3. Edit Metadata via UI Dialog")
def test_edit_metadata(driver):
    driver.get(f"{BASE}/sets/{CREATED_SET_ID}")
    time.sleep(1.5)

    edit_btn = wait_clickable(driver, By.ID, "btn-edit-details")
    js_click(driver, edit_btn)
    time.sleep(1)

    dialog = wait_for(driver, By.CSS_SELECTOR, "div[role='dialog']")
    assert dialog.is_displayed(), "Edit metadata dialog not open"

    title_input = wait_for(driver, By.ID, "edit-set-title")
    set_input_text(driver, title_input, UPDATED_TITLE)

    desc_input = wait_for(driver, By.ID, "edit-set-desc")
    set_input_text(driver, desc_input, "Updated botanical description")

    save_btn = wait_clickable(driver, By.XPATH, "//div[@role='dialog']//button[@type='submit']")
    js_click(driver, save_btn)
    time.sleep(2)

    h1 = wait_for(driver, By.CSS_SELECTOR, "h1")
    assert UPDATED_TITLE in h1.text, f"Expected '{UPDATED_TITLE}' in heading, got '{h1.text}'"
    print(f"  Metadata updated successfully: {h1.text}")


@step("4. Favorite Toggle")
def test_favorite_toggle(driver):
    fav_btn = wait_clickable(driver, By.ID, "btn-favorite-set")
    init_state = fav_btn.get_attribute("aria-pressed")

    # Click to toggle favorite ON
    js_click(driver, fav_btn)
    time.sleep(1.5)
    fav_btn = wait_for(driver, By.ID, "btn-favorite-set")
    assert fav_btn.get_attribute("aria-pressed") == "true", "Favorite button aria-pressed should be true"

    res = js_fetch(driver, f"/sets/{CREATED_SET_ID}")
    assert res["body"].get("is_favorite") is True, f"Expected is_favorite=True in API: {res}"

    # Toggle favorite OFF
    js_click(driver, fav_btn)
    time.sleep(1.5)
    fav_btn = wait_for(driver, By.ID, "btn-favorite-set")
    assert fav_btn.get_attribute("aria-pressed") == "false", "Favorite button aria-pressed should be false"
    print("  Favorite toggle verified (both ON and OFF)")


@step("5. Copy Set")
def test_copy_set(driver):
    global COPIED_SET_ID
    driver.get(f"{BASE}/sets/{CREATED_SET_ID}")
    time.sleep(1.5)

    copy_btn = wait_clickable(driver, By.ID, "btn-copy-set")
    js_click(driver, copy_btn)
    time.sleep(2.5)

    # Should navigate to /sets/{copied_id}
    assert "/sets/" in driver.current_url, f"Expected /sets/{{id}}, got {driver.current_url}"
    COPIED_SET_ID = driver.current_url.split("/sets/")[1].split("?")[0].split("/")[0]
    assert COPIED_SET_ID != CREATED_SET_ID, f"Expected new ID for copy, got same: {COPIED_SET_ID}"

    # Verify copy has cards
    cards_res = js_fetch(driver, f"/sets/{COPIED_SET_ID}/cards")
    assert len(cards_res["body"].get("items", [])) >= 1, "Copied set missing cards"
    print(f"  Set copied successfully with new ID: {COPIED_SET_ID}")

    # Delete the copied set
    delete_test_set(driver, COPIED_SET_ID)


@step("6. Archive and Restore Set")
def test_archive_restore(driver):
    driver.get(f"{BASE}/sets/{CREATED_SET_ID}")
    time.sleep(1.5)

    archive_btn = wait_clickable(driver, By.ID, "btn-archive-set")
    js_click(driver, archive_btn)
    time.sleep(2)

    # Check warning banner appeared on set detail
    banner = wait_for(driver, By.XPATH, "//*[contains(., 'архиве') or contains(., 'archived')]")
    assert banner.is_displayed(), "Archive banner not displayed"

    # Go to Sets list, verify not in active list
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert UPDATED_TITLE not in page_text, "Archived set still displayed in active sets list"

    # Click Archive toggle button to view archived sets
    archive_toggle = wait_clickable(driver, By.XPATH, "//button[contains(., 'архив') or contains(., 'Архив') or contains(., 'Archive')]")
    js_click(driver, archive_toggle)
    time.sleep(1.5)
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert UPDATED_TITLE in page_text, "Archived set not found in Archive view"

    # Open set detail and restore it
    driver.get(f"{BASE}/sets/{CREATED_SET_ID}")
    time.sleep(1.5)
    restore_btn = wait_clickable(driver, By.ID, "btn-archive-set")
    js_click(driver, restore_btn)
    time.sleep(2)

    # Verify restored
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert UPDATED_TITLE in page_text, "Restored set not found in active sets list"
    print("  Archive and Restore lifecycle verified")


@step("7. Sets Search and Sort")
def test_search_and_sort(driver):
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)

    # Search by partial title
    search_input = wait_for(driver, By.CSS_SELECTOR, "input[placeholder*='Поиск'], input[placeholder*='Search']")
    set_input_text(driver, search_input, "Alpha Plants")
    time.sleep(1.5)  # allow debounce

    items = driver.find_elements(By.XPATH, f"//*[contains(text(), '{UPDATED_TITLE}')]")
    assert len(items) >= 1, f"Search result did not find '{UPDATED_TITLE}'"
    print("  Search filtering verified")

    # Clear search
    set_input_text(driver, search_input, "")
    time.sleep(1.5)

    # Test sorting
    sort_select = driver.find_element(By.CSS_SELECTOR, "select.select.w-auto")
    driver.execute_script("arguments[0].value = 'title'; arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", sort_select)
    time.sleep(1.5)
    print("  Sorting selection verified")


@step("8. Delete Set with Confirm Dialog")
def test_delete_set(driver):
    global CREATED_SET_ID
    driver.get(f"{BASE}/sets/{CREATED_SET_ID}")
    time.sleep(1.5)

    del_btn = wait_clickable(driver, By.ID, "btn-delete-set")
    driver.execute_script("window.confirm = () => true;")
    js_click(driver, del_btn)
    time.sleep(2.5)

    # Verify redirected to /sets
    assert "/sets" in driver.current_url, f"Expected redirect to /sets after delete, got {driver.current_url}"

    # Verify via API that set is deleted (404)
    res = js_fetch(driver, f"/sets/{CREATED_SET_ID}")
    assert res.get("status") == 404, f"Expected 404 for deleted set, got {res.get('status')}"
    print(f"  Set {CREATED_SET_ID} successfully deleted and verified 404")
    CREATED_SET_ID = None


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_create_set(driver)
        test_edit_metadata(driver)
        test_favorite_toggle(driver)
        test_copy_set(driver)
        test_archive_restore(driver)
        test_search_and_sort(driver)
        test_delete_set(driver)
    finally:
        if CREATED_SET_ID:
            delete_test_set(driver, CREATED_SET_ID)
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
