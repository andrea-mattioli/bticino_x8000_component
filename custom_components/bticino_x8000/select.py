"""Select entities for Bticino X8000 using DataUpdateCoordinator."""

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
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
    """Set up Bticino X8000 select entities."""
    coordinator: BticinoCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    data = dict(config_entry.data)
    entities = []

    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        thermo_data = list(plant_data.values())[0]

        topology_id = thermo_data.get("id")
        thermostat_name = thermo_data.get("name")
        programs = thermo_data.get("programs", [])

        # Program Select
        if programs:
            entities.append(
                BticinoProgramSelect(
                    coordinator, plant_id, topology_id, thermostat_name, programs
                )
            )

        # Boost Select
        entities.append(
            BticinoBoostSelect(
                coordinator, plant_id, topology_id, thermostat_name, programs
            )
        )

    async_add_entities(entities)


class BticinoBaseSelect(CoordinatorEntity, SelectEntity):
    """Base class for select entities."""

    def __init__(
        self,
        coordinator: BticinoCoordinator,
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._plant_id = plant_id
        self._topology_id = topology_id
        self._thermostat_name = thermostat_name
        self._attr_has_entity_name = True
        # Initialize current option to None
        self._attr_current_option = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topology_id)},
            name=self._thermostat_name,
            manufacturer="Legrand",
            model="X8000",
        )

    @property
    def _thermostat_data(self) -> dict[str, Any]:
        """Get data from coordinator."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._topology_id, {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        IMPROVEMENT: Add raw data for debugging.
        Consistent with other platforms.
        """
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return {}
            
        return {
            "_raw_mode": self._thermostat_data.get("mode"),
            "_raw_programs": self._thermostat_data.get("programs"),
            "_last_selected": self.current_option,
            "_topology_id": self._topology_id,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state_from_coordinator()
        self.async_write_ha_state()
    
    def _update_state_from_coordinator(self) -> None:
        """To be implemented by subclasses."""
        pass


class BticinoBoostSelect(BticinoBaseSelect):
    """Select entity for boost control."""

    _attr_options = ["off", "30", "60", "90"]
    _attr_icon = "mdi:play-speed"
    _attr_name = "Boost"

    def __init__(
        self,
        coordinator,
        plant_id,
        topology_id,
        thermostat_name,
        programs,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"{DOMAIN}_{topology_id}_boost"
        self._programs = programs
        # Initial state calculation
        self._update_state_from_coordinator()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        IMPROVEMENT: Add boost specific attributes.
        Exposes the end time of the boost if active, matching climate.py behavior.
        """
        # Get base attributes (debug info)
        attrs = super().extra_state_attributes
        
        # Add Boost specific info if active
        if self._attr_current_option != "off" and self._thermostat_data:
            act_time = self._thermostat_data.get("activationTime")
            if act_time and "/" in act_time:
                # Format is usually start_time/end_time, we extract end_time
                attrs["_boost_end_time"] = act_time.split("/")[-1]
                
        return attrs

    def _update_state_from_coordinator(self) -> None:
        """Calculate current boost status from coordinator data."""
        data = self._thermostat_data
        if not data:
            return

        mode = data.get("mode", "").lower()

        if mode == "boost" and "activationTime" in data:
            activation_time = data["activationTime"]
            
            # IMPROVEMENT: Robust Parsing with try/except
            try:
                # Logic to guess original boost duration based on time remaining or start/end
                if "/" in activation_time:
                    # Format: start/end
                    times = activation_time.split("/")
                    if len(times) == 2:
                        start = dt_util.parse_datetime(times[0])
                        end = dt_util.parse_datetime(times[1])
                        if start and end:
                            duration = int((end - start).total_seconds() / 60)
                            if duration <= 45: self._attr_current_option = "30"
                            elif duration <= 75: self._attr_current_option = "60"
                            else: self._attr_current_option = "90"
                            return
                else:
                    # Only end time provided
                    end = dt_util.parse_datetime(activation_time)
                    if end:
                        now = dt_util.now()
                        end = dt_util.as_utc(end)
                        remaining = int((end - now).total_seconds() / 60)
                        # Heuristic estimation
                        if remaining > 0:
                            if remaining <= 30: self._attr_current_option = "30"
                            elif remaining <= 60: self._attr_current_option = "60"
                            else: self._attr_current_option = "90"
                            return
            except Exception as e:
                _LOGGER.warning("Error parsing boost time '%s': %s", activation_time, e)
        
        self._attr_current_option = "off"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option == self.current_option:
            return

        # IMPROVEMENT: Cooldown Protection
        if getattr(self.coordinator, "in_cool_down", False):
            _LOGGER.warning("Command ignored: Integration is in Cool Down (Rate Limit)")
            return

        payload = {}

        if option == "off":
            # Revert to automatic program
            program_number = 1
            if self._programs:
                program_number = self._programs[0]["number"]

            # Try to keep current function (heating/cooling)
            function = self._thermostat_data.get("function", "heating")
            
            payload = {
                "function": function,
                "mode": "automatic",
                "programs": [{"number": program_number}]
            }
            _LOGGER.info("Turning off boost for %s", self._thermostat_name)
        else:
            # Activate Boost
            now = dt_util.now()
            end_time = now + dt_util.timedelta(minutes=int(option))
            
            now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
            end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S")
            
            function = self._thermostat_data.get("function", "heating")
            set_point = DEFAULT_MAX_TEMP
            if function == "cooling":
                set_point = DEFAULT_MIN_TEMP

            payload = {
                "function": function,
                "mode": "boost",
                "activationTime": f"{now_str}/{end_str}",
                "setPoint": {
                    "value": set_point,
                    "unit": "C"
                }
            }
            _LOGGER.info("Activating boost %s min for %s", option, self._thermostat_name)

        # IMPROVEMENT: Optimistic Update
        self._attr_current_option = option
        self.async_write_ha_state()

        try:
            # Send command via Coordinator API
            await self.coordinator.api.set_chronothermostat_status(
                self._plant_id, self._topology_id, payload
            )
        except Exception as e:
            _LOGGER.error("Failed to set boost option: %s", e)
            # IMPROVEMENT: Revert on Failure
            self._update_state_from_coordinator()
            self.async_write_ha_state()
        
        # Update diagnostic sensors immediately
        self.coordinator.notify_listeners_only()


class BticinoProgramSelect(BticinoBaseSelect):
    """Select entity for thermostat program."""

    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Program"

    def __init__(
        self,
        coordinator,
        plant_id,
        topology_id,
        thermostat_name,
        programs,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"{DOMAIN}_{topology_id}_program"
        self._programs = programs
        self._attr_options = [prog["name"] for prog in programs]
        # Initial state calculation
        self._update_state_from_coordinator()

    def _update_state_from_coordinator(self) -> None:
        """Calculate current program from coordinator data."""
        data = self._thermostat_data
        if not data:
            return

        current_programs = data.get("programs", [])
        if current_programs:
            try:
                prog_num = int(current_programs[0].get("number", 0))
                for prog in self._programs:
                    if int(prog["number"]) == prog_num:
                        self._attr_current_option = prog["name"]
                        return
            except (ValueError, TypeError):
                pass
        
        self._attr_current_option = None

    async def async_select_option(self, option: str) -> None:
        """Change the selected program."""
        # Find number for name
        program_number = None
        for prog in self._programs:
            if prog["name"] == option:
                program_number = prog["number"]
                break
        
        if program_number is None:
            _LOGGER.error("Program %s not found", option)
            return

        # IMPROVEMENT: Cooldown Protection
        if getattr(self.coordinator, "in_cool_down", False):
            _LOGGER.warning("Command ignored: Integration is in Cool Down (Rate Limit)")
            return

        function = self._thermostat_data.get("function", "heating")
        
        payload = {
            "function": function,
            "mode": "automatic",
            "programs": [{"number": program_number}]
        }
        
        _LOGGER.info("Setting program %s for %s", option, self._thermostat_name)

        # IMPROVEMENT: Optimistic Update
        self._attr_current_option = option
        self.async_write_ha_state()

        try:
            await self.coordinator.api.set_chronothermostat_status(
                self._plant_id, self._topology_id, payload
            )
        except Exception as e:
            _LOGGER.error("Failed to set program: %s", e)
            # IMPROVEMENT: Revert on Failure
            self._update_state_from_coordinator()
            self.async_write_ha_state()

        # Update diagnostic sensors immediately
        self.coordinator.notify_listeners_only()