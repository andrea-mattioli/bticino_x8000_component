# api.py

import logging
import aiohttp
import json
from .auth import refresh_access_token
from .const import (
    DEFAULT_API_BASE_URL,
    THERMOSTAT_API_ENDPOINT,
    PLANTS,
    TOPOLOGY,
    AUTH_CHECK_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class BticinoX8000Api:
    def __init__(self, data):
        self.data = data
        self.header = {
            "Authorization": self.data["access_token"],
            "Ocp-Apim-Subscription-Key": self.data["subscription_key"],
            "Content-Type": "application/json",
        }

    async def check_api_endpoint_health(self):
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
                            f"Authenticated!. HTTP {status_code}, Content: {content}, data: {self.data}, Headers: {self.header}"
                        )
                        return True
                    else:
                        _LOGGER.warning(
                            f"L'endpoint API non è sano. Tentativo di refresh del token. HTTP {status_code}, Content: {content}, data: {self.data},"
                        )
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.check_api_endpoint_health()

                        return False
            except Exception as e:
                _LOGGER.warning(
                    f"L'endpoint API non è sano. Tentativo di refresh del token. Errore: {e}"
                )
                return False

    async def handle_unauthorized_error(self, response):
        status_code = response.status

        if status_code == 401:
            _LOGGER.warning("Received 401 Unauthorized error. Attempting token refresh")
            # Ottieni i nuovi dati dopo il refresh
            (
                access_token,
                refresh_token,
                access_token_expires_on,
            ) = await refresh_access_token(self.data)
            self.header = {
                "Authorization": access_token,
                "Ocp-Apim-Subscription-Key": self.data["subscription_key"],
                "Content-Type": "application/json",
            }
            print("NEW_HEADERS:", self.header)

    async def get_plants(self):
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
                    else:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_plants()
                        return {
                            "status_code": status_code,
                            "error": f"Errore nella richiesta di get_plants. Content: {content}, URL: {url}, HEADER: {self.header}",
                        }
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di get_plants: {e}",
                }

    async def get_topology(self, plantId):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plantId}{TOPOLOGY}"
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
                    else:
                        # Retry the request on 401 Unauthorized
                        if await self.handle_unauthorized_error(response):
                            # Retry the original request
                            return await self.get_plants()
                        return {
                            "status_code": status_code,
                            "error": f"Errore nella richiesta di get_topology. Content: {content}, HEADEr: {self.header}, URL: {url}",
                        }
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di get_topology: {e}",
                }

    async def set_chronothermostat_status(self, plantId, moduleId, data):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/addressLocation{PLANTS}/{plantId}/modules/parameter/id/value/{moduleId}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, headers=self.header, data=json.dumps(data)
                ) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.set_chronothermostat_status(
                            plantId, moduleId, data
                        )

                    return {"status_code": status_code, "text": content}
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di set_chronothermostat_status: {e}",
                }

    async def get_chronothermostat_status(self, plantId, moduleId):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/addressLocation{PLANTS}/{plantId}/modules/parameter/id/value/{moduleId}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.get_chronothermostat_status(plantId, moduleId)

                    return {"status_code": status_code, "data": json.loads(content)}
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di get_chronothermostat_status: {e}",
                }

    async def get_chronothermostat_measures(self, plantId, moduleId):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/addressLocation{PLANTS}/{plantId}/modules/parameter/id/value/{moduleId}/measures"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.get_chronothermostat_measures(
                            plantId, moduleId
                        )

                    return {"status_code": status_code, "data": json.loads(content)}
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di get_chronothermostat_measures: {e}",
                }

    async def get_chronothermostat_programlist(self, plantId, moduleId):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/chronothermostat/thermoregulation/addressLocation{PLANTS}/{plantId}/modules/parameter/id/value/{moduleId}/programlist"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.get_chronothermostat_programlist(
                            plantId, moduleId
                        )

                    return {
                        "status_code": status_code,
                        "data": json.loads(content)["chronothermostats"][0]["programs"],
                    }
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di get_chronothermostat_programlist: {e}",
                }

    async def get_subscriptions_C2C_notifications(self):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/subscription"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.get_subscriptions_C2C_notifications()

                    return {
                        "status_code": status_code,
                        "data": json.loads(content) if status_code == 200 else content,
                    }
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di get_subscriptions_C2C_notifications: {e}",
                }

    async def set_subscribe_C2C_notifications(self, plantId, data):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plantId}/subscription"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, headers=self.header, data=json.dumps(data)
                ) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.set_subscribe_C2C_notifications(plantId, data)

                    return {"status_code": status_code, "text": json.loads(content)}
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di set_subscribe_C2C_notifications: {e}",
                }

    async def delete_subscribe_C2C_notifications(self, plantId, subscriptionId):
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}{PLANTS}/{plantId}/subscription/{subscriptionId}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.delete(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    # Retry the request on 401 Unauthorized
                    if await self.handle_unauthorized_error(response):
                        # Retry the original request
                        return await self.delete_subscribe_C2C_notifications(
                            plantId, subscriptionId
                        )

                    return {"status_code": status_code, "text": content}
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": f"Errore nella richiesta di delete_subscribe_C2C_notifications: {e}",
                }
