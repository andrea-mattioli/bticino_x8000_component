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
        return self.coordinator.data.get(self._topology_id, {})


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

    @property
    def current_option(self) -> str | None:
        """Return current boost status calculated from coordinator data."""
        data = self._thermostat_data
        mode = data.get("mode", "").lower()

        if mode == "boost" and "activationTime" in data:
            activation_time = data["activationTime"]
            
            # Logic to guess original boost duration based on time remaining or start/end
            if "/" in activation_time:
                # Format: start/end
                times = activation_time.split("/")
                if len(times) == 2:
                    start = dt_util.parse_datetime(times[0])
                    end = dt_util.parse_datetime(times[1])
                    if start and end:
                        duration = int((end - start).total_seconds() / 60)
                        if duration <= 45: return "30"
                        if duration <= 75: return "60"
                        return "90"
            else:
                # Only end time provided
                end = dt_util.parse_datetime(activation_time)
                if end:
                    now = dt_util.now()
                    end = dt_util.as_utc(end)
                    remaining = int((end - now).total_seconds() / 60)
                    # Heuristic estimation
                    if remaining > 0:
                        if remaining <= 30: return "30"
                        if remaining <= 60: return "60"
                        return "90"
        
        return "off"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option == self.current_option:
            return

        if option == "off":
            # Revert to automatic program
            # We default to program 1 or whatever was active (difficult to know previous state)
            # Safe bet: Automatic mode with first program
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
            # Calculate times locally to send to API
            now = dt_util.now()
            end_time = now + dt_util.timedelta(minutes=int(option))
            
            # Format: YYYY-MM-DDTHH:MM:SS
            now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
            end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S")
            
            # Determine setpoint (Max for heating, Min for cooling)
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
                    "unit": "C" # API expects simple unit string usually
                }
            }
            _LOGGER.info("Activating boost %s min for %s", option, self._thermostat_name)

        # Send command via Coordinator API (Protected by Rate Limiter)
        await self.coordinator.api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )


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

    @property
    def current_option(self) -> str | None:
        """Return current program."""
        data = self._thermostat_data
        mode = data.get("mode", "").lower()

        # Only relevant if in automatic mode, though API reports program in array anyway
        # if mode == "automatic":
        current_programs = data.get("programs", [])
        if current_programs:
            prog_num = int(current_programs[0].get("number", 0))
            for prog in self._programs:
                if int(prog["number"]) == prog_num:
                    return prog["name"]
        
        return None

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

        function = self._thermostat_data.get("function", "heating")
        
        payload = {
            "function": function,
            "mode": "automatic",
            "programs": [{"number": program_number}]
        }
        
        _LOGGER.info("Setting program %s for %s", option, self._thermostat_name)

        await self.coordinator.api.set_chronothermostat_status(
            self._plant_id, self._topology_id, payload
        )
