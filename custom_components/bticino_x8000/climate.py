"""Climate platform for Bticino X8000."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DEFAULT_MAX_TEMP, DEFAULT_MIN_TEMP, DOMAIN
from .coordinator import BticinoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 climate entities."""
    coordinator: BticinoCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    data = config_entry.data

    # We iterate over the stored config data, NOT the coordinator data.
    # This guarantees entities are created even if the API is unreachable at boot.
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        thermo_data = list(plant_data.values())[0]

        entities.append(
            BticinoX8000Climate(
                coordinator=coordinator,
                plant_id=plant_id,
                thermo_data=thermo_data,
            )
        )

    async_add_entities(entities)


class BticinoX8000Climate(CoordinatorEntity, ClimateEntity):
    """Bticino X8000 Climate Entity using Coordinator."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_target_temperature_step = 0.1
    _attr_has_entity_name = True
    _attr_name = None  # Use device name

    def __init__(
        self,
        coordinator: BticinoCoordinator,
        plant_id: str,
        thermo_data: dict[str, Any],
    ) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self._plant_id = plant_id
        self._topology_id = thermo_data.get("id")
        self._device_name = thermo_data.get("name")
        self._attr_unique_id = f"{self._topology_id}_climate"

        self._programs_name = thermo_data.get("programs", [])

        # Initialize attributes with default safe values to prevent AttributeError
        # if the coordinator data is not yet available.
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = HVACAction.OFF
        self._attr_current_temperature = None
        self._attr_target_temperature = None

        # Initial state calculation (will overwrite defaults if data exists)
        self._update_state_from_coordinator()

    @property
    def device_info(self):
        """Device info."""
        return {
            "identifiers": {(DOMAIN, self._topology_id)},
            "name": self._device_name,
            "manufacturer": "Legrand",
            "model": "X8000",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state_from_coordinator()
        self.async_write_ha_state()

    def _update_state_from_coordinator(self):
        """Parse data from coordinator."""
        # CRITICAL FIX: Check if coordinator.data is None.
        # This happens when the integration loads during a Rate Limit ban (Boot Loop Fix).
        # If we proceed without this check, we get "AttributeError: 'NoneType' object has no attribute 'get'".
        if self.coordinator.data is None:
            return

        # Get data specific for this thermostat
        data = self.coordinator.data.get(self._topology_id)

        if not data:
            return

        try:
            # 1. Temperature
            thermometer = data.get("thermometer", {}).get("measures", [{}])[0]
            val = thermometer.get("value")
            if val is not None:
                self._attr_current_temperature = float(val)

            # 2. Target Temp
            set_point = data.get("setPoint", {})
            val = set_point.get("value")
            if val is not None:
                self._attr_target_temperature = float(val)

            # 3. Humidity (Optional extra attribute)
            hygrometer = data.get("hygrometer", {}).get("measures", [{}])[0]
            # Not a standard climate attribute, usually ignored or needs custom property
            # self._attr_current_humidity = float(hygrometer.get("value", 0))

            # 4. Mode Logic
            mode = data.get("mode", "").lower()
            function = data.get("function", "").lower()
            load_state = data.get("loadState", "").lower()

            # HVAC Mode
            if mode == "automatic":
                self._attr_hvac_mode = HVACMode.AUTO
            elif mode == "off" or mode == "protection":
                self._attr_hvac_mode = HVACMode.OFF
            elif mode in ["manual", "boost"]:
                if function == "heating":
                    self._attr_hvac_mode = HVACMode.HEAT
                elif function == "cooling":
                    self._attr_hvac_mode = HVACMode.COOL

            # HVAC Action
            self._attr_hvac_action = HVACAction.IDLE
            if load_state == "active":
                if function == "heating":
                    self._attr_hvac_action = HVACAction.HEATING
                elif function == "cooling":
                    self._attr_hvac_action = HVACAction.COOLING
            elif load_state == "inactive":
                self._attr_hvac_action = HVACAction.IDLE
            elif mode == "off":
                self._attr_hvac_action = HVACAction.OFF

        except Exception as e:
            _LOGGER.error("Error parsing data for %s: %s", self._device_name, e)

    # ------------------------------------------------------------------
    # COMMANDS (Go through API Throttling)
    # ------------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        # Check safety before accessing data (in case this is called blindly)
        if self.coordinator.data is None:
            _LOGGER.warning(
                "Cannot set HVAC mode: Data not available (Rate Limit active)"
            )
            return

        # Read current function/program from coordinator data to preserve them
        curr_data = self.coordinator.data.get(self._topology_id, {})
        function = curr_data.get("function", "heating")
        programs = curr_data.get("programs", [{"number": 1}])
        current_program = programs[0]["number"] if programs else 1

        payload = {}

        if hvac_mode == HVACMode.AUTO:
            payload = {
                "function": function,
                "mode": "automatic",
                "programs": [{"number": current_program}],
            }
        elif hvac_mode == HVACMode.OFF:
            payload = {"function": function, "mode": "off"}
        elif hvac_mode in [HVACMode.HEAT, HVACMode.COOL]:
            # Determine function based on requested mode
            target_function = "heating" if hvac_mode == HVACMode.HEAT else "cooling"

            # Safety fallback if target_temp is None
            target_val = (
                self.target_temperature if self.target_temperature is not None else 20.0
            )

            payload = {
                "function": target_function,
                "mode": "manual",
                "setPoint": {"value": target_val, "unit": self.temperature_unit},
            }

        _LOGGER.info("Setting HVAC Mode for %s: %s", self._device_name, hvac_mode)

        await self.coordinator.api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )
        # Note: We do NOT refresh immediately. We wait for Webhook or next poll.
        # Optimistic update could be added here if desired.

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return

        if self.coordinator.data is None:
            _LOGGER.warning(
                "Cannot set temperature: Data not available (Rate Limit active)"
            )
            return

        curr_data = self.coordinator.data.get(self._topology_id, {})
        function = curr_data.get("function", "heating")

        payload = {
            "function": function,
            "mode": "manual",
            "setPoint": {"value": temp, "unit": self.temperature_unit},
        }

        _LOGGER.info("Setting Temperature for %s: %s", self._device_name, temp)

        await self.coordinator.api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)
