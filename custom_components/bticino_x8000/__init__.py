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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
):
    """Set up the Bticino_X8000 component."""
    data = dict(config_entry.data)
    print("mydata:", data)
    for plant_data in data["selected_thermostats"]:
        plant_data = list(plant_data.values())[0]
        webhook_id = plant_data.get("webhook_id")
        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_register_webhook()
    hass.async_add_job(
        hass.config_entries.async_forward_entry_setup(config_entry, "climate")
    )

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

    update_interval = timedelta(minutes=2)
    async_track_time_interval(hass, update_token, update_interval)
    await update_token(dt_util.as_timestamp(dt_util.utcnow()))
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    data = config_entry.data
    print("mydata:", data)
    bticino_api = BticinoX8000Api(data)
    await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        webhook_id = plant_data.get("webhook_id")
        subscription_id = plant_data.get("subscription_id")
        response = await bticino_api.delete_subscribe_C2C_notifications(
            plant_id, subscription_id
        )
        if response["status_code"] == 200:
            print("Webhook subscription rimossa con successo!")
        else:
            print(f"Errore durante la rimozione della webhook subscription: {response}")

        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_remove_webhook()
    return True
