import os
import csv
import re

from bs4 import BeautifulSoup, NavigableString, Tag
from time import sleep
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, ElementNotInteractableException
from prettytable import PrettyTable
from dotenv import load_dotenv
from timeit import default_timer as timer

'''
On my machine, always run with the conda environment called 'test' to ensure all dependencies are met. Use 'pip install -r requirements.txt' to install dependencies.
'''


def ask_yes_no(prompt):
    '''Prompt the user with a yes/no question, re-prompting until a valid response is given.
    Returns True for yes, False for no.'''
    while True:
        response = input(prompt).strip().lower()
        if response in {'y', 'yes'}:
            return True
        if response in {'n', 'no'}:
            return False


def main():
    # Setup selenium to use Chrome browser w/ profile options
    driver = setup_selenium()

    # Load WhatsApp
    if not whatsapp_is_loaded(driver):
        print("You've quit WhatSoup.")
        driver.quit()
        return

    # Get chats
    chats = get_chats(driver)

    # Print chat summary
    print_chats(chats)

    # Prompt user to select a chat for export, then locate and load it in WhatsApp
    finished = False
    while not finished:
        chat_is_loaded = False
        while not chat_is_loaded:
            # Select a chat and locate in WhatsApp
            chat_is_loadable = False
            while not chat_is_loadable:
                # Ask user what chat to export
                selected_chat = select_chat(chats)
                if not selected_chat:
                    print("You've quit WhatSoup.")
                    driver.quit()
                    return

                # Find the selected chat in WhatsApp
                found_selected_chat = find_selected_chat(driver, selected_chat)
                if found_selected_chat:
                    # Break and proceed to load/scrape the chat
                    chat_is_loadable = True
                else:
                    # Clear chat search safely (no hard failure if clear button is not present)
                    clear_chat_search(driver)
            # Load entire chat history
            chat_is_loaded = load_selected_chat(driver)

        # Scrape the chat history
        scraped = scrape_chat(driver)

        # Export the chat
        scrape_is_exported(selected_chat, scraped)

        # Ask user if they wish to finish and exit WhatSoup
        finished = user_is_finished()

    # Quit WhatSoup
    print("You've quit WhatSoup.")
    driver.quit()
    return


def setup_selenium():
    '''Setup Selenium to use Chrome webdriver'''

    # Load driver and chrome profile from local directories. MacOS format below, window refer to README instructions for path format.
    load_dotenv()
    DRIVER_PATH = '/usr/local/bin/chromedriver' # put your chromedriver in this location or update the path here to point to it
    CHROME_PROFILE = '/Users/your_user_name/Library/Application Support/Google/Chrome/Default' # this should be the default Chrome profile where your WhatsApp Web is logged in. Update the path here to point to it.

    # Configure selenium
    options = webdriver.ChromeOptions()
    options.add_argument(f"user-data-dir={CHROME_PROFILE}")
    driver = webdriver.Chrome(
        executable_path=DRIVER_PATH, options=options)
    # Change default script timeout from 30sec to 90sec for execute_script tasks which slow down significantly in very large chats
    driver.set_script_timeout(90)

    return driver


def whatsapp_is_loaded(driver):
    '''Attempts to load WhatsApp in the browser'''

    print("Loading WhatsApp...", end="\r")

    # Open WhatsApp
    driver.get('https://web.whatsapp.com/')

    # Check if user is already logged in
    logged_in, wait_time = False, 20
    while not logged_in:

        # Try logging in
        logged_in = user_is_logged_in(driver, wait_time)

        # Allow user to try again and extend the wait time for WhatsApp to load
        if not logged_in:
            # Display error to user
            print(
                f"Error: WhatsApp did not load within {wait_time} seconds. Make sure you are logged in and let's try again.")

            if not ask_yes_no("Proceed (y/n)? "):
                return False

    # Success
    print("Success! WhatsApp finished loading and is ready.")
    return True


def user_is_logged_in(driver, wait_time):
    '''Checks if the user is logged in to WhatsApp by looking for the pressence of the chat-pane'''

    try:
        chat_pane = WebDriverWait(driver, wait_time).until(
            expected_conditions.presence_of_element_located((By.ID, 'pane-side')))
        return True
    except TimeoutException:
        return False


def get_chats(driver):
    '''Collects visible WhatsApp left-pane chat rows (name, time, and last message preview).'''

    print("Loading your chats...", end="\r")

    # Wrap in retry logic because WhatsApp frequently updates sidebar DOM while loading.
    retry_attempts = 0
    while retry_attempts < 3:
        retry_attempts += 1

        try:
            WebDriverWait(driver, 10).until(expected_conditions.presence_of_element_located(
                (By.XPATH, "//div[@id='pane-side']//div[@role='row']")))

            rows = driver.find_elements(By.XPATH, "//div[@id='pane-side']//div[@role='row']")
            chats = []

            for row in rows:
                if len(chats) >= 20:
                    break

                name_of_chat = None
                last_chat_time = "Unknown"
                last_chat_msg = ""

                # In left-pane rows, chat name is the first meaningful span[@title].
                titled_spans = row.find_elements(By.XPATH, ".//span[@title and normalize-space(@title)!='']")
                for span in titled_spans:
                    title = (span.get_attribute('title') or '').strip()
                    if title:
                        name_of_chat = title
                        break

                # Time is in the row-side _ak8i container and rendered as small text (e.g. Yesterday, Thursday, 12:30)
                time_spans = row.find_elements(By.XPATH, ".//div[contains(@class, '_ak8i')]//span")
                for span in time_spans:
                    txt = span.text.strip()
                    if txt and len(txt) <= 24:
                        last_chat_time = txt
                        break

                # Preview message is typically another title value in the same row, different from the chat name.
                for span in titled_spans:
                    title = (span.get_attribute('title') or '').strip()
                    if title and title != name_of_chat:
                        last_chat_msg = title
                        break

                # Fallback preview from visible row text
                if not last_chat_msg:
                    row_lines = [line.strip() for line in row.text.split('\n') if line.strip()]
                    for line in row_lines:
                        if line != name_of_chat and line != last_chat_time:
                            last_chat_msg = line
                            break

                if '\u202a' in last_chat_msg or '\u202c' in last_chat_msg:
                    last_chat_msg = last_chat_msg.lstrip(u'\u202a').rstrip(u'\u202c')

                chat = {"name": name_of_chat, "time": last_chat_time, "message": last_chat_msg}
                chats.append(chat)

            print("Success! Your chats have been loaded.")
            break

        # Catch errors related to DOM changes
        except (StaleElementReferenceException, ElementNotInteractableException) as e:
            if retry_attempts == 3:
                # Make sure we grant user option to exit if DOM keeps changing while scanning chat list
                print("This is taking longer than usual...")
                if not ask_yes_no("Try loading chats again (y/n)? "):
                    print('Error! Aborting chat load by user due to frequent DOM changes.')
                    if type(e).__name__ == 'StaleElementReferenceException':
                        raise StaleElementReferenceException
                    else:
                        raise ElementNotInteractableException
                retry_attempts = 0
            else:
                pass

    return chats


def _build_chats_table(chats, limit=None):
    '''Build and return a PrettyTable of chat rows, plus the count of rows added.
    Pass limit to cap the number of rows (e.g. limit=5 for the short summary).'''
    t = PrettyTable()
    t.field_names = ["#", "Chat Name", "Last Msg Time", "Last Msg"]
    for key in t.align.keys():
        t.align[key] = "l"
    t._max_width = {"#": 3, "Chat Name": 25, "Last Msg Time": 10, "Last Msg": 40}
    count = 0
    for i, chat in enumerate(chats, start=1):
        if limit is not None and i > limit:
            break
        t.add_row([str(i), chat['name'], chat['time'], chat['message']])
        count += 1
    return t, count


def print_chats(chats, full=False):
    '''Prints a summary of the scraped chats'''

    if full:
        t, _ = _build_chats_table(chats)
        print(t.get_string(title='Your WhatsApp Chats'))
        return

    # Print a short summary (up to 5 most recent chats)
    t, row_count = _build_chats_table(chats, limit=5)
    print(f"{t.get_string(title=f'Your {row_count} Most Recent WhatsApp Chats')}\n")

    # Ask user if they want a longer summary
    if ask_yes_no("Would you like to see a complete summary of the scraped chats (y/n)? "):
        print_chats(chats, full=True)


def select_chat(chats):
    '''Prompts the user to select a chat they want to scrape/export'''

    print("\nSelect a chat export option.\n  Options:\n  chat number\t\tSelect chat for export\n  -listchats\t\tList your chats\n  -quit\t\t\tQuit the application\n")
    while True:
        # Ask user to select chat for export
        selected_chat = None
        response = input(
            "What chat would you like to scrape and export? ")

        # Check users response
        if response.strip().lower() == '-listchats':
            print_chats(chats, full=True)
        elif response.strip().lower() == '-quit':
            return None
        else:
            # Make sure user entered a number correlating to the chat
            try:
                n = int(response)
            except ValueError:
                print("Uh oh! You didn't enter a number. Try again.")
            else:
                if n in range(1, len(chats)+1):
                    chat_index = n - 1
                    selected_chat = chats[chat_index]['name']
                    
                    # Check if chat name is None - this indicates extraction failed
                    if selected_chat is None:
                        print(f"Warning: Chat name could not be extracted for chat #{n}.")
                        print(f"Using last message instead: {chats[chat_index]['message'][:50]}...")
                        # Use the message text as an alternative identifier for searching
                        # But also mark it as unreliable
                        selected_chat = chats[chat_index]['message']
                        if not selected_chat:
                            print("Error: This chat has no extractable identifier. Please try another chat.")
                            continue
                    
                    return selected_chat
                else:
                    print(
                        f"Uh oh! The only valid options are numbers 1 - {len(chats)}. Try again.")


def load_selected_chat(driver):
    '''Loads entire chat history by repeatedly scrolling up to fetch more data from WhatsApp'''
    t0 = timer()
    print("Loading messages...", end="\r")

    message_list_element = get_message_list_element(driver)
    if not message_list_element:
        print("\n[DEBUG] get_message_list_element returned None. Dumping page structure for diagnosis...")
        soup_debug = BeautifulSoup(driver.page_source, 'lxml')
        
        # Dump full page structure to file for inspection
        with open('right-panel.html', 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"[DEBUG] Full page source saved to right-panel.html ({len(driver.page_source)} bytes)")
        
        # Check for common container patterns
        main_elem = soup_debug.find('main')
        if main_elem:
            print(f"[DEBUG] <main> element exists in DOM.")
        else:
            print(f"[DEBUG] <main> element NOT found.")
        
        # Check for divs with role=main
        role_main = soup_debug.find('div', {'role': 'main'})
        if role_main:
            print(f"[DEBUG] Found <div role='main'> in DOM.")
        
        # Check for any container with message classes
        msg_containers = soup_debug.find_all('div', class_=lambda x: x and ('message' in str(x)))
        print(f"[DEBUG] Found {len(msg_containers)} divs containing 'message' in class.")
        
        # Check for #pane-main or similar IDs
        pane_main = soup_debug.find(id='pane-main')
        if pane_main:
            print(f"[DEBUG] Found element with id='pane-main'.")
        
        # List all top-level divs with id or role attributes
        top_divs = soup_debug.find_all('div', limit=25)
        print(f"[DEBUG] Top divs: {[d.get('id') or d.get('role') for d in top_divs if d.get('id') or d.get('role')]}")
        
        print("Error! Could not locate the chat message list in WhatsApp.")
        return False

    # Don't try to send_keys to a div container - use JS for scrolling instead
    # Just ensure it's focused via JS
    try:
        driver.execute_script("arguments[0].focus();", message_list_element)
    except Exception:
        pass  # If focus fails, continue anyway

    # Use the REAL scroll container (JS walk-up from messages) for all scrolling.
    # get_message_list_element() returns an outer wrapper whose scrollTop writes
    # are silently ignored by the browser — we need the element the browser
    # actually scrolls, which is the largest-scrollHeight scrollable ancestor.
    real_scroll_el = _get_msg_scroll_container(driver) or message_list_element
    try:
        current_scroll_height = driver.execute_script("return arguments[0].scrollHeight;", real_scroll_el)
        ch = driver.execute_script("return arguments[0].clientHeight;", real_scroll_el)
    except Exception as e:
        print(f"\n[DEBUG] Failed to get scrollHeight: {e}")
        return False
    print(f"[DEBUG] load_selected_chat container: scrollHeight={current_scroll_height}, clientHeight={ch}")

    previous_scroll_height = current_scroll_height

    # Load all messages by scrolling up and continually checking scroll height to verify more messages have loaded
    all_msgs_loaded = False
    retry_attempts, success_attempts = 0, 0
    while not all_msgs_loaded:
        # Scroll to top of message list (fetches more messages)
        try:
            driver.execute_script(
                "arguments[0].scrollTop = 0;", real_scroll_el)
        except Exception as e:
            print(f"\n[DEBUG] Scroll failed: {e}")
            return False

        # Wait for WhatsApp to fetch older messages from the network.
        # 0.3 s is enough when history is already pre-loaded locally.
        sleep(0.3)

        # Get scroll height of the chat pane div so we can calculate if new messages were loaded
        try:
            previous_scroll_height = current_scroll_height
            current_scroll_height = driver.execute_script(
                "return arguments[0].scrollHeight;", real_scroll_el)
        except Exception as e:
            print(f"\n[DEBUG] Failed to check scroll height: {e}")
            return False

        # Check if scroll height changed
        if current_scroll_height > previous_scroll_height:
            # New messages were loaded, reset retry counter
            retry_attempts = 0

            # Increment success attempts for user awareness
            success_attempts += 1
            print(
                f"Load new messages succeeded {success_attempts} times", end="\r")

            # Loop back and load more messages
            continue

        # Check if all messages were loaded or retry loading more
        elif current_scroll_height == previous_scroll_height:
            # All messages loaded? Check if loading indicator still exists
            # Updated for 2026 WhatsApp Web HTML structure
            try:
                loading_earlier_msgs = driver.find_element(By.XPATH,
                    "//div[contains(text(),'loading') or contains(text(),'Loading')]").get_attribute('title')
            except NoSuchElementException:
                loading_earlier_msgs = ''
                all_msgs_loaded = True
            if 'load' not in loading_earlier_msgs:
                all_msgs_loaded = True
                print(
                    f"Success! Your entire chat history has been loaded in {round(timer() - t0, 1)} seconds.")
                break

            # Retry loading more messages
            else:
                # Make sure we grant user option to exit if ~60sec of attempting to load more messages doesn't result in new messages loading
                if retry_attempts >= 30:
                    print("This is taking longer than usual...")
                    if not ask_yes_no("Try loading more messages (y/n)? "):
                        print('Error! Aborting chat load by user due to loading timeout.')
                        return False
                    retry_attempts = 0

                # Increment retry acounter and load more messages
                else:
                    retry_attempts += 1
                    continue

    return True



def find_selected_chat(driver, selected_chat):
    '''Searches and loads the initial chat. Returns True/False if the chat is found and can be loaded.

    Assumptions:
    1) The chat is searchable and exists because we scraped it earlier in get_chats
    2) The searched chat will always be the first element under the search input box
    '''

    print(f"Searching for '{selected_chat}'...", end="\r")

    # Find the chat via left-pane search input
    chat_search = driver.find_element(By.XPATH,
        '//div[@aria-label="Search input textbox"][@contenteditable="true"]')
    chat_search.click()

    clear_chat_search(driver)

    # Type the chat name into the contenteditable textbox.
    driver.execute_script("arguments[0].textContent = arguments[1];", chat_search, selected_chat)
    driver.execute_script("arguments[0].dispatchEvent(new InputEvent('input', {bubbles: true}));", chat_search)

    # Fire listeners with keyboard updates.
    chat_search.send_keys(Keys.END)
    chat_search.send_keys(Keys.SPACE)
    chat_search.send_keys(Keys.BACKSPACE)

    # Wait for search results to load in the left sidebar.
    try:
        WebDriverWait(driver, 5).until(expected_conditions.presence_of_element_located(
            (By.XPATH, "//div[@id='pane-side']//div[@role='row']")))
    except TimeoutException:
        print(
            f"Error! '{selected_chat}' produced no search results in WhatsApp.")
        return False

    rows = driver.find_elements(By.XPATH, "//div[@id='pane-side']//div[@role='row']")
    exact_row = None
    partial_row = None

    for row in rows:
        name_spans = row.find_elements(By.XPATH, ".//span[@title and normalize-space(@title)!='']")
        for span in name_spans:
            name_title = (span.get_attribute('title') or '').strip()
            if not name_title:
                continue
            if name_title == selected_chat:
                exact_row = row
                break
            if selected_chat.lower() in name_title.lower() and not partial_row:
                partial_row = row
        if exact_row:
            break

    target_row = exact_row or partial_row
    if not target_row:
        print(f"Error! '{selected_chat}' produced no search results in WhatsApp.")
        return False

    try:
        clickable = target_row.find_element(By.XPATH, ".//div[@aria-selected]")
        clickable.click()
    except NoSuchElementException:
        target_row.click()

    try:
        WebDriverWait(driver, 7).until(expected_conditions.presence_of_element_located(
            (By.XPATH, "//header//span[@title and normalize-space(@title)!='']")))
        header_name = driver.find_element(By.XPATH, "//header//span[@title and normalize-space(@title)!='']").get_attribute('title').strip()
    except (TimeoutException, NoSuchElementException):
        header_name = ""

    if header_name and (header_name == selected_chat or selected_chat.lower() in header_name.lower()):
        print(f"Success! '{selected_chat}' was found.")
        return True

    # If header selector shape changes, still continue when a row click was successful.
    print(f"Success! '{selected_chat}' search result clicked.")
    return True


def clear_chat_search(driver):
    '''Clears the left sidebar search box safely across WhatsApp DOM variants.'''

    try:
        chat_search = driver.find_element(By.XPATH,
            '//div[@aria-label="Search input textbox"][@contenteditable="true"]')
    except NoSuchElementException:
        return

    chat_search.click()

    # Fast path: keyboard clear.
    chat_search.send_keys(Keys.COMMAND, 'a')
    chat_search.send_keys(Keys.BACKSPACE)

    # Ensure underlying contenteditable value is reset and listeners fire.
    driver.execute_script(
        "arguments[0].textContent = ''; arguments[0].dispatchEvent(new InputEvent('input', {bubbles: true}));",
        chat_search
    )

    # Optional clear/close button in some variants; ignore if absent.
    clear_buttons = driver.find_elements(By.XPATH,
        "//div[@id='side']//button[.//span[@data-icon='x-alt' or @data-icon='x']] | //div[@id='side']//*[@role='button' and (contains(translate(@aria-label,'CLEARCLOSE','clearclose'),'clear') or contains(translate(@aria-label,'CLEARCLOSE','clearclose'),'close'))]")
    if clear_buttons:
        try:
            clear_buttons[0].click()
        except Exception:
            pass


def get_message_list_element(driver):
    '''Finds the right-pane message list container across WhatsApp Web DOM variants.'''

    # Messages are nested with class="focusable-list-item message-in/message-out"
    # No <main> element needed - just find scrollable container holding these
    try:
        print("[DEBUG] Waiting for any message element (focusable-list-item)...", end="\r")
        WebDriverWait(driver, 10).until(expected_conditions.presence_of_element_located(
            (By.XPATH, "//div[contains(@class, 'focusable-list-item')]")))
        print("[DEBUG] Message elements found.                              ")
    except TimeoutException:
        print("[DEBUG] ERROR: No focusable-list-item found after 10 sec.")
        return None

    # XPath candidates for the scrollable message list container (no <main> needed)
    xpath_candidates = [
        "//div[contains(@class, 'focusable-list-item')]/ancestor::div[contains(@class, 'x1n2onr6')][1]",
        "//div[contains(@class, 'message-in') or contains(@class, 'message-out')]/ancestor::div[@tabindex='-1'][1]",
        "//div[contains(@class, 'focusable-list-item')]/ancestor::div[@role='presentation'][1]",
        "//div[contains(@class, '_amjv')]/ancestor::div[contains(@class, 'x1n2onr6')][1]"
    ]

    for i, xpath in enumerate(xpath_candidates, 1):
        print(f"[DEBUG] Trying XPath {i}/4: {xpath[:60]}...", end="\r")
        elems = driver.find_elements(By.XPATH, xpath)
        if elems:
            print(f"[DEBUG] XPath {i} found {len(elems)} element(s).          ")
            for j, elem in enumerate(elems, 1):
                try:
                    if elem.is_displayed():
                        # Check if this element is actually scrollable
                        size = elem.size
                        scrollable = size.get('height', 0) > 100
                        if scrollable:
                            print(f"[DEBUG] Element {j} is displayed and scrollable. Returning it.")
                            return elem
                        else:
                            print(f"[DEBUG] Element {j} found but not tall enough (h={size.get('height')}).")
                    else:
                        print(f"[DEBUG] Element {j} found but NOT displayed.")
                except StaleElementReferenceException:
                    print(f"[DEBUG] Element {j} is stale, skipping.")
                    continue
        else:
            print(f"[DEBUG] XPath {i} returned 0 elements.                    ")

    print("[DEBUG] No viable XPath found. Trying JS fallback to find scrollable...", end="\r")

    # JS fallback: find the scrollable ancestor of message bubbles directly
    try:
        js_elem = driver.execute_script(
            """
            const bubbles = Array.from(document.querySelectorAll("div[class*='focusable-list-item']"));
            console.log('[JS] Found ' + bubbles.length + ' focusable-list-item elements');
            if (!bubbles.length) return null;

            // Find common scrollable ancestor
            const getCandidates = (el) => {
              let node = el;
              while (node && node !== document.body) {
                const style = window.getComputedStyle(node);
                const scrollable = node.scrollHeight > node.clientHeight &&
                  (style.overflowY === 'auto' || style.overflowY === 'scroll');
                if (scrollable) return node;
                node = node.parentElement;
              }
              return null;
            };

            // Get the most common scrollable ancestor among all bubbles
            const candidates = bubbles.map(getCandidates).filter(x => x);
            console.log('[JS] Found ' + candidates.length + ' scrollable candidates');
            if (candidates.length === 0) return null;

            return candidates[0];
            """
        )
        if js_elem:
            print("[DEBUG] JS fallback found a scrollable container. Using it.")
            return js_elem
        else:
            print("[DEBUG] JS fallback found no scrollable container.")
            return None
    except Exception as e:
        print(f"[DEBUG] JS fallback threw exception: {str(e)[:80]}")
        return None


def scrape_chat(driver):
    '''Turns the chat into soup and scrapes it for key export information: message sender, message date/time, message contents'''

    t_scrape_start = timer()
    print("Scraping messages...", end="\r")

    # Verify the message list container is present
    if not get_message_list_element(driver):
        raise NoSuchElementException("Unable to locate message list container in right pane.")

    # Pass 1: scroll top→bottom capturing outerHTML of every message.
    # No reaction clicks here — keeping this pass clean avoids stale-element and
    # scroll-position problems that come from opening/closing popups mid-collection.
    print("Collecting messages and reactions...", end="\r")
    t_pass1_start = timer()
    ordered_keys, html_by_key, reactions_by_key = collect_all_message_html(driver)
    print(f"[TIMING] Scroll pass (messages + reactions): {round(timer() - t_pass1_start, 1)} s")

    if not ordered_keys:
        raise NoSuchElementException("No messages found after full scroll pass.")

    # Build BS4 objects from saved HTML strings
    t_bs4_start = timer()
    chat_messages = []
    for key in ordered_keys:
        soup_msg = BeautifulSoup(html_by_key[key], 'lxml')
        msg_div = soup_msg.find(
            'div', class_=lambda x: x and ('message-in' in x or 'message-out' in x))
        if msg_div:
            chat_messages.append(msg_div)

    chat_messages_count = len(chat_messages)
    print(f"[TIMING] BS4 parse ({chat_messages_count} msgs): {round(timer() - t_bs4_start, 1)} s")
    print(f"Collected {chat_messages_count} messages, {len(reactions_by_key)} with reactions.")

    # Map reactions to 0-based message indices using the shared key
    reaction_detail_map = {
        i: reactions_by_key[key]
        for i, key in enumerate(ordered_keys)
        if key in reactions_by_key
    }

    # Get users profile name
    you = get_users_profile_name(chat_messages)

    # Loop thru all chat messages, scrape chat info into a dict, and add it to a list
    t_loop_start = timer()
    messages = []
    messages_count = 0
    last_msg_date = None
    for message in chat_messages:
        # Count messages for progress message to user and to compare expected vs actual scraped chat messages
        messages_count += 1
        print(
            f"Scraping message {messages_count} of {chat_messages_count}", end="\r")

        # Dictionary for holding chat information (sender, msg date/time, msg contents, message content types, and data-id for debugging)
        message_scraped = {
            "sender": None,
            "datetime": None,
            "message": None,
            "reactions": None,
            "has_copyable_text": False,
            "has_selectable_text": False,
            "has_emoji_text": False,
            "has_media": False,
            "has_recall": False,
            "data-id": message.get('data-id')
        }

        # Approach for scraping: search for everything we need in 'copyable-text' to start with, then 'selectable-text', and so on as we look for certain HTML patterns. As patterns are identified, update the message_scraped dict.
        # Check if message has 'copyable-text' (copyable-text tends to be a container div for messages that have text in it, storing sender/datetime within data-* attributes)
        copyable_text = message.find('div', 'copyable-text')
        if copyable_text:
            message_scraped['has_copyable_text'] = True

            # Scrape the 'copyable-text' element for the message's sender, date/time, and contents
            copyable_scrape = scrape_copyable(copyable_text)

            # Update the message object
            if copyable_scrape['datetime']:
                message_scraped['datetime'] = copyable_scrape['datetime']
                last_msg_date = message_scraped['datetime']
            else:
                # Fallback: try to get datetime from the message element itself
                message_scraped['datetime'] = find_chat_datetime_when_copyable_does_not_exist(
                    message, last_msg_date)
                if message_scraped['datetime']:
                    last_msg_date = message_scraped['datetime']

            if copyable_scrape['sender']:
                message_scraped['sender'] = copyable_scrape['sender']
            else:
                # Fallback: determine sender from message class
                if 'message-out' in (message.get('class') or []):
                    message_scraped['sender'] = you
                elif messages:
                    message_scraped['sender'] = messages[-1]['sender']

            message_scraped['message'] = copyable_scrape['message']

            # Determine the content scope: for reply messages, restrict to the actual reply
            # content (exclude the quoted/replied-to section which has 'quoted-mention' class)
            content_scope = copyable_text  # default: entire copyable div
            is_reply = copyable_text.find(class_='quoted-mention') is not None
            if is_reply:
                # Find the reply content div (the direct child that does NOT contain quoted-mention)
                for child in copyable_text.children:
                    if hasattr(child, 'find') and child.name:
                        if not child.find(class_='quoted-mention') and 'quoted-mention' not in (child.get('class') or []):
                            content_scope = child
                            break

            # Check if message has 'selectable-text' within the content scope
            # 2026 WhatsApp uses data-testid="selectable-text" instead of CSS class
            selectable_text = None
            for el in content_scope.find_all(attrs={'data-testid': 'selectable-text'}):
                if el.name in ('span', 'div') and (el.get_text(strip=True) or el.find('img')):
                    selectable_text = el
                    break

            # Check if message has emojis and overwrite the message object w/ updated chat message
            if selectable_text:
                message_scraped['has_selectable_text'] = True

                # Does it contain emojis? Emoji's are renderd as <img> elements which are child to the parent span/div container w/ selectable-text class
                if selectable_text.find('img'):
                    message_scraped['has_emoji_text'] = True

                # Get message from selectable and overwrite existing chat message
                selectable_result = scrape_selectable(
                    selectable_text, message_scraped['has_emoji_text'])
                # Only override if selectable produced non-empty content
                if selectable_result and str(selectable_result).strip():
                    message_scraped['message'] = selectable_result

        # Check if message was recalled
        if is_recall_in_message(message):
            message_scraped['has_recall'] = True

            # Update the message object
            message_scraped['datetime'] = find_chat_datetime_when_copyable_does_not_exist(
                message, last_msg_date)
            last_msg_date = message_scraped['datetime']
            message_scraped['sender'] = you
            message_scraped['message'] = "<You deleted this message>"

        # Check if the message has media
        message_scraped['has_media'] = is_media_in_message(message)
        if message_scraped['has_media']:
            # Determine if it's specifically a sticker
            is_sticker = is_sticker_message(message)

            # Check if it also has text
            if message_scraped['has_copyable_text']:
                # Update chat message w/ media omission (note that copyable has already scraped the sender + datetime)
                label = '<Sticker>' if is_sticker else '<Media omitted>'
                message_scraped['message'] = f"{label} {message_scraped['message']}"

            else:
                # Without copyable, we need to scrape the sender in a different way
                if 'message-out' in (message.get('class') or []):
                    # Message was sent by the user
                    message_scraped['sender'] = you
                elif 'message-in' in (message.get('class') or []):
                    # Message was sent from a friend of the user
                    message_scraped['sender'] = find_media_sender_when_copyable_does_not_exist(
                        message)
                    if not message_scraped['sender']:
                        # Only occurs intermittently when the senders name does not exist in the message - so we take the last message's sender
                        message_scraped['sender'] = messages[-1]['sender']
                else:
                    pass

                # Get the date/time and update the message object
                message_scraped['datetime'] = find_chat_datetime_when_copyable_does_not_exist(
                    message, last_msg_date)
                last_msg_date = message_scraped['datetime']
                message_scraped['message'] = '<Sticker>' if is_sticker else '<Media omitted>'

        # Fallback: detect message type from aria-label for unhandled messages
        # (voice messages, videos, video notes, documents, view-once, etc.)
        if message_scraped['message'] is None or (isinstance(message_scraped['message'], str) and not message_scraped['message'].strip()):
            aria_label = message.get('aria-label') or ''

            # Determine sender if not set
            if not message_scraped['sender']:
                if 'message-out' in (message.get('class') or []):
                    message_scraped['sender'] = you
                elif messages:
                    message_scraped['sender'] = messages[-1]['sender']

            # Determine datetime if not set
            if not message_scraped['datetime']:
                message_scraped['datetime'] = find_chat_datetime_when_copyable_does_not_exist(
                    message, last_msg_date)
                if message_scraped['datetime']:
                    last_msg_date = message_scraped['datetime']

            # Detect type from aria-label or HTML structure
            if message.find(lambda tag: tag.name == 'title' and tag.string and 'view-once' in tag.string.lower()):
                message_scraped['message'] = '<View once message>'
            elif 'Voice message' in aria_label:
                message_scraped['message'] = '<Voice message>'
            elif 'Video note' in aria_label:
                message_scraped['message'] = '<Video note>'
            elif re.search(r'\bVideo\b', aria_label):
                message_scraped['message'] = '<Media omitted>'
            elif 'Document name:' in aria_label:
                doc_match = re.search(r'Document name:\s*(.+?)(?:\s+\d+\s*page|$)', aria_label)
                doc_name = doc_match.group(1).strip().rstrip('.') if doc_match else 'document'
                message_scraped['message'] = f'<Document: {doc_name}>'
            elif re.search(r'\bPhoto\b|\bImage\b|\bGIF\b', aria_label):
                message_scraped['message'] = '<Media omitted>'
            elif 'Sticker' in aria_label:
                message_scraped['message'] = '<Sticker>'
            elif re.search(r'\bPoll\b', aria_label):
                message_scraped['message'] = '<Poll>'
            else:
                # Try _akbu div for any text content (e.g. "You sent a view once message...")
                akbu = message.find('div', class_='_akbu')
                if akbu:
                    text = akbu.get_text(strip=True)
                    # Remove trailing timestamp
                    time_match = re.search(r'\d{1,2}:\d{2}$', text)
                    if time_match:
                        text = text[:time_match.start()].strip()
                    message_scraped['message'] = text if text else '<Unknown message type>'
                elif aria_label:
                    message_scraped['message'] = '<Media omitted>'
                else:
                    message_scraped['message'] = '<Unknown message type>'

        # Extract emoji reactions with reactor names (from Selenium panel click pass)
        # Falls back to simple emoji-only string from static HTML if Selenium map has no entry
        if reaction_detail_map and (messages_count - 1) in reaction_detail_map:
            message_scraped['reactions'] = reaction_detail_map[messages_count - 1]
        else:
            message_scraped['reactions'] = get_reactions(message)

        # Debug: dump HTML for messages that end up with blank/empty content
        clean_msg = str(message_scraped.get('message') or '')
        if not clean_msg.strip() or clean_msg.strip() in ('', 'None'):
            debug_file = f"debug_blank_msg_{messages_count}.html"
            with open(debug_file, 'w') as df:
                df.write(str(message))
            print(f"\n[DEBUG] Blank message #{messages_count} dumped to {debug_file}")
            print(f"  sender={message_scraped['sender']}, datetime={message_scraped['datetime']}")
            print(f"  has_copyable={message_scraped['has_copyable_text']}, has_media={message_scraped['has_media']}")
            print(f"  has_recall={message_scraped['has_recall']}, data-id={message_scraped['data-id']}")

        # Add the message object to list
        if 'grouped-sticker' not in (message.get('data-id') or ''):
            messages.append(message_scraped.copy())
        else:
            # Make duplicate entry for grouped sticker to match behavior with WhatsApp export (i.e. a group sticker == 2 lines in the txt export both with <Media omitted> messages)
            messages.append(message_scraped.copy())
            messages.append(message_scraped.copy())

            # Finally, update expectd msg count
            chat_messages_count += 1

        # Loop to the next chat message
        continue

    # Scrape summary
    print(f"[TIMING] Per-message scrape loop: {round(timer() - t_loop_start, 1)} s")
    if len(messages) == chat_messages_count:
        print(f"Success! All {len(messages)} messages have been scraped.")
    else:
        print(
            f"Warning! {len(messages)} messages scraped but {chat_messages_count} expected.")

    # Ensure all messages have valid datetime, sender, and message before building dict
    for m in messages:
        if m['datetime'] is None:
            m['datetime'] = last_msg_date if last_msg_date else datetime.now()
        if m['sender'] is None:
            m['sender'] = you if you else 'Unknown'
        if m['message'] is None:
            m['message'] = ''

    # Create a dict with chat date as key and empty list as value which will store all msgs for that date
    messages_dict = {msg_list['datetime'].strftime(
        "%m/%d/%Y"): [] for msg_list in messages}

    # Update the dict by inserting message content as values
    t_dict_start = timer()
    for m in messages:
        clean_msg = clean_message_html(m['message'])
        entry = {'time': m['datetime'].strftime("%I:%M %p"), 'sender': m['sender'], 'message': clean_msg}
        if m.get('reactions'):
            entry['reactions'] = m['reactions']
        else:
            entry['reactions'] = ''
        messages_dict[m['datetime'].strftime("%m/%d/%Y")].append(entry)

    print(f"[TIMING] Dict build + HTML clean: {round(timer() - t_dict_start, 1)} s")
    print(f"[TIMING] scrape_chat total: {round(timer() - t_scrape_start, 1)} s")
    return messages_dict


def clean_message_html(message):
    '''Converts a BeautifulSoup Tag or raw HTML string into clean plain text.

    - Replaces <img> emoji tags with their alt text
    - Replaces <strong> with *bold* (WhatsApp convention)
    - Converts <li> items to bullet lines using data-pre-plain-text prefix
    - Strips all remaining HTML tags
    - Collapses excessive whitespace
    '''
    if message is None:
        return ''

    # If it's already a plain string with no HTML, return as-is
    if isinstance(message, str):
        if '<' not in message:
            return message.strip()
        # Parse the HTML string
        soup = BeautifulSoup(message, 'lxml')
    elif isinstance(message, Tag):
        soup = message
    elif isinstance(message, NavigableString):
        return str(message).strip()
    else:
        return str(message).strip()

    # Replace <img> emoji tags with their alt text
    for img in soup.find_all('img'):
        alt = img.get('alt', '') or img.get('data-plain-text', '')
        img.replace_with(alt)

    # Replace <strong> / <b> with *text* (WhatsApp bold)
    for strong in soup.find_all(['strong', 'b']):
        strong.replace_with(f'*{strong.get_text()}*')

    # Replace <em> / <i> with _text_ (WhatsApp italic)
    for em in soup.find_all(['em', 'i']):
        em.replace_with(f'_{em.get_text()}_')

    # Convert list items to prefixed lines
    for li in soup.find_all('li'):
        # Get bullet prefix from inner span's data-pre-plain-text, or default to '- '
        prefix = ''
        inner_span = li.find('span', attrs={'data-pre-plain-text': True})
        if inner_span:
            prefix = inner_span.get('data-pre-plain-text', '- ')
        else:
            prefix = '- '
        li_text = li.get_text().strip()
        li.replace_with(f'\n{prefix}{li_text}')

    # Remove <ul>/<ol> wrappers (content already extracted from <li>)
    for ul in soup.find_all(['ul', 'ol']):
        ul.replace_with(ul.get_text())

    # Replace <a> links with just the href URL or link text
    for a in soup.find_all('a'):
        href = a.get('href', '')
        link_text = a.get_text().strip()
        # Use href if it looks like a URL, otherwise use the link text
        a.replace_with(href if href.startswith('http') else link_text)

    # Get remaining text
    text = soup.get_text()

    # Clean up whitespace: collapse multiple spaces (but preserve newlines)
    text = re.sub(r'[^\S\n]+', ' ', text)
    # Collapse multiple consecutive newlines to max 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def get_users_profile_name(chat_messages):
    '''Returns the user's profile name so we can determine who 'You' is in the conversation.

    WhatsApp's default 'export' fucntionality renders the users profile name and never 'You'.
    '''

    you = None
    for chat in chat_messages:
        if 'message-out' in str(chat.get('class', '')):
            chat_exists = chat.find('div', 'copyable-text')
            if chat_exists:
                try:
                    plain_text = chat_exists.get('data-pre-plain-text', '')
                    # Format: [HH:MM, MM/DD/YYYY] Sender Name: Message
                    if plain_text and '] ' in plain_text:
                        # Extract sender name between ] and :
                        parts = plain_text.split('] ', 1)
                        if len(parts) > 1:
                            sender_info = parts[1]
                            # Get the name before the colon
                            if ':' in sender_info:
                                you = sender_info.split(':')[0].strip()
                                break
                            else:
                                # If no colon, take the whole thing
                                you = sender_info.strip()
                                break
                except (IndexError, AttributeError):
                    continue
    return you


def _extract_copyable_content(el, fallback=''):
    '''Find the best content element from a copyable-text div.
    Checks for a span, then a non-empty div, then img alt-text, then returns fallback.'''
    content = el.find('span', 'copyable-text')
    if not content:
        for div in el.find_all('div', 'copyable-text'):
            if div.get_text(strip=True):
                content = div
                break
    if content:
        return content
    imgs = el.find_all('img', alt=True)
    img_text = ''.join(img.get('alt', '') for img in imgs)
    return img_text if img_text else fallback


def scrape_copyable(copyable_text):
    '''Returns a dict with values for sender, date/time, and contents of the WhatsApp message'''

    copyable_scrape = {'sender': None, 'datetime': None, 'message': None}

    # Get the elements attributes that hold the sender and date/time values
    pre_plain_text = copyable_text.get('data-pre-plain-text')

    # If this element doesn't have data-pre-plain-text, search upward or within for one that does
    if not pre_plain_text:
        # Try finding a parent or child with the attribute
        parent_with_attr = copyable_text.find_parent(attrs={'data-pre-plain-text': True})
        if parent_with_attr:
            pre_plain_text = parent_with_attr.get('data-pre-plain-text')
        else:
            child_with_attr = copyable_text.find(attrs={'data-pre-plain-text': True})
            if child_with_attr:
                pre_plain_text = child_with_attr.get('data-pre-plain-text')

    if not pre_plain_text:
        # Cannot extract sender/datetime — return None values so caller can handle
        copyable_scrape['message'] = _extract_copyable_content(
            copyable_text, fallback=copyable_text.get_text(strip=True))
        return copyable_scrape

    copyable_attrs = pre_plain_text.strip()[1:-1].split('] ')

    # Get the sender, date/time, and msg contents
    copyable_scrape['sender'] = copyable_attrs[1]
    copyable_scrape['datetime'] = parse_datetime(
        f"{copyable_attrs[0].split(', ')[1]} {copyable_attrs[0].split(', ')[0]}")

    # Get the text-only portion of the message contents
    # For reply messages, we need to exclude the quoted/replied-to content
    is_reply = copyable_text.find(class_='quoted-mention') is not None
    if is_reply:
        # Find the reply content div (the direct child that does NOT contain quoted-mention)
        reply_scope = None
        for child in copyable_text.children:
            if hasattr(child, 'find') and child.name:
                if not child.find(class_='quoted-mention') and 'quoted-mention' not in (child.get('class') or []):
                    reply_scope = child
                    break
        if reply_scope:
            content = reply_scope.find('span', 'copyable-text')
            if content:
                copyable_scrape['message'] = content
            else:
                copyable_scrape['message'] = reply_scope.get_text(strip=True)
        else:
            copyable_scrape['message'] = ''
    else:
        copyable_scrape['message'] = _extract_copyable_content(copyable_text, fallback='')

    return copyable_scrape


def scrape_selectable(selectable_text, has_emoji=False):
    '''Returns message contents of a chat by checking for and handling emojis'''

    # Does it contain emojis?
    if has_emoji:
        # Construct the message manually because emoji content is broken up into many span/img elements that we need to loop through
        # Loop over every child span of selectable-text, as these wrap the text and emojis/imgs
        message = ''
        for span in selectable_text.find_all('span'):

            # Loop over every child element of the span to construct the message
            for element in span.contents:
                # Check what kind of element it is
                if element.name is None:
                    # Text, ignoring empty strings
                    if element == ' ':
                        continue
                    else:
                        message += str(element)
                elif element.name == 'img':
                    # Emoji
                    message += element.get('alt')
                else:
                    # Skip other elements (note: have not found any occurrences of this happening...yet)
                    continue

        return message
    else:
        # Return the text only
        return selectable_text.text


def is_recall_in_message(message):
    '''Returns True if message contains recall pattern (a span will contain 'recalled' in data-*), if not returns False.'''
    for span in message.find_all('span'):
        if span.get('data-testid') == 'recalled':
            return True
    return False


# JavaScript that finds the true scrollable message-list container by walking up from the
# first visible message and returning the ancestor with the LARGEST scrollHeight.  This is
# identical to what the browser walks up to and avoids the XPath-based helper which can
# return an outer wrapper that doesn't actually scroll the message list.
_GET_MSG_SCROLL_CONTAINER_JS = """
    var msgs = document.querySelectorAll('div.message-in, div.message-out');
    if (!msgs.length) return null;
    var best = null, bestH = 0;
    var el = msgs[0].parentElement;
    while (el && el !== document.body) {
        if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
            if (el.scrollHeight > bestH) { bestH = el.scrollHeight; best = el; }
        }
        el = el.parentElement;
    }
    return best;
"""


def _get_msg_scroll_container(driver):
    '''Return the DOM element that actually scrolls the message list.
    Uses the largest-scrollHeight scrollable ancestor of the first visible message.
    This is guaranteed to be the right element regardless of WhatsApp's class names.'''
    return driver.execute_script(_GET_MSG_SCROLL_CONTAINER_JS)


def _scroll_step(driver, message_list_el, step_px=200):
    '''Scroll the message list down by step_px pixels and wait for the virtual DOM to
    render the new batch of messages.  Returns the scrollTop after the move.'''
    driver.execute_script(
        "arguments[0].scrollTop += arguments[1];",
        message_list_el, step_px)
    sleep(0.1)
    return driver.execute_script("return arguments[0].scrollTop;", message_list_el)


def collect_all_message_html(driver):
    '''Scroll the message list from top to bottom in a single pass, capturing:
      - outerHTML of every message-in / message-out element (for BS4 parsing)
      - reactor names for every reaction button (by clicking the live popup)

    Reactions are read inline, immediately when we first encounter each message,
    so we never need a second scroll pass.  After each popup is opened the scroll
    position is saved and restored so the outer loop is not disturbed.

    Returns (ordered_keys, html_by_key, reactions_by_key):
      ordered_keys    -- list of string keys in chronological order
      html_by_key     -- dict {key -> outerHTML string}
      reactions_by_key-- dict {key -> "Name: emoji; ..." string}
    '''
    message_list_el = _get_msg_scroll_container(driver)
    if not message_list_el:
        message_list_el = get_message_list_element(driver)
    if not message_list_el:
        return [], {}, {}

    client_height = driver.execute_script("return arguments[0].clientHeight;", message_list_el)
    scroll_height = driver.execute_script("return arguments[0].scrollHeight;", message_list_el)
    step_px = max(80, int(client_height * 1.5))
    print(f"[DEBUG] Scroll container: scrollHeight={scroll_height}, clientHeight={client_height}, step_px={step_px}")

    driver.execute_script("arguments[0].scrollTop = 0;", message_list_el)
    sleep(0.3)

    ordered_keys    = []
    html_by_key     = {}
    reactions_by_key = {}
    already_reacted  = set()   # keys whose reaction popup we've already read
    prev_scroll_top  = -1
    stuck_count = 0
    MAX_STUCK = 4
    chunk = 0

    while True:
        chunk += 1

        try:
            msg_els = driver.find_elements(
                By.CSS_SELECTOR, 'div.message-in, div.message-out')
        except Exception:
            break

        new_this_chunk = 0
        for msg_el in msg_els:
            try:
                data_id = driver.execute_script(
                    "var a = arguments[0].closest('[data-id]');"
                    "return a ? a.getAttribute('data-id') : null;",
                    msg_el)
                if data_id:
                    key = f'id:{data_id}'
                else:
                    inner_text = driver.execute_script(
                        "return arguments[0].innerText;", msg_el) or ''
                    key = f'text:{hash(inner_text[:300])}'

                is_new = key not in html_by_key
                if is_new:
                    outer_html = msg_el.get_attribute('outerHTML') or ''
                    if outer_html:
                        ordered_keys.append(key)
                        html_by_key[key] = outer_html
                        new_this_chunk += 1

                # Read reactions for this message if not done yet
                if key not in already_reacted:
                    try:
                        react_btns = msg_el.find_elements(
                            By.CSS_SELECTOR,
                            'button[aria-haspopup="true"][aria-label*="reaction"], '
                            'button[aria-haspopup="true"][aria-label*="Reaction"]')
                        if react_btns:
                            scroll_before = driver.execute_script(
                                "return arguments[0].scrollTop;", message_list_el)
                            driver.execute_script("arguments[0].click();", react_btns[0])
                            try:
                                WebDriverWait(driver, 2).until(
                                    expected_conditions.presence_of_element_located((
                                        By.CSS_SELECTOR,
                                        'div[role="listitem"][aria-label*="reacted with"]'
                                    ))
                                )
                                popup_soup = BeautifulSoup(driver.page_source, 'lxml')
                                listitems = popup_soup.find_all(
                                    'div',
                                    attrs={'role': 'listitem',
                                           'aria-label': lambda x: x and 'reacted with' in x})
                                reactor_parts = []
                                for item in listitems:
                                    aria = item.get('aria-label', '')
                                    if ' reacted with ' in aria:
                                        name, emoji = aria.split(' reacted with ', 1)
                                        reactor_parts.append(f"{name.strip()}: {emoji.strip()}")
                                if reactor_parts:
                                    reactions_by_key[key] = '; '.join(reactor_parts)
                            except TimeoutException:
                                pass
                            # Restore scroll and close popup regardless of outcome
                            driver.execute_script(
                                "arguments[0].scrollTop = arguments[1];",
                                message_list_el, scroll_before)
                            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                            sleep(0.15)
                    except StaleElementReferenceException:
                        pass
                    except Exception:
                        try:
                            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                        except Exception:
                            pass
                    finally:
                        already_reacted.add(key)

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        print(f"Pass 1 – chunk {chunk}: +{new_this_chunk} new  |  {len(ordered_keys)} total  |  {len(reactions_by_key)} reactions       ", end="\r")

        new_scroll_top = _scroll_step(driver, message_list_el, step_px=step_px)

        if new_scroll_top == prev_scroll_top:
            stuck_count += 1
            if stuck_count >= MAX_STUCK:
                break
        else:
            stuck_count = 0
            prev_scroll_top = new_scroll_top

    return ordered_keys, html_by_key, reactions_by_key


def get_reactions(message):
    '''Returns a string of emoji reactions on a message, or empty string if none.

    Reactions appear as <button> elements with aria-label containing "reaction".
    Format examples:
      - "reaction 💪. View reactions"
      - "Reactions 😂 2 in total. View reactions"
      - "Reactions 💪, ❤ 3 in total. View reactions"

    Returns a string like "💪" or "😂 x2" or "💪, ❤️ x3"
    '''
    reaction_buttons = message.find_all(
        'button', attrs={'aria-label': lambda x: x and 'reaction' in x.lower()})

    if not reaction_buttons:
        return ''

    reactions = []
    for btn in reaction_buttons:
        # Extract emoji(s) from img alt text
        emojis = []
        for img in btn.find_all('img'):
            alt = img.get('alt', '')
            if alt:
                emojis.append(alt)

        # Extract count from button text (only present when count > 1)
        count_text = btn.get_text(strip=True)
        count = None
        if count_text:
            # Count text is just the number, e.g. "2" or "3"
            try:
                count = int(count_text)
            except ValueError:
                pass

        if emojis:
            emoji_str = ', '.join(emojis)
            if count and count > 1:
                reactions.append(f'{emoji_str} x{count}')
            else:
                reactions.append(emoji_str)

    return '; '.join(reactions) if reactions else ''


def find_chat_datetime_when_copyable_does_not_exist(message, last_msg_date):
    '''Returns a message's date/time when there's no 'copyable-text' attribute within the message e.g. deleted messages, media w/ no text, etc.'''

    spans = message.find_all('span')
    # Check if spans exist
    if spans:
        for span in spans:
            # Check spans w/ text if they are dates/times
            if span.text:
                try:
                    parse_datetime(span.text, time_only=True)
                except ValueError:
                    # Span text is not a date/time value
                    continue
                else:
                    # Get the hour/minute time from the media message
                    message_time = span.text

                    # Get a sibling div holding the latest chat date, otherwise if that doesn't exist then grab the last msg date
                    try:
                        # Check if row from message list is a date and not a chat, grabs the first available prior date (this fires for all but the first date of chat history messaging)
                        sibling_el = message.find_previous_sibling(
                            "div", attrs={'data-id': False})
                        sibling_date = sibling_el.text if sibling_el else None
                        if not sibling_date:
                            # Use the previous messages date if it exists
                            if last_msg_date:
                                sibling_date = last_msg_date.strftime(
                                    '%m/%d/%Y')
                            else:
                                # Otherwise use the next available subsequent date (note this fires only on the first message w/ rare conditions when copyable-text doesn't exist; could assign the wrong date if for example the next available date is 1+ day in advance of the current message)
                                next_sibling_el = message.find_next_sibling(
                                    "div", attrs={'data-id': False})
                                sibling_date = next_sibling_el.text if next_sibling_el else None

                        # If we still have no date, raise to fall through to the except handler
                        if not sibling_date:
                            raise ValueError("No sibling date found")

                        # Try converting to a date/time object
                        media_message_datetime = parse_datetime(
                            f"{sibling_date} {message_time}")

                        # Build date/time object
                        message_datetime = parse_datetime(
                            f"{media_message_datetime.strftime('%m/%d/%Y')} {media_message_datetime.strftime('%I:%M %p')}")

                        return message_datetime

                    # Otherwise last message's date/time (note this could assign the wrong date if for example the last message was 1+ days ago)
                    except (ValueError, AttributeError):
                        if last_msg_date:
                            message_datetime = parse_datetime(
                                f"{last_msg_date.strftime('%m/%d/%Y')} {message_time}")
                            return message_datetime
                        else:
                            # No date information available at all
                            return None

    else:
        return None


def parse_datetime(text, time_only=False):
    '''Try parsing and returning datetimes in a North American standard, otherwise raise a ValueError'''
    # TODO lazy approach to handling variances of North America date/time values MM/DD/YYYY AM/PM or YYYY-MM-DD A.M./P.M.

    # Normalize the text
    text = text.upper().replace("A.M.", "AM").replace("P.M.", "PM")

    # Try parsing when text is some datetime value e.g. 2/15/2021 2:35 P.M. or 2/26/2026 19:00
    if not time_only:
        # Try 12-hour formats first (with AM/PM)
        for fmt in ('%m/%d/%Y %I:%M %p', '%Y-%m-%d %I:%M %p'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        
        # Try 24-hour formats (no AM/PM)
        for fmt in ('%m/%d/%Y %H:%M', '%Y-%m-%d %H:%M'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        
        raise ValueError(
            f"{text} does not match a valid datetime format. Supported formats: MM/DD/YYYY HH:MM (24h), MM/DD/YYYY H:MM AM/PM (12h), etc.")

    # Try parsing when text is some time value e.g. 2:35 PM or 19:00
    else:
        # Try 12-hour format first
        try:
            return datetime.strptime(text, '%I:%M %p')
        except ValueError:
            pass
        
        # Try 24-hour format
        try:
            return datetime.strptime(text, '%H:%M')
        except ValueError:
            pass
        
        raise ValueError(
            f"{text} does not match expected time format. Supported formats: 'H:MM AM/PM' (12-hour) or 'HH:MM' (24-hour).")



def is_media_in_message(message):
    '''Returns True if media is discovered within the message by checking the soup for known media flags. If not, it returns False.'''

    # First check for data-testid attributes containing 'media' or 'download' (this covers gifs, videos, downloadable content)
    possible_media_spans = message.find_all(attrs={'data-testid': True})
    for span in possible_media_spans:
        # Media types are stored in 'data-testid' attribute
        media_attr = span.get('data-testid')

        if 'media' in media_attr or 'download' in media_attr:
            return True
        else:
            continue

    # Check if the media is a shared contact e.g. vCard/VCF, or a sticker
    if message.get('class'):
        # Check for shared contact
        copyable = message.find('div', 'copyable-text')
        if copyable:
            # Get all buttons
            buttons = copyable.find_all('div', {'role': 'button'})
            if buttons:
                # Look for contact card button pattern (2 divs w/ titles of 'Message X' and 'Add to a group')
                for button in buttons:
                    # Only check buttons with Title attribute
                    if button.get('title'):
                        # Check if 'Message' is in the title (full title would be for example 'Message Bob Ross')
                        if 'Message' in button.get('title'):
                            # Next sibling should always be the 'Add to a group' button
                            if button.nextSibling:
                                if button.nextSibling.get('title') == 'Add to a group':
                                    return True

        # Check for group sticker (2 side-by-side stickers)
        data_id = message.get('data-id') or ''
        if 'grouped-sticker' in data_id:
            return True

        # Check for individual sticker
        images = message.find_all('img')
        if images:
            for image in images:
                if 'blob' in (image.get('src') or ''):
                    return True

    return False


def is_sticker_message(message):
    '''Returns True if the message is a sticker (individual or grouped).'''
    data_id = message.get('data-id') or ''

    # Grouped sticker
    if 'grouped-sticker' in data_id:
        return True

    # Individual sticker: has blob image but no copyable-text (text messages)
    # and no other media indicators like download buttons
    has_copyable = message.find('div', 'copyable-text') is not None
    if has_copyable:
        return False

    # Check for blob image (sticker rendered as blob)
    images = message.find_all('img')
    has_blob = any('blob' in (img.get('src') or '') for img in images)

    if has_blob:
        # Make sure it's not a regular image/video with download button
        has_download = any(
            'download' in (el.get('data-testid') or '')
            for el in message.find_all(attrs={'data-testid': True})
        )
        if not has_download:
            return True

    # Check aria-label for sticker indication
    aria = message.get('aria-label') or ''
    if 'sticker' in aria.lower():
        return True

    return False


def find_media_sender_when_copyable_does_not_exist(message):
    '''Returns a sender's name when there's no 'copyable-text' attribute within the message'''

    # Check to see if senders name is stored in a span's aria-label attribute (note: this seems to be where it's stored if the persons name is just text / no emoji)
    spans = message.find_all('span')
    has_emoji = False
    for span in spans:
        if span.get('aria-label'):
            # Last char in aria-label is always colon after the senders name
            if span.get('aria-label') != 'Voice message':
                return span.get('aria-label')[:-1]
        elif span.find('img'):
            # Emoji is in name and needs to be handled differently
            has_emoji = True
            break
        else:
            continue

    # Manually construct the senders name if it has an emoji by building a string from span.text and img/emoji tags
    if has_emoji:
        # Try legacy selector first (div with 'color-#' class)
        color_divs = message.select("div[class*='color']")
        if color_divs:
            emoji_name_elements = color_divs[0].next

            # Loop over every child element of the span to construct the senders name
            name = ''
            for element in emoji_name_elements.contents:
                # Check what kind of element it is
                if element.name is None:
                    # Text, ignoring empty strings
                    if element == ' ':
                        continue
                    else:
                        name += str(element)
                elif element.name == 'img':
                    # Emoji
                    name += element.get('alt', '')
                else:
                    # Skip other elements
                    continue

            return name

        # Fallback: try to extract sender from the message's aria-label (format: "SenderName: message text")
        aria_label = message.get('aria-label') or ''
        if ':' in aria_label:
            return aria_label.split(':')[0].strip()

        # Fallback: look for a span with data-pre-plain-text containing the sender name
        pre_plain = message.find(attrs={'data-pre-plain-text': True})
        if pre_plain:
            # Format: "[HH:MM, M/DD/YYYY] Sender: "
            pre_text = pre_plain.get('data-pre-plain-text', '')
            if '] ' in pre_text and ':' in pre_text:
                sender_part = pre_text.split('] ', 1)[1]
                return sender_part.rstrip(': ').strip()

        # Could not determine sender with emoji name
        return None

    # There is no sender name in the message, an issue that occurrs very infrequently (e.g. 6000+ msg chat occurred 3 times) - pattern for this seems to be 1) sender name has no emoji, 2) msg has media, 3) msg does not have text, 4) msg is a follow-up / consecutive message (doesn't have tail-in icon in message span/svg)
    else:
        # TODO: Study this pattern more and fix later if possible. Solution for now is to return None and then we take the last message's sender from our data structure.
        return None


def scrape_is_exported(selected_chat, scraped):
    '''Returns True/False if an export file type is selected and succesfully exported'''

    print("\nSelect an export format.\n  Options:\n  txt\t\tExport to .txt file type\n  csv\t\tExport to .csv file type\n  html\t\tExport to .html file type\n  -abort\tAbort the export\n")
    is_exported = False
    while not is_exported:
        # Ask user to select export type
        response = input(
            "What format do you want to export to? ")

        # Check users response
        if response.strip().lower() == 'txt':
            if export_txt(selected_chat, scraped):
                is_exported = True
        elif response.strip().lower() == 'csv':
            if export_csv(selected_chat, scraped):
                is_exported = True
        elif response.strip().lower() == 'html':
            if export_html(selected_chat, scraped):
                is_exported = True
        elif response.strip().lower() == '-abort':
            print(f"You've aborted the export for '{selected_chat}'.")
            return False
        else:
            print(
                f"Uh oh! '{response.strip().lower()}' is not a valid option. Try again.")

    return True


def _make_export_path(selected_chat, ext):
    '''Create the exports directory if needed and return the full output file path.'''
    export_dir_setup()
    now = datetime.now().strftime('%Y-%m-%d %H.%M.%S.%p')
    return f"exports/WhatsApp Chat with {selected_chat} - {now}.{ext}"


def export_txt(selected_chat, scraped):
    '''Returns True if the scraped data for a selected export is written to local .txt file without any exceptions thrown'''

    filepath = _make_export_path(selected_chat, 'txt')
    print(f"Exporting to local .txt file...", end="\r")
    try:
        with open(filepath, "wb") as text_file:
            for date_write, messages_write in scraped.items():
                for message_write in messages_write:
                    line = f"{date_write}, {message_write['time']} - {message_write['sender']}: {message_write['message']}\n"
                    text_file.write(line.encode())
        print(f"Success! '{os.path.basename(filepath)}' exported.")
        return True
    except Exception as error:
        print(f"Error during txt export! Error info: {error}")
        return False


def export_csv(selected_chat, scraped):
    '''Returns True if the scraped data for a selected export is written to local .csv file without any exceptions thrown'''

    data = []
    for date, messages in scraped.items():
        for message in messages:
            data.append([date, message['time'], message['sender'],
                         message['message'], message.get('reactions', '')])

    filepath = _make_export_path(selected_chat, 'csv')
    print(f"Exporting to local .csv file...", end="\r")
    try:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file, delimiter=",")
            writer.writerow(['Date', 'Time', 'Sender', 'Message', 'Reactions'])
            writer.writerows(data)
        print(f"Success! '{os.path.basename(filepath)}' exported.")
        return True
    except Exception as error:
        print(f"Error during csv export! Error info: {error}")
        return False


def export_html(selected_chat, scraped):
    '''Returns True if the scraped data for a selected export is written to local .html file without any exceptions thrown'''

    data = []
    for date, messages in scraped.items():
        for message in messages:
            data.append([date, message['time'],
                         message['sender'], message['message'],
                         message.get('reactions', '')])

    t = PrettyTable()
    t.field_names = ['Date', 'Time', 'Sender', 'Message', 'Reactions']
    for message in data:
        t.add_row(message)
    html = t.get_html_string()

    filepath = _make_export_path(selected_chat, 'html')
    print(f"Exporting to local .html file...", end="\r")
    try:
        with open(filepath, "wb") as html_file:
            html_file.write(html.encode())
        print(f"Success! '{os.path.basename(filepath)}' exported.")
        return True
    except Exception as error:
        print(f"Error during html export! Error info: {error}")
        return False


def export_dir_setup():
    '''Creates a local 'exports' directory if it does not already exist'''

    if not os.path.isdir('exports'):
        os.mkdir('exports')
        print(
            f"'exports' directory created: {os.path.dirname(os.path.abspath(__file__))}")


def user_is_finished():
    '''Returns True/False is the user wants to finish and exit WhatSoup'''
    return not ask_yes_no("Proceed with exporting another chat (y/n)? ")


if __name__ == "__main__":
    main()
