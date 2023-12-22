import logging
import aiohttp
import json
from datetime import datetime, timedelta
from .const import DEFAULT_AUTH_BASE_URL, AUTH_REQ_ENDPOINT
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def exchange_code_for_tokens(client_id, client_secret, redirect_uri, code):
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
    access_token_expires_on = datetime.utcnow() + timedelta(
        seconds=token_data.get("expires_in")
    )

    return access_token, refresh_token, access_token_expires_on


async def refresh_access_token(data):
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
    access_token_expires_on = datetime.utcnow() + timedelta(
        seconds=token_data.get("expires_in")
    )
    return access_token, refresh_token, access_token_expires_on
