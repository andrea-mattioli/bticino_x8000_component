"""Climate."""

# pylint: disable=duplicate-code

import copy
import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import get_api
from .api import BticinoX8000Api

# from .input_select import BticinoX8000ProgramInputSelect
from .const import (
    ATTR_END_DATETIME,
    ATTR_HVAC_MODE,
    ATTR_SCHEDULE_NAME,
    ATTR_TARGET_TEMPERATURE,
    ATTR_TIME_BOOST_MODE,
    ATTR_TIME_PERIOD,
    DOMAIN,
    SERVICE_SET_BOOST_MODE,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_TEMPERATURE_WITH_END_DATETIME,
    SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD,
    SERVICE_SET_TURN_OFF_WITH_END_DATETIME,
    SERVICE_SET_TURN_OFF_WITH_TIME_PERIOD,
)

_LOGGER = logging.getLogger(__name__)
SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.TURN_ON
)
BOOST_TIME = ["30", "60", "90"]
DEFAULT_MAX_TEMP = 40
DEFAULT_MIN_TEMP = 7
HVAC_MODES = ["heating", "cooling"]
PRECISION_HALVES = 0.1


# pylint: disable=R0902,R0904
# pylint: disable=W0223
class BticinoX8000ClimateEntity(ClimateEntity):
    """Bticino X8000 Climate entity."""

    _attr_supported_features = SUPPORT_FLAGS
    _enable_turn_on_off_backwards_compatibility = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = PRECISION_HALVES
    _attr_hvac_mode = HVACMode.AUTO
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_min_temp = DEFAULT_MIN_TEMP
    # NO POLLING: Legrand allows ~500 API calls/day per subscription key.
    # State arrives via C2C webhook; async_update only runs when explicitly
    # requested (e.g. the homeassistant.update_entity service).
    _attr_should_poll = False
    _custom_attributes: dict[str, Any] = {}

    def __init__(
        self,
        api: BticinoX8000Api,
        config: dict[str, Any],
    ) -> None:
        """Init."""
        self._attr_hvac_modes = [
            HVACMode.AUTO,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.OFF,
        ]
        #        self._attr_hvac_action = [
        #            HVACAction.HEATING,
        #            HVACAction.COOLING,
        #            HVACAction.OFF,
        #        ]
        self._bticino_api = api
        self._plant_id: str = config["plant_id"]
        self._topology_id: str = config["topology_id"]
        self._programs_name = config["programs"]
        self._program_number: list[dict[str, Any]] = []
        self._name: str = config["thermostat_name"]
        self._set_point: float | None = None
        self._temperature: float | None = None
        self._humidity: float | None = None
        self._function: str = ""
        self._mode: str = ""
        self._program: str = ""
        self._load_state: str = ""
        self._activation_time: str = ""
        # Last state shown (may include a command applied locally) and last
        # state actually reported by Legrand (webhook or API read).
        self._last_chrono_data: dict[str, Any] | None = None
        self._last_reported_data: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        """Listen for webhook updates and load the initial state."""
        self.async_on_remove(
            async_dispatcher_connect(  # type: ignore[has-type]
                self.hass,
                f"{DOMAIN}_webhook_update",
                self.handle_webhook_update,
            )
        )
        if not self.has_data():
            await self.async_sync_manual()

    async def async_update(self) -> None:
        """Fetch the current state from the API (one call, on request only)."""
        await self.async_sync_manual()

    def _with_sender(self, chrono_data: dict[str, Any]) -> dict[str, Any]:
        """Make sure the data carries this thermostat's plant/module ids."""
        data = copy.deepcopy(chrono_data)
        sender = data.setdefault("sender", {})
        plant = sender.setdefault("plant", {})
        plant.setdefault("id", self._plant_id)
        plant.setdefault("module", {}).setdefault("id", self._topology_id)
        return data

    def _dispatch_chronothermostat(
        self, chrono_data: dict[str, Any], optimistic: bool = False
    ) -> None:
        """Send thermostat data to this climate entity and its sensors/selects."""
        async_dispatcher_send(  # type: ignore[has-type]
            self.hass,
            f"{DOMAIN}_webhook_update",
            {
                "data": [
                    {"data": {"chronothermostats": [self._with_sender(chrono_data)]}}
                ],
                "optimistic": optimistic,
            },
        )

    def _set_point_for_payload(self) -> float | None:
        """Return the set point, or the last one reported by the thermostat."""
        if self._set_point is not None:
            return self._set_point
        value = ((self._last_reported_data or {}).get("setPoint") or {}).get("value")
        return float(value) if value is not None else None

    @staticmethod
    def _program_numbers(programs: Any) -> list[int]:
        return [int(p["number"]) for p in programs or [] if p.get("number") is not None]

    def _apply_command_locally(
        self, payload: dict[str, Any], response: dict[str, Any]
    ) -> None:
        """Show the commanded state right away, without an extra API call.

        The next webhook notification (or a manual refresh) replaces it with
        the real state reported by the thermostat.
        """
        if response.get("status_code") != 200 or self._last_chrono_data is None:
            return
        merged = copy.deepcopy(self._last_chrono_data)
        merged.update(copy.deepcopy(payload))
        if "activationTime" not in payload:
            merged.pop("activationTime", None)
        if (payload.get("mode") or "").lower() == "automatic":
            # In automatic mode the program decides the set point: reuse the one
            # last reported for the same program, otherwise it is unknown until
            # the thermostat reports it.
            reported = self._last_reported_data or {}
            same_program = (reported.get("mode") or "").lower() == "automatic" and (
                self._program_numbers(reported.get("programs"))
                == self._program_numbers(payload.get("programs"))
            )
            merged["setPoint"] = (
                copy.deepcopy(reported.get("setPoint"))
                if same_program
                else {"value": None}
            )
        _LOGGER.debug("Climate %s: applying command locally: %s", self._name, payload)
        self._dispatch_chronothermostat(merged, optimistic=True)

    def _update_attrs(self, custom_attrs: dict[str, Any]) -> None:
        """Update custom attributes."""
        self._custom_attributes = custom_attrs

    def _get_program_name(self, program: list[dict[str, Any]]) -> str:
        if not program:
            return self._program
        for thermostat_program in self._programs_name:
            if int(program[0]["number"]) == int(thermostat_program["number"]):
                program_name: str = thermostat_program["name"]
                return program_name
        return "Program not found"

    def _get_program_number(self, program: str) -> str:
        for thermostat_program in self._programs_name:
            if program == thermostat_program["name"]:
                program_number: str = thermostat_program["number"]
                return program_number
        return "Program not found"

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self._topology_id}_climate"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link with other entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topology_id)},
            name=self._name,  # Just "Sala", not "Bticino Sala"
            manufacturer="Legrand",
            model="X8000",
        )

    @property
    def name(self) -> str:
        """Return the name of the climate entity."""
        return self._name

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return "°C"

    @property
    def umidity_unit(self) -> str:
        """Return the unit of measurement."""
        return "%"

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._set_point

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._temperature

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity."""
        return self._humidity

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation mode."""
        if self._mode:
            if self._mode.lower() == "automatic":
                return HVACMode.AUTO
        if self._mode and self._function:
            if (
                self._mode.lower() == "manual" or self._mode.lower() == "boost"
            ) and self._function.lower() == "heating":
                return HVACMode.HEAT
            if (
                self._mode.lower() == "manual" or self._mode.lower() == "boost"
            ) and self._function.lower() == "cooling":
                return HVACMode.COOL
            if self._mode.lower() == "protection" or self._mode.lower() == "off":
                return HVACMode.OFF
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current operation action."""
        if self._mode and self._function and self._load_state:
            if (
                (
                    self._mode.lower() == "manual"
                    or self._mode.lower() == "boost"
                    or self._mode.lower() == "automatic"
                )
                and self._function.lower() == "heating"
                and self._load_state.lower() == "active"
            ):
                return HVACAction.HEATING
            if (
                (
                    self._mode.lower() == "manual"
                    or self._mode.lower() == "boost"
                    or self._mode.lower() == "automatic"
                )
                and self._function.lower() == "cooling"
                and self._load_state.lower() == "active"
            ):
                return HVACAction.COOLING
            if self._load_state.lower() == "inactive":
                return HVACAction.OFF
        return None

    async def async_turn_off(self) -> None:
        """Set thermostat to off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        """Set thermostat to on."""
        await self.async_set_hvac_mode(HVACMode.AUTO)

    # pylint: disable=W0239
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return a dictionary of extra state attributes."""
        attrs = dict(super().extra_state_attributes or {})
        attrs.update(self._custom_attributes)
        return attrs

    @callback
    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates."""
        _LOGGER.info(
            "WEBHOOK RECEIVED for climate %s - Full event: %s",
            self._name,
            event,
        )
        data_list = event["data"]

        if not data_list:
            _LOGGER.warning(
                "Climate %s: Received empty webhook update data", self._name
            )
            return

        _LOGGER.debug("Climate %s: Parsing chronothermostats from webhook", self._name)
        chronothermostats = event["data"][0]["data"]["chronothermostats"]
        _LOGGER.debug(
            "Climate %s: Found %d chronothermostats in webhook",
            self._name,
            len(chronothermostats),
        )

        for chronothermostat_data in chronothermostats:
            plant_data = chronothermostat_data.get("sender", {}).get("plant", {})
            plant_id = plant_data.get("id")
            topology_id = plant_data.get("module", {}).get("id")

            if (
                not plant_id
                or not topology_id
                or (plant_id != self._plant_id)
                or (topology_id != self._topology_id)
            ):
                continue
            self._last_chrono_data = copy.deepcopy(chronothermostat_data)
            if not event.get("optimistic"):
                self._last_reported_data = copy.deepcopy(chronothermostat_data)
            thermometer_data = chronothermostat_data.get("thermometer", {}).get(
                "measures", [{}]
            )[0]
            hygrometer_data = chronothermostat_data.get("hygrometer", {}).get(
                "measures", [{}]
            )[0]
            self._function = chronothermostat_data.get("function")
            self._mode = chronothermostat_data.get("mode")
            self._load_state = chronothermostat_data.get("loadState")
            self._program_number = chronothermostat_data.get("programs", [])
            self._program = self._get_program_name(self._program_number)
            if "activationTime" in chronothermostat_data:
                self._activation_time = chronothermostat_data.get("activationTime")
                self._update_attrs(
                    {
                        "mode": self._mode.lower(),
                        "status": self._load_state.lower(),
                        "current_program": self._program,
                        "available_programs": [
                            option["name"] for option in self._programs_name
                        ],
                        self._mode.lower()
                        + "_time_remaining": self.calculate_remaining_time(
                            self._activation_time
                        ),
                    }
                )
            else:
                self._update_attrs(
                    {
                        "mode": self._mode.lower(),
                        "status": self._load_state.lower(),
                        "current_program": self._program,
                        "available_programs": [
                            option["name"] for option in self._programs_name
                        ],
                    }
                )
            if "setPoint" in chronothermostat_data:
                value = (chronothermostat_data.get("setPoint") or {}).get("value")
                self._set_point = float(value) if value is not None else None
            if thermometer_data.get("value") is not None:
                self._temperature = float(thermometer_data["value"])
            if hygrometer_data.get("value") is not None:
                self._humidity = float(hygrometer_data["value"])

            _LOGGER.info(
                "Climate %s updated from webhook: temp=%s°C, humidity=%s%%, "
                "target=%s°C, mode=%s, program=%s, status=%s",
                self._name,
                self._temperature,
                self._humidity,
                self._set_point,
                self._mode,
                self._program,
                self._load_state,
            )

            # Trigger an update of the entity state
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        if hvac_mode == "auto":
            payload = {
                "function": self._function,
                "mode": "automatic",
                "setPoint": {
                    "value": self._set_point_for_payload(),
                    "unit": self.temperature_unit,
                },
                "programs": [{"number": self._program_number[0]["number"]}],
            }
        elif hvac_mode == "off":
            payload = {
                "function": self._function,
                "mode": "off",
            }
        elif hvac_mode == "heat":
            payload = {
                "function": "heating",
                "mode": "manual",
                "setPoint": {
                    "value": self._set_point_for_payload(),
                    "unit": self.temperature_unit,
                },
                "programs": [{"number": self._program_number[0]["number"]}],
            }
        elif hvac_mode == "cool":
            payload = {
                "function": "cooling",
                "mode": "manual",
                "setPoint": {
                    "value": self._set_point_for_payload(),
                    "unit": self.temperature_unit,
                },
                "programs": [{"number": self._program_number[0]["number"]}],
            }
        else:
            _LOGGER.error("Invalid hvac_mode: %s", hvac_mode)
            return
        response = await self._bticino_api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )
        if response["status_code"] != 200:
            _LOGGER.error(
                "Error setting hvac_mode for %s. Status code: %s",
                self._name,
                response,
            )
        self._apply_command_locally(payload, response)

    async def async_therm_manual(
        self, hvac_modes: str, target_temperature: str | None, end_timestamp: str
    ) -> None:
        """Set manual."""
        _LOGGER.debug(hvac_modes, target_temperature, end_timestamp)
        now_timestamp = dt_util.now().strftime("%Y-%m-%dT%H:%M:%S")
        if target_temperature is not None:
            payload = {
                "function": hvac_modes,
                "mode": "manual",
                "activationTime": now_timestamp + "/" + end_timestamp,
                "setPoint": {
                    "value": target_temperature,
                    "unit": self.temperature_unit,
                },
            }
        else:
            payload = {
                "function": self._function,
                "mode": hvac_modes,
                "activationTime": now_timestamp + "/" + end_timestamp,
            }
        response = await self._bticino_api.set_chronothermostat_status(
            self._plant_id,
            self._topology_id,
            payload,
        )
        if response["status_code"] != 200:
            _LOGGER.error(
                "Error setting temperature for %s. Status code: %s",
                self._name,
                response,
            )
        self._apply_command_locally(payload, response)

    async def _async_service_set_temperature_with_end_datetime(
        self, **kwargs: Any
    ) -> None:
        hvac_mode = kwargs[ATTR_HVAC_MODE]
        target_temperature = kwargs[ATTR_TARGET_TEMPERATURE]
        end_datetime = kwargs[ATTR_END_DATETIME]
        end_timestamp = end_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        _LOGGER.debug(
            "Setting %s to target temperature %s with end datetime %s",
            self.entity_id,
            target_temperature,
            end_timestamp,
        )
        await self.async_therm_manual(hvac_mode, target_temperature, end_timestamp)

    async def _async_service_set_boost_mode(self, **kwargs: Any) -> None:
        hvac_mode = kwargs[ATTR_HVAC_MODE]
        if hvac_mode == "cooling":
            set_pont = DEFAULT_MIN_TEMP
        else:
            set_pont = DEFAULT_MAX_TEMP

        now_timestamp = dt_util.now().strftime("%Y-%m-%dT%H:%M:%S")
        boost_30 = (dt_util.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
        boost_60 = (dt_util.now() + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S")
        boost_90 = (dt_util.now() + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%S")

        boost_time = kwargs[ATTR_TIME_BOOST_MODE]

        if int(boost_time) == 30:
            payload = {
                "function": hvac_mode,
                "mode": "boost",
                "activationTime": now_timestamp + "/" + boost_30,
                "setPoint": {"value": set_pont, "unit": self.temperature_unit},
            }
        elif int(boost_time) == 60:
            payload = {
                "function": hvac_mode,
                "mode": "boost",
                "activationTime": now_timestamp + "/" + boost_60,
                "setPoint": {"value": set_pont, "unit": self.temperature_unit},
            }
        elif int(boost_time) == 90:
            payload = {
                "function": hvac_mode,
                "mode": "boost",
                "activationTime": now_timestamp + "/" + boost_90,
                "setPoint": {"value": set_pont, "unit": self.temperature_unit},
            }
        else:
            _LOGGER.error("Invalid boost_time: %s (must be 30, 60, or 90)", boost_time)
            return
        response = await self._bticino_api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )
        if response["status_code"] != 200:
            _LOGGER.error(
                "Error setting %s to boost with time period %s Min: ERROR = %s",
                self._name,
                boost_time,
                response,
            )
        self._apply_command_locally(payload, response)

    async def _async_service_set_temperature_with_time_period(
        self, **kwargs: Any
    ) -> None:
        hvac_mode = kwargs[ATTR_HVAC_MODE]
        target_temperature = kwargs[ATTR_TARGET_TEMPERATURE]
        time_period = kwargs[ATTR_TIME_PERIOD]

        _LOGGER.info(
            "Setting %s to target temperature %s with time period %s",
            self.entity_id,
            target_temperature,
            time_period,
        )
        end_timestamp = (
            dt_util.now() + timedelta(seconds=time_period.seconds)
        ).strftime("%Y-%m-%dT%H:%M:%S")
        await self.async_therm_manual(hvac_mode, target_temperature, end_timestamp)

    async def _async_service_set_turn_off_with_time_period(self, **kwargs: Any) -> None:
        time_period = kwargs[ATTR_TIME_PERIOD]

        _LOGGER.info(
            "Turn off thermostat %s with time period %s",
            self.entity_id,
            time_period,
        )
        end_timestamp = (
            dt_util.now() + timedelta(seconds=time_period.seconds)
        ).strftime("%Y-%m-%dT%H:%M:%S")
        await self.async_therm_manual("off", None, end_timestamp)

    async def _async_service_set_turn_off_with_end_datetime(
        self, **kwargs: Any
    ) -> None:
        end_datetime = kwargs[ATTR_END_DATETIME]
        end_timestamp = end_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        _LOGGER.debug(
            "Turn off thermostat %s with end datetime %s",
            self.entity_id,
            end_timestamp,
        )
        await self.async_therm_manual("off", None, end_timestamp)

    async def _async_service_set_schedule(self, **kwargs: Any) -> None:
        selected_schedule = kwargs[ATTR_SCHEDULE_NAME]
        _LOGGER.debug(
            "Set program schedule %s on %s", selected_schedule, self.entity_id
        )
        self._get_program_number(selected_schedule)
        payload = {
            "function": self._function,
            "mode": "automatic",
            "setPoint": {
                "value": self._set_point_for_payload(),
                "unit": self.temperature_unit,
            },
            "programs": [{"number": self._get_program_number(selected_schedule)}],
        }
        response = await self._bticino_api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )
        if response["status_code"] != 200:
            _LOGGER.error(
                "Error setting %s program %s: ERROR = %s",
                self._name,
                selected_schedule,
                response,
            )
        self._apply_command_locally(payload, response)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is not None:
            payload = {
                "function": self._function,
                "mode": "manual",
                "setPoint": {
                    "value": target_temperature,
                    "unit": self.temperature_unit,
                },
            }
            response = await self._bticino_api.set_chronothermostat_status(
                self._plant_id,
                self._topology_id,
                payload,
            )

            if response["status_code"] != 200:
                _LOGGER.error(
                    "Error setting temperature for %s. Status code: %s",
                    self._name,
                    response,
                )
            self._apply_command_locally(payload, response)

    def has_data(
        self,
    ) -> bool:
        """Entity data."""
        if (
            not self._function
            and not self._mode
            and not self._program
            and not self._load_state
        ):
            return False
        return True

    def calculate_remaining_time(self, date_string: str) -> dict[str, Any]:
        """Convert string to date object."""
        date_to_compare = dt_util.parse_datetime(date_string)
        if date_to_compare is None:
            return {}
        date_to_compare = dt_util.as_utc(date_to_compare)
        current_date = dt_util.now()
        time_difference = date_to_compare - current_date
        remaining_days = time_difference.days
        remaining_seconds = time_difference.total_seconds()
        remaining_hours, remainder = divmod(remaining_seconds, 3600)
        remaining_minutes, remaining_seconds = divmod(remainder, 60)

        return {
            "days": remaining_days,
            "hours": remaining_hours,
            "minutes": remaining_minutes,
            "seconds": remaining_seconds,
        }

    async def async_sync_manual(self) -> None:
        """Force sync chronothermostat status (one API call)."""
        _LOGGER.info(
            "Climate %s: Starting async_sync_manual() - Calling API...",
            self._name,
        )
        response = await self._bticino_api.get_chronothermostat_status(
            self._plant_id, self._topology_id
        )
        if response["status_code"] != 200:
            _LOGGER.error(
                "Error updating status for %s. Status code: %s, response: %s",
                self._name,
                response["status_code"],
                response.get("error"),
            )
            return
        try:
            chronothermostat_data = response["data"]["chronothermostats"][0]
        except (KeyError, IndexError, TypeError):
            _LOGGER.error(
                "Climate %s: unexpected status response: %s",
                self._name,
                response.get("data"),
            )
            return
        # Same path as a webhook: updates this entity and its sensors/selects
        self._dispatch_chronothermostat(chronothermostat_data)
        _LOGGER.info(
            "Climate %s: async_sync_manual() completed - temp=%s°C, "
            "humidity=%s%%, target=%s°C, mode=%s, program=%s",
            self._name,
            self._temperature,
            self._humidity,
            self._set_point,
            self._mode,
            self._program,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add entry."""
    data = dict(config_entry.data)
    api = get_api(hass, config_entry)
    entities = []
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        topology_id = plant_data.get("id")
        thermostat_name = plant_data.get("name")
        programs = plant_data.get("programs")
        config = {
            "plant_id": plant_id,
            "topology_id": topology_id,
            "thermostat_name": thermostat_name,
            "programs": programs,
        }
        _LOGGER.info("THERMOSTAT_DATA: %s", config)
        entities.append(BticinoX8000ClimateEntity(api, config))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_SET_BOOST_MODE,
        {
            vol.Required(ATTR_HVAC_MODE): vol.In(HVAC_MODES),
            vol.Required(ATTR_TIME_BOOST_MODE): vol.In(BOOST_TIME),
        },
        "_async_service_set_boost_mode",
    )
    platform.async_register_entity_service(
        SERVICE_SET_TEMPERATURE_WITH_END_DATETIME,
        {
            vol.Required(ATTR_HVAC_MODE): vol.In(HVAC_MODES),
            vol.Required(ATTR_TARGET_TEMPERATURE): vol.All(
                vol.Coerce(float), vol.Range(min=DEFAULT_MIN_TEMP, max=DEFAULT_MAX_TEMP)
            ),
            vol.Required(ATTR_END_DATETIME): cv.datetime,
        },
        "_async_service_set_temperature_with_end_datetime",
    )
    platform.async_register_entity_service(
        SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD,
        {
            vol.Required(ATTR_HVAC_MODE): vol.In(HVAC_MODES),
            vol.Required(ATTR_TARGET_TEMPERATURE): vol.All(
                vol.Coerce(float), vol.Range(min=DEFAULT_MIN_TEMP, max=DEFAULT_MAX_TEMP)
            ),
            vol.Required(ATTR_TIME_PERIOD): vol.All(
                cv.time_period,
                cv.positive_timedelta,
            ),
        },
        "_async_service_set_temperature_with_time_period",
    )
    platform.async_register_entity_service(
        SERVICE_SET_TURN_OFF_WITH_TIME_PERIOD,
        {
            vol.Required(ATTR_TIME_PERIOD): vol.All(
                cv.time_period,
                cv.positive_timedelta,
            ),
        },
        "_async_service_set_turn_off_with_time_period",
    )

    platform.async_register_entity_service(
        SERVICE_SET_TURN_OFF_WITH_END_DATETIME,
        {
            vol.Required(ATTR_END_DATETIME): cv.datetime,
        },
        "_async_service_set_turn_off_with_end_datetime",
    )

    platform.async_register_entity_service(
        SERVICE_SET_SCHEDULE,
        {vol.Required(ATTR_SCHEDULE_NAME): cv.string},
        "_async_service_set_schedule",
    )
