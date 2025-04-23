"""Auth."""

import logging
from datetime import timedelta  # noqa: D100
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .const import AUTH_REQ_ENDPOINT, DEFAULT_AUTH_BASE_URL

_LOGGER = logging.getLogger(__name__)


async def exchange_code_for_tokens(
    client_id: str, client_secret: str, code: str
) -> tuple[str, Any, Any]:
    """Get access token."""
    token_url = f"{DEFAULT_AUTH_BASE_URL}{AUTH_REQ_ENDPOINT}"
    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_secret": client_secret,
        "client_id": client_id,
    }

    async with (
        aiohttp.ClientSession() as session,
        session.post(token_url, data=payload) as response,
    ):
        token_data = await response.json()

    access_token = "Bearer " + str(token_data.get("access_token"))
    refresh_token = token_data.get("refresh_token")
    access_token_expires_on = dt_util.utcnow() + timedelta(
        seconds=token_data.get("expires_in")
    )

    return access_token, refresh_token, access_token_expires_on


async def refresh_access_token(data: dict[str, Any]) -> tuple[str, Any, Any]:
    """Refresh access token."""
    token_url = f"{DEFAULT_AUTH_BASE_URL}{AUTH_REQ_ENDPOINT}"
    payload = {
        "refresh_token": data["refresh_token"],
        "grant_type": "refresh_token",
        "client_secret": data["client_secret"],
        "client_id": data["client_id"],
    }

    async with (
        aiohttp.ClientSession() as session,
        session.post(token_url, data=payload) as response,
    ):
        token_data = await response.json()
    access_token = "Bearer " + token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    access_token_expires_on = dt_util.utcnow() + timedelta(
        seconds=token_data.get("expires_in")
    )
    return access_token, refresh_token, access_token_expires_on
