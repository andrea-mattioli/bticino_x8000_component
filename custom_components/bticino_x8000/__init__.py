from datetime import timedelta  # noqa: D104
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import BticinoX8000Api
from .auth import refresh_access_token
from .webhook import BticinoX8000WebhookHandler

# import datetime

PLATFORMS = [Platform.CLIMATE]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
):
    """Set up the Bticino_X8000 component."""
    data = dict(config_entry.data)

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

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload Entry."""
    data = config_entry.data
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
            _LOGGER.debug("Webhook subscription rimossa con successo!")
        else:
            _LOGGER.debug(
                "Errore durante la rimozione della webhook subscription: %s", response
            )

        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_remove_webhook()
    return True
