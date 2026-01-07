"""Config Flow."""

# mypy: disable-error-code=no-any-return
# pylint: disable=W0223
import asyncio  # Added for timeouts
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

# Timeout for API calls during config flow (seconds)
API_TIMEOUT = 20


class BticinoX8000ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Bticino ConfigFlow."""

    def __init__(self) -> None:
        """Init."""
        self.data: dict[str, Any] = {}
        # Map: "Display Name (Plant ID)" -> Thermostat Data Object
        self._selection_map: dict[str, Any] = {}
        self.bticino_api: BticinoX8000Api | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """User configuration."""
        errors = {}

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

        if user_input is not None:
            # IMPROVEMENT: Basic validation for empty fields
            for key, value in user_input.items():
                if isinstance(value, str) and not value.strip():
                    errors[key] = "value_empty"

            if not errors:
                self.data = user_input
                authorization_url = self.get_authorization_url(user_input)

                # IMPROVEMENT (UX): Move Auth URL to description_placeholders
                # instead of showing it as an error message.
                return self.async_show_form(
                    step_id="get_authorize_code",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                "browser_url",
                                description="Paste here the browser URL",
                                default="",
                            ): str,
                        }
                    ),
                    description_placeholders={
                        "auth_url": authorization_url,
                    },
                )

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
            errors=errors,
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

    async def async_step_get_authorize_code(  # pylint: disable=too-many-locals,too-many-nested-blocks
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Get authorization code."""
        errors = {}
        if user_input is not None:
            try:
                parsed_url = urlparse(user_input["browser_url"])
                query_params = parse_qs(parsed_url.query)

                if (
                    not query_params.get("code", [""])[0]
                    or not query_params.get("state", [""])[0]
                ):
                    raise ValueError("Invalid URL: Missing code or state.")

                self.data["code"] = query_params.get("code", [""])[0]

                # Exchange code for tokens
                (
                    access_token,
                    refresh_token,
                    access_token_expires_on,
                ) = await exchange_code_for_tokens(
                    self.hass,
                    self.data["client_id"],
                    self.data["client_secret"],
                    query_params.get("code", [""])[0],
                )

                self.data["access_token"] = access_token
                self.data["refresh_token"] = refresh_token
                self.data["access_token_expires_on"] = access_token_expires_on

                # Init API
                self.bticino_api = BticinoX8000Api(self.hass, self.data)

                if not await self.bticino_api.check_api_endpoint_health():
                    return self.async_abort(
                        reason="Auth Failed! API endpoint unreachable."
                    )

                # IMPROVEMENT: Fetch plants with Timeout & Robust Parsing
                try:
                    async with asyncio.timeout(API_TIMEOUT):
                        plants_data = await self.bticino_api.get_plants()
                except TimeoutError:
                    return self.async_abort(reason="Timeout retrieving plants.")

                # Check status code
                if plants_data.get("status_code") != 200:
                    _LOGGER.error("Failed to get plants: %s", plants_data)
                    return self.async_abort(
                        reason="API Error: Could not retrieve plants."
                    )

                # Robust Parsing: Handle nested structure safely
                plants_payload = plants_data.get("data", {})
                # Some API versions wrap it in "plants", others return list directly
                plants_list = []
                if isinstance(plants_payload, dict):
                    plants_list = plants_payload.get("plants", [])
                elif isinstance(plants_payload, list):
                    plants_list = plants_payload

                if not isinstance(plants_list, list):
                    _LOGGER.error(
                        "Unexpected API structure for plants: %s", type(plants_payload)
                    )
                    plants_list = []

                # Unique list of IDs
                plant_ids = list(
                    {plant.get("id") for plant in plants_list if plant.get("id")}
                )

                self._selection_map = {}

                for plant_id in plant_ids:
                    try:
                        # IMPROVEMENT: Timeout for Topology
                        async with asyncio.timeout(API_TIMEOUT):
                            topologies = await self.bticino_api.get_topology(plant_id)

                        if topologies.get("status_code") != 200:
                            continue

                        # Robust Parsing for Topology
                        topo_data = topologies.get("data", {})
                        modules = []

                        # Handle potential nesting: plant -> modules OR just modules
                        if "plant" in topo_data and isinstance(
                            topo_data["plant"], dict
                        ):
                            modules = topo_data["plant"].get("modules", [])
                        elif "modules" in topo_data:
                            modules = topo_data.get("modules", [])
                        elif isinstance(topo_data, list):
                            modules = topo_data

                        for thermo in modules:
                            if not isinstance(thermo, dict) or "id" not in thermo:
                                continue

                            thermo_name = thermo.get("name", "Unknown")

                            # IMPROVEMENT: Fetch programs with safe timeout handling inside helper
                            try:
                                programs = await self.get_programs_from_api(
                                    plant_id, thermo["id"]
                                )
                            except Exception:
                                _LOGGER.warning(
                                    "Could not fetch programs for %s", thermo_name
                                )
                                programs = []

                            # IMPROVEMENT (UX): Disambiguate names by adding Plant ID
                            display_name = f"{thermo_name} (Plant {plant_id})"

                            self._selection_map[display_name] = {
                                "id": thermo["id"],
                                "name": thermo_name,
                                "programs": programs,
                                "plant_id": plant_id,  # Store plant_id for later retrieval
                            }

                    except TimeoutError:
                        _LOGGER.warning(
                            "Timeout fetching topology for plant %s", plant_id
                        )
                        continue
                    except Exception as e:
                        _LOGGER.error("Error processing plant %s: %s", plant_id, e)
                        continue

                if not self._selection_map:
                    return self.async_abort(reason="No compatible thermostats found.")

                return self.async_show_form(
                    step_id="select_thermostats",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                "selected_thermostats",
                                description="Select Thermostats",
                                default=list(self._selection_map.keys()),
                            ): cv.multi_select(list(self._selection_map.keys())),
                        }
                    ),
                )

            except ValueError as error:
                _LOGGER.error("Auth flow error: %s", error)
                errors["base"] = "auth_callback_error"
                # Fall through to show form again
            except Exception as e:
                _LOGGER.exception("Unexpected error in auth flow")
                return self.async_abort(reason="unknown_error")

        # Re-show form if user_input is None or if ValueError occurred
        # We need to re-generate the auth URL to be safe
        auth_url = self.get_authorization_url(self.data)
        return self.async_show_form(
            step_id="get_authorize_code",
            data_schema=vol.Schema(
                {
                    vol.Required("browser_url"): str,
                }
            ),
            description_placeholders={"auth_url": auth_url},
            errors=errors,
        )

    async def get_programs_from_api(
        self, plant_id: str, topology_id: str
    ) -> list[dict[str, Any]] | None:
        """Retrieve the program list with timeout protection."""
        if self.bticino_api is not None:
            try:
                # 5 second timeout for programs is sufficient, don't block flow too long
                async with asyncio.timeout(5):
                    programs = await self.bticino_api.get_chronothermostat_programlist(
                        plant_id, topology_id
                    )
            except TimeoutError:
                return []

            if programs.get("status_code") != 200:
                return []

            # Robust Parsing for Programs
            data = programs.get("data", {})
            chrono_list = []

            if "chronothermostats" in data:
                chrono_list = data["chronothermostats"]
            elif isinstance(data, list):
                chrono_list = data  # Rare case

            if chrono_list and isinstance(chrono_list, list) and len(chrono_list) > 0:
                item = chrono_list[0]
                if isinstance(item, dict):
                    programs_list = item.get("programs", [])
                    return [p for p in programs_list if p.get("number") != 0]

            return []
        return None

    async def async_step_select_thermostats(
        self, user_input: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """User can select one o more thermostat to add."""

        # IMPROVEMENT: Reconstruct structure using the Selection Map
        # This properly maps the selected "Display Names" back to the full data objects
        # and groups them by plant_id as expected by the integration structure.

        # Structure target: [ { plant_id: { id: ..., name: ..., programs: ..., webhook_id: ... } } ]
        final_selection = []

        for display_name in user_input["selected_thermostats"]:
            if display_name in self._selection_map:
                thermo_data = self._selection_map[display_name]
                plant_id = thermo_data.pop("plant_id")  # Remove helper key

                # Add webhook ID
                thermo_data["webhook_id"] = generate_id()

                final_selection.append({plant_id: thermo_data})

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
                "selected_thermostats": final_selection,
            },
        )
