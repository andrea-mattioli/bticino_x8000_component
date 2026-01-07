"""Number platform for Bticino X8000 configuration."""

import logging
from datetime import timedelta

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_UPDATE_INTERVAL,
    CONF_COOL_DOWN,
    CONF_DEBOUNCE,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
    MIN_COOL_DOWN,
    MAX_COOL_DOWN,
    MIN_DEBOUNCE,
    MAX_DEBOUNCE,
)
from .coordinator import BticinoCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 number platform."""
    coordinator: BticinoCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Instantiate the 3 configuration entities
    entities = [
        BticinoUpdateIntervalNumber(coordinator),
        BticinoCoolDownNumber(coordinator),
        BticinoDebounceNumber(coordinator),
    ]
    
    async_add_entities(entities)


class BticinoBaseNumber(CoordinatorEntity, NumberEntity):
    """Base class for Bticino configuration numbers."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX  # BOX is better for precise numerical input than a slider

    def __init__(self, coordinator: BticinoCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        # Unique ID is generated using the Entry ID to be globally unique
        self._attr_unique_id = f"{self._attr_key}_{coordinator.entry.entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link this entity to the 'Bticino Cloud Service' virtual device."""
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
        This ensures the User can change configuration (like increasing the interval)
        even when the API is down or rate-limited (Coordinator is failed).
        """
        return True

    async def _update_config_entry(self, key: str, value: float) -> None:
        """Helper to save the new value to the Config Entry options (disk)."""
        new_options = dict(self.coordinator.entry.options)
        new_options[key] = value
        
        await self.hass.config_entries.async_update_entry(
            self.coordinator.entry, 
            options=new_options
        )
        self.async_write_ha_state()


class BticinoUpdateIntervalNumber(BticinoBaseNumber):
    """
    Configuration entity to adjust the Normal Polling Interval.
    Default: 15 minutes.
    """
    _attr_name = "Update Interval"
    _attr_icon = "mdi:timer-cog"
    _attr_key = "bticino_update_interval"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = NumberDeviceClass.DURATION
    
    # Boundaries from const.py
    _attr_native_min_value = MIN_UPDATE_INTERVAL
    _attr_native_max_value = MAX_UPDATE_INTERVAL
    _attr_native_step = 1

    @property
    def native_value(self) -> float:
        """Return the current normal_interval in minutes."""
        return self.coordinator.normal_interval.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        new_minutes = int(value)
        _LOGGER.info("User changed Update Interval to %s minutes", new_minutes)

        # 1. Update Coordinator Memory
        new_delta = timedelta(minutes=new_minutes)
        self.coordinator.normal_interval = new_delta
        
        # 2. Apply immediately ONLY if not in Cool Down mode
        # If we are banned (Cool Down), we must respect the 60min wait.
        # The new interval will be applied automatically once the ban expires.
        if self.coordinator.update_interval != self.coordinator.cool_down_interval:
            self.coordinator.update_interval = new_delta

        # 3. Save to Disk
        await self._update_config_entry(CONF_UPDATE_INTERVAL, new_minutes)


class BticinoCoolDownNumber(BticinoBaseNumber):
    """
    Configuration entity to adjust the Cool Down Interval (Ban Wait Time).
    Default: 60 minutes.
    """
    _attr_name = "Cool Down Interval"
    _attr_icon = "mdi:timer-lock-open"
    _attr_key = "bticino_cool_down"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = NumberDeviceClass.DURATION
    
    # Boundaries from const.py
    _attr_native_min_value = MIN_COOL_DOWN
    _attr_native_max_value = MAX_COOL_DOWN
    _attr_native_step = 1

    @property
    def native_value(self) -> float:
        """Return the current cool_down_interval in minutes."""
        return self.coordinator.cool_down_interval.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        new_minutes = int(value)
        _LOGGER.info("User changed Cool Down Interval to %s minutes", new_minutes)

        # 1. Update Coordinator Memory
        new_delta = timedelta(minutes=new_minutes)
        self.coordinator.cool_down_interval = new_delta
        
        # 2. Apply immediately ONLY if currently in Cool Down mode
        # If we are currently waiting for a ban to expire, update the wait time.
        # (Note: This resets the timer, effectively restarting the wait, which is safer)
        if self.coordinator.update_interval.total_seconds() >= 600: # Heuristic: >10 min implies Cool Down
             self.coordinator.update_interval = new_delta

        # 3. Save to Disk
        await self._update_config_entry(CONF_COOL_DOWN, new_minutes)


class BticinoDebounceNumber(BticinoBaseNumber):
    """
    Configuration entity to adjust the Webhook Debounce time.
    Default: 1.0 second.
    """
    _attr_name = "Webhook Debounce"
    _attr_icon = "mdi:traffic-light"
    _attr_key = "bticino_webhook_debounce"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    
    # Boundaries from const.py
    _attr_native_min_value = MIN_DEBOUNCE
    _attr_native_max_value = MAX_DEBOUNCE
    _attr_native_step = 0.1  # Allow decimal precision

    @property
    def native_value(self) -> float:
        """Return the current debounce_time in seconds."""
        return self.coordinator.debounce_time

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        _LOGGER.info("User changed Webhook Debounce to %s seconds", value)

        # 1. Update Coordinator Memory
        self.coordinator.debounce_time = value
        
        # 2. Save to Disk
        await self._update_config_entry(CONF_DEBOUNCE, value)
