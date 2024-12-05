"""Init."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import BticinoX8000Api
from .auth import refresh_access_token
from .const import DOMAIN
from .webhook import BticinoX8000WebhookHandler

PLATFORMS = [Platform.CLIMATE]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> bool:
    """Set up the Bticino_X8000 component."""
    data = dict(config_entry.data)
    bticino_api = BticinoX8000Api(data)
    hass.data.setdefault(DOMAIN, {})

    async def add_c2c_subscription(plant_id: str, webhook_id: str) -> str | None:
        """Subscribe C2C."""
        if bticino_api is not None:
            webhook_path = "/api/webhook/"
            webhook_endpoint = data["external_url"] + webhook_path + webhook_id
            response = await bticino_api.set_subscribe_c2c_notifications(
                plant_id, {"EndPointUrl": webhook_endpoint}
            )
            if response["status_code"] == 201:
                _LOGGER.debug("Webhook subscription registrata con successo!")
                subscription_id: str = response["text"]["subscriptionId"]
                return subscription_id
        return None

    async def update_token(now: dt_util.dt.datetime | None) -> None:
        _LOGGER.debug("Refreshing access token: %s", now)
        (
            access_token,
            refresh_token,
            access_token_expires_on,
        ) = await refresh_access_token(data)
        data["access_token"] = access_token
        data["refresh_token"] = refresh_token
        data["access_token_expires_on"] = access_token_expires_on
        hass.config_entries.async_update_entry(config_entry, data=data)

    update_interval = timedelta(minutes=60)
    async_track_time_interval(hass, update_token, update_interval)
    hass.async_create_task(update_token(None))
    await update_token(None)
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        webhook_id = plant_data.get("webhook_id")
        subscription_id = await add_c2c_subscription(plant_id, webhook_id)
        if subscription_id is not None:
            plant_data["subscription_id"] = subscription_id
        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_register_webhook()
    hass.config_entries.async_update_entry(config_entry, data=data)
    _LOGGER.debug("selected_thermostats: %s", data["selected_thermostats"])
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, "climate")
    )
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Entry."""
    data = dict(config_entry.data)
    bticino_api = BticinoX8000Api(data)
    await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        webhook_id = plant_data.get("webhook_id")
        subscription_id = plant_data.get("subscription_id")
        response = await bticino_api.delete_subscribe_c2c_notifications(
            plant_id, subscription_id
        )
        if response["status_code"] == 200:
            _LOGGER.info("Webhook subscription rimossa con successo!")
        else:
            _LOGGER.error(
                "Errore durante la rimozione della webhook subscription: %s", response
            )

        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_remove_webhook()
    return True
