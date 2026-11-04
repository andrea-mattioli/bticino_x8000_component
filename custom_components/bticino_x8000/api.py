"""Api."""

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .auth import refresh_access_token
from .const import (
    DEFAULT_API_BASE_URL,
    PLANTS,
    THERMOSTAT_API_ENDPOINT,
    TOPOLOGY,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _parse_json(content: str) -> Any:
    """Return the decoded JSON body, or the raw text if it is not JSON."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


class BticinoX8000Api:
    """Legrand API class.

    Tokens are read from ``self.data`` on every request. The same dict is shared
    with the config entry setup, so a refresh done anywhere is seen everywhere.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        """Init function."""
        self.data = data
        self.last_error: str | None = None
        self._refresh_lock = asyncio.Lock()

    @property
    def header(self) -> dict[str, str]:
        """Build the request headers from the current token."""
        return {
            "Authorization": self.data["access_token"],
            "Ocp-Apim-Subscription-Key": self.data["subscription_key"],
            "Content-Type": "application/json",
        }

    async def async_refresh_token(self) -> None:
        """Refresh the access token and store it in the shared data.

        Raises on failure.
        """
        async with self._refresh_lock:
            await self._async_refresh_token_locked()

    async def _async_refresh_token_locked(self) -> None:
        access_token, refresh_token, expires_on = await refresh_access_token(self.data)
        self.data["access_token"] = access_token
        if refresh_token:
            self.data["refresh_token"] = refresh_token
        self.data["access_token_expires_on"] = expires_on

    async def _async_refresh_after_401(self, used_token: str) -> bool:
        """Refresh the token after a 401. Return True if the call can be retried."""
        async with self._refresh_lock:
            if self.data.get("access_token") != used_token:
                # Another call refreshed the token while this one was waiting.
                return True
            try:
                await self._async_refresh_token_locked()
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Token refresh failed after 401 error: %s", e)
                return False
        _LOGGER.debug("Token refreshed after 401 error")
        return True

    async def _async_send(
        self, method: str, url: str, body: str | None
    ) -> tuple[int, str, str]:
        """Send one request. Return status, body and the token that was used."""
        header = self.header
        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.request(
                    method, url, headers=header, data=body
                ) as response:
                    return (
                        response.status,
                        await response.text(),
                        header["Authorization"],
                    )
        except TimeoutError as e:
            raise aiohttp.ServerTimeoutError(f"Timeout calling {url}") from e

    async def _async_request(
        self, method: str, url: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, str]:
        """Call the API. On 401, refresh the token and retry exactly once.

        A second retry is never attempted: Legrand allows only 10 calls per
        minute once 4xx errors are returned, so looping on 401 ends in 429.
        Raises aiohttp.ClientError on network errors.
        """
        body = json.dumps(payload) if payload is not None else None
        status_code, content, used_token = await self._async_send(method, url, body)
        if status_code != 401:
            return status_code, content

        _LOGGER.debug("%s %s returned 401: %s", method, url, content)
        if not await self._async_refresh_after_401(used_token):
            return status_code, content

        status_code, content, _ = await self._async_send(method, url, body)
        if status_code == 401:
            _LOGGER.error(
                "%s %s still returns 401 with a freshly refreshed token, "
                "not retrying again. Response: %s",
                method,
                url,
                content,
            )
        return status_code, content

    async def check_api_endpoint_health(self) -> bool:
        """Use /plants endpoint to validate token."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            self.last_error = f"network error: {e}"
            _LOGGER.error("Error during health check: %s", e)
            return False
        if status_code == 200:
            _LOGGER.info("Token valid. /plants accessible")
            self.last_error = None
            return True
        self.last_error = f"GET /plants returned HTTP {status_code}"
        _LOGGER.error(
            "Health check failed: GET %s returned HTTP %s. Response: %s",
            url,
            status_code,
            content,
        )
        return False

    async def get_plants(self) -> dict[str, Any]:
        """Retrieve thermostat plants."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        _LOGGER.info("API CALL: GET %s", url)
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            _LOGGER.error("get_plants - Network error: %s", e, exc_info=True)
            return {"status_code": 500, "error": f"Failed get_plants: {e}"}

        _LOGGER.info(
            "API RESPONSE: GET plants - status=%s, content preview: %s",
            status_code,
            content[:200],
        )
        if status_code != 200:
            _LOGGER.error(
                "get_plants - HTTP error %s. Content: %s", status_code, content
            )
            return {
                "status_code": status_code,
                "error": f"Failed get_plants. HTTP {status_code}: {content}",
            }
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            _LOGGER.error(
                "get_plants - Error parsing response: %s, content: %s",
                e,
                content,
                exc_info=True,
            )
            return {"status_code": 500, "error": f"Error parsing response: {e}"}
        if "plants" not in data:
            _LOGGER.error(
                "get_plants - Response missing 'plants' key. "
                "Available keys: %s, response: %s",
                list(data.keys()),
                content,
            )
            return {
                "status_code": 500,
                "error": f"Invalid response structure. Keys found: {list(data.keys())}",
            }
        return {"status_code": status_code, "data": data["plants"]}

    async def get_topology(self, plant_id: str) -> dict[str, Any]:
        """Retrieve thermostat topology."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plant_id}{TOPOLOGY}"
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            _LOGGER.error(
                "get_topology - Network error for plant_id: %s. Error: %s",
                plant_id,
                e,
                exc_info=True,
            )
            return {"status_code": 500, "error": f"Failed to get topology: {e}"}

        _LOGGER.debug(
            "get_topology - plant_id: %s, status_code: %s, content preview: %s",
            plant_id,
            status_code,
            content[:200],
        )
        if status_code != 200:
            _LOGGER.error(
                "get_topology - HTTP error %s for plant_id: %s. Content: %s",
                status_code,
                plant_id,
                content,
            )
            return {
                "status_code": status_code,
                "error": f"Failed to get topology. HTTP {status_code}: {content}",
            }
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            _LOGGER.error(
                "get_topology - Error parsing response: %s. plant_id: %s, content: %s",
                e,
                plant_id,
                content,
                exc_info=True,
            )
            return {"status_code": 500, "error": f"Error parsing response: {e}"}
        if "plant" not in data or "modules" not in data["plant"]:
            _LOGGER.error(
                "get_topology - Invalid response structure. "
                "plant_id: %s, available keys: %s, response: %s",
                plant_id,
                list(data.keys()),
                content,
            )
            return {
                "status_code": 500,
                "error": f"Invalid response structure. Keys found: {list(data.keys())}",
            }
        return {"status_code": status_code, "data": data["plant"]["modules"]}

    def _chronothermostat_url(self, plant_id: str, module_id: str) -> str:
        return (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}"
        )

    async def set_chronothermostat_status(
        self, plant_id: str, module_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Set thermostat status."""
        url = self._chronothermostat_url(plant_id, module_id)
        try:
            status_code, content = await self._async_request("POST", url, data)
        except aiohttp.ClientError as e:
            return {
                "status_code": 500,
                "error": f"Error during set_chronothermostat_status request: {e}",
            }
        return {"status_code": status_code, "text": content}

    async def get_chronothermostat_status(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        """Get thermostat status."""
        url = self._chronothermostat_url(plant_id, module_id)
        _LOGGER.info(
            "API CALL: GET chronothermostat_status - plant=%s, module=%s",
            plant_id,
            module_id,
        )
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            return {
                "status_code": 500,
                "error": f"Error during get_chronothermostat_status request: {e}",
            }
        _LOGGER.info(
            "API RESPONSE: GET chronothermostat_status - status=%s, content preview: %s",
            status_code,
            content[:300],
        )
        if status_code != 200:
            return {"status_code": status_code, "error": content}
        return {"status_code": status_code, "data": _parse_json(content)}

    async def get_chronothermostat_measures(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        """Get thermostat measures."""
        url = f"{self._chronothermostat_url(plant_id, module_id)}/measures"
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            return {
                "status_code": 500,
                "error": f"Error during get_chronothermostat_measures request: {e}",
            }
        if status_code != 200:
            return {"status_code": status_code, "error": content}
        return {"status_code": status_code, "data": _parse_json(content)}

    async def get_chronothermostat_programlist(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        """Get thermostat programlist."""
        url = f"{self._chronothermostat_url(plant_id, module_id)}/programlist"
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            _LOGGER.error(
                "get_chronothermostat_programlist - Network error: %s. "
                "plant_id: %s, module_id: %s",
                e,
                plant_id,
                module_id,
                exc_info=True,
            )
            return {
                "status_code": 500,
                "error": f"Error during get_chronothermostat_programlist request: {e}",
            }

        _LOGGER.debug(
            "get_chronothermostat_programlist - plant_id: %s, module_id: %s, "
            "status_code: %s, content: %s",
            plant_id,
            module_id,
            status_code,
            content[:500],
        )
        if status_code != 200:
            _LOGGER.error(
                "get_chronothermostat_programlist - HTTP error. "
                "plant_id: %s, module_id: %s, status: %s, content: %s",
                plant_id,
                module_id,
                status_code,
                content,
            )
            return {
                "status_code": status_code,
                "error": f"HTTP {status_code}: {content}",
            }

        try:
            data = json.loads(content)
            if "chronothermostats" not in data:
                _LOGGER.error(
                    "get_chronothermostat_programlist - Response missing "
                    "'chronothermostats' key. plant_id: %s, module_id: %s, "
                    "available keys: %s, response: %s",
                    plant_id,
                    module_id,
                    list(data.keys()),
                    content,
                )
                return {
                    "status_code": 500,
                    "error": f"Invalid response structure. Keys found: {list(data.keys())}",
                }
            if not data["chronothermostats"]:
                _LOGGER.warning(
                    "get_chronothermostat_programlist - Empty chronothermostats list. "
                    "plant_id: %s, module_id: %s",
                    plant_id,
                    module_id,
                )
                return {"status_code": 200, "data": []}
            return {
                "status_code": status_code,
                "data": data["chronothermostats"][0]["programs"],
            }
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            _LOGGER.error(
                "get_chronothermostat_programlist - Error parsing response: %s. "
                "plant_id: %s, module_id: %s, content: %s",
                e,
                plant_id,
                module_id,
                content,
                exc_info=True,
            )
            return {"status_code": 500, "error": f"Error parsing response: {e}"}

    async def get_subscriptions_c2c_notifications(self) -> dict[str, Any]:
        """Get C2C subscriptions.

        Legrand answers 204 No Content when there are no subscriptions.
        """
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/subscription"
        try:
            status_code, content = await self._async_request("GET", url)
        except aiohttp.ClientError as e:
            return {
                "status_code": 500,
                "error": f"Error during get_subscriptions_C2C_notifications request: {e}",
            }
        if status_code == 200:
            return {"status_code": status_code, "data": _parse_json(content)}
        if status_code == 204:
            return {"status_code": status_code, "data": []}
        return {"status_code": status_code, "data": content}

    async def set_subscribe_c2c_notifications(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Add C2C subscriptions."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plant_id}/subscription"
        try:
            status_code, content = await self._async_request("POST", url, data)
        except aiohttp.ClientError as e:
            return {
                "status_code": 500,
                "error": f"Error during set_subscribe_C2C_notifications request: {e}",
            }
        return {"status_code": status_code, "text": _parse_json(content)}

    async def delete_subscribe_c2c_notifications(
        self, plant_id: str, subscription_id: str
    ) -> dict[str, Any]:
        """Remove C2C subscriptions."""
        if not subscription_id or subscription_id == "None":
            _LOGGER.error(
                "Cannot delete subscription: subscription_id is empty or None"
            )
            return {
                "status_code": 400,
                "error": "Invalid subscription_id (empty or None)",
            }

        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}"
            f"{PLANTS}/{plant_id}/subscription/{subscription_id}"
        )
        _LOGGER.debug(
            "DELETE C2C subscription - URL: %s, plant_id: %s, subscription_id: %s",
            url,
            plant_id,
            subscription_id,
        )
        try:
            status_code, content = await self._async_request("DELETE", url)
        except aiohttp.ClientError as e:
            _LOGGER.error(
                "HTTP error during delete_subscribe_c2c_notifications: %s",
                e,
                exc_info=True,
            )
            return {
                "status_code": 500,
                "error": f"Error during delete_subscribe_C2C_notifications request: {e}",
            }
        _LOGGER.debug(
            "DELETE C2C response - Status: %s, Content: %s",
            status_code,
            content[:200] if content else "empty",
        )
        return {"status_code": status_code, "text": content}
