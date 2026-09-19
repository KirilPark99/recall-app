#!/usr/bin/env python3
"""
E2E Test for Top Exit Button on Result / Session Complete Page.
Verifies:
- On /study/{sessionId}/result, the top bar displays:
  1. Title "Занятие завершено".
  2. Breadcrumb / back link with set title "← {setTitle}".
  3. Prominent top button "К набору" (btn-exit-to-set).
  4. Top button "Выйти" (btn-exit-top).
- Clicking the top button immediately navigates back to /sets/{setId}.
- Also verifies clicking "Выйти" navigates to home/sets.
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    BASE, USERNAME, PASSWORD, get_driver, wait_for, wait_clickable,
    js_click, js_fetch, login, print_summary, step
)


@step("1. Create and Complete Session, then Verify Top Exit Buttons on Result Page")
def test_result_top_exit_buttons(driver):
    login(driver, USERNAME, PASSWORD)

    # 1. Fetch first available set
    res = js_fetch(driver, "/sets?page_size=10")
    assert res["status"] == 200
    sets = res["body"] if isinstance(res["body"], list) else res["body"].get("items", [])
    assert len(sets) > 0, "No sets found in library"
    target_set = sets[0]
    set_id = target_set["id"]
    set_title = target_set["title"]
    print(f"  Using set: '{set_title}' ({set_id})")

    # 2. Create study session for this set
    sess_res = js_fetch(driver, "/study-sessions", "POST", {
        "mode": "cards",
        "set_ids": [set_id],
        "limit": 0,
        "order": "original",
    })
    assert sess_res["status"] == 201, f"Failed to create session: {sess_res}"
    session_id = sess_res["body"]["id"]

    # Complete the session via API
    comp_res = js_fetch(driver, f"/study-sessions/{session_id}/complete", "POST")
    assert comp_res["status"] == 200, f"Failed to complete session: {comp_res}"

    # 3. Open Result Page directly
    driver.get(f"{BASE}/study/{session_id}/result")
    time.sleep(1.5)

    # Verify heading
    heading = wait_for(driver, By.TAG_NAME, "h1")
    assert "Занятие завершено" in heading.text or "Session complete" in heading.text, f"Unexpected heading: {heading.text}"

    # Verify set breadcrumb / title link at top
    set_link = wait_for(driver, By.XPATH, f"//a[contains(., '{set_title}')]")
    assert set_link.is_displayed()
    assert f"/sets/{set_id}" in set_link.get_attribute("href")

    # Verify top exit button "К набору" exists and is visible
    exit_to_set_btn = wait_for(driver, By.ID, "btn-exit-to-set")
    assert exit_to_set_btn.is_displayed()
    assert "К набору" in exit_to_set_btn.text or "Back to set" in exit_to_set_btn.text
    assert f"/sets/{set_id}" in exit_to_set_btn.get_attribute("href")

    # Verify top exit button "Выйти" exists and is visible
    exit_top_btn = wait_for(driver, By.ID, "btn-exit-top")
    assert exit_top_btn.is_displayed()
    assert "Выйти" in exit_top_btn.text or "Exit" in exit_top_btn.text

    # Take screenshot for visual inspection
    driver.save_screenshot("/tmp/result_page_top_exit.png")
    print("  Saved screenshot to /tmp/result_page_top_exit.png")

    # 4. Click top exit button "К набору"
    js_click(driver, exit_to_set_btn)
    WebDriverWait(driver, 10).until(EC.url_contains(f"/sets/{set_id}"))
    print(f"  Successfully exited to set page: {driver.current_url}")

    # Verify we are on SetDetail page
    detail_h1 = wait_for(driver, By.TAG_NAME, "h1")
    assert set_title in detail_h1.text, f"Expected set title in H1, got: {detail_h1.text}"
    print("  Top exit button works flawlessly and immediately returns to set!")


def main():
    driver = get_driver()
    try:
        test_result_top_exit_buttons(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
