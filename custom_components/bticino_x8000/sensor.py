"""Sensor platform for Bticino X8000."""

# pylint: disable=duplicate-code

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(  # pylint: disable=too-many-locals
    hass: HomeAssistant,  # pylint: disable=unused-argument
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 sensors."""
    data = dict(config_entry.data)
    entities: list[SensorEntity] = []

    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        thermo_data = list(plant_data.values())[0]

        topology_id = thermo_data.get("id")
        thermostat_name = thermo_data.get("name")

        # Temperatura attuale
        entities.append(
            BticinoTemperatureSensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
            )
        )

        # Umidità attuale
        entities.append(
            BticinoHumiditySensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
            )
        )

        # Temperatura target
        entities.append(
            BticinoTargetTemperatureSensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
            )
        )

        # Programma corrente
        programs = thermo_data.get("programs", [])
        entities.append(
            BticinoProgramSensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
                programs=programs,
            )
        )

        # Mode
        entities.append(
            BticinoModeSensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
            )
        )

        # Status
        entities.append(
            BticinoStatusSensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
            )
        )

        # Boost time remaining
        entities.append(
            BticinoBoostTimeRemainingSensor(
                data=data,
                plant_id=plant_id,
                topology_id=topology_id,
                thermostat_name=thermostat_name,
            )
        )

        _LOGGER.debug("Created %d sensors for %s", 7, thermostat_name)

    async_add_entities(entities, update_before_add=False)

    # Sensors will be populated by webhook events from climate entity
    # No additional API calls needed


class BticinoBaseSensor(SensorEntity):
    """Base class for Bticino sensors."""

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the sensor."""
        self._data = data
        self._plant_id = plant_id
        self._topology_id = topology_id
        self._thermostat_name = thermostat_name
        self._attr_should_poll = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link with climate entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topology_id)},
            name=self._thermostat_name,
            manufacturer="Legrand",
            model="X8000",
        )

    async def async_added_to_hass(self) -> None:
        """Register dispatcher connection for webhook updates."""
        async_dispatcher_connect(  # type: ignore[has-type]
            self.hass,
            f"{DOMAIN}_webhook_update",
            self.handle_webhook_update,
        )

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates - to be implemented by subclasses."""


class BticinoTemperatureSensor(BticinoBaseSensor):
    """Sensor for current temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the temperature sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Temperature"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_temperature"
        self._attr_native_value = None

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for temperature."""
        _LOGGER.debug(
            "Temperature sensor %s received webhook event: %s",
            self._thermostat_name,
            event,
        )
        try:
            data_list = event.get("data", [])
            if not data_list:
                _LOGGER.debug(
                    "Temperature sensor %s: No data in webhook event",
                    self._thermostat_name,
                )
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )
            _LOGGER.debug(
                "Temperature sensor %s: Found %d chronothermostats in webhook",
                self._thermostat_name,
                len(chronothermostats),
            )

            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update temperature - READ FROM measures ARRAY like climate does
                thermometer_data = chrono_data.get("thermometer", {}).get(
                    "measures", [{}]
                )[0]
                if thermometer_data and "value" in thermometer_data:
                    self._attr_native_value = float(thermometer_data["value"])
                    self.schedule_update_ha_state()
                    _LOGGER.info(
                        "✅ Temperature sensor updated for %s: %s°C",
                        self._thermostat_name,
                        self._attr_native_value,
                    )
                else:
                    _LOGGER.warning(
                        "Temperature sensor %s: No temperature data in webhook. "
                        "Thermometer data: %s",
                        self._thermostat_name,
                        thermometer_data,
                    )
                return
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for temperature %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )


class BticinoHumiditySensor(BticinoBaseSensor):
    """Sensor for current humidity."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the humidity sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Humidity"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_humidity"
        self._attr_native_value = None

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for humidity."""
        _LOGGER.debug(
            "Humidity sensor %s received webhook event", self._thermostat_name
        )
        try:
            data_list = event.get("data", [])
            if not data_list:
                _LOGGER.debug(
                    "Humidity sensor %s: No data in webhook event",
                    self._thermostat_name,
                )
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )

            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update humidity - READ FROM measures ARRAY like climate does
                hygrometer_data = chrono_data.get("hygrometer", {}).get(
                    "measures", [{}]
                )[0]
                if hygrometer_data and "value" in hygrometer_data:
                    self._attr_native_value = float(hygrometer_data["value"])
                    self.schedule_update_ha_state()
                    _LOGGER.info(
                        "✅ Humidity sensor updated for %s: %s%%",
                        self._thermostat_name,
                        self._attr_native_value,
                    )
                else:
                    _LOGGER.warning(
                        "Humidity sensor %s: No humidity data in webhook. Hygrometer data: %s",
                        self._thermostat_name,
                        hygrometer_data,
                    )
                return
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for humidity %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )


class BticinoTargetTemperatureSensor(BticinoBaseSensor):
    """Sensor for target temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the target temperature sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Target Temperature"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_target_temperature"
        self._attr_native_value = None

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for target temperature."""
        _LOGGER.debug(
            "Target temperature sensor %s received webhook event", self._thermostat_name
        )
        try:
            data_list = event.get("data", [])
            if not data_list:
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )
            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update target temperature
                set_point = chrono_data.get("setPoint", {})
                if set_point and "value" in set_point:
                    self._attr_native_value = float(set_point["value"])
                    self.schedule_update_ha_state()
                    _LOGGER.info(
                        "✅ Target temperature sensor updated for %s: %s°C",
                        self._thermostat_name,
                        self._attr_native_value,
                    )
                return
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for target temperature %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )


class BticinoProgramSensor(BticinoBaseSensor):
    """Sensor for current program."""

    _attr_icon = "mdi:calendar-clock"

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
        programs: list[dict[str, Any]],
    ) -> None:
        """Initialize the program sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Current Program"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_current_program"
        self._attr_native_value = None
        self._programs = programs  # Store programs list for name lookup

    def _get_program_name(self, program_number: int) -> str:
        """Get program name from program number."""
        for program in self._programs:
            if int(program.get("number", -1)) == program_number:
                return program.get("name", "Unknown")
        return "Unknown"

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for current program."""
        try:
            data_list = event.get("data", [])
            if not data_list:
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )
            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update program - API returns programs array with number
                programs = chrono_data.get("programs", [])
                if programs and len(programs) > 0:
                    program_number = int(programs[0].get("number", 0))
                    self._attr_native_value = self._get_program_name(program_number)
                    self.schedule_update_ha_state()
                    _LOGGER.debug(
                        "Program sensor updated for %s: %s (number: %s)",
                        self._thermostat_name,
                        self._attr_native_value,
                        program_number,
                    )
                return
        except (KeyError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for program %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )


class BticinoModeSensor(BticinoBaseSensor):
    """Sensor for current mode."""

    _attr_icon = "mdi:thermostat"

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the mode sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Mode"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_mode"
        self._attr_native_value = None

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for mode."""
        try:
            data_list = event.get("data", [])
            if not data_list:
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )
            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update mode
                mode = chrono_data.get("mode")
                if mode:
                    self._attr_native_value = mode.lower()
                    self.schedule_update_ha_state()
                    _LOGGER.debug(
                        "Mode sensor updated for %s: %s",
                        self._thermostat_name,
                        self._attr_native_value,
                    )
                return
        except (KeyError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for mode %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )


class BticinoStatusSensor(BticinoBaseSensor):
    """Sensor for current status."""

    _attr_icon = "mdi:power"

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Status"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_status"
        self._attr_native_value = None

    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for status."""
        try:
            data_list = event.get("data", [])
            if not data_list:
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )
            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update status
                load_state = chrono_data.get("loadState")
                if load_state:
                    self._attr_native_value = load_state.lower()
                    self.schedule_update_ha_state()
                    _LOGGER.debug(
                        "Status sensor updated for %s: %s",
                        self._thermostat_name,
                        self._attr_native_value,
                    )
                return
        except (KeyError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for status %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )


class BticinoBoostTimeRemainingSensor(BticinoBaseSensor):
    """Sensor for boost time remaining."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer"

    def __init__(
        self,
        data: dict[str, Any],
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
    ) -> None:
        """Initialize the boost time remaining sensor."""
        super().__init__(data, plant_id, topology_id, thermostat_name)
        self._attr_name = f"{thermostat_name} Boost Time Remaining"
        self._attr_unique_id = f"bticino_x8000_{topology_id}_boost_time_remaining"
        self._attr_native_value = None

    def handle_webhook_update(  # pylint: disable=too-many-locals
        self, event: dict[str, Any]
    ) -> None:
        """Handle webhook updates for boost time remaining."""
        try:
            data_list = event.get("data", [])
            if not data_list:
                return

            chronothermostats = (
                data_list[0].get("data", {}).get("chronothermostats", [])
            )
            for chrono_data in chronothermostats:
                plant_data = chrono_data.get("sender", {}).get("plant", {})
                plant_id = plant_data.get("id")
                topology_id = plant_data.get("module", {}).get("id")

                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Update boost time remaining
                mode = chrono_data.get("mode", "").lower()
                if mode == "boost" and "activationTime" in chrono_data:
                    activation_time = chrono_data["activationTime"]

                    # Parse end time
                    if "/" in activation_time:
                        end_time_str = activation_time.split("/")[1]
                    else:
                        end_time_str = activation_time

                    end_time = dt_util.parse_datetime(end_time_str)
                    if end_time:
                        now = dt_util.now()
                        end_time = dt_util.as_utc(end_time)
                        remaining_seconds = (end_time - now).total_seconds()
                        remaining_minutes = max(0, int(remaining_seconds / 60))

                        self._attr_native_value = remaining_minutes
                        _LOGGER.debug(
                            "Boost time remaining updated for %s: %s minutes",
                            self._thermostat_name,
                            self._attr_native_value,
                        )
                else:
                    self._attr_native_value = 0

                self.schedule_update_ha_state()
                return
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(
                "Error handling webhook update for boost time remaining %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )
