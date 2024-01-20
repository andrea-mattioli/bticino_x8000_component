"""Climate."""
from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    DEFAULT_MIN_TEMP,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_HOME,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import BticinoX8000Api
from .const import (
    ATTR_BOOST_MODE,
    ATTR_END_DATETIME,
    ATTR_TARGET_TEMPERATURE,
    ATTR_TIME_BOOST_MODE,
    ATTR_TIME_PERIOD,
    DOMAIN,
    SERVICE_CLEAR_TEMPERATURE_SETTING,
    SERVICE_SET_BOOST_MODE,
    SERVICE_SET_TEMPERATURE_WITH_END_DATETIME,
    SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD,
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
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_target_temperature_step = 0.1
    _custom_attributes = {}

    def __init__(self, data, plant_id, topology_id, thermostat_name, programs) -> None:
        """Init."""
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
        self._bticino_api = BticinoX8000Api(data)
        self._plant_id = plant_id
        self._topology_id = topology_id
        self._programs_name = programs
        self._program_number = None
        self._name = thermostat_name
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
        """Return the target temperature."""
        return self._set_point

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._temperature

    @property
    def current_humidity(self):
        """Return the current humidity."""
        return self._humidity

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation mode."""
        if self._mode is not None and self._function is not None:
            if (
                self._mode.lower() == "manual"
                or self._mode.lower() == "boost"
                or self._mode.lower() == "automatic"
            ) and self._function.lower() == "heating":
                return HVACMode.HEAT
            if (
                self._mode.lower() == "manual"
                or self._mode.lower() == "boost"
                or self._mode.lower() == "automatic"
            ) and self._function.lower() == "cooling":
                return HVACMode.COOL
            if self._mode.lower() == "protection" or self._mode.lower() == "off":
                return HVACMode.OFF
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current operation action."""
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
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def state_attributes(self):
        """Return the list of cusom attributes."""
        attrs = super().state_attributes or {}
        attrs.update(self._custom_attributes)
        return attrs

    @callback
    def handle_webhook_update(self, event):
        """Handle webhook updates."""
        _LOGGER.debug("EVENT: %s", event["data"][0])
        data_list = event["data"]

        _LOGGER.debug("Received data from webhook")

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
            # Trigger an update of the entity state
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
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
        """Entity data."""
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
        """Conver string to date object."""
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
        """Force sync chronothermostat status."""
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
    """Add entry."""
    data = config_entry.data
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        topology_id = plant_data.get("id")
        thermostat_name = plant_data.get("name")
        programs = plant_data.get("programs")
        my_entity = BticinoX8000ClimateEntity(
            data,
            plant_id,
            topology_id,
            thermostat_name,
            programs,
        )
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
                vol.Coerce(float), vol.Range(min=DEFAULT_MIN_TEMP, max=DEFAULT_MAX_TEMP)
            ),
            vol.Required(ATTR_END_DATETIME): cv.datetime,
        },
        "_async_service_set_temperature_with_end_datetime",
    )
    platform.async_register_entity_service(
        SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD,
        {
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
        SERVICE_CLEAR_TEMPERATURE_SETTING,
        {},
        "_async_service_clear_temperature_setting",
    )
    return True
