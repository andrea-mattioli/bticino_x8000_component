import logging

# from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from typing import Any, cast
from homeassistant.util import dt as dt_util
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

# from datetime import datetime, timedelta
from datetime import datetime, timedelta, timezone
from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    DEFAULT_MIN_TEMP,
    PRESET_AWAY,
    PRESET_NONE,
    PRESET_BOOST,
    PRESET_HOME,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol
from homeassistant.const import (
    ATTR_SUGGESTED_AREA,
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    STATE_OFF,
    UnitOfTemperature,
)

from .const import (
    DOMAIN,
    SERVICE_SET_BOOST_MODE,
    SERVICE_SET_TEMPERATURE_WITH_END_DATETIME,
    SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD,
    SERVICE_CLEAR_TEMPERATURE_SETTING,
    ATTR_END_DATETIME,
    ATTR_TARGET_TEMPERATURE,
    ATTR_TIME_PERIOD,
    ATTR_TIME_BOOST_MODE,
    ATTR_BOOST_MODE,
)

_LOGGER = logging.getLogger(__name__)
SUPPORT_FLAGS = ClimateEntityFeature.TARGET_TEMPERATURE
BOOST_TIME = (30, 60, 90)
DEFAULT_MAX_TEMP = 40
DEFAULT_MIN_TEMP = 7
BOOST_MODES = ["heating", "cooling"]


class BticinoX8000ClimateEntity(ClimateEntity):
    """Representation of a Bticino X8000 Climate entity."""

    _attr_supported_features = SUPPORT_FLAGS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = PRECISION_HALVES
    _attr_hvac_mode = HVACMode.AUTO
    _attr_max_temp = DEFAULT_MAX_TEMP
    _custom_attributes = {}

    def __init__(
        self, bticino_api, plant_id, topology_id, topology_name, programs
    ) -> None:
        self._attr_hvac_modes = [
            # HVACMode.AUTO,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.OFF,
        ]
        self._attr_hvac_action = [
            HVACAction.HEATING,
            HVACAction.COOLING,
            HVACAction.OFF,
        ]
        self._bticino_api = bticino_api
        self._plant_id = plant_id
        self._topology_id = topology_id
        self._topology_name = topology_name
        self._programs_name = programs
        self._program_number = None
        self._name = topology_name
        self._set_point = None
        self._temperature = None
        self._humidity = None
        self._function = None
        self._mode = None
        self._program = None
        self._loadState = None
        self._activationTime = None

    def _update_attrs(self, custom_attrs):
        """Update custom attributes."""
        self._custom_attributes = custom_attrs

    def _get_program_name(self, program):
        for thermostat_program in self._programs_name:
            if int(program[0]["number"]) == int(thermostat_program["number"]):
                return thermostat_program["name"]

    def _get_program_number(self, program):
        for thermostat_program in self._programs_name:
            if program == thermostat_program["name"]:
                return thermostat_program["number"]

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._topology_id}_climate"

    @property
    def name(self):
        """Return the name of the climate entity."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return "°C"

    @property
    def umidity_unit(self):
        """Return the unit of measurement."""
        return "%"

    @property
    def target_temperature(self):
        return self._set_point

    @property
    def current_temperature(self):
        return self._temperature

    @property
    def current_humidity(self):
        """Return the current humidity."""
        return self._humidity

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation."""
        print("Calling hvac_mode method.")
        if self._mode is not None and self._function is not None:
            print("HVAC_MODE:", self._mode.lower(), self._function.lower())
            if self._mode.lower() == "manual" and self._function.lower() == "heating":
                return HVACMode.HEAT
            if self._mode.lower() == "manual" and self._function.lower() == "cooling":
                return HVACMode.COOL
            if self._mode.lower() == "protection" or self._mode.lower() == "off":
                return HVACMode.OFF
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current operation."""
        print("HVAC_ACTION:", self._mode, self._function, self._loadState)
        if (
            self._mode is not None
            and self._function is not None
            and self._loadState is not None
        ):
            if (
                (
                    self._mode.lower() == "manual"
                    or self._mode.lower() == "boost"
                    or self._mode.lower() == "automatic"
                )
                and self._function.lower() == "heating"
                and self._loadState.lower() == "active"
            ):
                return HVACAction.HEATING
            if (
                (
                    self._mode.lower() == "manual"
                    or self._mode.lower() == "boost"
                    or self._mode.lower() == "automatic"
                )
                and self._function.lower() == "cooling"
                and self._loadState.lower() == "active"
            ):
                return HVACAction.COOLING
            if self._loadState.lower() == "inactive":
                return HVACAction.OFF
        return None

    @property
    def state(self):
        """Return the current load state."""
        return self._loadState

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def state_attributes(self):
        """Restituisce gli attributi di stato personalizzati."""
        attrs = super().state_attributes or {}
        attrs.update(self._custom_attributes)
        return attrs

    @callback
    def handle_webhook_update(self, event):
        """Handle webhook updates."""
        print("EVENT:", event["data"][0])
        data_list = event["data"]

        _LOGGER.info("Received data from webhook")

        if not data_list:
            _LOGGER.warning("Received empty webhook update data")
            return

        chronothermostats = event["data"][0]["data"]["chronothermostats"]
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
            set_point = chronothermostat_data.get("setPoint", {})
            thermometer_data = chronothermostat_data.get("thermometer", {}).get(
                "measures", [{}]
            )[0]
            hygrometer_data = chronothermostat_data.get("hygrometer", {}).get(
                "measures", [{}]
            )[0]
            self._function = chronothermostat_data.get("function")
            self._mode = chronothermostat_data.get("mode")
            self._program_number = chronothermostat_data.get("programs", [])
            self._program = self._get_program_name(self._program_number)
            if "activationTime" in chronothermostat_data:
                self._activationTime = chronothermostat_data.get("activationTime")
                self._update_attrs(
                    {
                        "programs": self._program,
                        self._mode.lower()
                        + "_time_remainig": self.calculate_remaining_time(
                            self._activationTime
                        ),
                    }
                )
            else:
                self._update_attrs(
                    {
                        "programs": self._program,
                    }
                )
            self._loadState = chronothermostat_data.get("loadState")
            self._set_point = float(set_point.get("value"))
            self._temperature = float(thermometer_data.get("value"))
            self._humidity = float(hygrometer_data.get("value"))
            print(
                "my data to send:",
                self._loadState,
                self._temperature,
                self._humidity,
                self._mode,
                self._program,
                self._activationTime,
            )
            # Trigger an update of the entity state
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == "auto":
            payload = {
                "function": self._function,
                "mode": "automatic",
                "setPoint": {"value": self._set_point, "unit": self.temperature_unit},
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
                "mode": "automatic",
                "setPoint": {"value": self._set_point, "unit": self.temperature_unit},
                "programs": [{"number": self._program_number[0]["number"]}],
            }
        elif hvac_mode == "cool":
            payload = {
                "function": "cooling",
                "mode": "automatic",
                "setPoint": {"value": self._set_point, "unit": self.temperature_unit},
                "programs": [{"number": self._program_number[0]["number"]}],
            }
        response = await self._bticino_api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )
        if response["status_code"] != 200:
            _LOGGER.error(
                "Error setting hvac_mode for %s. Status code: %s",
                self._name,
                response,
            )

    async def async_therm_manual(self, target_temperature, end_timestamp):
        return True

    async def _async_service_set_temperature_with_end_datetime(
        self, **kwargs: Any
    ) -> None:
        target_temperature = kwargs[ATTR_TARGET_TEMPERATURE]
        end_datetime = kwargs[ATTR_END_DATETIME]
        end_timestamp = int(dt_util.as_timestamp(end_datetime))

        _LOGGER.debug(
            "Setting %s to target temperature %s with end datetime %s",
            self.entity_id,
            target_temperature,
            end_timestamp,
        )
        await self.async_therm_manual(target_temperature, end_timestamp)

    async def _async_service_set_boost_mode(self, **kwargs: Any) -> None:
        boost_mode = kwargs[ATTR_BOOST_MODE]
        print("NOW:", dt_util.now().strftime("%Y-%m-%dT%H:%M:%S"))
        if boost_mode == "cooling":
            set_pont = DEFAULT_MIN_TEMP
        else:
            set_pont = DEFAULT_MAX_TEMP

        now_timestamp = dt_util.now().strftime("%Y-%m-%dT%H:%M:%S")
        boost_30 = (dt_util.now() + datetime.timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        boost_60 = (dt_util.now() + datetime.timedelta(minutes=60)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        boost_90 = (dt_util.now() + datetime.timedelta(minutes=90)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )

        boost_time = kwargs[ATTR_TIME_BOOST_MODE]

        if int(boost_time) == 30:
            payload = {
                "function": boost_mode,
                "mode": "boost",
                "activationTime": now_timestamp + "/" + boost_30,
                "setPoint": {"value": set_pont, "unit": self.temperature_unit},
            }
        elif int(boost_time) == 60:
            payload = {
                "function": boost_mode,
                "mode": "boost",
                "activationTime": now_timestamp + "/" + boost_60,
                "setPoint": {"value": set_pont, "unit": self.temperature_unit},
            }
        elif int(boost_time) == 90:
            payload = {
                "function": boost_mode,
                "mode": "boost",
                "activationTime": now_timestamp + "/" + boost_90,
                "setPoint": {"value": set_pont, "unit": self.temperature_unit},
            }
        print("PAYLOAD:", payload)
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

    async def _async_service_set_temperature_with_time_period(
        self, **kwargs: Any
    ) -> None:
        target_temperature = kwargs[ATTR_TARGET_TEMPERATURE]
        time_period = kwargs[ATTR_TIME_PERIOD]

        _LOGGER.debug(
            "Setting %s to target temperature %s with time period %s",
            self.entity_id,
            target_temperature,
            time_period,
        )

        now_timestamp = dt_util.as_timestamp(dt_util.utcnow())
        end_timestamp = int(now_timestamp + time_period.seconds)
        await self.async_therm_manual(target_temperature, end_timestamp)

    async def _async_service_clear_temperature_setting(self, **kwargs: Any) -> None:
        _LOGGER.debug("Clearing %s temperature setting", self.entity_id)
        await self.async_therm_manual(None, None)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        print(target_temperature)
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

    def has_data(self):
        return (
            self._set_point is not None
            and self._temperature is not None
            and self._humidity is not None
            and self._function is not None
            and self._mode is not None
            and self._program is not None
            and self._loadState is not None
        )

    def calculate_remaining_time(self, date_string):
        # Converte la stringa in un oggetto datetime consapevole del fuso orario
        date_to_compare_str = dt_util.parse_datetime(date_string).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        current_date_str = dt_util.now().strftime("%Y-%m-%dT%H:%M:%S")
        date_to_compare = dt_util.parse_datetime(date_to_compare_str)
        current_date = dt_util.parse_datetime(current_date_str)
        time_difference = date_to_compare - current_date
        remaining_days = time_difference.days
        remaining_seconds = time_difference.total_seconds()
        remaining_hours, remainder = divmod(remaining_seconds, 3600)
        remaining_minutes, remaining_seconds = divmod(remainder, 60)

        remaining_time = {
            "days": remaining_days,
            "hours": remaining_hours,
            "minutes": remaining_minutes,
            "seconds": remaining_seconds,
        }
        return remaining_time

    async def async_sync_manual(self):
        response = await self._bticino_api.get_chronothermostat_status(
            self._plant_id, self._topology_id
        )

        if response["status_code"] == 200:
            chronothermostat_data = response["data"]["chronothermostats"][0]
            self._function = chronothermostat_data["function"]
            self._mode = chronothermostat_data["mode"]
            self._program_number = chronothermostat_data["programs"]
            self._program = self._get_program_name(self._program_number)
            if "activationTime" in chronothermostat_data:
                self._activationTime = chronothermostat_data.get("activationTime")
                self._update_attrs(
                    {
                        "programs": self._program,
                        self._mode.lower()
                        + "_time_remainig": self.calculate_remaining_time(
                            self._activationTime
                        ),
                    }
                )
            else:
                self._update_attrs(
                    {
                        "programs": self._program,
                    }
                )
            self._loadState = chronothermostat_data["loadState"]
            set_point_data = chronothermostat_data["setPoint"]
            self._set_point = float(set_point_data["value"])
            thermometer_data = chronothermostat_data["thermometer"]["measures"][0]
            self._temperature = float(thermometer_data["value"])
            hygrometer_data = chronothermostat_data["hygrometer"]["measures"][0]
            self._humidity = float(hygrometer_data["value"])
            print("STATUS:", self._function, self._mode)
            self.async_write_ha_state()
        else:
            _LOGGER.error(
                "Error updating temperature for %s. Status code: %s",
                self._name,
                response["status_code"],
            )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_id = config_entry.entry_id
    entry_id_options = config_entry.options[entry_id]
    my_entity = BticinoX8000ClimateEntity(
        hass.data[DOMAIN][entry_id]["api"],
        entry_id_options["plant_id"],
        entry_id_options["topology_id"],
        entry_id_options["topology_name"],
        entry_id_options["programs"],
    )
    # async_add_entities = entity_platform.current_platform.async_add_entities
    async_add_entities([my_entity])
    if not my_entity.has_data():
        await my_entity.async_sync_manual()

    async_dispatcher_connect(
        hass,
        f"{DOMAIN}_webhook_update",
        my_entity.handle_webhook_update,
    )
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_SET_BOOST_MODE,
        {
            vol.Required(ATTR_BOOST_MODE): vol.In(BOOST_MODES),
            vol.Required(ATTR_TIME_BOOST_MODE): vol.In(BOOST_TIME),
        },
        "_async_service_set_boost_mode",
    )
    platform.async_register_entity_service(
        SERVICE_SET_TEMPERATURE_WITH_END_DATETIME,
        {
            vol.Required(ATTR_TARGET_TEMPERATURE): vol.All(
                vol.Coerce(float), vol.Range(min=7, max=DEFAULT_MAX_TEMP)
            ),
            vol.Required(ATTR_END_DATETIME): cv.datetime,
        },
        "_async_service_set_temperature_with_end_datetime",
    )
    platform.async_register_entity_service(
        SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD,
        {
            vol.Required(ATTR_TARGET_TEMPERATURE): vol.All(
                vol.Coerce(float), vol.Range(min=7, max=DEFAULT_MAX_TEMP)
            ),
            vol.Required(ATTR_TIME_PERIOD): vol.All(
                cv.time_period,
                cv.positive_timedelta,
            ),
        },
        "_async_service_set_temperature_with_time_period",
    )
    platform.async_register_entity_service(
        SERVICE_CLEAR_TEMPERATURE_SETTING,
        {},
        "_async_service_clear_temperature_setting",
    )
    return True
