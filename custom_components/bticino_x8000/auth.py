"""Authentication utilities for the Bticino X8000 custom component."""

import logging
import time
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .const import AUTH_REQ_ENDPOINT, DEFAULT_AUTH_BASE_URL

_LOGGER = logging.getLogger(__name__)


async def exchange_code_for_tokens(
    client_id: str, client_secret: str, code: str
) -> tuple[str, Any, Any]:
    """Get access token from authorization code."""
    token_url = f"{DEFAULT_AUTH_BASE_URL}{AUTH_REQ_ENDPOINT}"
    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_secret": client_secret,
        "client_id": client_id,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=payload) as response:
            token_data = await response.json()

    access_token = "Bearer " + token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    # Gestione robusta della scadenza
    expires_on = token_data.get("expires_on")
    expires_in = token_data.get("expires_in")

    if expires_on:
        expires_ts = int(expires_on)
    elif expires_in:
        expires_ts = int(time.time()) + int(expires_in)
    else:
        _LOGGER.warning("Missing 'expires_in' or 'expires_on' in token response.")
        expires_ts = int(time.time()) + 3600  # default fallback

    access_token_expires_on = dt_util.utc_from_timestamp(expires_ts)

    _LOGGER.debug("Access token expires on: %s", access_token_expires_on.isoformat())
    _LOGGER.debug("Token data: %s", token_data)

    return access_token, refresh_token, access_token_expires_on


async def refresh_access_token(data: dict[str, Any]) -> tuple[str, Any, Any]:
    """Refresh access token using refresh token."""
    token_url = f"{DEFAULT_AUTH_BASE_URL}{AUTH_REQ_ENDPOINT}"
    payload = {
        "refresh_token": data["refresh_token"],
        "grant_type": "refresh_token",
        "client_secret": data["client_secret"],
        "client_id": data["client_id"],
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=payload) as response:
            token_data = await response.json()

    access_token = "Bearer " + token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    # Stessa logica di gestione scadenza
    expires_on = token_data.get("expires_on")
    expires_in = token_data.get("expires_in")

    if expires_on:
        expires_ts = int(expires_on)
    elif expires_in:
        expires_ts = int(time.time()) + int(expires_in)
    else:
        _LOGGER.warning("Missing 'expires_in' or 'expires_on' in refresh response.")
        expires_ts = int(time.time()) + 3600  # fallback

    access_token_expires_on = dt_util.utc_from_timestamp(expires_ts)

    _LOGGER.debug("Refreshed token expires on: %s", access_token_expires_on.isoformat())
    _LOGGER.debug("Refreshed token data: %s", token_data)

    return access_token, refresh_token, access_token_expires_on
