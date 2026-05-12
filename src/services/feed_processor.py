"""
src/services/feed_processor.py
Integration snippet: resolve template and favicon, build embed, send message.
Adapt to your db and discord client wrappers.
"""

import asyncio
from src.lib import db
from src.lib.favicons import fetch_favicon
from src.lib.template_renderer import build_embed_from_template

# adapt send_message/edit_message to your discord wrapper
from src.lib.discord_client import send_message, edit_message

async def process_new_item(feed: dict, item: dict):
    # feed: dict with keys id, link, feed_title, favicon_url, favicon_fetched_at, target_channel_id, ...
    # item: dict with title, link, summary, content, pubDate (datetime), author

    # load per-thread template (or per-feed)
    row = await db.fetchrow("SELECT id, message_template FROM threads WHERE feed_id = $1 LIMIT 1", feed['id'])
    template = None
    if row:
        template = row.get('message_template')
    template = template or feed.get('message_template') or "{head} **{title}**\n{summary}\n{link}"

    favicon_url = feed.get('favicon_url')
    stale = not feed.get('favicon_fetched_at') or ((asyncio.get_event_loop().time() - feed.get('favicon_fetched_at').timestamp()) > 24*3600)

    # Kick off background favicon fetch if missing or stale
    if (not favicon_url) or stale:
        async def _fetch_and_store():
            try:
                url = await fetch_favicon(feed.get('link') or feed.get('home'))
                if url:
                    await db.execute("UPDATE feeds SET favicon_url = $1, favicon_fetched_at = NOW() WHERE id = $2", url, feed['id'])
                    # Optionally edit the message later to include the favicon if we recorded message id
            except Exception:
                pass
        asyncio.create_task(_fetch_and_store())

    embed = build_embed_from_template({
        'title': item.get('title'),
        'link': item.get('link'),
        'summary': item.get('summary'),
        'content': item.get('content'),
        'pubDate': item.get('pubDate'),
        'author': item.get('author'),
        'feed_title': feed.get('feed_title'),
    }, template, favicon_url)

    channel_id = feed.get('target_channel_id')
    message = await send_message(channel_id, embed=embed)
    # If favicon later found, you can edit the message by fetch stored message.id and re-run build_embed_from_template
