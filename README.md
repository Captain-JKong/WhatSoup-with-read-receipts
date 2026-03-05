# WhatSoup 🍲

A WhatsApp Web scraper that exports your entire chat history — including **emoji reactions with reactor names**.

> This is a fork of [eddyharrington/WhatSoup](https://github.com/eddyharrington/WhatSoup), rewritten to work with the 2026 WhatsApp Web DOM and extended with reaction scraping.

## Table of Contents

1. [Overview](#overview)
2. [What's New vs the Original](#whats-new-vs-the-original)
3. [Example Output](#example-output)
4. [Prerequisites](#prerequisites)
5. [Setup](#setup)
6. [Usage](#usage)
7. [Frequently Asked Questions](#frequently-asked-questions)

---

## Overview

### Problem

WhatsApp's built-in export:
1. Caps at 40,000 messages
2. Strips the text from media messages (replaces with `<Media omitted>`)
3. Only exports to `.txt`
4. Never includes reactions

### Solution

WhatSoup loads your chat in Chrome, scrolls through the virtual DOM to capture every message, and exports to `.txt`, `.csv`, or `.html` — with full reaction details (reactor name + emoji) included.

---

## What's New vs the Original

| Feature | Original WhatSoup | This fork |
| :--- | :--- | :--- |
| WhatsApp Web compatibility | 2021 DOM | ✅ 2026 DOM |
| Loading method | Repeated scroll-to-top, waits for DOM growth | ✅ Virtual DOM scroll (top → bottom) |
| Reactions | ❌ Not captured | ✅ Reactor names + emoji (e.g. `Alice: 👍; Bob: ❤️`) |
| Export formats | txt, csv, html | ✅ txt, csv, html (all include reactions column) |
| Performance | Very slow on large chats (8+ hrs for 50k msgs) | ✅ Significantly faster — scrapes only what's in the virtual viewport |
| Deprecated | ⛔ Yes | ✅ Actively maintained |

---

## Example Output

**WhatsApp Chat with Bob Ross.csv** (excerpt)

| Date | Time | Sender | Message | Reactions |
| :--- | :--- | :--- | :--- | :--- |
| 02/14/2021 | 02:04 PM | Eddy Harrington | Hey Bob 👋 Let's move to Signal! | |
| 02/14/2021 | 02:05 PM | Bob Ross | You can do anything you want. This is your world. | Alice: 👍; Bob: ❤️ |
| 02/15/2021 | 08:30 AM | Eddy Harrington | How about we use WhatSoup 🍲 to backup our cherished chats? | |
| 02/19/2021 | 11:24 AM | Bob Ross | \<Media omitted\> My latest happy 🌲 painting for you. | |

**WhatsApp Chat with Bob Ross.txt** (excerpt)

```
02/14/2021, 02:04 PM - Eddy Harrington: Hey Bob 👋 Let's move to Signal!
02/14/2021, 02:05 PM - Bob Ross: You can do anything you want. This is your world.
02/19/2021, 11:24 AM - Bob Ross: <Media omitted> My latest happy 🌲 painting for you.
```

---

## Prerequisites

- macOS (tested; Windows/Linux may need minor path adjustments)
- Google Chrome installed
- Python 3.10+
- A WhatsApp account with an active WhatsApp Web session (already logged in to [web.whatsapp.com](https://web.whatsapp.com) in your Chrome profile)
- Basic familiarity with running Python scripts in a terminal

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Captain-JKong/WhatSoup-with-read-receipts.git
cd WhatSoup-with-read-receipts
```

### 2. Create and activate a virtual environment

```bash
# Mac / Linux
python3 -m venv env
source env/bin/activate

# Windows
python -m venv env
env\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure paths in `whatsoup.py`

Open `whatsoup.py` and update the two constants near the top of `setup_selenium()`:

```python
DRIVER_PATH    = '/usr/local/bin/chromedriver'   # path to your ChromeDriver binary
CHROME_PROFILE = '/Users/your-username/Library/Application Support/Google/Chrome/Default'
```

- **ChromeDriver**: download the version matching your Chrome from [chromedriver.chromium.org](https://chromedriver.chromium.org/downloads) and note its path.
- **Chrome Profile**: open Chrome, go to `chrome://version`, and copy the **Profile Path** value (everything up to and including the profile folder, e.g. `Default`).

> **Mac note**: on first run macOS may block ChromeDriver with an "unidentified developer" prompt. Follow [these instructions](https://stackoverflow.com/a/60362134) to grant it an exception, then re-run.

---

## Usage

```bash
python whatsoup.py
```

The script will:
1. Open Chrome with your existing WhatsApp Web session
2. Show up to 20 of your most recent chats
3. Ask you to pick a chat by number
4. Load the full chat history by scrolling WhatsApp's virtual message list
5. Scrape every message and click open every reaction popup to capture reactor names
6. Ask for an export format (`txt`, `csv`, or `html`)
7. Save the file to an `exports/` folder in the project directory

### Tips

- Make sure WhatsApp Web is already logged in before running — the script will wait up to 20 seconds for it to load.
- WhatsApp's language must be set to **English** (the script matches English HTML attributes).
- The `exports/` folder is git-ignored; your chat exports won't be committed.

---

## Frequently Asked Questions

### Does it download pictures / media?
No. Media is noted as `<Media omitted>` in the output, the same as WhatsApp's own export. If a media message also has a caption, the caption text is included.

### How does it handle reactions?
During the scroll pass, whenever a message with a reaction button is encountered for the first time, the script clicks the reaction button, reads the popup listing each reactor's name and emoji, then closes the popup and continues. The result is stored as e.g. `Alice: 👍; Bob: ❤️` in the `Reactions` column/field.

### How large of chats can I export?
The script has been tested on chats with 2,800–11,000 messages. Because it scrolls WhatsApp's virtual DOM (only ~10 messages are in the DOM at a time) rather than loading everything into memory, it is much less RAM-intensive than the original. Very large chats (50k+) are theoretically supported but untested.

### How long does it take?

Scroll speed depends on your machine and network latency to WhatsApp's servers. Rough estimates:

| # of messages | Approximate time |
| :--- | :--- |
| 500 | < 1 min |
| 2,800 | 2–5 min |
| 10,000 | 10–20 min |
| 50,000 | TBD |

Chats with many reactions will take longer (each reaction popup requires ~2s to open and parse).

### Can I contribute?
Yes, please do — PRs and issues are welcome.
