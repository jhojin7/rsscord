"""
src/lib/favicons.py
Utilities to fetch and cache favicons for domains.
Requires: aiohttp and beautifulsoup4.
"""

import asyncio
from yarl import URL
import aiohttp
from bs4 import BeautifulSoup
from typing import Optional

DEFAULT_TIMEOUT = 7

async def _is_image_response(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.head(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True) as resp:
            ct = resp.headers.get('Content-Type', '')
            if ct.startswith('image/'):
                return True
        # fallback to GET when HEAD doesn't return content-type
        async with session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True) as resp:
            ct = resp.headers.get('Content-Type', '')
            return ct.startswith('image/')
    except Exception:
        return False

async def _try_basic(session: aiohttp.ClientSession, domain_url: str) -> Optional[str]:
    try:
        u = URL(domain_url)
        root = f"{u.scheme}://{u.host}/favicon.ico"
        if await _is_image_response(session, root):
            return root
        dd = f"https://icons.duckduckgo.com/ip3/{u.host}.ico"
        if await _is_image_response(session, dd):
            return dd
        google = f"https://www.google.com/s2/favicons?sz=64&domain_url={domain_url}"
        if await _is_image_response(session, google):
            return google
    except Exception:
        pass
    return None

async def _parse_homepage(session: aiohttp.ClientSession, domain_url: str) -> Optional[str]:
    try:
        u = URL(domain_url)
        home = f"{u.scheme}://{u.host}/"
        async with session.get(home, timeout=DEFAULT_TIMEOUT, allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            rels = ['icon', 'shortcut icon', 'apple-touch-icon', 'apple-touch-icon-precomposed']
            for rel in rels:
                tag = soup.find('link', rel=rel)
                if tag and tag.get('href'):
                    try:
                        href = URL(tag['href']).join(URL(str(resp.url))).human_repr()
                    except Exception:
                        # try simple join
                        href = str(URL(tag['href'], base=str(resp.url)))
                    if await _is_image_response(session, href):
                        return href
    except Exception:
        pass
    return None

async def fetch_favicon(domain_url: str) -> Optional[str]:
    """
    Try to resolve a favicon URL for the given domain/feed link.
    Returns a URL string or None.
    """
    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # quick services first
        basic = await _try_basic(session, domain_url)
        if basic:
            return basic
        # parse homepage for <link rel="icon">
        parsed = await _parse_homepage(session, domain_url)
        if parsed:
            return parsed
        # last attempt
        return await _try_basic(session, domain_url)
