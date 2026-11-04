"""Select entities for Bticino X8000."""

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import get_api
from .api import BticinoX8000Api
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _climate_entity_id(hass: HomeAssistant, topology_id: str) -> str | None:
    """Return the real entity_id of the thermostat's climate entity.

    The entity_id must not be guessed from the thermostat name: it differs as
    soon as the name has special characters or the user renamed the entity.
    """
    return er.async_get(hass).async_get_entity_id(
        "climate", DOMAIN, f"{topology_id}_climate"
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bticino X8000 select entities."""
    data = dict(config_entry.data)
    api = get_api(hass, config_entry)
    entities: list[SelectEntity] = []

    # Aggiungi select per ogni termostato
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        thermo_data = list(plant_data.values())[0]

        thermostat_id = thermo_data.get("id")
        thermostat_name = thermo_data.get("name")
        programs = thermo_data.get("programs", [])

        # Select per i programmi
        if programs:
            program_select = BticinoProgramSelect(
                api=api,
                plant_id=plant_id,
                topology_id=thermostat_id,
                thermostat_name=thermostat_name,
                programs=programs,
            )
            entities.append(program_select)
            _LOGGER.debug(
                "Created program select for %s with programs: %s",
                thermostat_name,
                [p["name"] for p in programs],
            )

        # Select per il boost (uno per termostato)
        boost_select = BticinoBoostSelect(
            api=api,
            plant_id=plant_id,
            topology_id=thermostat_id,
            thermostat_name=thermostat_name,
            programs=programs,
        )
        entities.append(boost_select)
        _LOGGER.debug("Created boost select for %s", thermostat_name)

    async_add_entities(entities, update_before_add=False)


# pylint: disable=abstract-method  # We implement async_select_option instead
class BticinoBoostSelect(SelectEntity):  # pylint: disable=too-many-instance-attributes
    """Select entity for boost control."""

    _attr_should_poll = False  # NO POLLING! Updates via webhook only

    def __init__(  # pylint: disable=too-many-arguments
        self,
        api: BticinoX8000Api,
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
        programs: list[dict[str, Any]],
    ) -> None:
        """Initialize the boost select."""
        self._bticino_api = api
        self._plant_id = plant_id
        self._topology_id = topology_id
        self._thermostat_name = thermostat_name
        self._programs = programs

        self._attr_options = ["off", "30", "60", "90"]
        self._attr_name = f"{thermostat_name} Boost"
        self._attr_icon = "mdi:play-speed"
        self._attr_unique_id = f"{DOMAIN}_{topology_id}_boost"
        self._attr_current_option = "off"  # Default: sarà aggiornato da async_update
        self._last_program_number: int | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link with climate entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topology_id)},
            name=self._thermostat_name,  # Just "Sala", not "Bticino Sala"
            manufacturer="Legrand",
            model="X8000",
        )

    async def async_added_to_hass(self) -> None:
        """Register dispatcher connection for webhook updates."""
        self.async_on_remove(
            async_dispatcher_connect(  # type: ignore[has-type]
                self.hass,
                f"{DOMAIN}_webhook_update",
                self.handle_webhook_update,
            )
        )
        _LOGGER.debug(
            "Boost select %s connected to webhook dispatcher", self._thermostat_name
        )

    @callback
    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for boost state."""
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

                # Filtra solo per il nostro termostato
                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Aggiorna stato boost
                self._update_boost_state_from_data(chrono_data)
                self.async_write_ha_state()
                _LOGGER.debug(
                    "Boost select updated from webhook for %s: %s",
                    self._thermostat_name,
                    self._attr_current_option,
                )
                return
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Error handling webhook update for boost %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )

    def _update_boost_state_from_data(  # pylint: disable=too-many-branches,too-many-nested-blocks
        self, chrono_data: dict[str, Any]
    ) -> None:
        """Update boost state from chronothermostat data."""
        mode = (chrono_data.get("mode") or "").lower()
        programs = chrono_data.get("programs") or []
        if programs and programs[0].get("number") is not None:
            self._last_program_number = programs[0]["number"]

        if mode == "boost":
            if "activationTime" in chrono_data:
                # Calcola durata boost dai timestamp
                activation_time = chrono_data["activationTime"]
                _LOGGER.debug(
                    "Boost detected for %s, activationTime: %s",
                    self._thermostat_name,
                    activation_time,
                )

                # Format può essere:
                # 1. "2025-11-21T10:00:00/2025-11-21T11:00:00" (start/end)
                # 2. "2025-11-21T11:00:00" (solo end timestamp)

                if "/" in activation_time:
                    # Formato start/end
                    times = activation_time.split("/")
                    if len(times) == 2:
                        start = dt_util.parse_datetime(times[0])
                        end = dt_util.parse_datetime(times[1])
                        if start and end:
                            duration_minutes = int((end - start).total_seconds() / 60)
                            # Arrotonda a 30/60/90
                            if duration_minutes <= 45:
                                self._attr_current_option = "30"
                            elif duration_minutes <= 75:
                                self._attr_current_option = "60"
                            else:
                                self._attr_current_option = "90"
                            _LOGGER.debug(
                                "Boost duration calculated from start/end: %s minutes",
                                self._attr_current_option,
                            )
                            return
                else:
                    # Formato singolo timestamp (end time)
                    # Calcola quanto tempo rimane
                    end = dt_util.parse_datetime(activation_time)
                    if end:
                        now = dt_util.now()
                        end = dt_util.as_utc(end)
                        remaining_minutes = int((end - now).total_seconds() / 60)

                        _LOGGER.debug(
                            "Boost remaining time for %s: %s minutes",
                            self._thermostat_name,
                            remaining_minutes,
                        )

                        # Stima la durata originale in base al tempo rimanente
                        # Se rimangono più di 20 minuti, probabilmente è 30
                        # Se rimangono più di 50 minuti, probabilmente è 60
                        # Se rimangono più di 80 minuti, probabilmente è 90
                        if remaining_minutes > 0:
                            if remaining_minutes <= 30:
                                self._attr_current_option = "30"
                            elif remaining_minutes <= 60:
                                self._attr_current_option = "60"
                            else:
                                self._attr_current_option = "90"
                            _LOGGER.debug(
                                "Boost duration estimated from remaining time: %s minutes",
                                self._attr_current_option,
                            )
                            return
            else:
                _LOGGER.warning(
                    "Boost mode active for %s but no activationTime found",
                    self._thermostat_name,
                )

        # Se non è boost, è off
        self._attr_current_option = "off"

    async def async_update(self) -> None:
        """Fetch current boost state from API."""
        try:
            response = await self._bticino_api.get_chronothermostat_status(
                self._plant_id, self._topology_id
            )

            if response["status_code"] == 200:
                chrono_data = response["data"]["chronothermostats"][0]
                self._update_boost_state_from_data(chrono_data)
                _LOGGER.debug(
                    "Boost state for %s: %s",
                    self._thermostat_name,
                    self._attr_current_option,
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Error reading boost state for %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option and apply to thermostat."""
        if option not in self._attr_options:
            _LOGGER.error(
                "Invalid boost option: %s. Available: %s",
                option,
                self._attr_options,
            )
            return

        climate_entity_id = _climate_entity_id(self.hass, self._topology_id)
        if climate_entity_id is None:
            _LOGGER.error(
                "Climate entity for thermostat %s not found in the entity registry",
                self._thermostat_name,
            )
            return

        self._attr_current_option = option
        self.async_write_ha_state()

        if option == "off":
            # Back to automatic mode with the program that was active before
            # the boost (first program if unknown)
            if self._programs:
                default_program = next(
                    (
                        prog["name"]
                        for prog in self._programs
                        if self._last_program_number is not None
                        and int(prog["number"]) == int(self._last_program_number)
                    ),
                    self._programs[0]["name"],
                )
                await self.hass.services.async_call(
                    DOMAIN,
                    "set_schedule",
                    {
                        "entity_id": climate_entity_id,
                        "schedule_name": default_program,
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "Boost disabled for %s, returning to program: %s",
                    self._thermostat_name,
                    default_program,
                )
        else:
            # Attiva boost con durata selezionata
            # Determina hvac_mode dal clima corrente
            climate_state = self.hass.states.get(climate_entity_id)
            hvac_mode = "heating"  # Default
            if climate_state:
                current_hvac = climate_state.state
                if current_hvac == "cool":
                    hvac_mode = "cooling"

            await self.hass.services.async_call(
                DOMAIN,
                "set_boost_mode",
                {
                    "entity_id": climate_entity_id,
                    "hvac_mode": hvac_mode,
                    "boost_time": option,
                },
                blocking=True,
            )
            _LOGGER.info(
                "Boost activated for %s: %s minutes (%s)",
                self._thermostat_name,
                option,
                hvac_mode,
            )


# pylint: disable=abstract-method  # We implement async_select_option instead
class BticinoProgramSelect(
    SelectEntity
):  # pylint: disable=too-many-instance-attributes
    """Select entity for thermostat program."""

    _attr_should_poll = False  # NO POLLING! Updates via webhook only

    def __init__(  # pylint: disable=too-many-arguments
        self,
        api: BticinoX8000Api,
        plant_id: str,
        topology_id: str,
        thermostat_name: str,
        programs: list[dict[str, Any]],
    ) -> None:
        """Initialize the program select."""
        self._bticino_api = api
        self._plant_id = plant_id
        self._topology_id = topology_id
        self._thermostat_name = thermostat_name
        self._programs = programs

        # Crea lista opzioni dai nomi dei programmi
        self._attr_options = [prog["name"] for prog in programs]
        self._attr_name = f"{thermostat_name} Program"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_unique_id = f"{DOMAIN}_{topology_id}_program"

        # Default al primo programma, sarà aggiornato da async_update
        self._attr_current_option = (
            self._attr_options[0] if self._attr_options else None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link with climate entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topology_id)},
            name=self._thermostat_name,  # Just "Sala", not "Bticino Sala"
            manufacturer="Legrand",
            model="X8000",
        )

    async def async_added_to_hass(self) -> None:
        """Register dispatcher connection for webhook updates."""
        self.async_on_remove(
            async_dispatcher_connect(  # type: ignore[has-type]
                self.hass,
                f"{DOMAIN}_webhook_update",
                self.handle_webhook_update,
            )
        )
        _LOGGER.debug(
            "Program select %s connected to webhook dispatcher", self._thermostat_name
        )

    @callback
    def handle_webhook_update(self, event: dict[str, Any]) -> None:
        """Handle webhook updates for program state."""
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

                # Filtra solo per il nostro termostato
                if plant_id != self._plant_id or topology_id != self._topology_id:
                    continue

                # Aggiorna stato programma
                self._update_program_state_from_data(chrono_data)
                self.async_write_ha_state()
                _LOGGER.debug(
                    "Program select updated from webhook for %s: %s",
                    self._thermostat_name,
                    self._attr_current_option,
                )
                return
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Error handling webhook update for program %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )

    def _update_program_state_from_data(self, chrono_data: dict[str, Any]) -> None:
        """Update program state from chronothermostat data."""
        mode = (chrono_data.get("mode") or "").lower()

        # Se è in modalità automatica, leggi il programma attivo
        if mode == "automatic" and "programs" in chrono_data:
            program_list = chrono_data["programs"]
            if program_list:
                program_number = program_list[0].get("number")
                # Find the program name by number
                for prog in self._programs:
                    if prog["number"] == program_number:
                        self._attr_current_option = prog["name"]
                        return

    async def async_update(self) -> None:
        """Fetch current program from API."""
        try:
            response = await self._bticino_api.get_chronothermostat_status(
                self._plant_id, self._topology_id
            )

            if response["status_code"] == 200:
                chrono_data = response["data"]["chronothermostats"][0]
                self._update_program_state_from_data(chrono_data)
                _LOGGER.debug(
                    "Program state for %s: %s (mode: %s)",
                    self._thermostat_name,
                    self._attr_current_option,
                    chrono_data.get("mode", "unknown"),
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Error reading program for %s: %s",
                self._thermostat_name,
                e,
                exc_info=True,
            )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option and apply to thermostat."""
        if option not in self._attr_options:
            _LOGGER.error(
                "Invalid program option: %s. Available: %s",
                option,
                self._attr_options,
            )
            return

        climate_entity_id = _climate_entity_id(self.hass, self._topology_id)
        if climate_entity_id is None:
            _LOGGER.error(
                "Climate entity for thermostat %s not found in the entity registry",
                self._thermostat_name,
            )
            return

        self._attr_current_option = option
        self.async_write_ha_state()

        # Call the service to change program
        await self.hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {
                "entity_id": climate_entity_id,
                "schedule_name": option,
            },
            blocking=True,
        )
        _LOGGER.info(
            "Program changed to '%s' for thermostat %s",
            option,
            self._thermostat_name,
        )
