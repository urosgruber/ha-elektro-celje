"""Download of the Elektro Celje feeds."""

from __future__ import annotations

import asyncio

import aiohttp

from .const import FEED_URL

TIMEOUT_SECONDS = 30
MAX_BODY_BYTES = 1_000_000
USER_AGENT = (
    "HomeAssistant-elektro_celje/2.0.0 "
    "(+https://github.com/urosgruber/ha-elektro-celje)"
)


class FeedError(Exception):
    """The feed could not be downloaded."""


async def async_fetch_feed(session: aiohttp.ClientSession, region: str) -> str:
    """Download the feed of one region and return the body as text."""
    url = FEED_URL.format(region=region)
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            # Do not follow a redirect: it could lead to another host. A 3xx
            # answer is a FeedError like any other status that is not 200.
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}, allow_redirects=False
            ) as response:
                if response.status != 200:
                    raise FeedError(f"{url} returned HTTP {response.status}")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise FeedError(f"{url} is larger than 1 MB")
    except TimeoutError as err:
        raise FeedError(f"{url} timed out") from err
    except aiohttp.ClientError as err:
        raise FeedError(f"{url} failed: {err}") from err
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as err:
        raise FeedError(f"{url} is not valid UTF-8") from err
