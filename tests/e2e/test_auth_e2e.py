#!/usr/bin/env python3
"""
E2E Test: Authentication & Session Management
- Valid login
- Invalid credentials rejection
- Change password & re-login verification & restore password
- Active sessions list & single session revocation
- Logout all devices
- Standard logout & protected route protection
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from helpers import (
    BASE, step, get_driver, login, logout, js_click, js_fetch,
    wait_for, wait_clickable, ADMIN_USER, ADMIN_PASS, set_input_text, print_summary
)

TEMP_PASS = "TempPassAdmin999!"


@step("1. Successful Login")
def test_login_success(driver):
    login(driver, ADMIN_USER, ADMIN_PASS)
    assert driver.current_url.rstrip("/") in (BASE, f"{BASE}/"), f"Expected home URL, got {driver.current_url}"
    print("  Login successful, redirected to home page")


@step("2. Standard Logout and Protected Route Redirection")
def test_logout_and_protection(driver):
    # Click logout in sidebar
    logout_btn = wait_clickable(driver, By.XPATH, "//aside//button[contains(., 'Выйти') or contains(., 'Log out')]")
    js_click(driver, logout_btn)
    time.sleep(2)

    assert "/login" in driver.current_url, f"Expected /login URL, got {driver.current_url}"

    # Try navigating directly to protected route /sets
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    assert "/login" in driver.current_url, f"Protected route did not redirect to /login: {driver.current_url}"
    print("  Successfully logged out and verified protected route redirection")


@step("3. Invalid Credentials Rejection")
def test_invalid_credentials(driver):
    driver.get(f"{BASE}/login")
    time.sleep(1)

    u_input = wait_for(driver, By.ID, "username")
    set_input_text(driver, u_input, ADMIN_USER)

    p_input = wait_for(driver, By.ID, "password")
    set_input_text(driver, p_input, "CompletelyWrongPassword123!")

    submit_btn = wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit']")
    js_click(driver, submit_btn)
    time.sleep(1.5)

    alert = wait_for(driver, By.CSS_SELECTOR, "p[role='alert']")
    assert alert.is_displayed(), "Error alert not displayed for wrong credentials"
    assert "/login" in driver.current_url, f"Should remain on /login, got {driver.current_url}"
    print(f"  Invalid login rejected with message: '{alert.text}'")


@step("4. Change Password via Settings UI")
def test_change_password(driver):
    # Login with current password
    login(driver, ADMIN_USER, ADMIN_PASS)

    driver.get(f"{BASE}/settings")
    time.sleep(1.5)

    cur_p = wait_for(driver, By.ID, "cur-pass")
    set_input_text(driver, cur_p, ADMIN_PASS)

    new_p = wait_for(driver, By.ID, "new-pass")
    set_input_text(driver, new_p, TEMP_PASS)

    # Submit password change form
    change_btn = wait_clickable(driver, By.XPATH, "//form[contains(., 'пароль') or contains(., 'password')]//button[@type='submit']")
    driver.execute_script("arguments[0].scrollIntoView(true);", change_btn)
    time.sleep(0.5)
    js_click(driver, change_btn)
    time.sleep(2)

    status = wait_for(driver, By.CSS_SELECTOR, "p[role='status']")
    assert "изменён" in status.text or "changed" in status.text.lower(), f"Unexpected status: {status.text}"
    print("  Password successfully changed to temporary password")


@step("5. Verify Login with New Password and Reject Old Password")
def test_verify_new_password(driver):
    logout(driver)

    # Try old password
    driver.get(f"{BASE}/login")
    time.sleep(1)
    u_input = wait_for(driver, By.ID, "username")
    set_input_text(driver, u_input, ADMIN_USER)
    p_input = wait_for(driver, By.ID, "password")
    set_input_text(driver, p_input, ADMIN_PASS)
    js_click(driver, wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit']"))
    time.sleep(1.5)

    alert = wait_for(driver, By.CSS_SELECTOR, "p[role='alert']")
    assert alert.is_displayed(), "Old password should have been rejected"

    # Now login with new password
    p_input = wait_for(driver, By.ID, "password")
    set_input_text(driver, p_input, TEMP_PASS)
    js_click(driver, wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit']"))
    time.sleep(2)

    assert "/login" not in driver.current_url, f"Failed to login with new password: {driver.current_url}"
    print("  Old password rejected, new password accepted")


@step("6. Restore Original Password")
def test_restore_password(driver):
    driver.get(f"{BASE}/settings")
    time.sleep(1.5)

    cur_p = wait_for(driver, By.ID, "cur-pass")
    set_input_text(driver, cur_p, TEMP_PASS)

    new_p = wait_for(driver, By.ID, "new-pass")
    set_input_text(driver, new_p, ADMIN_PASS)

    change_btn = wait_clickable(driver, By.XPATH, "//form[contains(., 'пароль') or contains(., 'password')]//button[@type='submit']")
    driver.execute_script("arguments[0].scrollIntoView(true);", change_btn)
    time.sleep(0.5)
    js_click(driver, change_btn)
    time.sleep(2)

    status = wait_for(driver, By.CSS_SELECTOR, "p[role='status']")
    assert "изменён" in status.text or "changed" in status.text.lower(), f"Failed to restore original password: {status.text}"
    print("  Original password restored successfully")


@step("7. Active Sessions List and Revocation")
def test_sessions_list_and_revoke(driver):
    # Create a second authenticated session via separate client (requests)
    import requests
    s = requests.Session()
    csrf_res = s.get("http://127.0.0.1:8000/api/v1/auth/csrf")
    csrf_token = csrf_res.json()["csrf_token"]
    login_res = s.post(
        "http://127.0.0.1:8000/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token, "User-Agent": "Secondary-Device/1.0"},
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    assert login_res.status_code == 200, f"Failed to create second session: {login_res.text}"

    driver.get(f"{BASE}/settings")
    time.sleep(2)

    # Check sessions in the active sessions section
    session_items = driver.find_elements(By.CSS_SELECTOR, "section:has(button.btn-danger) ul li")
    if not session_items:
        session_items = driver.find_elements(By.XPATH, "//h2[contains(., 'сессии') or contains(., 'Sessions')]/..//ul/li")

    assert len(session_items) >= 2, f"Expected at least 2 sessions, found {len(session_items)}"
    print(f"  Found {len(session_items)} active sessions")

    # Click the delete/revoke button on the non-current session
    revoke_btn = wait_clickable(driver, By.CSS_SELECTOR, "section:has(button.btn-danger) ul li button.btn-ghost")
    js_click(driver, revoke_btn)
    time.sleep(2)

    # Verify session count decreased
    updated_items = driver.find_elements(By.CSS_SELECTOR, "section:has(button.btn-danger) ul li")
    if not updated_items:
        updated_items = driver.find_elements(By.XPATH, "//h2[contains(., 'сессии') or contains(., 'Sessions')]/..//ul/li")
    assert len(updated_items) == len(session_items) - 1, f"Expected {len(session_items) - 1} sessions after revoke, got {len(updated_items)}"
    print("  Successfully revoked non-current session")


@step("8. Logout All Sessions")
def test_logout_all(driver):
    driver.get(f"{BASE}/settings")
    time.sleep(1.5)

    revoke_all_btn = wait_clickable(driver, By.CSS_SELECTOR, "button.btn-danger")
    js_click(driver, revoke_all_btn)
    time.sleep(2.5)

    # After logout all, navigating anywhere should redirect to /login
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    assert "/login" in driver.current_url, f"Expected /login after logout all, got {driver.current_url}"

    # Re-login to ensure clean state
    login(driver, ADMIN_USER, ADMIN_PASS)
    print("  Logout all devices verified successfully")


def main():
    driver = get_driver()
    try:
        test_login_success(driver)
        test_logout_and_protection(driver)
        test_invalid_credentials(driver)
        test_change_password(driver)
        test_verify_new_password(driver)
        test_restore_password(driver)
        test_sessions_list_and_revoke(driver)
        test_logout_all(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
