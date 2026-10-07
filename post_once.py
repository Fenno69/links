"""One-shot version of bot.py for GitHub Actions (no extra packages needed).

Checks the blog once; if today's post hasn't been sent yet, posts its links
to the channel with @everyone and records the post id in last_posted.json.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
FORCE = os.getenv("FORCE") == "true"

FEED_URL = "https://ixlstudy.blogspot.com/feeds/posts/default?alt=json&max-results=1"
STATE_FILE = Path(__file__).with_name("last_posted.json")
PART_RE = re.compile(r"\{\s*p1:\s*'([^']*)',\s*p2:\s*'([^']*)',\s*p3:\s*'([^']*)'\s*\}")
HEADERS = {"User-Agent": "DiscordBot (daily-links, 1.0)"}


def fetch_latest_post():
    req = urllib.request.Request(FEED_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        entry = json.load(resp)["feed"]["entry"][0]
    links = ["".join(m) for m in PART_RE.findall(entry["content"]["$t"])]
    published = dt.datetime.fromisoformat(entry["published"]["$t"])
    return entry["id"]["$t"], entry["title"]["$t"], published, links


def chunk_lines(lines, header, limit=1900):
    msgs, cur = [], header
    for line in lines:
        if len(cur) + len(line) + 1 > limit:
            msgs.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    if cur:
        msgs.append(cur)
    return msgs


def send(content):
    body = json.dumps({
        "content": content,
        "allowed_mentions": {"parse": ["everyone"]},
        "flags": 4,  # suppress link previews
    }).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
        data=body, method="POST",
        headers={**HEADERS, "Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30).close()


def main():
    post_id, title, published, links = fetch_latest_post()
    last_id = json.loads(STATE_FILE.read_text())["id"] if STATE_FILE.exists() else None
    # Compare dates in the blog's own timezone so "today" matches the site.
    today = dt.datetime.now(published.tzinfo).date()
    if not FORCE:
        if post_id == last_id:
            return print("already posted")
        if published.date() != today:
            return print(f"no post for today yet (latest is {published.date()})")
    if not links:
        sys.exit(f"found post '{title}' but no links in it (page format may have changed)")

    header = f"@everyone **{title}** ({published:%B %d, %Y}) - {len(links)} links\n"
    for msg in chunk_lines(links, header):
        send(msg)
    STATE_FILE.write_text(json.dumps({"id": post_id}))
    print(f"posted {len(links)} links from '{title}'")


main()
