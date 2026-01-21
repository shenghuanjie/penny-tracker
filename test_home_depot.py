import time
import random
import undetected_chromedriver as uc
from selenium import webdriver  # Need this for ActionChains
from selenium.webdriver.common.action_chains import ActionChains  # Import Standard ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def main():
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-popup-blocking")

    driver = uc.Chrome(options=options, version_main=138)
    driver.get("https://www.homedepot.com")
    wait = WebDriverWait(driver, 15)

    try:
        zip_code = "94538"
        print(f"--- Starting Zip Update to {zip_code} ---")

        # 1. Click Trigger
        print("Looking for 'Delivery Zip' button...")
        trigger = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[@data-testid='delivery-zip-button']")))
        driver.execute_script("arguments[0].click();", trigger)
        print("Trigger clicked.")

        # 2. Wait for Drawer
        print("Waiting for drawer content...")
        wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//div[@data-testid='header-drawer-content']")))
        time.sleep(2)

        # 3. Find Input (JS Strategy)
        print("Finding input...")
        zip_input = driver.execute_script("""
            var drawer = document.querySelector('div[data-testid="header-drawer-content"]');
            if (!drawer) return null;
            return drawer.querySelector('input[placeholder="Enter ZIP Code"]');
        """)

        if not zip_input:
            raise Exception("Input not found via JS!")

        # 4. THE FIX: React-Compatible Typing
        # A. Clear value via JS (Safer than Ctrl+A which fails on Mac)
        driver.execute_script("arguments[0].value = '';", zip_input)

        # B. Focus
        driver.execute_script("arguments[0].focus();", zip_input)

        # C. Type normally (Standard selenium method on the element)
        # We use .send_keys on the element directly, not ActionChains
        zip_input.send_keys(zip_code)

        # D. CRITICAL: Force React to see the change
        # This manually fires the events that React listens for
        print("Dispatching React events...")
        driver.execute_script("""
            var element = arguments[0];
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            element.dispatchEvent(new KeyboardEvent('blur', { bubbles: true }));
        """, zip_input)

        time.sleep(1)

        # 5. Click Update
        print("Clicking Update...")
        update_btn = driver.find_element(By.XPATH,
                                         "//div[@data-testid='header-drawer-content']//button[contains(text(), 'Update')]")
        driver.execute_script("arguments[0].click();", update_btn)

        print("Update clicked. Waiting for page reload...")
        time.sleep(5)

    except Exception as e:
        print(f"!!! FAILED: {e}")
        driver.save_screenshot("debug_failure.png")

    print("Continuing...")
    time.sleep(10)


if __name__ == "__main__":
    main()
