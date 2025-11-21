"""Config Flow."""

# mypy: disable-error-code=no-any-return
# pylint: disable=W0223
import logging
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.webhook import async_generate_id as generate_id
from homeassistant.helpers import config_validation as cv

from .api import BticinoX8000Api
from .auth import exchange_code_for_tokens
from .const import (
    AUTH_URL_ENDPOINT,
    CLIENT_ID,
    CLIENT_SECRET,
    DEFAULT_AUTH_BASE_URL,
    DEFAULT_REDIRECT_URI,
    DOMAIN,
    SUBSCRIPTION_KEY,
)

_LOGGER = logging.getLogger(__name__)


class BticinoX8000ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Bticino ConfigFlow."""

    def __init__(self) -> None:
        """Init."""
        self.data: dict[str, Any] = {}
        self._thermostat_options: dict[str, Any] = {}
        self.bticino_api: BticinoX8000Api | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """User configuration."""
        if self.hass.config.external_url is not None:
            external_url = self.hass.config.external_url
        else:
            external_url = (
                "My HA external url ex: "
                "https://example.com:8123 "
                "(specify the port if is not standard 443)"
            )

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "client_id",
                            description="Client ID",
                            default=CLIENT_ID,
                        ): str,
                        vol.Required(
                            "client_secret",
                            description="Client Secret",
                            default=CLIENT_SECRET,
                        ): str,
                        vol.Required(
                            "subscription_key",
                            description="Subscription Key",
                            default=SUBSCRIPTION_KEY,
                        ): str,
                        vol.Required(
                            "external_url",
                            description="HA external_url",
                            default=external_url,
                        ): str,
                    }
                ),
            )

        self.data = user_input
        authorization_url = self.get_authorization_url(user_input)
        message = (
            f"Click the link below to authorize Bticino X8000. "
            f"After authorization, paste the browser URL here.\n\n"
            f"{authorization_url}"
        )
        return self.async_show_form(
            step_id="get_authorize_code",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "browser_url",
                        description="Paste here the browser URL",
                        default="Paste here the browser URL",
                    ): str,
                }
            ),
            errors={"base": message},
        )

    def get_authorization_url(self, user_input: dict[str, Any]) -> str:
        """Compose the auth url."""
        state = secrets.token_hex(16)
        return (
            f"{DEFAULT_AUTH_BASE_URL}{AUTH_URL_ENDPOINT}?"
            + f"client_id={user_input['client_id']}"
            + "&response_type=code"
            + f"&state={state}"
            + f"&redirect_uri={DEFAULT_REDIRECT_URI}"
        )

    async def async_step_get_authorize_code(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Get authorization code."""
        if user_input is not None:
            try:
                parsed_url = urlparse(user_input["browser_url"])
                _LOGGER.debug("Parsed URL: %s", parsed_url)
                query_params = parse_qs(parsed_url.query)
                _LOGGER.debug("Query Parameters: %s", query_params)

                if (
                    not query_params.get("code", [""])[0]
                    or not query_params.get("state", [""])[0]
                ):
                    raise ValueError(
                        "Unable to identify the Authorize Code or State. "
                        "Please make sure to provide a valid URL."
                    )

                self.data["code"] = query_params.get("code", [""])[0]

                (
                    access_token,
                    refresh_token,
                    access_token_expires_on,
                ) = await exchange_code_for_tokens(
                    self.data["client_id"],
                    self.data["client_secret"],
                    query_params.get("code", [""])[0],
                )

                self.data["access_token"] = access_token
                self.data["refresh_token"] = refresh_token
                self.data["access_token_expires_on"] = access_token_expires_on

                self.bticino_api = BticinoX8000Api(self.data)

                if not await self.bticino_api.check_api_endpoint_health():
                    return self.async_abort(reason="Auth Failed!")

                # Fetch and display the list of thermostats
                plants_data = await self.bticino_api.get_plants()
                _LOGGER.info("PLANTS_DATA: %s", plants_data)
                if plants_data["status_code"] == 200:
                    thermostat_options: dict[Any, Any] = {}
                    plant_ids = list({plant["id"] for plant in plants_data["data"]})
                    _LOGGER.info("PLANTS_LIST: %s", plant_ids)
                    for plant_id in plant_ids:
                        _LOGGER.debug("Processing plant_id: %s", plant_id)
                        try:
                            topologies = await self.bticino_api.get_topology(plant_id)
                            _LOGGER.debug(
                                "TOPOLOGIES for plant %s: %s", plant_id, topologies
                            )

                            # Check if topology fetch was successful
                            if topologies.get("status_code") != 200:
                                _LOGGER.error(
                                    "Failed to get topology for plant %s: %s. Skipping plant.",
                                    plant_id,
                                    topologies.get("error"),
                                )
                                continue  # Skip this plant instead of crashing

                            if "data" not in topologies:
                                _LOGGER.error(
                                    "No data in topology response for plant %s. Skipping plant.",
                                    plant_id,
                                )
                                continue

                            if plant_id not in thermostat_options:
                                thermostat_options[plant_id] = []

                            for thermo in topologies["data"]:
                                _LOGGER.debug(
                                    "Processing thermostat: %s in plant: %s",
                                    thermo.get("id"),
                                    plant_id,
                                )

                                try:
                                    programs = await self.get_programs_from_api(
                                        plant_id, thermo["id"]
                                    )
                                    _LOGGER.debug(
                                        "Programs retrieved for thermo %s: %s programs found",
                                        thermo["id"],
                                        len(programs) if programs else 0,
                                    )
                                except Exception as e:
                                    _LOGGER.error(
                                        "Failed to get programs for thermo %s in plant %s: %s. "
                                        "Using empty program list.",
                                        thermo.get("id"),
                                        plant_id,
                                        e,
                                        exc_info=True,
                                    )
                                    programs = []  # Fallback to empty list

                                thermostat_options[plant_id].append(
                                    {
                                        "id": thermo["id"],
                                        "name": thermo["name"],
                                        "programs": programs,
                                    }
                                )
                        except Exception as e:
                            _LOGGER.error(
                                "Unexpected error processing plant %s: %s. Skipping plant.",
                                plant_id,
                                e,
                                exc_info=True,
                            )
                            continue  # Skip this plant and continue with others

                    self._thermostat_options = thermostat_options
                    _LOGGER.info("THERMOSTAT_DETECTED: %s", self._thermostat_options)

                return self.async_show_form(
                    step_id="select_thermostats",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                "selected_thermostats",
                                description="Select Thermostats",
                                default=[
                                    options["name"]
                                    for options_list in self._thermostat_options.values()
                                    for options in options_list
                                ],
                            ): cv.multi_select(
                                [
                                    options["name"]
                                    for options_list in self._thermostat_options.values()
                                    for options in options_list
                                ]
                            ),
                        }
                    ),
                )

            except ValueError as error:
                _LOGGER.error(error)
                return await self.async_step_get_authorize_code()
        return await self.async_step_user(self.data)

    async def get_programs_from_api(
        self, plant_id: str, topology_id: str
    ) -> list[dict[str, Any]] | None:
        """Retrieve the program list."""
        if self.bticino_api is not None:
            _LOGGER.debug(
                "get_programs_from_api - Fetching programs for plant_id: %s, topology_id: %s",
                plant_id,
                topology_id,
            )

            programs = await self.bticino_api.get_chronothermostat_programlist(
                plant_id, topology_id
            )

            _LOGGER.debug("get_programs_from_api - Response: %s", programs)

            # Check if API call was successful
            if programs.get("status_code") != 200:
                _LOGGER.error(
                    "get_programs_from_api - Failed to get programs. "
                    "plant_id: %s, topology_id: %s, status: %s, error: %s",
                    plant_id,
                    topology_id,
                    programs.get("status_code"),
                    programs.get("error"),
                )
                return []  # Return empty list instead of None to avoid crashes

            # Check if data key exists
            if "data" not in programs:
                _LOGGER.warning(
                    "get_programs_from_api - No data in response. "
                    "plant_id: %s, topology_id: %s",
                    plant_id,
                    topology_id,
                )
                return []

            # Filter programs
            filtered_programs = [
                program for program in programs["data"] if program.get("number") != 0
            ]

            _LOGGER.debug(
                "get_programs_from_api - Filtered programs count: %s for topology_id: %s",
                len(filtered_programs),
                topology_id,
            )

            return filtered_programs
        return None

    async def async_step_select_thermostats(
        self, user_input: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """User can select one o more thermostat to add."""
        selected_thermostats = [
            {thermo_id: {**thermo_data, "webhook_id": generate_id()}}
            for thermo_id, thermo_list in self._thermostat_options.items()
            for thermo_data in thermo_list
            if thermo_data["name"] in user_input["selected_thermostats"]
        ]
        _LOGGER.info("My_selected_thermostats: %s", selected_thermostats)
        return self.async_create_entry(
            title="Bticino X8000",
            data={
                "client_id": self.data["client_id"],
                "client_secret": self.data["client_secret"],
                "subscription_key": self.data["subscription_key"],
                "external_url": self.data["external_url"],
                "access_token": self.data["access_token"],
                "refresh_token": self.data["refresh_token"],
                "access_token_expires_on": self.data["access_token_expires_on"],
                "selected_thermostats": selected_thermostats,
            },
        )
