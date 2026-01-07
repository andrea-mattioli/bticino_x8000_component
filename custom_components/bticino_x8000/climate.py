"""Climate platform for Bticino X8000."""

import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    PRESET_NONE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, DEFAULT_MAX_TEMP, DEFAULT_MIN_TEMP
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
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_target_temperature_step = 0.1
    _attr_has_entity_name = True
    _attr_name = None # Use device name

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
        
        # Initialize Preset Modes: Boost + Programs from config
        self._attr_preset_modes = [PRESET_NONE, "Boost"]
        if self._programs_name:
            self._attr_preset_modes.extend([p.get("name") for p in self._programs_name])
        
        # Initialize attributes with safe defaults
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = HVACAction.OFF
        self._attr_preset_mode = PRESET_NONE
        self._attr_current_temperature = None
        self._attr_target_temperature = None
        
        # Debug storage
        self._last_command_payload = {}
        self._last_command_success = None 
        
        # Initial state calculation
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Add raw data for debugging.
        Includes Boost end time if active.
        """
        attrs = {
            "_raw_last_command": self._last_command_payload,
            "_last_command_success": self._last_command_success,
            "_topology_id": self._topology_id,
        }
        
        # IMPROVEMENT (Review Pt. 3): Add Boost end time if available
        if self._attr_preset_mode == "Boost" and self.coordinator.data:
            data = self.coordinator.data.get(self._topology_id, {})
            act_time = data.get("activationTime")
            if act_time:
                # Clean up format (sometimes it is 'start/end', we want end)
                attrs["_boost_end_time"] = act_time.split("/")[-1] if "/" in act_time else act_time
                
        if _LOGGER.isEnabledFor(logging.DEBUG):
            return attrs
        return {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state_from_coordinator()
        self.async_write_ha_state()

    def _update_state_from_coordinator(self):
        """Parse data from coordinator."""
        if self.coordinator.data is None:
            return

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
            
            # 3. Mode Logic
            mode = data.get("mode", "").lower()
            function = data.get("function", "").lower()
            load_state = data.get("loadState", "").lower()

            # HVAC Mode & Preset Mode
            # IMPROVEMENT (Review Pt. 2): Strictly reset preset if not in a preset-compatible mode
            self._attr_preset_mode = PRESET_NONE
            
            if mode == "automatic":
                self._attr_hvac_mode = HVACMode.AUTO
                current_prog_num = data.get("programs", [{}])[0].get("number")
                if current_prog_num is not None:
                     for prog in self._programs_name:
                         if prog.get("number") == current_prog_num:
                             self._attr_preset_mode = prog.get("name")
                             break
            elif mode == "off" or mode == "protection":
                self._attr_hvac_mode = HVACMode.OFF
            elif mode == "boost":
                self._attr_hvac_mode = HVACMode.HEAT if function == "heating" else HVACMode.COOL
                self._attr_preset_mode = "Boost"
            elif mode == "manual":
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
    # COMMANDS
    # ------------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if self.coordinator.data is None:
            _LOGGER.warning("Cannot set HVAC mode: Data not available (Rate Limit active)")
            return

        if getattr(self.coordinator, "in_cool_down", False):
            _LOGGER.warning("Command ignored: Integration is in Cool Down (Rate Limit)")
            return

        curr_data = self.coordinator.data.get(self._topology_id, {})
        function = curr_data.get("function", "heating")
        programs = curr_data.get("programs", [{"number": 1}])
        current_program = programs[0]["number"] if programs else 1
        
        payload = {}
        
        if hvac_mode == HVACMode.AUTO:
            payload = {
                "function": function,
                "mode": "automatic",
                "programs": [{"number": current_program}]
            }
        elif hvac_mode == HVACMode.OFF:
            payload = {
                "function": function,
                "mode": "off"
            }
        elif hvac_mode in [HVACMode.HEAT, HVACMode.COOL]:
            target_function = "heating" if hvac_mode == HVACMode.HEAT else "cooling"
            target_val = self.target_temperature if self.target_temperature is not None else 20.0
            
            payload = {
                "function": target_function,
                "mode": "manual",
                "setPoint": {
                    "value": target_val, 
                    "unit": self.temperature_unit
                }
            }

        _LOGGER.info("Setting HVAC Mode for %s: %s", self._device_name, hvac_mode)
        self._last_command_payload = payload
        self._last_command_success = False
        
        try:
            await self.coordinator.api.set_chronothermostat_status(
                self._plant_id, self._topology_id, payload
            )
            
            self._last_command_success = True

            # Optimistic State Update
            self._attr_hvac_mode = hvac_mode
            if hvac_mode == HVACMode.AUTO:
                self._attr_preset_mode = PRESET_NONE # Or try to keep current program name
            elif hvac_mode == HVACMode.OFF:
                self._attr_preset_mode = PRESET_NONE
                self._attr_hvac_action = HVACAction.OFF
            else:
                self._attr_preset_mode = PRESET_NONE
            
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error("Failed to set HVAC mode: %s", e)
            self._last_command_success = False
            # Revert on Failure
            self._update_state_from_coordinator()
            self.async_write_ha_state()
        
        self.coordinator.notify_listeners_only()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return

        if self.coordinator.data is None:
             _LOGGER.warning("Cannot set temperature: Data not available (Rate Limit active)")
             return
             
        if getattr(self.coordinator, "in_cool_down", False):
            _LOGGER.warning("Command ignored: Integration is in Cool Down (Rate Limit)")
            return

        curr_data = self.coordinator.data.get(self._topology_id, {})
        function = curr_data.get("function", "heating")
        
        payload = {
            "function": function,
            "mode": "manual",
            "setPoint": {
                "value": temp,
                "unit": self.temperature_unit
            }
        }
        
        _LOGGER.info("Setting Temperature for %s: %s", self._device_name, temp)
        self._last_command_payload = payload
        self._last_command_success = False
        
        try:
            await self.coordinator.api.set_chronothermostat_status(
                self._plant_id, self._topology_id, payload
            )

            self._last_command_success = True

            # Optimistic State Update
            self._attr_target_temperature = temp
            
            # Setting temp forces manual mode usually
            if function == "heating":
                self._attr_hvac_mode = HVACMode.HEAT
            elif function == "cooling":
                self._attr_hvac_mode = HVACMode.COOL
            self._attr_preset_mode = PRESET_NONE
            
            # IMPROVEMENT (Review Pt. 1): Optimistic HVAC Action Inference
            # If target > current, assume HEATING. If target < current, assume COOLING.
            # This makes the UI feel instantly responsive.
            if self._attr_current_temperature is not None:
                if temp > self._attr_current_temperature:
                    self._attr_hvac_action = HVACAction.HEATING
                elif temp < self._attr_current_temperature:
                    self._attr_hvac_action = HVACAction.COOLING
                else:
                    self._attr_hvac_action = HVACAction.IDLE
            
            self.async_write_ha_state()

        except Exception as e:
             _LOGGER.error("Failed to set temperature: %s", e)
             self._last_command_success = False
             # Revert on Failure
             self._update_state_from_coordinator()
             self.async_write_ha_state()
        
        self.coordinator.notify_listeners_only()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode (Boost or Program)."""
        if self.coordinator.data is None:
            _LOGGER.warning("Cannot set Preset: Data not available")
            return

        if getattr(self.coordinator, "in_cool_down", False):
            _LOGGER.warning("Command ignored: Integration is in Cool Down")
            return

        curr_data = self.coordinator.data.get(self._topology_id, {})
        function = curr_data.get("function", "heating")

        payload = {}

        if preset_mode == PRESET_NONE:
            target_val = self.target_temperature if self.target_temperature else 20.0
            payload = {
                "function": function,
                "mode": "manual",
                "setPoint": {"value": target_val, "unit": self.temperature_unit}
            }
        elif preset_mode == "Boost":
            payload = {
                "function": function,
                "mode": "boost",
                "setPoint": {
                    "value": self.target_temperature if self.target_temperature else 21.0, 
                    "unit": self.temperature_unit
                }
            }
        else:
            prog_number = None
            for prog in self._programs_name:
                if prog.get("name") == preset_mode:
                    prog_number = prog.get("number")
                    break
            
            if prog_number:
                payload = {
                    "function": function,
                    "mode": "automatic",
                    "programs": [{"number": prog_number}]
                }
            else:
                _LOGGER.warning("Unknown preset mode: %s", preset_mode)
                return

        _LOGGER.info("Setting Preset %s for %s", preset_mode, self._device_name)
        self._last_command_payload = payload
        self._last_command_success = False

        try:
            await self.coordinator.api.set_chronothermostat_status(
                self._plant_id, self._topology_id, payload
            )
            
            self._last_command_success = True

            # Optimistic Update
            self._attr_preset_mode = preset_mode
            if preset_mode == "Boost":
                pass
            elif preset_mode != PRESET_NONE:
                self._attr_hvac_mode = HVACMode.AUTO
            
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error("Failed to set preset mode: %s", e)
            self._last_command_success = False
            # Revert on Failure
            self._update_state_from_coordinator()
            self.async_write_ha_state()

        self.coordinator.notify_listeners_only()

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)