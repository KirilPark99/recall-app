#!/usr/bin/env python3
"""
E2E Test: Admin Panel (Full Lifecycle)
- Verify system statistics & overview
- Toggle server registration setting & verify persistence
- Create new user via Admin UI form
- Toggle user active / suspended (archive / restore) state
- Toggle user role (user <-> admin)
- Delete user via Admin UI with confirm
- Trigger database backup creation & verify backup listed
- Verify audit log entries recorded
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from helpers import (
    BASE, step, get_driver, login, js_click,
    wait_for, wait_clickable, set_input_text, print_summary
)

NEW_USER = f"adm_{int(time.time()) % 100000}"
NEW_PASS = "E2ePass1234!"


@step("1. Login as Admin")
def test_login_admin(driver):
    login(driver)


@step("2. Verify System Statistics")
def test_admin_system_stats(driver):
    driver.get(f"{BASE}/admin")
    time.sleep(2)

    h1 = wait_for(driver, By.TAG_NAME, "h1")
    assert "Управление" in h1.text or "Admin" in h1.text or "Администрирование" in h1.text, f"Unexpected admin title: {h1.text}"

    stat_cards = driver.find_elements(By.CSS_SELECTOR, "section.grid > div.card")
    assert len(stat_cards) >= 4, f"Expected at least 4 stat cards, got {len(stat_cards)}"
    stats_text = " | ".join(c.text for c in stat_cards)
    print(f"  System stats verified: {stats_text}")


@step("3. Toggle Server Registration Setting")
def test_toggle_registration(driver):
    reg_cb = wait_for(driver, By.CSS_SELECTOR, "section.card input[type='checkbox']")
    initial_checked = reg_cb.is_selected()

    # Toggle checkbox
    js_click(driver, reg_cb)
    time.sleep(1.5)

    # Reload and verify persistence
    driver.refresh()
    time.sleep(2)
    reg_cb = wait_for(driver, By.CSS_SELECTOR, "section.card input[type='checkbox']")
    assert reg_cb.is_selected() != initial_checked, "Registration setting did not toggle/persist"

    # Restore initial state
    js_click(driver, reg_cb)
    time.sleep(1.5)
    print("  Server registration setting toggled and persisted")


@step("4. Create User via Admin UI")
def test_create_user(driver):
    driver.get(f"{BASE}/admin")
    time.sleep(2)

    user_input = wait_for(driver, By.CSS_SELECTOR, "input[aria-label='Имя нового пользователя']")
    set_input_text(driver, user_input, NEW_USER)

    pass_input = wait_for(driver, By.CSS_SELECTOR, "input[aria-label='Пароль']")
    set_input_text(driver, pass_input, NEW_PASS)

    create_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать')]")
    js_click(driver, create_btn)
    time.sleep(2)

    # Verify user appears in user list
    WebDriverWait(driver, 8).until(
        lambda d: any(NEW_USER in li.text for li in d.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li"))
    )
    print(f"  Created user '{NEW_USER}' via Admin UI")


@step("5. Toggle User Active / Blocked Status")
def test_toggle_user_active(driver):
    user_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li")
    target_li = next((li for li in user_items if NEW_USER in li.text), None)
    assert target_li is not None, f"Could not find user '{NEW_USER}'"

    # Click archive/block button
    toggle_active_btn = target_li.find_elements(By.CSS_SELECTOR, "button")[1]
    js_click(driver, toggle_active_btn)
    time.sleep(2)

    # Verify blocked badge appears
    driver.refresh()
    time.sleep(2)
    user_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li")
    target_li = next((li for li in user_items if NEW_USER in li.text), None)
    assert "блок" in target_li.text or "blocked" in target_li.text, f"Expected blocked badge for {NEW_USER}, got: {target_li.text}"

    # Click restore/unblock button ("Из архива")
    toggle_active_btn = target_li.find_elements(By.CSS_SELECTOR, "button")[1]
    js_click(driver, toggle_active_btn)
    time.sleep(2)

    driver.refresh()
    time.sleep(2)
    user_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li")
    target_li = next((li for li in user_items if NEW_USER in li.text), None)
    assert "блок" not in target_li.text and "blocked" not in target_li.text, f"User {NEW_USER} should be unblocked"
    print(f"  Toggled active/blocked status for '{NEW_USER}' successfully")


@step("6. Toggle User Role (User <-> Admin)")
def test_toggle_user_role(driver):
    user_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li")
    target_li = next((li for li in user_items if NEW_USER in li.text), None)
    assert target_li is not None, f"Could not find user '{NEW_USER}'"

    # Click role toggle button (+admin)
    role_btn = target_li.find_elements(By.CSS_SELECTOR, "button")[0]
    assert "+admin" in role_btn.text, f"Expected +admin button, got: {role_btn.text}"
    js_click(driver, role_btn)
    time.sleep(2)

    # Verify promoted to admin
    driver.refresh()
    time.sleep(2)
    user_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li")
    target_li = next((li for li in user_items if NEW_USER in li.text), None)
    assert "админ" in target_li.text or "admin" in target_li.text, f"User {NEW_USER} should have admin badge"

    # Click -admin to restore user role
    role_btn = target_li.find_elements(By.CSS_SELECTOR, "button")[0]
    assert "-admin" in role_btn.text, f"Expected -admin button, got: {role_btn.text}"
    js_click(driver, role_btn)
    time.sleep(2)
    print(f"  Toggled role for '{NEW_USER}' (user -> admin -> user) successfully")


@step("7. Delete User via Admin UI")
def test_delete_user(driver):
    driver.execute_script("window.confirm = function() { return true; };")

    user_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li")
    target_li = next((li for li in user_items if NEW_USER in li.text), None)
    assert target_li is not None, f"Could not find user '{NEW_USER}'"

    # Trash button is the 3rd button
    del_btn = target_li.find_elements(By.CSS_SELECTOR, "button")[2]
    js_click(driver, del_btn)
    try:
        driver.switch_to.alert.accept()
    except:
        pass
    time.sleep(2)

    # Verify user disappears
    WebDriverWait(driver, 8).until(
        lambda d: not any(NEW_USER in li.text for li in d.find_elements(By.CSS_SELECTOR, "section:nth-of-type(3) ul li"))
    )
    print(f"  Deleted user '{NEW_USER}' via Admin UI")


@step("8. Create Database Backup via Admin UI")
def test_create_backup(driver):
    backup_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать резервную копию') or contains(., 'резервную') or contains(., 'backup')]")
    js_click(driver, backup_btn)
    time.sleep(3)

    # Verify backup appears in backups list
    backup_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(4) ul li")
    assert len(backup_items) > 0, "No backups found after creation"
    first_backup = backup_items[0].text
    assert ".sqlite3" in first_backup or ".db" in first_backup or "KiB" in first_backup or "MiB" in first_backup, f"Unexpected backup entry: {first_backup}"
    print(f"  Backup created successfully: {first_backup}")


@step("9. Verify Audit Log")
def test_audit_log(driver):
    audit_items = driver.find_elements(By.CSS_SELECTOR, "section:nth-of-type(5) ul li")
    assert len(audit_items) > 0, "No audit log items found"
    audit_text = " | ".join(li.text for li in audit_items[:3])
    print(f"  Audit log verified (recent events: {audit_text})")


def main():
    driver = get_driver()
    try:
        test_login_admin(driver)
        test_admin_system_stats(driver)
        test_toggle_registration(driver)
        test_create_user(driver)
        test_toggle_user_active(driver)
        test_toggle_user_role(driver)
        test_delete_user(driver)
        test_create_backup(driver)
        test_audit_log(driver)
    finally:
        driver.quit()
        print_summary()


if __name__ == "__main__":
    main()
