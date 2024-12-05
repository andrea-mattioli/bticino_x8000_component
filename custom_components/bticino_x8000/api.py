"""Api."""

import json
import logging
from typing import Any

import aiohttp

from .auth import refresh_access_token
from .const import (
    AUTH_CHECK_ENDPOINT,
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
        """Check API endpoint helth."""
        url = f"{DEFAULT_API_BASE_URL}{AUTH_CHECK_ENDPOINT}"

        payload = {
            "key1": "value1",
            "key2": "value2",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, headers=self.header, json=payload
                ) as response:
                    status_code = response.status
                    content = await response.text()
                    if status_code == 200:
                        _LOGGER.info(
                            "Authenticated!. HTTP %s, Content: %s, data: %s, Headers: %s",
                            status_code,
                            content,
                            self.data,
                            self.header,
                        )
                        return True
                    if status_code == 401:
                        _LOGGER.debug(
                            "Attempt to update token. HTTP %s, Content: %s, data: %s",
                            status_code,
                            content,
                            self.data,
                        )
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.check_api_endpoint_health()

                        return False
            except aiohttp.ClientError as e:
                _LOGGER.error(
                    "The endpoint API is unhealthy. Attempt to update token. Error: %s",
                    e,
                )
            return False

    async def handle_unauthorized_error(self, response: aiohttp.ClientResponse) -> bool:
        """Head off 401 Unauthorized."""
        status_code = response.status

        if status_code == 401:
            _LOGGER.debug("Received 401 Unauthorized error. Attempting token refresh")
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
            return True
        return False

    async def get_plants(self) -> dict[str, Any]:
        """Retrieve thermostat plants."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    if status_code == 200:
                        return {
                            "status_code": status_code,
                            "data": json.loads(content)["plants"],
                        }
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_plants()
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

                    if status_code == 200:
                        return {
                            "status_code": status_code,
                            "data": json.loads(content)["plant"]["modules"],
                        }
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_topology(plant_id)
                    return {
                        "status_code": status_code,
                        "error": "Failed to get topology.",
                    }
            except aiohttp.ClientError as e:
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
                    "error": (
                        f"Error during set_chronothermostat_status request: " f"{e}"
                    ),
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
                    if status_code == 401:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_chronothermostat_programlist(
                                plant_id, module_id
                            )

                    return {
                        "status_code": status_code,
                        "data": json.loads(content)["chronothermostats"][0]["programs"],
                    }
            except aiohttp.ClientError as e:
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
