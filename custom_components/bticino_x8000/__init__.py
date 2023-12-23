import logging
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .auth import exchange_code_for_tokens, refresh_access_token
from .api import BticinoX8000Api
from .const import DOMAIN
from .climate import BticinoX8000ClimateEntity
from .webhook import BticinoX8000WebhookHandler
from homeassistant.components.webhook import (
    async_generate_id as generate_id,
)

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.helpers.event import async_track_time_interval

from datetime import datetime, timedelta
from homeassistant.util import dt as dt_util

# import datetime

PLATFORMS = [Platform.CLIMATE]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up the Bticino_X8000 component."""
    # data = config_entry.data
    data = dict(config_entry.data)
    # _LOGGER.error(f"My_hass_options contain {config_entry.options}")
    #    (
    #        access_token,
    #        refresh_token,
    #        access_token_expires_on,
    #    ) = await refresh_access_token(data)
    #    data["access_token"] = access_token
    #    data["refresh_token"] = refresh_token
    #    data["access_token_expires_on"] = access_token_expires_on
    #    hass.config_entries.async_update_entry(config_entry, data=data)

    entry_id = config_entry.entry_id

    options_copy = dict(config_entry.options)
    entry_id_options = options_copy.setdefault(entry_id, {})

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    domain_data = hass.data[DOMAIN].setdefault(entry_id, {})

    if not domain_data.get("api"):
        bticino_api = BticinoX8000Api(data)
        domain_data["api"] = bticino_api

    plants_data = await domain_data["api"].get_plants()
    if plants_data["status_code"] == 200:
        plant_ids = [plant["id"] for plant in plants_data["data"]]

        for plant_id in plant_ids:
            # Controlla se le opzioni contengono già dati per questa pianta
            if "plant_id" not in entry_id_options:
                entry_id_options["plant_id"] = plant_id

            # Controlla se il webhook è già presente nelle opzioni
            if "webhook" not in entry_id_options:
                entry_id_options["webhook"] = generate_id()

            # Registra il webhook solo se non è già presente
            webhook_handler = BticinoX8000WebhookHandler(
                hass,
                domain_data["api"],
                plant_id,
                webhook_url=data["external_url"],
                webhook_id=entry_id_options["webhook"],
                subscription_id=None,
            )
            entry_id_options[
                "subscription_id"
            ] = await webhook_handler.async_register_webhook()
            if entry_id_options["subscription_id"] == None:
                sub_id_list = await domain_data[
                    "api"
                ].get_subscriptions_C2C_notifications()
                for item in sub_id_list["data"]:
                    if entry_id_options["webhook"] in item["EndPointUrl"]:
                        entry_id_options["subscription_id"] = item["subscriptionId"]
                        break

            topologies = await domain_data["api"].get_topology(plant_id)

            for topology in topologies["data"]:
                topology_id = topology["id"]
                topology_name = topology["name"]
                if "topology_id" not in entry_id_options:
                    entry_id_options["topology_id"] = topology_id
                    entry_id_options["topology_name"] = topology_name
                    programs = await domain_data[
                        "api"
                    ].get_chronothermostat_programlist(plant_id, topology_id)
                    for program in programs["data"]:
                        if program["number"] == 0:
                            programs["data"].remove(program)

                    entry_id_options.setdefault("programs", programs["data"])

                climate_entity = BticinoX8000ClimateEntity(
                    domain_data["api"],
                    plant_id,
                    topology_id,
                    entry_id_options["topology_name"],
                    entry_id_options["programs"],
                )

                hass.async_add_job(
                    hass.config_entries.async_forward_entry_setup(
                        config_entry, "climate"
                    )
                )

            # Assegnare la copia delle opzioni al config_entry
            hass.config_entries.async_update_entry(config_entry, options=options_copy)

    async def update_token(now):
        _LOGGER.debug("Refreshing access token")
        (
            access_token,
            refresh_token,
            access_token_expires_on,
        ) = await refresh_access_token(data)

        data["access_token"] = access_token
        data["refresh_token"] = refresh_token
        data["access_token_expires_on"] = dt_util.as_utc(access_token_expires_on)
        hass.config_entries.async_update_entry(config_entry, data=data)

    update_interval = timedelta(hours=1)
    async_track_time_interval(hass, update_token, update_interval)
    await update_token(dt_util.as_timestamp(dt_util.utcnow()))
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    data = config_entry.data
    options = config_entry.options
    for entry_id in options:
        webhook_handler = BticinoX8000WebhookHandler(
            hass,
            hass.data[DOMAIN][entry_id]["api"],
            options[entry_id]["plant_id"],
            webhook_url=data["external_url"],
            webhook_id=options[entry_id]["webhook"],
            subscription_id=options[entry_id]["subscription_id"],
        )
        await webhook_handler.async_remove_webhook()
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)
    return True
