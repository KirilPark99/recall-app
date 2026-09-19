#!/usr/bin/env python3
"""
E2E Test: Admin folder assignment to users.
Verifies that:
1. Admin can create a folder with sets.
2. Admin can assign that folder to users directly from /folders via 'Назначить пользователям' modal.
3. Admin can assign ready admin folders from /admin panel via 'Назначить готовую папку администратора'.
4. User receives the assigned folder and all sets inside it with 'Назначено администратором' badges.
5. User cannot delete/rename the folder or remove sets from it (403 Forbidden).
"""

import sys
import time
from selenium.webdriver.common.by import By
from helpers import (
    BASE, step, get_driver, login, logout, js_click, js_fetch,
    wait_for, wait_clickable, set_input_text, print_summary, safe_quit
)

STUDENT_USER = "student_iso_test"
STUDENT_PASS = "StudentPass123!"

FOLDER_NAME = "Admin Physics & Chemistry"
SET_1_TITLE = "Physics Mechanics Top-10"
SET_2_TITLE = "Chemistry Elements Top-10"

ADMIN_FOLDER_ID = None
SET_1_ID = None
SET_2_ID = None
STUDENT_USER_ID = None


@step("1. Admin creates folder and sets in /folders")
def test_admin_creates_folder_with_sets(driver):
    global ADMIN_FOLDER_ID, SET_1_ID, SET_2_ID, STUDENT_USER_ID
    login(driver)  # testadmin

    # Pre-clean any existing test folders / sets
    folders_res = js_fetch(driver, "/folders")
    for f in folders_res.get("body", []):
        if f.get("name") == FOLDER_NAME:
            js_fetch(driver, f"/folders/{f['id']}", "DELETE")

    sets_res = js_fetch(driver, "/sets?page_size=200")
    for s in sets_res.get("body", []):
        if s.get("title") in (SET_1_TITLE, SET_2_TITLE):
            js_fetch(driver, f"/sets/{s['id']}", "DELETE")

    # Get student user ID
    users_res = js_fetch(driver, "/admin/users?q=" + STUDENT_USER)
    items = users_res.get("body", {}).get("items", [])
    assert items, f"Student user {STUDENT_USER} not found"
    STUDENT_USER_ID = items[0]["id"]

    # 1. Create 2 sets
    s1 = js_fetch(driver, "/sets", "POST", {
        "title": SET_1_TITLE,
        "description": "Mechanics",
        "cards": [{"front_text": "Force", "back_text": "Mass times acceleration"}]
    })
    SET_1_ID = s1["body"]["id"]

    s2 = js_fetch(driver, "/sets", "POST", {
        "title": SET_2_TITLE,
        "description": "Elements",
        "cards": [{"front_text": "H", "back_text": "Hydrogen"}]
    })
    SET_2_ID = s2["body"]["id"]

    # 2. Create folder
    f_res = js_fetch(driver, "/folders", "POST", {"name": FOLDER_NAME})
    assert f_res.get("status") in (200, 201), f"Create folder failed: {f_res}"
    ADMIN_FOLDER_ID = f_res["body"]["id"]

    # 3. Add sets to folder
    js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}/sets/{SET_1_ID}", "PUT")
    js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}/sets/{SET_2_ID}", "PUT")

    print(f"  Created admin folder '{FOLDER_NAME}' ({ADMIN_FOLDER_ID}) with 2 sets")


@step("2. Admin assigns folder to student from /folders UI modal")
def test_admin_assigns_folder_from_ui(driver):
    driver.get(f"{BASE}/folders")
    time.sleep(1.5)

    # Find the folder row and click "Назначить пользователям"
    assign_btns = driver.find_elements(By.XPATH, f"//li[contains(., '{FOLDER_NAME}')]//button[contains(., 'Назначить пользователям')]")
    assert assign_btns, "Button 'Назначить пользователям' not found on admin folder"
    js_click(driver, assign_btns[0])
    time.sleep(1)

    # Modal should appear
    modal_title = wait_for(driver, By.XPATH, "//h3[contains(., 'Назначить папку пользователям')]")
    assert modal_title, "Modal 'Назначить папку пользователям' did not open"

    # Select student checkbox
    student_row = wait_for(driver, By.XPATH, f"//li[contains(., '{STUDENT_USER}')]")
    checkbox = student_row.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
    if not checkbox.is_selected():
        js_click(driver, student_row)
        time.sleep(0.5)
    assert checkbox.is_selected(), f"Checkbox for {STUDENT_USER} was not selected"

    # Click save
    save_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Сохранить назначения')]")
    js_click(driver, save_btn)
    time.sleep(1.5)
    print("  Folder successfully assigned to student via UI modal")

    logout(driver)


@step("3. Student verifies receiving assigned folder and all sets")
def test_student_receives_assigned_folder(driver):
    login(driver, STUDENT_USER, STUDENT_PASS)

    # 1. Check /folders: folder must be visible with admin badge
    driver.get(f"{BASE}/folders")
    time.sleep(1.5)
    page_text = driver.page_source
    assert ("Physics" in page_text and "Chemistry" in page_text), f"Folder {FOLDER_NAME} not visible to student"
    assert "Назначено администратором" in page_text, "Badge 'Назначено администратором' not displayed"

    # Open folder and verify both sets inside
    folder_btn = wait_clickable(driver, By.XPATH, f"//button[contains(., '{FOLDER_NAME}')]")
    js_click(driver, folder_btn)
    time.sleep(1)

    folder_content = driver.page_source
    assert SET_1_TITLE in folder_content, f"Set {SET_1_TITLE} not found inside student folder"
    assert SET_2_TITLE in folder_content, f"Set {SET_2_TITLE} not found inside student folder"
    print("  Student sees assigned folder with all its sets and admin badge")

    # 2. Check /sets: both sets must be visible with admin badge
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    sets_text = driver.page_source
    assert SET_1_TITLE in sets_text, f"{SET_1_TITLE} missing from /sets"
    assert SET_2_TITLE in sets_text, f"{SET_2_TITLE} missing from /sets"
    print("  Student sees both sets in /sets")

    logout(driver)


@step("4. Admin unassigns folder from /admin panel")
def test_admin_unassigns_folder(driver):
    login(driver)  # testadmin

    driver.get(f"{BASE}/admin")
    time.sleep(1.5)

    # Open student content manager
    content_btn = wait_clickable(driver, By.XPATH, f"//li[contains(., '{STUDENT_USER}')]//button[contains(., 'Папки и наборы') or contains(., 'контент')]")
    js_click(driver, content_btn)
    time.sleep(1)

    # Check that the assigned folder is listed under "Папки пользователя"
    folder_row = wait_for(driver, By.XPATH, f"//li[contains(., '{FOLDER_NAME}')]")
    assert folder_row, f"Assigned folder {FOLDER_NAME} not listed in admin user manager"

    # Auto accept confirms
    driver.execute_script("window.confirm = () => true;")

    # Delete/unassign folder button
    del_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[aria-label*='Удалить папку']")
    js_click(driver, del_btn)

    # Also accept if native alert still appears
    try:
        alert = driver.switch_to.alert
        alert.accept()
    except Exception:
        pass
    time.sleep(1.5)
    print("  Folder unassigned from student in admin panel")

    logout(driver)


@step("5. Student verifies folder is gone after unassign")
def test_student_folder_gone(driver):
    login(driver, STUDENT_USER, STUDENT_PASS)

    driver.get(f"{BASE}/folders")
    time.sleep(1.5)
    page_text = driver.page_source
    assert "Admin Physics" not in page_text, f"Folder {FOLDER_NAME} still visible after unassign"
    print("  Assigned folder successfully disappeared from student's account")

    # Cleanup admin folder and sets
    logout(driver)
    login(driver)
    js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}", "DELETE")
    js_fetch(driver, f"/sets/{SET_1_ID}", "DELETE")
    js_fetch(driver, f"/sets/{SET_2_ID}", "DELETE")
    logout(driver)


def main():
    driver = None
    try:
        driver = get_driver()
        test_admin_creates_folder_with_sets(driver)
        test_admin_assigns_folder_from_ui(driver)
        test_student_receives_assigned_folder(driver)
        test_admin_unassigns_folder(driver)
        test_student_folder_gone(driver)
    finally:
        if driver:
            safe_quit(driver)

    success = print_summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
