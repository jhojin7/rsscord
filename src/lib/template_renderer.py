"""
src/lib/template_renderer.py
Simple, safe template replacement for feed messages.

Placeholders: {head}, {title}, {link}, {summary}, {content}, {pubDate}, {author}, {feed_title}
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional

PLACEHOLDER_RE = re.compile(r'\{([a-zA-Z0-9_]+)\}')


def sanitize_mentions(text: str) -> str:
    if not text:
        return text
    # avoid mass pings
    return text.replace('@everyone', '[everyone]').replace('@here', '[here]')


def safe_replace(template: str, data: Dict[str, Any]) -> str:
    if not template:
        return ''
    def repl(match):
        key = match.group(1)
        v = data.get(key)
        if v is None:
            return ''
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)
    return PLACEHOLDER_RE.sub(repl, template)


def build_embed_from_template(item: Dict[str, Any], template: str, favicon_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns an embed-like dict matching typical discord.py embed structure.
    Adjust to your message send helper.
    """
    data = dict(item)
    # normalize possible keys
    feed_title = item.get('feed_title') or item.get('feedTitle') or item.get('feed')
    data.setdefault('head', feed_title or item.get('author') or '')
    rendered = safe_replace(template, data)
    rendered = sanitize_mentions(rendered)

    embed = {
        'title': item.get('title'),
        'url': item.get('link'),
        'description': rendered if rendered else None,
        'timestamp': item.get('pubDate').isoformat() if isinstance(item.get('pubDate'), datetime) else None,
        'author': {
            'name': feed_title or item.get('author') or '',
            'icon_url': favicon_url
        } if (feed_title or item.get('author')) else None,
        'thumbnail': {'url': favicon_url} if favicon_url else None,
    }
    # remove None values for cleanliness
    return {k: v for k, v in embed.items() if v is not None}
