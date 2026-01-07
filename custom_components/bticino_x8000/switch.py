"""Switch platform for Bticino X8000 configuration."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_NOTIFY_ERRORS,
)
from .coordinator import BticinoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 switch platform."""
    coordinator: BticinoCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Instantiate the switch entity for controlling error notifications
    entities = [
        BticinoNotifyErrorsSwitch(coordinator),
    ]

    async_add_entities(entities)


class BticinoNotifyErrorsSwitch(CoordinatorEntity, SwitchEntity):
    """
    Configuration switch to enable/disable persistent error notifications.
    
    If ON: Rate Limit (429) errors will show a yellow notification in the HA Dashboard.
    If OFF: Errors are only logged to the system log (silent mode).
    """

    _attr_has_entity_name = True
    _attr_name = "Enable Error Notifications"
    _attr_icon = "mdi:bell-alert"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: BticinoCoordinator) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        # Unique ID generated from Entry ID to be globally unique
        self._attr_unique_id = f"bticino_notify_errors_{coordinator.entry.entry_id}"

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
        Users must be able to disable notifications even if the system is currently broken.
        """
        return True

    @property
    def is_on(self) -> bool:
        """Return True if notifications are enabled, False otherwise."""
        return self.coordinator.notify_errors

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable error notifications."""
        await self._update_notification_setting(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable error notifications."""
        await self._update_notification_setting(False)

    async def _update_notification_setting(self, enabled: bool) -> None:
        """Helper to update the setting in memory and persist it to disk."""
        _LOGGER.info("User changed Error Notifications to %s", "ON" if enabled else "OFF")

        # 1. Update Coordinator Memory (Immediate effect)
        self.coordinator.notify_errors = enabled
        
        # 2. Update Home Assistant State (UI Feedback)
        self.async_write_ha_state()

        # 3. Persist to Config Entry Options (Save to disk)
        new_options = dict(self.coordinator.entry.options)
        new_options[CONF_NOTIFY_ERRORS] = enabled
        
        await self.hass.config_entries.async_update_entry(
            self.coordinator.entry, 
            options=new_options
        )
