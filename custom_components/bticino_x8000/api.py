"""Api."""

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


class BticinoX8000Api:
    """Legrand API class."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Init function."""
        self.data = data
        self.header = {
            "Authorization": self.data["access_token"],
            "Ocp-Apim-Subscription-Key": self.data["subscription_key"],
            "Content-Type": "application/json",
        }

    async def check_api_endpoint_health(self) -> bool:
        """Use /plants endpoint to validate token."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 200:
                        _LOGGER.info("Token valid. /plants accessible")
                        return True
                    if status_code == 401:
                        _LOGGER.debug("Unauthorized. Attempt token refresh")
                        if await self.handle_unauthorized_error(response):
                            return await self.check_api_endpoint_health()
                    else:
                        _LOGGER.error(
                            "Error during health check. Status code: %s, Content: %s",
                            status_code,
                            content,
                        )
            except aiohttp.ClientError as e:
                _LOGGER.error("Error during health check: %s", e)
        return False

    async def handle_unauthorized_error(self, response: aiohttp.ClientResponse) -> bool:
        """Head off 401 Unauthorized."""
        status_code = response.status

        if status_code == 401:
            _LOGGER.debug("Received 401 Unauthorized error. Attempting token refresh")
            try:
                (
                    access_token,
                    _,
                    _,
                ) = await refresh_access_token(self.data)
                self.header = {
                    "Authorization": access_token,
                    "Ocp-Apim-Subscription-Key": self.data["subscription_key"],
                    "Content-Type": "application/json",
                }
                _LOGGER.debug("Token refresh successful after 401 error")
                return True
            except Exception as e:
                _LOGGER.error(
                    "Token refresh failed after 401 error: %s", e, exc_info=True
                )
                return False
        return False

    async def get_plants(self) -> dict[str, Any]:
        """Retrieve thermostat plants."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    _LOGGER.debug(
                        "get_plants - status_code: %s, content preview: %s",
                        status_code,
                        content[:200],
                    )

                    if status_code == 200:
                        try:
                            data = json.loads(content)
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
                            return {
                                "status_code": status_code,
                                "data": data["plants"],
                            }
                        except (KeyError, json.JSONDecodeError) as e:
                            _LOGGER.error(
                                "get_plants - Error parsing response: %s, content: %s",
                                e,
                                content,
                                exc_info=True,
                            )
                            return {
                                "status_code": 500,
                                "error": f"Error parsing response: {e}",
                            }
                    if status_code == 401:
                        _LOGGER.debug("get_plants - Received 401, attempting token refresh")
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_plants()
                    _LOGGER.error(
                        "get_plants - HTTP error %s. Content: %s", status_code, content
                    )
                    return {
                        "status_code": status_code,
                        "error": (
                            f"Failed get_plants. "
                            f"Content: {content}, "
                            f"URL: {url}, "
                            f"HEADER: {self.header}"
                        ),
                    }
            except aiohttp.ClientError as e:
                _LOGGER.error("get_plants - Network error: %s", e, exc_info=True)
                return {
                    "status_code": 500,
                    "error": f"Failed get_plants: {e}",
                }

    async def get_topology(self, plant_id: str) -> dict[str, Any]:
        """Retrieve thermostat topology."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plant_id}{TOPOLOGY}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    _LOGGER.debug(
                        "get_topology - plant_id: %s, status_code: %s, content preview: %s",
                        plant_id,
                        status_code,
                        content[:200],
                    )

                    if status_code == 200:
                        try:
                            data = json.loads(content)
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
                            return {
                                "status_code": status_code,
                                "data": data["plant"]["modules"],
                            }
                        except (KeyError, json.JSONDecodeError) as e:
                            _LOGGER.error(
                                "get_topology - Error parsing response: %s. "
                                "plant_id: %s, content: %s",
                                e,
                                plant_id,
                                content,
                                exc_info=True,
                            )
                            return {
                                "status_code": 500,
                                "error": f"Error parsing response: {e}",
                            }
                    if status_code == 401:
                        _LOGGER.debug(
                            "get_topology - Received 401 for plant_id: %s, attempting token refresh",
                            plant_id,
                        )
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_topology(plant_id)
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
            except aiohttp.ClientError as e:
                _LOGGER.error(
                    "get_topology - Network error for plant_id: %s. Error: %s",
                    plant_id,
                    e,
                    exc_info=True,
                )
                return {
                    "status_code": 500,
                    "error": f"Failed to get topology: {e}",
                }

    async def set_chronothermostat_status(
        self, plant_id: str, module_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Set thermostat status."""
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, headers=self.header, data=json.dumps(data)
                ) as response:
                    status_code = response.status
                    content = await response.text()

                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.set_chronothermostat_status(
                                plant_id, module_id, data
                            )

                    return {"status_code": status_code, "text": content}
            except aiohttp.ClientError as e:
                return {
                    "status_code": 500,
                    "error": (f"Error during set_chronothermostat_status request: {e}"),
                }

    async def get_chronothermostat_status(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        """Get thermostat status."""
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_chronothermostat_status(
                                plant_id, module_id
                            )
                    return {"status_code": status_code, "data": json.loads(content)}
            except aiohttp.ClientError as e:
                return {
                    "status_code": 500,
                    "error": f"Error during get_chronothermostat_status request: {e}",
                }

    async def get_chronothermostat_measures(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        """Get thermostat measures."""
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}/measures"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_chronothermostat_measures(
                                plant_id, module_id
                            )
                    return {"status_code": status_code, "data": json.loads(content)}
            except aiohttp.ClientError as e:
                return {
                    "status_code": 500,
                    "error": f"Error during get_chronothermostat_measures request: {e}",
                }

    async def get_chronothermostat_programlist(
        self, plant_id: str, module_id: str
    ) -> dict[str, Any]:
        """Get thermostat programlist."""
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/"
            f"addressLocation{PLANTS}/{plant_id}/modules/parameter/id/value/{module_id}/"
            f"programlist"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    _LOGGER.debug(
                        "get_chronothermostat_programlist - plant_id: %s, module_id: %s, "
                        "status_code: %s",
                        plant_id,
                        module_id,
                        status_code,
                    )
                    _LOGGER.debug(
                        "get_chronothermostat_programlist - content: %s", content[:500]
                    )

                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_chronothermostat_programlist(
                                plant_id, module_id
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
                        _LOGGER.debug(
                            "get_chronothermostat_programlist - parsed JSON keys: %s",
                            list(data.keys()),
                        )

                        if "chronothermostats" not in data:
                            _LOGGER.error(
                                "get_chronothermostat_programlist - Response missing 'chronothermostats' key. "
                                "plant_id: %s, module_id: %s, available keys: %s, response: %s",
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
                            return {
                                "status_code": 200,
                                "data": [],
                            }

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
                        return {
                            "status_code": 500,
                            "error": f"Error parsing response: {e}",
                        }

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

    async def get_subscriptions_c2c_notifications(self) -> dict[str, Any]:
        """Get C2C subscriptions."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/subscription"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_subscriptions_c2c_notifications()

                    return {
                        "status_code": status_code,
                        "data": json.loads(content) if status_code == 200 else content,
                    }
            except aiohttp.ClientError as e:
                return {
                    "status_code": 500,
                    "error": f"Error during get_subscriptions_C2C_notifications request: {e}",
                }

    async def set_subscribe_c2c_notifications(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Add C2C subscriptions."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plant_id}/subscription"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, headers=self.header, data=json.dumps(data)
                ) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.set_subscribe_c2c_notifications(
                                plant_id, data
                            )

                    return {"status_code": status_code, "text": json.loads(content)}
            except aiohttp.ClientError as e:
                return {
                    "status_code": 500,
                    "error": f"Error during set_subscribe_C2C_notifications request: {e}",
                }

    async def delete_subscribe_c2c_notifications(
        self, plant_id: str, subscription_id: str
    ) -> dict[str, Any]:
        """Remove C2C subscriptions."""
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}"
            f"{PLANTS}/{plant_id}/subscription/{subscription_id}"
        )

        async with aiohttp.ClientSession() as session:
            try:
                async with session.delete(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.delete_subscribe_c2c_notifications(
                                plant_id, subscription_id
                            )

                    return {"status_code": status_code, "text": content}
            except aiohttp.ClientError as e:
                return {
                    "status_code": 500,
                    "error": f"Error during delete_subscribe_C2C_notifications request: {e}",
                }
