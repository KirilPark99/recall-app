#!/usr/bin/env python3
"""
E2E Test: Folders (CRUD, set association, duplicate validation)
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from helpers import (
    BASE, step, get_driver, login, js_click, js_fetch,
    wait_for, wait_clickable, create_test_set, delete_test_set, print_summary
)

FOLDER_NAME = "E2E Test Folder"
SET_ID = None


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Setup test set")
def test_setup_set(driver):
    global SET_ID
    SET_ID = create_test_set(driver, title="Set for Folder Test", cards=[("F1", "B1")])
    print(f"  Created test set: {SET_ID}")


@step("3. Navigate to Folders page and create folder")
def test_create_folder(driver):
    driver.get(f"{BASE}/folders")
    time.sleep(1)

    # Find folder input
    folder_input = wait_for(driver, By.CSS_SELECTOR, "input[placeholder*='папк' i], input[placeholder*='folder' i]")
    folder_input.clear()
    folder_input.send_keys(FOLDER_NAME)

    # Click create button
    create_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать') or contains(., 'Create')]")
    js_click(driver, create_btn)
    time.sleep(1.5)

    # Verify folder in list
    folder_btn = wait_for(driver, By.XPATH, f"//button[contains(., '{FOLDER_NAME}')]")
    assert folder_btn is not None, f"Folder {FOLDER_NAME} not found in UI"
    print("  Folder created and visible in list")


@step("4. Duplicate folder validation")
def test_duplicate_folder(driver):
    folder_input = wait_for(driver, By.CSS_SELECTOR, "input[placeholder*='папк' i], input[placeholder*='folder' i]")
    folder_input.clear()
    folder_input.send_keys(FOLDER_NAME)

    create_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать') or contains(., 'Create')]")
    js_click(driver, create_btn)
    time.sleep(1)

    # Expect error message
    err = wait_for(driver, By.XPATH, "//*[contains(., 'Папка с таким названием уже есть') or contains(., 'already')]")
    assert err.is_displayed(), "Duplicate error message not displayed"
    print("  Duplicate folder rejected with error message")


@step("5. Add set to folder")
def test_add_set_to_folder(driver):
    # Expand folder
    folder_btn = wait_clickable(driver, By.XPATH, f"//button[contains(., '{FOLDER_NAME}')]")
    js_click(driver, folder_btn)
    time.sleep(0.5)

    # Find select to add set
    select_el = wait_for(driver, By.CSS_SELECTOR, "select.select")
    # Select our test set by value
    driver.execute_script(f"""
        const sel = arguments[0];
        sel.value = '{SET_ID}';
        sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
    """, select_el)
    time.sleep(1.5)

    # Verify set appears inside the folder
    set_link = wait_for(driver, By.XPATH, f"//a[contains(., 'Set for Folder Test')]")
    assert set_link is not None, "Set link not found inside folder"
    print("  Set added to folder successfully")


@step("6. Remove set from folder")
def test_remove_set_from_folder(driver):
    remove_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Убрать') or contains(., 'Remove')]")
    js_click(driver, remove_btn)
    time.sleep(1.5)

    # Verify count badge is 0 or set link is gone
    set_links = driver.find_elements(By.XPATH, "//a[contains(., 'Set for Folder Test')]")
    assert len(set_links) == 0, "Set was not removed from folder"
    print("  Set removed from folder successfully")


@step("7. Delete folder")
def test_delete_folder(driver):
    # Auto-accept confirm dialogs
    driver.execute_script("window.confirm = () => true;")

    # Find delete button in folder card
    delete_btn = wait_clickable(driver, By.XPATH, f"//li[contains(., '{FOLDER_NAME}')]//button[@aria-label='Удалить' or @aria-label='Delete' or contains(@class, 'btn-ghost')]")
    js_click(driver, delete_btn)
    time.sleep(1.5)

    # Verify folder is gone
    folders = driver.find_elements(By.XPATH, f"//button[contains(., '{FOLDER_NAME}')]")
    assert len(folders) == 0, f"Folder {FOLDER_NAME} still present after deletion"
    print("  Folder deleted successfully")


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
        test_setup_set(driver)
        test_create_folder(driver)
        test_duplicate_folder(driver)
        test_add_set_to_folder(driver)
        test_remove_set_from_folder(driver)
        test_delete_folder(driver)
        test_cleanup(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
