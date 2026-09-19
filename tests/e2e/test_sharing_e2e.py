#!/usr/bin/env python3
"""
E2E Test: Sharing & Permissions Lifecycle
- Create set as owner
- Open Share Dialog
- Create shareable access link
- Grant direct permission to another user
- Revoke direct permission
- Revoke share link
- Create fresh share link and redeem as second user
- Verify recipient has reader access (read cards, no edit controls)
- Clean up test set and test user
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from helpers import (
    BASE, step, get_driver, login, logout, js_click, js_fetch,
    wait_for, wait_clickable, set_input_text, create_test_set,
    delete_test_set, print_summary
)

SET_ID = None
RECIPIENT_USERNAME = "share_tester_e2e"
RECIPIENT_PASSWORD = "SharePassword123!"
RECIPIENT_USER_ID = None
SHARE_TOKEN = None


@step("1. Login as Admin Owner")
def test_login_admin(driver):
    login(driver)


@step("2. Setup Set and Recipient User")
def test_setup_set_and_second_user(driver):
    global SET_ID, RECIPIENT_USER_ID
    SET_ID = create_test_set(
        driver,
        title="Sharing E2E Test Set",
        cards=[("Carbon", "Углерод"), ("Nitrogen", "Азот")],
    )
    print(f"  Created test set {SET_ID}")

    # Ensure recipient user exists
    users_resp = js_fetch(driver, "/admin/users", "GET")
    if users_resp and users_resp.get("status") == 200:
        items = users_resp.get("body", {}).get("items", [])
        existing = [u for u in items if u.get("username") == RECIPIENT_USERNAME]
        if existing:
            RECIPIENT_USER_ID = existing[0]["id"]
            print(f"  Recipient user already exists: {RECIPIENT_USERNAME} (ID: {RECIPIENT_USER_ID})")
        else:
            create_resp = js_fetch(driver, "/admin/users", "POST", {
                "username": RECIPIENT_USERNAME,
                "password": RECIPIENT_PASSWORD,
                "role": "user",
            })
            assert create_resp and create_resp.get("status") in (200, 201), f"Failed to create user: {create_resp}"
            RECIPIENT_USER_ID = create_resp.get("body", {}).get("user_id")
            print(f"  Created recipient user: {RECIPIENT_USERNAME} (ID: {RECIPIENT_USER_ID})")


@step("3. Open Share Dialog via UI")
def test_open_share_dialog(driver):
    driver.get(f"{BASE}/sets/{SET_ID}")
    time.sleep(2)

    share_btn = wait_clickable(driver, By.ID, "btn-share-set")
    js_click(driver, share_btn)
    time.sleep(1)

    dialog = wait_for(driver, By.CSS_SELECTOR, "div[role='dialog']")
    assert "Доступ к набору" in dialog.text, "Share dialog did not open"
    print("  Share dialog opened successfully")


@step("4. Create Shareable Access Link")
def test_create_share_link(driver):
    # Click 'Создать ссылку'
    create_link_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать ссылку') or contains(., 'Create link')]")
    js_click(driver, create_link_btn)
    time.sleep(1.5)

    code_elem = wait_for(driver, By.CSS_SELECTOR, "div[role='dialog'] code")
    link_text = code_elem.text
    assert "/share/" in link_text, f"Expected share link URL, got: {link_text}"
    token = link_text.split("/share/")[-1].strip()
    assert len(token) > 0, "Failed to extract token from share link"
    print(f"  Created share link with token: {token}")


@step("5. Grant Direct Permission to User")
def test_grant_direct_permission(driver):
    user_input = wait_for(driver, By.CSS_SELECTOR, "input[aria-label='Имя пользователя']")
    set_input_text(driver, user_input, RECIPIENT_USERNAME)

    grant_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Дать доступ')]")
    js_click(driver, grant_btn)
    time.sleep(1.5)

    # Verify user appears in perms list
    perm_items = driver.find_elements(By.CSS_SELECTOR, "section[aria-label='Пользователи'] ul li")
    usernames = [p.text for p in perm_items]
    assert any(RECIPIENT_USERNAME in u for u in usernames), f"Expected {RECIPIENT_USERNAME} in permissions list, found: {usernames}"
    print(f"  Granted direct permission to {RECIPIENT_USERNAME}")


@step("6. Revoke Direct Permission")
def test_revoke_direct_permission(driver):
    perm_items = driver.find_elements(By.CSS_SELECTOR, "section[aria-label='Пользователи'] ul li")
    target_li = None
    for li in perm_items:
        if RECIPIENT_USERNAME in li.text:
            target_li = li
            break
    assert target_li is not None, f"Could not find {RECIPIENT_USERNAME} item to revoke"

    del_btn = target_li.find_element(By.CSS_SELECTOR, "button")
    js_click(driver, del_btn)
    time.sleep(1.5)

    perm_items_after = driver.find_elements(By.CSS_SELECTOR, "section[aria-label='Пользователи'] ul li")
    usernames_after = [p.text for p in perm_items_after]
    assert not any(RECIPIENT_USERNAME in u for u in usernames_after), f"{RECIPIENT_USERNAME} still present after revoking"
    print(f"  Revoked direct permission for {RECIPIENT_USERNAME}")


@step("7. Revoke Share Link")
def test_revoke_share_link(driver):
    trash_btn = wait_clickable(driver, By.CSS_SELECTOR, "section[aria-label='Ссылки'] ul li button")
    js_click(driver, trash_btn)
    time.sleep(1.5)

    WebDriverWait(driver, 8).until(
        lambda d: any("отозвана" in l.text for l in d.find_elements(By.CSS_SELECTOR, "section[aria-label='Ссылки'] ul li"))
    )
    print("  Revoked share link verified (marked as отозвана)")


@step("8. Create New Share Link and Redeem as Recipient User")
def test_redeem_share_link_as_recipient(driver):
    global SHARE_TOKEN
    # Create another fresh link for recipient to redeem
    create_link_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Создать ссылку') or contains(., 'Create link')]")
    js_click(driver, create_link_btn)
    time.sleep(1.5)

    code_elem = wait_for(driver, By.CSS_SELECTOR, "div[role='dialog'] code")
    link_text = code_elem.text
    SHARE_TOKEN = link_text.split("/share/")[-1].strip()
    print(f"  Fresh share token: {SHARE_TOKEN}")

    # Logout admin
    driver.get(f"{BASE}/")
    time.sleep(1)
    logout(driver)

    # Login as recipient user
    login(driver, username=RECIPIENT_USERNAME, password=RECIPIENT_PASSWORD)
    time.sleep(1.5)

    # Navigate to redeem page
    driver.get(f"{BASE}/share/{SHARE_TOKEN}")
    time.sleep(2)

    # Verify redemption screen
    open_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Открыть набор')]")
    js_click(driver, open_btn)
    time.sleep(2)

    # Verify we are on the set page
    assert f"/sets/{SET_ID}" in driver.current_url, f"Expected set page, got {driver.current_url}"
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Carbon" in body_text and "Nitrogen" in body_text, "Cards not visible to recipient"

    # Verify recipient cannot edit (no edit metadata or delete buttons)
    edit_btns = driver.find_elements(By.ID, "btn-edit-details")
    delete_btns = driver.find_elements(By.ID, "btn-delete-set")
    assert len(edit_btns) == 0, "Recipient should NOT see edit details button"
    assert len(delete_btns) == 0, "Recipient should NOT see delete set button"
    print(f"  Recipient successfully redeemed share link and has read-only access to set {SET_ID}")


@step("9. Cleanup Test Data")
def test_cleanup(driver):
    global SET_ID, RECIPIENT_USER_ID
    logout(driver)
    login(driver)  # login back as admin

    if SET_ID:
        delete_test_set(driver, SET_ID)
        print(f"  Cleaned up test set {SET_ID}")
        SET_ID = None

    if RECIPIENT_USER_ID:
        resp = js_fetch(driver, f"/admin/users/{RECIPIENT_USER_ID}", "DELETE")
        print(f"  Deleted recipient user {RECIPIENT_USER_ID}: status {resp.get('status') if resp else 'unknown'}")
        RECIPIENT_USER_ID = None


def main():
    driver = get_driver()
    try:
        test_login_admin(driver)
        test_setup_set_and_second_user(driver)
        test_open_share_dialog(driver)
        test_create_share_link(driver)
        test_grant_direct_permission(driver)
        test_revoke_direct_permission(driver)
        test_revoke_share_link(driver)
        test_redeem_share_link_as_recipient(driver)
    finally:
        try:
            test_cleanup(driver)
        except Exception as e:
            print(f"  Cleanup failed: {e}")
        driver.quit()
        print_summary()


if __name__ == "__main__":
    main()
