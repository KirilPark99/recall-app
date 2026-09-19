#!/usr/bin/env python3
"""
E2E Test: Import & Export (Text import, preview, set creation, JSON/CSV export)
"""

import sys
import time
from selenium.webdriver.common.by import By
from helpers import (
    BASE, step, get_driver, login, js_click, js_fetch,
    wait_for, wait_clickable, delete_test_set, print_summary
)

IMPORTED_SET_TITLE = "Imported Animals Test Set"
IMPORTED_SET_ID = None

IMPORT_TEXT = """cat\tкот
dog\tсобака
fish\tрыба
bird\tптица"""


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Open Import dialog from Sets page")
def test_open_import(driver):
    driver.get(f"{BASE}/sets")
    time.sleep(1.5)

    # Click "Импорт наборов" / "Import"
    import_btn = wait_clickable(driver, By.XPATH, "//button[contains(., 'Импорт') or contains(., 'Import')]")
    js_click(driver, import_btn)
    time.sleep(1)

    # Verify dialog is open
    dialog = wait_for(driver, By.CSS_SELECTOR, "div[role='dialog']")
    assert dialog.is_displayed(), "Import dialog not displayed"
    print("  Import dialog opened successfully")


@step("3. Enter TSV data and request preview")
def test_enter_data_preview(driver):
    textarea = wait_for(driver, By.ID, "import-text")
    textarea.clear()
    textarea.send_keys(IMPORT_TEXT)

    # Select delimiter Tab
    delim_select = driver.find_element(By.ID, "import-delim")
    driver.execute_script("arguments[0].value = 'tab'; arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", delim_select)
    time.sleep(0.5)

    # Submit preview
    preview_btn = wait_clickable(driver, By.XPATH, "//button[@type='submit' and (contains(., 'предпросмотр') or contains(., 'Preview') or contains(., 'Показать'))]")
    js_click(driver, preview_btn)
    time.sleep(2)

    # Verify preview table has rows
    sample_rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    assert len(sample_rows) >= 4, f"Expected at least 4 sample rows, got {len(sample_rows)}"
    print(f"  Preview verified: {len(sample_rows)} rows displayed")


@step("4. Confirm import with set title")
def test_confirm_import(driver):
    global IMPORTED_SET_ID

    title_input = wait_for(driver, By.ID, "import-title")
    title_input.clear()
    title_input.send_keys(IMPORTED_SET_TITLE)
    time.sleep(0.5)

    confirm_btn = wait_clickable(driver, By.XPATH, "//div[@role='dialog']//button[contains(@class, 'btn-primary') and (contains(., 'Импортировать') or contains(., 'Import'))]")
    js_click(driver, confirm_btn)
    time.sleep(3)

    # Verify we navigated to the new set page
    assert "/sets/" in driver.current_url and "/sets" != driver.current_url, f"Expected /sets/{{id}} URL, got {driver.current_url}"
    IMPORTED_SET_ID = driver.current_url.split("/sets/")[1].split("?")[0].split("/")[0]
    print(f"  Imported set created with ID: {IMPORTED_SET_ID}")


@step("5. Verify imported cards on SetDetail page")
def test_verify_imported_cards(driver):
    driver.get(f"{BASE}/sets/{IMPORTED_SET_ID}")
    time.sleep(1.5)

    # Check title
    h1 = wait_for(driver, By.CSS_SELECTOR, "h1")
    assert IMPORTED_SET_TITLE in h1.text, f"Expected set title '{IMPORTED_SET_TITLE}', got '{h1.text}'"

    # Check cards via API
    cards_res = js_fetch(driver, f"/sets/{IMPORTED_SET_ID}/cards")
    assert cards_res.get("status") == 200, f"Failed to get cards: {cards_res}"
    items = cards_res["body"].get("items", [])
    assert len(items) == 4, f"Expected 4 cards, got {len(items)}"
    terms = [c["front_text"] for c in items]
    assert "cat" in terms and "dog" in terms and "fish" in terms, f"Terms missing in {terms}"
    print(f"  Verified 4 cards imported: {terms}")


@step("6. Verify JSON Export")
def test_export_json(driver):
    res = js_fetch(driver, f"/sets/{IMPORTED_SET_ID}/export?format=json")
    assert res.get("status") == 200, f"JSON export failed: {res}"
    body = res.get("body", {})
    assert "cards" in body or "items" in body or len(body) > 0, f"Empty JSON export body: {body}"
    print("  JSON export verified via API")


@step("7. Verify CSV Export")
def test_export_csv(driver):
    # Fetch CSV raw text
    script = f"""
        const res = await fetch('/api/v1/sets/{IMPORTED_SET_ID}/export?format=csv', {{ credentials: 'same-origin' }});
        return {{ status: res.status, text: await res.text() }};
    """
    res = driver.execute_script(f"return (async () => {{ {script} }})()")
    assert res.get("status") == 200, f"CSV export failed: {res}"
    csv_text = res.get("text", "")
    assert "cat" in csv_text and "dog" in csv_text, f"CSV export missing terms: {csv_text}"
    print("  CSV export verified")


@step("8. Cleanup imported set")
def test_cleanup(driver):
    global IMPORTED_SET_ID
    if IMPORTED_SET_ID:
        delete_test_set(driver, IMPORTED_SET_ID)
        print("  Cleaned up imported set")


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_open_import(driver)
        test_enter_data_preview(driver)
        test_confirm_import(driver)
        test_verify_imported_cards(driver)
        test_export_json(driver)
        test_export_csv(driver)
        test_cleanup(driver)
    finally:
        driver.quit()

    if not print_summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
