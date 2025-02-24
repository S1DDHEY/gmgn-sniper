import asyncio
import time
import subprocess
import os
import sys
import pyautogui
import pandas as pd
import re
import csv
from bs4 import BeautifulSoup

# =============================================================================
# Configuration
# =============================================================================

# Base URL with placeholder (token)
BASE_URL = "https://gmgn.ai/sol/token/{placeholder}"

# Path to your Chrome executable (adjust if needed)
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Temporary user data directory (make sure it exists)
TEMP_USER_DATA_DIR = r"C:\temp\my_temp_chrome_profile"
os.makedirs(TEMP_USER_DATA_DIR, exist_ok=True)

# Remote debugging port for Chrome (must be free)
REMOTE_DEBUGGING_PORT = 9223

# Image file path for the pop-up close (cross) button
IMAGE_CLOSE = "./images/close_button.png"

# Confidence level for image matching (requires OpenCV)
CONFIDENCE = 0.8

# Paths for token input and logging/output folders
TOKEN_FILE_PATH = "./data/new_coins.txt"
LOG_FILE_PATH = "./data/log.txt"
OUTPUT_DIR = "./data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =============================================================================
# Stdout Tee Setup (logs stdout to both console and a log file)
# =============================================================================

class Tee:
    """
    A simple class to redirect stdout to multiple file-like objects.
    """
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()

def setup_stdout_tee(log_file_path):
    log_dir = os.path.dirname(log_file_path)
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(log_file_path, "a", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, log_file)

# =============================================================================
# PyAutoGUI Helper Function
# =============================================================================

def wait_and_click(image_file, description, timeout=30, region=None, confidence=CONFIDENCE):
    """
    Wait until the given image appears on the screen (or within a region) and then click its center.
    """
    print(f"Waiting for {description}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        location = pyautogui.locateOnScreen(image_file, confidence=confidence, region=region)
        if location:
            center = pyautogui.center(location)
            pyautogui.moveTo(center.x, center.y, duration=0.25)
            pyautogui.click()
            print(f"Clicked on {description}.")
            return True
        time.sleep(1)
    print(f"Timeout: Could not find {description}.")
    return False

# =============================================================================
# Browser Launch and Termination
# =============================================================================

def launch_browser(url):
    """
    Launch a new Chrome instance with remote debugging enabled and open the given URL.
    """
    args = [
        CHROME_PATH,
        f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}",
        f"--user-data-dir={TEMP_USER_DATA_DIR}",
        url
    ]
    process = subprocess.Popen(args)
    print(f"Launched Chrome with URL: {url}")
    return process

def terminate_browser_with_pyautogui(process):
    """
    Close the Chrome tab using the Ctrl+w shortcut via pyautogui.
    """
    print("Closing the Chrome tab using Ctrl+w shortcut...")
    pyautogui.hotkey('ctrl', 'w')
    time.sleep(3)
    print("Chrome tab closed.")

# =============================================================================
# Token File Reader using Pandas
# =============================================================================

def read_last_token(file_path):
    """
    Reads the token (placeholder) from the last non-empty line of a text file.
    """
    if not os.path.exists(file_path):
        print(f"Token file {file_path} does not exist.")
        return None
    try:
        df = pd.read_csv(file_path, header=None, names=["token"])
        if df.empty:
            print("Token file is empty.")
            return None
        last_token = df.iloc[-1]["token"]
        return str(last_token).strip()
    except Exception as e:
        print(f"Error reading token file: {e}")
        return None

# =============================================================================
# Asynchronous Scraping using Playwright & BeautifulSoup
# =============================================================================

async def scrape_page_text():
    """
    Connect to the Chrome instance via the CDP, wait for the page to load,
    and then scrape the text only from the target div (with class "css-1jy8g2v").
    It then uses BeautifulSoup to extract the plain text.
    """
    from playwright.async_api import async_playwright

    page_text = ""
    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{REMOTE_DEBUGGING_PORT}")
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            print("No browser context found.")
        else:
            pages = context.pages
            if pages:
                page = pages[0]
                await page.wait_for_load_state("networkidle")
                # Instead of scraping the entire body, get inner HTML of the target div.
                try:
                    div_html = await page.inner_html("div.css-1jy8g2v")
                except Exception as e:
                    print("Target div not found. Falling back to entire body.")
                    div_html = await page.inner_html("body")
                soup = BeautifulSoup(div_html, "html.parser")
                page_text = soup.get_text(separator="\n", strip=True)
                print("Scraped text from target div.")
            else:
                print("No pages found in the browser context.")
        await p.stop()
    except Exception as e:
        print(f"Error during scraping: {e}")
        await p.stop()
    return page_text

# =============================================================================
# Regex Extraction Function
# =============================================================================

def extract_data(text):
    """
    Use regex to extract the required fields from the given text.
    Returns a dictionary with keys: snipers, bluechip, top10, audit, and (optionally) rug_prob.
    """
    # Extract "Snipers": expects pattern: "Snipers" then a line with ">" then the value.
    snipers_match = re.search(r'Snipers\s*\n\s*>\s*\n\s*(\S+)', text)
    snipers = snipers_match.group(1) if snipers_match else ''

    # Extract "BlueChip": expects similar pattern.
    bluechip_match = re.search(r'BlueChip\s*\n\s*>\s*\n\s*(\S+)', text)
    bluechip = bluechip_match.group(1) if bluechip_match else ''

    # Extract "Top 10": expects the value immediately following "Top 10".
    top10_match = re.search(r'Top 10\s*\n\s*(\S+)', text)
    top10 = top10_match.group(1) if top10_match else ''

    # Extract "Audit": expects a ">" line then two lines (e.g., "Safe" and "4/4").
    audit_match = re.search(r'Audit\s*\n\s*>\s*\n\s*(\S+)\s*\n\s*(\S+)', text)
    if audit_match:
        audit = f"{audit_match.group(1)} {audit_match.group(2)}"
    else:
        audit = ''

    # Optionally extract "Rug probability": the value immediately following the line.
    rug_prob_match = re.search(r'Rug probability\s*\n\s*(\S+)', text)
    rug_prob = rug_prob_match.group(1) if rug_prob_match else None

    return {
        'snipers': snipers,
        'bluechip': bluechip,
        'top10': top10,
        'audit': audit,
        'rug_prob': rug_prob
    }

# =============================================================================
# CSV Writing Function
# =============================================================================

def write_csv(data, csv_file_path):
    """
    Write (or append) a row of extracted data to the CSV file.
    If the file does not exist, write the header first.
    """
    # Define base headers
    fieldnames = ['snipers', 'bluechip', 'top10', 'audit']
    # Add rug_prob header only if data is present
    if data.get('rug_prob') is not None:
        fieldnames.append('rug_prob')
    
    write_header = not os.path.exists(csv_file_path)
    with open(csv_file_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        # Remove the rug_prob key if it's None so it doesn't appear as "None" in CSV
        if data.get('rug_prob') is None and 'rug_prob' in data:
            del data['rug_prob']
        writer.writerow(data)
    print(f"Extracted data written to {csv_file_path}")

# =============================================================================
# Main Loop
# =============================================================================

def main():
    # Set up logging (stdout now goes to console and the log file)
    setup_stdout_tee(LOG_FILE_PATH)
    
    print("=== Starting Token-Based Scraping Automation ===")
    
    while True:
        print("\n----- New Iteration -----")
        # 1. Read the token (placeholder) from the last line of the token file
        token = read_last_token(TOKEN_FILE_PATH)
        if not token:
            print("No valid token found. Waiting for 10 seconds before retrying...")
            time.sleep(10)
            continue

        # Determine the CSV file path for the current token
        CSV_FILE_PATH = os.path.join(OUTPUT_DIR, f"{token}.csv")
        if os.path.exists(CSV_FILE_PATH):
            print(f"Token {token} has already been processed. Waiting for a new token...")
            time.sleep(5)
            continue

        # 2. Construct the URL from the BASE_URL and token
        url = BASE_URL.format(placeholder=token)
        print(f"Constructed URL: {url}")

        # 3. Launch Chrome with the constructed URL
        chrome_process = launch_browser(url)
        time.sleep(5)  # Wait for Chrome to load

        # 4. (Optional) Click the pop-up close button if present
        if not wait_and_click(IMAGE_CLOSE, "pop-up close button", timeout=30):
            print("Could not perform the pyautogui action for the pop-up; continuing anyway.")

        time.sleep(10)  # Allow page to settle

        # 5. Scrape the target div's text using Playwright and BeautifulSoup
        try:
            page_text = asyncio.run(scrape_page_text())
        except Exception as e:
            print(f"Error during asynchronous scraping: {e}")
            page_text = ""

        if not page_text:
            print("No page text retrieved; skipping extraction for this iteration.")
        else:
            # 6. Extract the required fields using regex
            extracted = extract_data(page_text)
            print("Extracted Data:")
            for key, value in extracted.items():
                print(f"  {key}: {value}")
            
            # 7. Write the extracted data to the CSV file
            write_csv(extracted, CSV_FILE_PATH)

        # 8. Close the Chrome tab using the Ctrl+w shortcut via pyautogui
        terminate_browser_with_pyautogui(chrome_process)

        # Wait before checking for new tokens
        print("Iteration complete. Waiting for 5 seconds before next iteration...\n")
        time.sleep(5)

if __name__ == "__main__":
    main()
