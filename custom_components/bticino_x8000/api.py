"""Api with strict rate limiting, concurrency control and token persistence."""

import asyncio
import json
import logging
from datetime import datetime  # Added for timestamp tracking
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .auth import refresh_access_token
from .const import (
    DEFAULT_API_BASE_URL,
    DOMAIN,
    PLANTS,
    THERMOSTAT_API_ENDPOINT,
    TOPOLOGY,
)

_LOGGER = logging.getLogger(__name__)

# Base delay between calls (starting point for exponential backoff)
API_DELAY_SECONDS = 2.0
MAX_CONCURRENT_REQUESTS = 1

# IMPROVEMENT: Granular timeouts (HA Best Practice).
# Fail fast on connection (10s) but allow processing time (20s total).
HTTP_TIMEOUT_TOTAL = 20
HTTP_TIMEOUT_CONNECT = 10


# --- Custom Exceptions Definition ---
class BticinoApiError(Exception):
    """Base class for all API errors."""


class RateLimitError(BticinoApiError):
    """Raised when the API returns a 429 error."""


class AuthError(BticinoApiError):
    """Raised when authentication fails or token cannot be refreshed."""


class BticinoX8000Api:
    """Legrand API class with Rate Limiting, Backoff, and Shared Session."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """Init function."""
        self.hass = hass
        self.data = data
        self.header = {
            "Authorization": self.data.get("access_token"),
            "Ocp-Apim-Subscription-Key": self.data.get("subscription_key"),
            "Content-Type": "application/json",
        }
        # RENAMED: Lock specifically used to serialize token refresh operations
        self._token_refresh_lock = asyncio.Lock()
        self._api_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.auth_broken = False

        # Diagnostic: Internal counters for telemetry
        self.call_count = 0
        self.api_success_count = 0
        self.api_rate_limit_count = 0
        self.api_auth_fail_count = 0
        self.api_other_fail_count = 0
        self.last_call_time = None

        # Use Home Assistant's shared session
        self._session = async_get_clientsession(hass)

    async def _async_request(
        self, method: str, url: str, payload: dict | None = None
    ) -> dict[str, Any]:
        """
        Wrapper for all API calls.
        Handles Rate Limiting (Exponential Backoff), Session reuse, and Retries.
        Raises specific exceptions (RateLimitError, AuthError) on failure.
        """
        # MOVED: The counter increment has been moved inside the loop below
        # to track physical requests correctly.

        if self.auth_broken:
            _LOGGER.warning(
                "Authentication previously broken. Skipping request to %s", url
            )
            self.api_auth_fail_count += 1
            raise AuthError("Authentication is broken")

        # ACQUIRE SEMAPHORE (Serialize requests)
        async with self._api_semaphore:
            # Minimal pacing to avoid bursting even before the first request
            await asyncio.sleep(0.5)

            attempts = 0
            max_attempts = 3
            current_delay = API_DELAY_SECONDS

            while attempts < max_attempts:
                attempts += 1

                # FIX: Count physical requests (including retries) for accurate Rate Limit tracking
                # This is now inside the semaphore and retry loop to reflect real server load
                self.call_count += 1
                self.last_call_time = dt_util.utcnow()

                try:
                    request_args = {
                        "headers": self.header,
                        # IMPROVEMENT: Use granular timeout configuration
                        "timeout": aiohttp.ClientTimeout(
                            total=HTTP_TIMEOUT_TOTAL, connect=HTTP_TIMEOUT_CONNECT
                        ),
                    }
                    if payload:
                        request_args["json"] = payload

                    # Log the attempt (Counter is already incremented above)
                    _LOGGER.debug(
                        "API Call #%s | Attempt %s/%s: %s %s",
                        self.call_count,
                        attempts,
                        max_attempts,
                        method,
                        url,
                    )

                    async with self._session.request(
                        method, url, **request_args
                    ) as response:
                        status_code = response.status
                        content = await response.text()

                        # CASE 1: SUCCESS (200 OK, 201 Created, 409 Conflict)
                        if status_code in (200, 201, 409):
                            self.api_success_count += 1
                            try:
                                return {
                                    "status_code": status_code,
                                    "data": json.loads(content),
                                }
                            except json.JSONDecodeError:
                                return {"status_code": status_code, "data": {}}

                        # CASE 2: TOKEN EXPIRED (401)
                        if status_code == 401:
                            if attempts < max_attempts:
                                _LOGGER.warning(
                                    "401 Unauthorized. Acquiring lock to refresh token..."
                                )

                                async with self._token_refresh_lock:
                                    if (
                                        self.header["Authorization"]
                                        != self.data["access_token"]
                                    ):
                                        _LOGGER.info(
                                            "Token refreshed by another thread. Retrying request."
                                        )
                                    else:
                                        if await self._handle_token_refresh():
                                            _LOGGER.info(
                                                "Token refreshed and SAVED. Retrying request."
                                            )
                                        else:
                                            _LOGGER.error(
                                                "Token refresh FAILED. Marking auth as broken."
                                            )
                                            self.auth_broken = True
                                            self.api_auth_fail_count += 1
                                            raise AuthError("Token refresh failed")

                                # Retry immediately after refresh
                                continue
                            else:
                                _LOGGER.error("401 Loop detected. Stop retrying.")
                                self.api_auth_fail_count += 1
                                raise AuthError("Unauthorized - Retry limit reached")

                        # CASE 3: RATE LIMIT (429) - FATAL IMMEDIATE STOP
                        # Logic changed: Do NOT retry on 429. This prevents extending the ban.
                        if status_code == 429:
                            _LOGGER.error(
                                "429 Rate Limit Detected on attempt %s. ABORTING RETRIES.",
                                attempts,
                            )
                            self.api_rate_limit_count += 1
                            raise RateLimitError(
                                f"Persistent Rate Limit (429) detected"
                            )

                        # CASE 4: SERVER ERROR (5xx)
                        # We still retry for 500+ errors as they might be temporary glitches.
                        if status_code >= 500:
                            if attempts < max_attempts:
                                _LOGGER.warning(
                                    "Server Error %s detected. Sleeping for %s seconds before retry...",
                                    status_code,
                                    current_delay,
                                )
                                await asyncio.sleep(current_delay)
                                current_delay *= 2  # Double the delay for next attempt
                                continue
                            else:
                                self.api_other_fail_count += 1
                                raise BticinoApiError(
                                    f"Persistent Server Error {status_code} after {max_attempts} attempts"
                                )

                        # CASE 5: CLIENT ERRORS (4xx except 401/429/409)
                        _LOGGER.error("HTTP Client Error %s: %s", status_code, content)
                        self.api_other_fail_count += 1
                        raise BticinoApiError(
                            f"HTTP Client Error {status_code}: {content}"
                        )

                except aiohttp.ClientError as e:
                    _LOGGER.error("Network error during request to %s: %s", url, e)
                    if attempts < max_attempts:
                        _LOGGER.debug(
                            "Network error. Sleeping %s seconds...", current_delay
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= 2
                    else:
                        self.api_other_fail_count += 1
                        raise BticinoApiError(f"Network error: {e}")
                except Exception as e:
                    # FIX: If it's one of our custom exceptions, re-raise it immediately
                    # so the Coordinator can handle the specific error type (e.g. Rate Limit)
                    if isinstance(e, BticinoApiError):
                        raise e

                    # Log only genuine unexpected crashes
                    _LOGGER.exception("Unexpected error during request to %s", url)
                    self.api_other_fail_count += 1
                    raise e

            self.api_other_fail_count += 1
            raise BticinoApiError("Request failed - Unknown loop exit")

    async def _handle_token_refresh(self) -> bool:
        """Handle token refresh and PERSIST it to disk."""
        try:
            # Pass self.hass to use the shared session in auth.py
            access_token, refresh_token, _ = await refresh_access_token(
                self.hass, self.data
            )

            self.data["access_token"] = access_token
            self.data["refresh_token"] = refresh_token
            self.header["Authorization"] = access_token

            entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in entries:
                if entry.data.get("client_id") == self.data.get("client_id"):
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                        },
                    )
                    _LOGGER.info("Successfully saved new token to ConfigEntry storage.")
                    break

            return True
        except Exception as e:
            _LOGGER.error("Fatal error refreshing token: %s", e)
            return False

    # --- Public Methods ---

    async def check_api_endpoint_health(self) -> bool:
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        try:
            response = await self._async_request("GET", url)
            return response["status_code"] == 200
        except Exception:
            return False

    async def get_plants(self) -> dict[str, Any]:
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        return await self._async_request("GET", url)

    async def get_topology(self, plant_id: str) -> dict[str, Any]:
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plant_id}{TOPOLOGY}"
        return await self._async_request("GET", url)

    async def get_chronothermostat_status(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}"
        )
        return await self._async_request("GET", url)

    async def set_chronothermostat_status(
        self, plant_id: str, module_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}"
        )
        return await self._async_request("POST", url, payload=data)

    async def get_chronothermostat_programlist(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}/programlist"
        )
        return await self._async_request("GET", url)

    async def get_subscriptions_c2c_notifications(self) -> dict[str, Any]:
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/subscription"
        return await self._async_request("GET", url)

    async def set_subscribe_c2c_notifications(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plant_id}/subscription"
        return await self._async_request("POST", url, payload=data)

    async def delete_subscribe_c2c_notifications(
        self, plant_id: str, subscription_id: str
    ) -> dict[str, Any]:
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}"
            f"{PLANTS}/{plant_id}/subscription/{subscription_id}"
        )
        return await self._async_request("DELETE", url)
