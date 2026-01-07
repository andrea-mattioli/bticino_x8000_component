"""Authentication utilities for the Bticino X8000 custom component."""

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import AUTH_REQ_ENDPOINT, DEFAULT_AUTH_BASE_URL

_LOGGER = logging.getLogger(__name__)


async def exchange_code_for_tokens(
    hass: HomeAssistant, client_id: str, client_secret: str, code: str
) -> tuple[str, Any, Any]:
    """Get access token from authorization code using HA shared session."""
    token_url = f"{DEFAULT_AUTH_BASE_URL}{AUTH_REQ_ENDPOINT}"
    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_secret": client_secret,
        "client_id": client_id,
    }

    _LOGGER.debug("exchange_code_for_tokens - Requesting token from: %s", token_url)

    # FIX: Uso della sessione condivisa (Best Practice HA)
    session = async_get_clientsession(hass)
    
    try:
        async with session.post(token_url, data=payload) as response:
            status_code = response.status
            _LOGGER.debug("exchange_code_for_tokens - Response status: %s", status_code)

            if status_code != 200:
                content = await response.text()
                _LOGGER.error(
                    "exchange_code_for_tokens - Token request failed. "
                    "Status: %s, Response: %s",
                    status_code,
                    content,
                )
                raise ValueError(
                    f"Failed to exchange code for tokens. Status: {status_code}"
                )

            try:
                token_data = await response.json()
            except Exception as e:
                content = await response.text()
                _LOGGER.error(
                    "exchange_code_for_tokens - Failed to parse JSON: %s. Content: %s",
                    e,
                    content,
                    exc_info=True,
                )
                raise ValueError(f"Invalid JSON response from auth server: {e}") from e

    except Exception as e:
        _LOGGER.error("exchange_code_for_tokens - Network/Session error: %s", e)
        raise

    # FIX CODE REVIEW: Controllo simmetrico esistenza access_token
    if not token_data.get("access_token"):
        _LOGGER.error(
            "exchange_code_for_tokens - Missing access_token in response: %s", token_data
        )
        raise ValueError("Missing access_token in token exchange response")

    access_token = "Bearer " + token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")
    
    expires_ts = int(time.time()) + int(expires_in) if expires_in else int(time.time()) + 3600
    access_token_expires_on = dt_util.utc_from_timestamp(expires_ts)

    return access_token, refresh_token, access_token_expires_on


async def refresh_access_token(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[str, Any, Any]:
    """Refresh access token using HA shared session."""
    token_url = f"{DEFAULT_AUTH_BASE_URL}{AUTH_REQ_ENDPOINT}"
    payload = {
        "refresh_token": data["refresh_token"],
        "grant_type": "refresh_token",
        "client_secret": data["client_secret"],
        "client_id": data["client_id"],
    }

    _LOGGER.debug("refresh_access_token - Requesting token refresh from: %s", token_url)

    # FIX: Uso della sessione condivisa
    session = async_get_clientsession(hass)

    try:
        async with session.post(token_url, data=payload) as response:
            status_code = response.status
            _LOGGER.debug("refresh_access_token - Response status: %s", status_code)

            if status_code != 200:
                content = await response.text()
                _LOGGER.error(
                    "refresh_access_token - Refresh failed. Status: %s, Response: %s",
                    status_code,
                    content,
                )
                raise ValueError(f"Failed to refresh token. Status: {status_code}")

            try:
                token_data = await response.json()
            except Exception as e:
                content = await response.text()
                _LOGGER.error(
                    "refresh_access_token - Failed to parse JSON response: %s. Content: %s",
                    e,
                    content,
                    exc_info=True,
                )
                raise ValueError(f"Invalid JSON response from auth server: {e}") from e

    except Exception as e:
        _LOGGER.error("refresh_access_token - Network/Session error: %s", e)
        raise

    if not token_data.get("access_token"):
        _LOGGER.error(
            "refresh_access_token - Missing access_token in response: %s", token_data
        )
        raise ValueError("Missing access_token in refresh response")

    access_token = "Bearer " + token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    expires_on = token_data.get("expires_on")
    expires_in = token_data.get("expires_in")

    if expires_on:
        expires_ts = int(expires_on)
    elif expires_in:
        expires_ts = int(time.time()) + int(expires_in)
    else:
        _LOGGER.warning("Missing 'expires_in' or 'expires_on' in refresh response.")
        expires_ts = int(time.time()) + 3600

    access_token_expires_on = dt_util.utc_from_timestamp(expires_ts)

    _LOGGER.debug("Refreshed token expires on: %s", access_token_expires_on.isoformat())
    _LOGGER.debug("Refreshed token data keys: %s", list(token_data.keys()))

    return access_token, refresh_token, access_token_expires_on
