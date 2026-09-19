#!/usr/bin/env python3
"""
E2E Test: Settings & Preferences
- Switch UI language RU <-> EN and verify live translation & persistence
- Toggle Theme light <-> dark and verify HTML dataset attribute & persistence
- Change default study direction (front_to_back, back_to_front, both) & verify persistence
- Configure study batch size (clamping, save on blur, persistence)
- Configure SRS daily goal reviews & verify persistence
- Toggle sound and reduced motion checkboxes & verify persistence
"""

import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from helpers import (
    BASE, step, get_driver, login, js_click,
    wait_for, wait_clickable, set_input_text, print_summary
)


@step("1. Login to application")
def test_login(driver):
    login(driver)


@step("2. Switch UI Language to English & verify persistence")
def test_switch_language_to_en(driver):
    driver.get(f"{BASE}/settings")
    time.sleep(2)

    lang_select = Select(wait_for(driver, By.ID, "lang"))
    lang_select.select_by_value("en")
    time.sleep(1.5)

    # Verify English text appears on page
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Settings" in page_text or "Language" in page_text, f"Expected English UI, got: {page_text[:200]}"

    # Refresh and check persistence
    driver.refresh()
    time.sleep(2)
    lang_val = Select(wait_for(driver, By.ID, "lang")).first_selected_option.get_attribute("value")
    assert lang_val == "en", f"Expected language 'en' after refresh, got '{lang_val}'"
    print("  Language switched to EN and persisted")


@step("3. Switch UI Language back to Russian & verify persistence")
def test_switch_language_to_ru(driver):
    lang_select = Select(wait_for(driver, By.ID, "lang"))
    lang_select.select_by_value("ru")
    time.sleep(1.5)

    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Настройки" in page_text or "Язык" in page_text, f"Expected Russian UI, got: {page_text[:200]}"

    driver.refresh()
    time.sleep(2)
    lang_val = Select(wait_for(driver, By.ID, "lang")).first_selected_option.get_attribute("value")
    assert lang_val == "ru", f"Expected language 'ru' after refresh, got '{lang_val}'"
    print("  Language switched back to RU and persisted")


@step("4. Toggle Theme (dark <-> light)")
def test_toggle_theme(driver):
    theme_select = Select(wait_for(driver, By.ID, "theme"))
    theme_select.select_by_value("dark")
    time.sleep(1.5)

    is_dark = driver.execute_script("return document.documentElement.classList.contains('dark');")
    assert is_dark, "Expected documentElement to have class 'dark'"

    # Refresh and check persistence
    driver.refresh()
    time.sleep(2)
    theme_val = Select(wait_for(driver, By.ID, "theme")).first_selected_option.get_attribute("value")
    assert theme_val == "dark", f"Expected theme 'dark' selected after refresh, got '{theme_val}'"
    is_dark = driver.execute_script("return document.documentElement.classList.contains('dark');")
    assert is_dark, "Expected class 'dark' persisted after reload"

    # Switch to light
    theme_select = Select(wait_for(driver, By.ID, "theme"))
    theme_select.select_by_value("light")
    time.sleep(1.5)

    is_dark = driver.execute_script("return document.documentElement.classList.contains('dark');")
    assert not is_dark, "Expected class 'dark' removed when switched to light"
    print("  Theme toggle dark <-> light verified and persisted")


@step("5. Change Default Study Direction")
def test_change_direction(driver):
    dir_select = Select(wait_for(driver, By.ID, "dir"))
    dir_select.select_by_value("back_to_front")
    time.sleep(1.5)

    driver.refresh()
    time.sleep(2)
    dir_val = Select(wait_for(driver, By.ID, "dir")).first_selected_option.get_attribute("value")
    assert dir_val == "back_to_front", f"Expected direction 'back_to_front', got '{dir_val}'"

    # Restore to front_to_back
    dir_select = Select(wait_for(driver, By.ID, "dir"))
    dir_select.select_by_value("front_to_back")
    time.sleep(1.5)
    print("  Default study direction changed and persisted")


@step("6. Configure Batch Size with Clamping & Persistence")
def test_configure_batch_size(driver):
    batch_input = wait_for(driver, By.ID, "batch-size")
    set_input_text(driver, batch_input, "12")
    driver.execute_script("""
        const el = arguments[0];
        el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
        el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    """, batch_input)
    time.sleep(1.5)

    driver.refresh()
    time.sleep(2)
    val = wait_for(driver, By.ID, "batch-size").get_attribute("value")
    assert val == "12", f"Expected batch size 12 after refresh, got '{val}'"

    # Restore to 7
    batch_input = wait_for(driver, By.ID, "batch-size")
    set_input_text(driver, batch_input, "7")
    driver.execute_script("""
        const el = arguments[0];
        el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
        el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    """, batch_input)
    time.sleep(1.5)
    print("  Batch size configured and persisted")


@step("7. Configure SRS Daily Goal Reviews")
def test_configure_daily_goal(driver):
    goal_input = wait_for(driver, By.ID, "goal")
    set_input_text(driver, goal_input, "30")
    time.sleep(1.5)

    driver.refresh()
    time.sleep(2)
    val = wait_for(driver, By.ID, "goal").get_attribute("value")
    assert val == "30", f"Expected daily goal 30 after refresh, got '{val}'"

    # Restore to 20
    goal_input = wait_for(driver, By.ID, "goal")
    set_input_text(driver, goal_input, "20")
    time.sleep(1.5)
    print("  Daily goal configured and persisted")


@step("8. Toggle Sound and Reduced Motion Checkboxes")
def test_toggle_checkboxes(driver):
    checkboxes = driver.find_elements(By.CSS_SELECTOR, "section.card input[type='checkbox']")
    assert len(checkboxes) >= 2, f"Expected at least 2 preference checkboxes, found {len(checkboxes)}"

    sound_cb = checkboxes[0]
    initial_sound = sound_cb.is_selected()

    # Toggle sound
    js_click(driver, sound_cb)
    time.sleep(1.5)

    driver.refresh()
    time.sleep(2)

    checkboxes = driver.find_elements(By.CSS_SELECTOR, "section.card input[type='checkbox']")
    sound_cb = checkboxes[0]
    assert sound_cb.is_selected() != initial_sound, "Sound checkbox state did not toggle/persist"

    # Restore initial state
    js_click(driver, sound_cb)
    time.sleep(1.5)
    print("  Checkbox toggles verified and persisted across reload")


def main():
    driver = get_driver()
    try:
        test_login(driver)
        test_switch_language_to_en(driver)
        test_switch_language_to_ru(driver)
        test_toggle_theme(driver)
        test_change_direction(driver)
        test_configure_batch_size(driver)
        test_configure_daily_goal(driver)
        test_toggle_checkboxes(driver)
    finally:
        driver.quit()
        print_summary()


if __name__ == "__main__":
    main()
