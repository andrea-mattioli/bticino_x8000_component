"""Sensor platform for Bticino X8000 using DataUpdateCoordinator."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
    EntityCategory,  # Added for diagnostic sensor
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType  # Added for Service Device
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import BticinoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 sensors."""
    coordinator: BticinoCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Debug log to indicate the setup start
    _LOGGER.debug("Setting up Bticino X8000 sensor platform")

    # Use config data to iterate over selected thermostats.
    # This ensures entities are created even if the coordinator is initially empty.
    data = dict(config_entry.data)
    entities = []
    
    selected_thermostats = data.get("selected_thermostats", [])
    _LOGGER.debug("Found %d selected thermostats in configuration", len(selected_thermostats))

    for plant_data in selected_thermostats:
        plant_id = list(plant_data.keys())[0]
        thermo_data = list(plant_data.values())[0]

        topology_id = thermo_data.get("id")
        thermostat_name = thermo_data.get("name")
        programs = thermo_data.get("programs", [])
        
        _LOGGER.debug("Creating sensors for thermostat: %s (ID: %s)", thermostat_name, topology_id)

        # Create standard sensors
        sensors_classes = [
            BticinoTemperatureSensor,
            BticinoHumiditySensor,
            BticinoTargetTemperatureSensor,
            BticinoModeSensor,
            BticinoStatusSensor,
            BticinoBoostTimeRemainingSensor,
        ]

        for sensor_class in sensors_classes:
            entities.append(
                sensor_class(
                    coordinator, plant_id, topology_id, thermostat_name
                )
            )

        # Create Program sensor (needs extra argument for program list)
        entities.append(
            BticinoProgramSensor(
                coordinator, plant_id, topology_id, thermostat_name, programs
            )
        )
    
    # --- NEW: Singleton API Counter Sensor (Engineering Solution) ---
    # This sensor is now independent of physical thermostats.
    # It creates its own "Virtual Hub" device.
    entities.append(BticinoApiCountSensor(coordinator))
    # ---------------------------------------------------------------

    _LOGGER.debug("Total entities to add: %d", len(entities))

    # CRITICAL FIX: Removed 'update_before_add=True'
    # This prevents the sensors from forcing an API call immediately during initialization.
    # If the system is in "Cool Down" (Rate Limit) mode, forcing an update here would
    # break the silence and trigger another error notification.
    # Entities will start as 'Unavailable' until the first successful Coordinator update.
    async_add_entities(entities)


class BticinoBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Bticino sensors."""

    def __init__(
        self,
        coordinator: BticinoCoordinator,
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the sensor."""
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
            via_device=(DOMAIN, self._plant_id),
        )

    @property
    def _thermostat_data(self) -> dict[str, Any]:
        """Retrieve data specific to this thermostat from coordinator."""
        # CRITICAL FIX: Safety check for None data.
        # When the integration loads during a Rate Limit ban (fixed boot loop),
        # self.coordinator.data is None. We must return an empty dict to prevent crashes.
        if self.coordinator.data is None:
            return {}

        # Coordinator data structure is flat: {topology_id: {data...}}
        return self.coordinator.data.get(self._topology_id, {}) or {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # This method is called automatically when the coordinator receives new data.
        # We log the update here to provide visibility into the data flow.
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Entity %s (%s) received data update from coordinator",
                self.name,
                self.unique_id,
            )
        # Call the parent method to actually update the state in Home Assistant
        super()._handle_coordinator_update()

    def _get_nested_value(self, path: list[str | int], cast_type: type = str) -> Any:
        """Helper to extract values deeply nested in the dictionary."""
        data = self._thermostat_data
        try:
            for key in path:
                if isinstance(data, list):
                    # Handle list access if key is an integer index
                    # Ensure key is actually an int before using it as index
                    if isinstance(key, int):
                        idx = key
                        if 0 <= idx < len(data):
                            data = data[idx]
                        else:
                            return None
                    else:
                        return None
                elif isinstance(data, dict):
                    data = data.get(str(key))
                else:
                    return None

                if data is None:
                    return None

            return cast_type(data)
        except (ValueError, TypeError, IndexError):
            return None


class BticinoTemperatureSensor(BticinoBaseSensor):
    """Sensor for current temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Temperature"

    def __init__(self, coordinator, plant_id, topology_id, thermostat_name):
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"bticino_x8000_{topology_id}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        # Path: thermometer -> measures -> [0] -> value
        return self._get_nested_value(["thermometer", "measures", 0, "value"], float)


class BticinoHumiditySensor(BticinoBaseSensor):
    """Sensor for current humidity."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Humidity"

    def __init__(self, coordinator, plant_id, topology_id, thermostat_name):
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"bticino_x8000_{topology_id}_humidity"

    @property
    def native_value(self) -> float | None:
        """Return the humidity."""
        # Path: hygrometer -> measures -> [0] -> value
        return self._get_nested_value(["hygrometer", "measures", 0, "value"], float)


class BticinoTargetTemperatureSensor(BticinoBaseSensor):
    """Sensor for target temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    # Target temperature is a setting, not a measurement
    _attr_state_class = None
    _attr_name = "Target Temperature"

    def __init__(self, coordinator, plant_id, topology_id, thermostat_name):
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"bticino_x8000_{topology_id}_target_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the target temperature."""
        # Path: setPoint -> value
        return self._get_nested_value(["setPoint", "value"], float)


class BticinoProgramSensor(BticinoBaseSensor):
    """Sensor for current program."""

    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Current Program"

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
        self._attr_unique_id = f"bticino_x8000_{topology_id}_current_program"
        self._programs = programs

    @property
    def native_value(self) -> str | None:
        """Return the name of the current program."""
        # API returns: programs -> [0] -> number
        prog_number = self._get_nested_value(["programs", 0, "number"], int)

        if prog_number is not None:
            # Match number to static name from config
            for prog in self._programs:
                if int(prog.get("number", -1)) == prog_number:
                    return prog.get("name")
            return f"Program {prog_number}"

        return None


class BticinoModeSensor(BticinoBaseSensor):
    """Sensor for current mode."""

    _attr_icon = "mdi:thermostat"
    # Using SensorDeviceClass.ENUM would require defined options,
    # keeping as generic string for safety against API changes.
    _attr_name = "Mode"

    def __init__(self, coordinator, plant_id, topology_id, thermostat_name):
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"bticino_x8000_{topology_id}_mode"

    @property
    def native_value(self) -> str | None:
        """Return the current mode (e.g., automatic, manual, boost)."""
        val = self._thermostat_data.get("mode")
        return val.lower() if val else None


class BticinoStatusSensor(BticinoBaseSensor):
    """Sensor for current status (active/inactive)."""

    _attr_icon = "mdi:power"
    _attr_name = "Status"

    def __init__(self, coordinator, plant_id, topology_id, thermostat_name):
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"bticino_x8000_{topology_id}_status"

    @property
    def native_value(self) -> str | None:
        """Return the load state (heating active or not)."""
        val = self._thermostat_data.get("loadState")
        return val.lower() if val else None


class BticinoBoostTimeRemainingSensor(BticinoBaseSensor):
    """Sensor for boost time remaining."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Boost Time Remaining"

    def __init__(self, coordinator, plant_id, topology_id, thermostat_name):
        super().__init__(coordinator, plant_id, topology_id, thermostat_name)
        self._attr_unique_id = f"bticino_x8000_{topology_id}_boost_time_remaining"

    @property
    def native_value(self) -> int | None:
        """Return remaining boost time in minutes."""
        data = self._thermostat_data
        mode = data.get("mode", "").lower()

        # Check mode first. If not boost, return 0 (UX choice).
        if mode == "boost" and "activationTime" in data:
            activation_time = data["activationTime"]
            try:
                # Parse end time from "start/end" or just "end"
                if "/" in activation_time:
                    end_time_str = activation_time.split("/")[1]
                else:
                    end_time_str = activation_time

                end_time = dt_util.parse_datetime(end_time_str)
                if end_time:
                    # Compare UTC with UTC to avoid timezone errors
                    now = dt_util.utcnow()
                    end_time = dt_util.as_utc(end_time)
                    remaining_seconds = (end_time - now).total_seconds()
                    return max(0, int(remaining_seconds / 60))
            except (ValueError, TypeError, IndexError):
                pass

        return 0

# --- SPECIAL DIAGNOSTIC SENSOR (Engineering Solution) ---

class BticinoApiCountSensor(CoordinatorEntity, SensorEntity):
    """
    Diagnostic sensor for API usage.
    
    Architectural Note:
    This sensor is NOT attached to a specific thermostat.
    It creates a separate Virtual Device ("Bticino Cloud Service") 
    representing the account/gateway connection.
    """

    _attr_icon = "mdi:api"
    _attr_name = "API Call Count"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "calls"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BticinoCoordinator):
        super().__init__(coordinator)
        # Use the Config Entry ID to generate a truly unique ID for this instance
        self._attr_unique_id = f"bticino_api_count_{coordinator.entry.entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        """
        Create a Virtual Device for the Cloud Service.
        This separates infrastructure metrics from climate devices.
        """
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Bticino Cloud Service",
            manufacturer="Legrand",
            model="API Gateway",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """
        OVERRIDE: Always available.
        
        This sensor reads a local internal counter (coordinator.api.call_count).
        It does NOT depend on a successful API response. 
        It must remain visible even during Rate Limit bans (when coordinator fails)
        so the user can diagnose the cause of the ban.
        """
        return True

    @property
    def native_value(self) -> int:
        """Return the total number of API calls made since boot."""
        return self.coordinator.api.call_count
