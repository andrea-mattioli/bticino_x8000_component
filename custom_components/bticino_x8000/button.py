"""Button platform for Bticino X8000 configuration."""

import logging

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BticinoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 button platform."""
    coordinator: BticinoCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Instantiate the button entity for manual troubleshooting
    entities = [
        BticinoForceTokenButton(coordinator),
    ]

    async_add_entities(entities)


class BticinoForceTokenButton(CoordinatorEntity, ButtonEntity):
    """
    Button entity to force a manual Token Refresh.
    
    Useful for troubleshooting:
    If the integration stops updating but doesn't show specific errors (or shows 401s that don't auto-fix),
    pressing this button forces a complete re-authentication flow against the Legrand cloud.
    """

    _attr_has_entity_name = True
    _attr_name = "Force Token Refresh"
    _attr_icon = "mdi:key-refresh"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = ButtonDeviceClass.RESTART  # 'RESTART' conveys the idea of resetting a connection

    def __init__(self, coordinator: BticinoCoordinator) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        # Unique ID generated from Entry ID to be globally unique
        self._attr_unique_id = f"bticino_force_token_{coordinator.entry.entry_id}"

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
        CRITICAL: If the API is broken (Coordinator Failed), the user MUST be able 
        to press this button to try and fix the Token!
        """
        return True

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("User pressed 'Force Token Refresh' button.")
        
        # Call the public method we added to the coordinator
        await self.coordinator.async_force_token_refresh()
