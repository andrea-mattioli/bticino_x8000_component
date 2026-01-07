"""Number platform for Bticino X8000 configuration."""

import logging
from datetime import timedelta

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COOL_DOWN,
    CONF_DEBOUNCE,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    MAX_COOL_DOWN,
    MAX_DEBOUNCE,
    MAX_UPDATE_INTERVAL,
    MIN_COOL_DOWN,
    MIN_DEBOUNCE,
    MIN_UPDATE_INTERVAL,
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
    _attr_mode = (
        NumberMode.BOX
    )  # BOX is better for precise numerical input than a slider

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

    @property
    def extra_state_attributes(self) -> dict:
        """
        IMPROVEMENT: Add debug attributes.
        This allows troubleshooting configuration changes (timestamps and raw values)
        without needing to check the logs.
        """
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return {}

        return {
            "_last_set_value_native": self.native_value,
            "_last_debug_timestamp": dt_util.utcnow().isoformat(),
            "_active_interval_minutes": self.coordinator.update_interval.total_seconds()
            / 60,
        }

    async def _update_config_entry(
        self, key: str, value: float, force_refresh: bool = False
    ) -> None:
        """
        Helper to save the new value to the Config Entry options (disk).

        Args:
            key: Config key to update.
            value: New value.
            force_refresh: If True, triggers an API refresh even if in Cool Down mode.
        """
        new_options = dict(self.coordinator.entry.options)
        new_options[key] = value

        # self.hass.config_entries.async_update_entry returns a bool, not a coroutine.
        self.hass.config_entries.async_update_entry(
            self.coordinator.entry, options=new_options
        )

        self.async_write_ha_state()

        # IMPROVEMENT: Smart Refresh Logic
        # 1. If force_refresh is True (e.g. changing Cool Down settings), we refresh immediately.
        # 2. If NOT in Cool Down, we refresh to apply new normal interval.
        # 3. If in Cool Down and force_refresh is False, we skip to avoid useless API calls.
        in_cool_down = getattr(self.coordinator, "in_cool_down", False)

        if force_refresh or not in_cool_down:
            _LOGGER.debug(
                "Triggering refresh. Force: %s, In CoolDown: %s",
                force_refresh,
                in_cool_down,
            )
            await self.coordinator.async_request_refresh()


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
        """
        Return the ACTIVE polling interval in minutes.
        We return 'self.coordinator.update_interval' instead of 'normal_interval'.
        If the system is in Cool Down (Ban), this will correctly show 60 minutes
        instead of the configured 15, reflecting the real system behavior.
        """
        return self.coordinator.update_interval.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        new_minutes = int(value)
        _LOGGER.info("User changed Update Interval to %s minutes", new_minutes)

        # 1. Update Coordinator Memory
        new_delta = timedelta(minutes=new_minutes)
        self.coordinator.normal_interval = new_delta

        # 2. Apply immediately ONLY if not in Cool Down mode
        # Use safer attribute check for 'in_cool_down' using getattr
        in_cool_down = getattr(self.coordinator, "in_cool_down", False)

        if not in_cool_down:
            self.coordinator.update_interval = new_delta

        # 3. Save to Disk
        # We DO NOT force refresh here if banned, as normal interval doesn't matter during a ban.
        await self._update_config_entry(
            CONF_UPDATE_INTERVAL, new_minutes, force_refresh=False
        )


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
        # Use specific boolean flag.
        in_cool_down = getattr(self.coordinator, "in_cool_down", False)

        if in_cool_down:
            self.coordinator.update_interval = new_delta

        # 3. Save to Disk and FORCE REFRESH
        # If the user changes this value, they likely want to shorten the wait
        # and try again immediately, so we bypass the cool down check for the refresh.
        await self._update_config_entry(CONF_COOL_DOWN, new_minutes, force_refresh=True)


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

    # Force display precision to 1 decimal place (e.g. "1.0")
    _attr_native_precision = 1

    @property
    def native_value(self) -> float:
        """Return the current debounce_time in seconds."""
        return self.coordinator.debounce_time

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        # Ensure proper rounding for float steps.
        value = round(value, 1)
        _LOGGER.info("User changed Webhook Debounce to %s seconds", value)

        # 1. Update Coordinator Memory
        self.coordinator.debounce_time = value

        # 2. Save to Disk
        await self._update_config_entry(CONF_DEBOUNCE, value, force_refresh=False)
