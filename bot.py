"""Posts the daily link list from ixlstudy.blogspot.com to a Discord channel.

Reproduces the site's "Copy All Links" button: every link in today's post,
one per line, then posts it with an @everyone ping.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
CHECK_MINUTES = int(os.getenv("CHECK_MINUTES", "15"))

FEED_URL = "https://ixlstudy.blogspot.com/feeds/posts/default?alt=json&max-results=1"
STATE_FILE = Path(__file__).with_name("last_posted.json")
PART_RE = re.compile(r"\{\s*p1:\s*'([^']*)',\s*p2:\s*'([^']*)',\s*p3:\s*'([^']*)'\s*\}")


async def fetch_latest_post():
    """Return (post_id, title, date, links) for the newest blog post."""
    async with aiohttp.ClientSession() as session:
        async with session.get(FEED_URL) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    entry = data["feed"]["entry"][0]
    html = entry["content"]["$t"]
    # Same thing the page's globalCopyAll() does: p1 + p2 + p3 for every link.
    links = ["".join(m) for m in PART_RE.findall(html)]
    published = dt.datetime.fromisoformat(entry["published"]["$t"])
    return entry["id"]["$t"], entry["title"]["$t"], published.date(), links


def chunk_lines(lines, header, limit=1900):
    """Split lines into Discord-sized messages (2000 char max)."""
    msgs, cur = [], header
    for line in lines:
        if len(cur) + len(line) + 1 > limit:
            msgs.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    if cur:
        msgs.append(cur)
    return msgs


def load_last_id():
    try:
        return json.loads(STATE_FILE.read_text())["id"]
    except (FileNotFoundError, KeyError, ValueError):
        return None


def save_last_id(post_id):
    STATE_FILE.write_text(json.dumps({"id": post_id}))


class LinksBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        check_for_new_post.start()

    async def post_links(self, channel, force=False):
        """Post today's links. Returns a status string."""
        post_id, title, date, links = await fetch_latest_post()
        if not force:
            if post_id == load_last_id():
                return "already posted"
            if date != dt.date.today():
                return f"no post for today yet (latest is {date})"
        if not links:
            return f"found post '{title}' but no links in it (page format may have changed)"

        header = f"@everyone **{title}** ({date:%B %d, %Y}) - {len(links)} links\n"
        mentions = discord.AllowedMentions(everyone=True)
        for msg in chunk_lines(links, header):
            await channel.send(msg, allowed_mentions=mentions, suppress_embeds=True)
        save_last_id(post_id)
        return f"posted {len(links)} links from '{title}'"


bot = LinksBot()


@tasks.loop(minutes=CHECK_MINUTES)
async def check_for_new_post():
    channel = bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)
    try:
        print("check:", await bot.post_links(channel))
    except Exception as e:  # keep the loop alive if the site is down
        print("check failed:", e)


@check_for_new_post.before_loop
async def before_check():
    await bot.wait_until_ready()


@bot.tree.command(name="postlinks", description="Post today's links to the links channel now")
@app_commands.default_permissions(manage_guild=True)
async def postlinks(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel = bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)
    status = await bot.post_links(channel, force=True)
    await interaction.followup.send(status, ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
