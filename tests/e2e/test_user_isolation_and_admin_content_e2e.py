#!/usr/bin/env python3
"""
E2E Test: User isolation, admin assignment, and admin content immutability.
Requirements:
1. Each user has their own folders and sets in /sets and /folders.
2. Only admin decides which sets/folders are assigned to users.
3. Users can create their own sets and folders and edit/delete them.
4. Users CANNOT modify, rename, delete, or alter admin-created/assigned sets and folders (HTTP 403 & UI guards).
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

ADMIN_SET_TITLE = "Admin Biology 101"
USER_SET_TITLE = "Student Vocab Set"
USER_FOLDER_NAME = "Student Personal Folder"
ADMIN_FOLDER_NAME = "Admin Assigned Biology Folder"

ADMIN_SET_ID = None
USER_SET_ID = None
USER_FOLDER_ID = None
ADMIN_FOLDER_ID = None
STUDENT_USER_ID = None


@step("1. Admin setups student account and admin set")
def test_admin_setup(driver):
    global ADMIN_SET_ID, STUDENT_USER_ID
    login(driver)  # logs in as testadmin

    # Check if student exists or create
    users_res = js_fetch(driver, "/admin/users?q=" + STUDENT_USER)
    items = users_res.get("body", {}).get("items", [])
    if items:
        STUDENT_USER_ID = items[0]["id"]
        # Reset password to known
        js_fetch(driver, f"/admin/users/{STUDENT_USER_ID}/reset-password", "POST", {"new_password": STUDENT_PASS})
    else:
        c_res = js_fetch(driver, "/admin/users", "POST", {
            "username": STUDENT_USER,
            "password": STUDENT_PASS,
            "role": "user"
        })
        assert c_res.get("status") in (200, 201), f"Failed to create user: {c_res}"
        STUDENT_USER_ID = c_res["body"]["user_id"]

    assert STUDENT_USER_ID is not None, "STUDENT_USER_ID not obtained"
    print(f"  Student user ID: {STUDENT_USER_ID}")

    # Create admin set
    set_res = js_fetch(driver, "/sets", "POST", {
        "title": ADMIN_SET_TITLE,
        "description": "Admin set for testing immutability and isolation",
        "cards": [
            {"front_text": "Cell", "back_text": "Basic unit of life"},
            {"front_text": "DNA", "back_text": "Genetic blueprint"},
            {"front_text": "RNA", "back_text": "Messenger"}
        ]
    })
    assert set_res.get("status") in (200, 201), f"Create admin set failed: {set_res}"
    ADMIN_SET_ID = set_res["body"]["id"]
    print(f"  Admin set created: {ADMIN_SET_ID}")

    logout(driver)


@step("2. Verify isolation: student does not see admin's set or folders")
def test_student_isolation(driver):
    login(driver, STUDENT_USER, STUDENT_PASS)

    # Check /sets
    driver.get(f"{BASE}/sets")
    time.sleep(1)
    sets_res = js_fetch(driver, "/sets")
    sets_items = sets_res.get("body", [])
    titles = [s["title"] for s in sets_items]
    assert ADMIN_SET_TITLE not in titles, f"Isolation leak! Student sees admin set: {titles}"
    print("  Student /sets is clean, does NOT contain admin set")

    # Check /folders
    driver.get(f"{BASE}/folders")
    time.sleep(1)
    folders_res = js_fetch(driver, "/folders")
    folders_items = folders_res.get("body", [])
    assert len(folders_items) == 0, f"Student has unexpected folders: {folders_items}"
    print("  Student /folders is clean and empty")


@step("3. Student creates own folder and set, and can edit them")
def test_student_creates_own_content(driver):
    global USER_SET_ID, USER_FOLDER_ID

    # 1. Create own folder
    driver.get(f"{BASE}/folders")
    time.sleep(1)
    f_res = js_fetch(driver, "/folders", "POST", {"name": USER_FOLDER_NAME})
    assert f_res.get("status") in (200, 201), f"Student failed to create folder: {f_res}"
    USER_FOLDER_ID = f_res["body"]["id"]
    print(f"  Student created own folder: {USER_FOLDER_ID}")

    # 2. Create own set
    s_res = js_fetch(driver, "/sets", "POST", {
        "title": USER_SET_TITLE,
        "description": "Student personal vocab",
        "cards": [
            {"front_text": "Bonjour", "back_text": "Hello"},
            {"front_text": "Merci", "back_text": "Thank you"}
        ]
    })
    assert s_res.get("status") in (200, 201), f"Student failed to create set: {s_res}"
    USER_SET_ID = s_res["body"]["id"]
    print(f"  Student created own set: {USER_SET_ID}")

    # 3. Add own set to own folder
    add_res = js_fetch(driver, f"/folders/{USER_FOLDER_ID}/sets/{USER_SET_ID}", "PUT")
    assert add_res.get("status") in (200, 201), f"Failed to add set to folder: {add_res}"

    # 4. Rename own folder
    ren_res = js_fetch(driver, f"/folders/{USER_FOLDER_ID}", "PATCH", {"name": USER_FOLDER_NAME + " Renamed"})
    assert ren_res.get("status") == 200, f"Failed to rename own folder: {ren_res}"

    # 5. Patch own set
    patch_res = js_fetch(driver, f"/sets/{USER_SET_ID}", "PATCH", {
        "title": USER_SET_TITLE + " Updated",
        "expected_content_version": s_res["body"]["content_version"]
    })
    assert patch_res.get("status") == 200, f"Failed to patch own set: {patch_res}"
    print("  Student successfully created, edited, and organized their own content")

    logout(driver)


@step("4. Admin assigns set and creates admin folder for student")
def test_admin_assigns_content(driver):
    global ADMIN_FOLDER_ID
    login(driver)  # testadmin

    # Verify admin can get user content
    content_res = js_fetch(driver, f"/admin/users/{STUDENT_USER_ID}/content")
    assert content_res.get("status") == 200, f"Failed to get user content: {content_res}"
    data = content_res.get("body", {})
    assert "assigned_sets" in data and "folders" in data
    print(f"  Admin fetched user content: {len(data['assigned_sets'])} sets, {len(data['folders'])} folders")

    # 1. Admin assigns admin set to student
    assign_res = js_fetch(driver, f"/admin/users/{STUDENT_USER_ID}/sets", "POST", {"set_id": ADMIN_SET_ID})
    assert assign_res.get("status") == 200, f"Failed to assign set: {assign_res}"
    print("  Admin assigned set to student")

    # 2. Admin creates folder for student with that set
    f_res = js_fetch(driver, f"/admin/users/{STUDENT_USER_ID}/folders", "POST", {
        "name": ADMIN_FOLDER_NAME,
        "set_ids": [ADMIN_SET_ID]
    })
    assert f_res.get("status") == 200, f"Failed to create admin folder: {f_res}"
    ADMIN_FOLDER_ID = f_res["body"]["folder_id"]
    print(f"  Admin created folder for student: {ADMIN_FOLDER_ID}")

    logout(driver)


@step("5. Verify student sees assigned content with admin badges")
def test_student_sees_assigned_content(driver):
    login(driver, STUDENT_USER, STUDENT_PASS)

    # 1. Check /sets: should see ADMIN_SET_TITLE with badge
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    page_text = driver.page_source
    assert ADMIN_SET_TITLE in page_text, "Admin set not found in student's /sets"
    assert "Назначено администратором" in page_text, "Admin badge not visible in /sets"
    print("  Student sees assigned admin set with badge in /sets")

    # 2. Check /folders: should see ADMIN_FOLDER_NAME with badge
    driver.get(f"{BASE}/folders")
    time.sleep(1.5)
    page_text = driver.page_source
    assert ADMIN_FOLDER_NAME in page_text, "Admin folder not found in student's /folders"
    assert "Назначено администратором" in page_text, "Admin badge not visible in /folders"
    print("  Student sees assigned admin folder with badge in /folders")


@step("6. Verify student CANNOT modify admin-created folder (immutability)")
def test_admin_folder_immutability(driver):
    # 1. Try to delete admin folder -> MUST FAIL with 403
    del_res = js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}", "DELETE")
    assert del_res.get("status") == 403, f"Expected 403 on delete admin folder, got: {del_res}"
    print("  DELETE /folders/{admin_folder_id} -> 403 Forbidden (Blocked as required)")

    # 2. Try to rename admin folder -> MUST FAIL with 403
    ren_res = js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}", "PATCH", {"name": "Hacked Folder"})
    assert ren_res.get("status") == 403, f"Expected 403 on rename admin folder, got: {ren_res}"
    print("  PATCH /folders/{admin_folder_id} -> 403 Forbidden (Blocked as required)")

    # 3. Try to add a set to admin folder -> MUST FAIL with 403
    add_res = js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}/sets/{USER_SET_ID}", "PUT")
    assert add_res.get("status") == 403, f"Expected 403 on add set to admin folder, got: {add_res}"
    print("  PUT /folders/{admin_folder_id}/sets -> 403 Forbidden (Blocked as required)")

    # 4. Try to remove a set from admin folder -> MUST FAIL with 403
    rem_res = js_fetch(driver, f"/folders/{ADMIN_FOLDER_ID}/sets/{ADMIN_SET_ID}", "DELETE")
    assert rem_res.get("status") == 403, f"Expected 403 on remove set from admin folder, got: {rem_res}"
    print("  DELETE /folders/{admin_folder_id}/sets -> 403 Forbidden (Blocked as required)")


@step("7. Verify student CANNOT modify admin-created set (immutability)")
def test_admin_set_immutability(driver):
    # 1. Student opens set detail page: can view, but no Edit or Delete buttons
    driver.get(f"{BASE}/sets/{ADMIN_SET_ID}")
    time.sleep(1.5)
    page_text = driver.page_source
    assert ADMIN_SET_TITLE in page_text, "Cannot view admin set"
    assert "Назначено администратором" in page_text, "Badge missing on set detail page"

    # Verify editor button is absent for non-owner
    edit_btns = driver.find_elements(By.ID, "btn-edit-details")
    assert len(edit_btns) == 0, "Non-owner should not see 'Изменить' button"

    # 2. Try to navigate directly to editor: must show read-only block banner
    driver.get(f"{BASE}/sets/{ADMIN_SET_ID}/edit")
    time.sleep(1.5)
    editor_text = driver.page_source
    assert "Редактирование недоступно" in editor_text or "только для чтения" in editor_text, \
        f"Editor did not show read-only banner for admin set: {editor_text[:500]}"
    print("  Editor UI blocked with read-only banner")

    # 3. Try to add cards via API -> MUST FAIL with 403
    add_card_res = js_fetch(driver, f"/sets/{ADMIN_SET_ID}/cards/batch", "POST", {
        "cards": [{"front_text": "Hacked", "back_text": "Card"}],
        "expected_content_version": 1
    })
    assert add_card_res.get("status") == 403, f"Expected 403 on add card to admin set, got: {add_card_res}"
    print("  POST /sets/{admin_set_id}/cards/batch -> 403 Forbidden (Blocked as required)")

    # 4. Try to patch set metadata via API -> MUST FAIL with 404 or 403
    patch_res = js_fetch(driver, f"/sets/{ADMIN_SET_ID}", "PATCH", {
        "title": "Hacked Title",
        "expected_content_version": 1
    })
    assert patch_res.get("status") in (403, 404), f"Expected 403/404 on patch admin set, got: {patch_res}"
    print("  PATCH /sets/{admin_set_id} -> 404/403 Forbidden (Blocked as required)")

    # 5. Try to delete set via API -> MUST FAIL with 404 or 403
    del_res = js_fetch(driver, f"/sets/{ADMIN_SET_ID}", "DELETE")
    assert del_res.get("status") in (403, 404), f"Expected 403/404 on delete admin set, got: {del_res}"
    print("  DELETE /sets/{admin_set_id} -> 404/403 Forbidden (Blocked as required)")

    # 6. Try to remove admin set from library via API -> MUST FAIL with 403
    lib_del_res = js_fetch(driver, f"/library/sets/{ADMIN_SET_ID}", "DELETE")
    assert lib_del_res.get("status") == 403, f"Expected 403 on remove admin set from library, got: {lib_del_res}"
    print("  DELETE /library/sets/{admin_set_id} -> 403 Forbidden (Blocked as required)")

    logout(driver)


@step("8. Admin unassigns content and removes admin folder")
def test_admin_unassigns_content(driver):
    login(driver)  # testadmin

    # Admin unassigns set from student
    unassign_res = js_fetch(driver, f"/admin/users/{STUDENT_USER_ID}/sets/{ADMIN_SET_ID}", "DELETE")
    assert unassign_res.get("status") == 200, f"Failed to unassign set: {unassign_res}"
    print("  Admin unassigned set from student")

    # Admin deletes admin folder
    del_f_res = js_fetch(driver, f"/admin/users/{STUDENT_USER_ID}/folders/{ADMIN_FOLDER_ID}", "DELETE")
    assert del_f_res.get("status") == 200, f"Failed to delete admin folder: {del_f_res}"
    print("  Admin deleted admin folder")

    logout(driver)


@step("9. Verify student clean state after unassign")
def test_student_state_after_unassign(driver):
    login(driver, STUDENT_USER, STUDENT_PASS)

    # Check /sets: admin set is gone, student's own set remains
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)
    sets_res = js_fetch(driver, "/sets")
    titles = [s["title"] for s in sets_res.get("body", [])]
    assert ADMIN_SET_TITLE not in titles, f"Admin set still visible after unassign: {titles}"
    assert any(USER_SET_TITLE in t for t in titles), f"Student's own set missing: {titles}"
    print("  Admin set successfully disappeared from student's library, own set intact")

    # Check /folders: admin folder is gone, student's own folder remains
    driver.get(f"{BASE}/folders")
    time.sleep(1.5)
    folders_res = js_fetch(driver, "/folders")
    f_names = [f["name"] for f in folders_res.get("body", [])]
    assert ADMIN_FOLDER_NAME not in f_names, f"Admin folder still visible after delete: {f_names}"
    assert any(USER_FOLDER_NAME in n for n in f_names), f"Student's own folder missing: {f_names}"
    print("  Admin folder successfully disappeared, student's own folder intact")

    # Clean up student's own content
    js_fetch(driver, f"/folders/{USER_FOLDER_ID}", "DELETE")
    js_fetch(driver, f"/sets/{USER_SET_ID}", "DELETE")
    print("  Student's own test content cleaned up")

    logout(driver)


def main():
    driver = None
    try:
        driver = get_driver()
        test_admin_setup(driver)
        test_student_isolation(driver)
        test_student_creates_own_content(driver)
        test_admin_assigns_content(driver)
        test_student_sees_assigned_content(driver)
        test_admin_folder_immutability(driver)
        test_admin_set_immutability(driver)
        test_admin_unassigns_content(driver)
        test_student_state_after_unassign(driver)
    finally:
        if driver:
            safe_quit(driver)

    success = print_summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
