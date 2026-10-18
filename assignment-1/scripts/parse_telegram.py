"""Turn a Telegram chat export into the dataset for by the classifier.

Reads the `messages.html` file produced by Telegram Desktop's "Export chat
history" for the chat with my OpenClaw assistant, keeps only the messages I
sent, and writes them to a CSV with one row per unique message:

    id                  SHA-256 hash of the message text
    message             the raw text I sent
    has_remind_keyword  1 if the text matches the regex \\bremind\\w*, else 0
    timestamp           when the message was sent (ISO 8601)
    label               left empty to be filled in later (reminder = 1, other = 0)

Two filters are applied before writing: messages from the first few days are
dropped (mostly assistant setup), as are messages that only consist of a
filler reply such as "yes" or "lgtm", which carry no meaning on their own.

The raw export and the resulting CSV contain personal messages, so they are
kept out of the repository.

Usage: python parse_telegram.py <messages.html> <output.csv>
"""

import csv
import hashlib
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

USER_NAME = "Stiven Triana"
REMIND_PATTERN = re.compile(r"\bremind\w*", re.IGNORECASE)
TIMESTAMP_FORMAT = "%d %B %Y, %H:%M:%S"
CSV_COLUMNS = ["id", "message", "has_remind_keyword", "timestamp", "label"]
SETUP_DAYS = 2
NON_WORD_PATTERN = re.compile(r"[^\w\s]")
FILLER_PHRASES = frozenset(
    [
        "yes", "no", "y", "n", "yep", "yeah", "yup", "nope", "nah",
        "ok", "okay", "k", "kk", "sure", "go ahead", "do it", "sounds good",
        "lgtm", "thanks", "thank you", "thx", "ty", "cool", "nice", "great",
        "perfect", "done", "continue", "proceed", "correct", "right",
        "fine", "approved", "confirmed", "hey", "hi", "hello",
    ]
)


def extract_text(text_div) -> str:
    for line_break in text_div.find_all("br"):
        line_break.replace_with("\n")
    return text_div.get_text().strip()


def parse_timestamp(date_div) -> str:
    raw = date_div.get("title", "") if date_div else ""
    try:
        return datetime.strptime(raw, TIMESTAMP_FORMAT).isoformat()
    except ValueError:
        return ""


def extract_user_messages(html_path: Path) -> list[dict]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    messages = []
    current_sender = ""

    for message_div in soup.select("div.message.default"):
        from_name_div = message_div.select_one("div.from_name")
        # "joined" messages omit the sender and inherit it from the previous one
        if from_name_div:
            current_sender = from_name_div.get_text().strip()
        if current_sender != USER_NAME:
            continue

        text_div = message_div.select_one("div.body > div.text")
        if not text_div:
            continue

        text = extract_text(text_div)
        if not text:
            continue

        messages.append(
            {
                "message": text,
                "timestamp": parse_timestamp(message_div.select_one("div.date")),
            }
        )
    return messages


def drop_setup_period(messages: list[dict]) -> list[dict]:
    timestamps = [
        datetime.fromisoformat(item["timestamp"])
        for item in messages
        if item["timestamp"]
    ]
    if not timestamps:
        return messages

    cutoff = min(timestamps) + timedelta(days=SETUP_DAYS)
    return [
        item
        for item in messages
        if not item["timestamp"] or datetime.fromisoformat(item["timestamp"]) >= cutoff
    ]


def is_filler(text: str) -> bool:
    normalized = " ".join(NON_WORD_PATTERN.sub(" ", text.lower()).split())
    return normalized in FILLER_PHRASES


def drop_filler(messages: list[dict]) -> list[dict]:
    return [item for item in messages if not is_filler(item["message"])]


def build_rows(messages: list[dict]) -> list[dict]:
    rows = []
    seen_ids = set()
    for item in messages:
        message_id = hashlib.sha256(item["message"].encode("utf-8")).hexdigest()
        if message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        rows.append(
            {
                "id": message_id,
                "message": item["message"],
                "has_remind_keyword": int(bool(REMIND_PATTERN.search(item["message"]))),
                "timestamp": item["timestamp"],
                "label": "",
            }
        )
    return rows


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: parse_telegram.py <messages.html> <output.csv>")
        return 1

    all_messages = extract_user_messages(Path(sys.argv[1]))
    after_setup = drop_setup_period(all_messages)
    after_filler = drop_filler(after_setup)
    rows = build_rows(after_filler)

    with open(sys.argv[2], "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    keyword_count = sum(row["has_remind_keyword"] for row in rows)
    print(f"user messages: {len(all_messages)}")
    print(f"after dropping first {SETUP_DAYS} days: {len(after_setup)}")
    print(f"after dropping filler replies: {len(after_filler)}")
    print(f"after dedup: {len(rows)}")
    print(f"has_remind_keyword=1: {keyword_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
