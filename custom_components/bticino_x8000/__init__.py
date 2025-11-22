"""Init."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import BticinoX8000Api
from .auth import refresh_access_token
from .const import DOMAIN
from .webhook import BticinoX8000WebhookHandler

PLATFORMS = [Platform.CLIMATE, Platform.SELECT]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(  # pylint: disable=too-many-statements
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
            _LOGGER.debug(
                "add_c2c_subscription - Subscribing C2C for plant_id: %s, webhook: %s",
                plant_id,
                webhook_endpoint,
            )
            try:
                response = await bticino_api.set_subscribe_c2c_notifications(
                    plant_id, {"EndPointUrl": webhook_endpoint}
                )
                _LOGGER.debug(
                    "add_c2c_subscription - Response for plant %s: %s",
                    plant_id,
                    response,
                )

                if response["status_code"] == 201:
                    _LOGGER.debug(
                        "add_c2c_subscription - Webhook subscription successful for plant: %s",
                        plant_id,
                    )
                    subscription_id: str = response["text"]["subscriptionId"]
                    return subscription_id

                _LOGGER.error(
                    "add_c2c_subscription - Failed to subscribe C2C. "
                    "plant_id: %s, status: %s, response: %s",
                    plant_id,
                    response.get("status_code"),
                    response,
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "add_c2c_subscription - Exception during C2C subscription. "
                    "plant_id: %s, error: %s",
                    plant_id,
                    e,
                    exc_info=True,
                )
        return None

    def schedule_token_refresh() -> None:
        """Schedule the next token refresh based on expiration time."""
        expires_on = data.get("access_token_expires_on")
        if expires_on is None:
            _LOGGER.warning(
                "schedule_token_refresh - No expiration time found, using default 50 minutes"
            )
            delay_seconds = 3000  # 50 minutes fallback
        else:
            # Calculate time until expiration
            now = dt_util.utcnow()
            time_until_expiry = (expires_on - now).total_seconds()

            # Refresh 5 minutes before expiration (300 seconds buffer)
            delay_seconds = max(time_until_expiry - 300, 60)

            _LOGGER.debug(
                "schedule_token_refresh - Token expires in %.1f minutes. "
                "Scheduling refresh in %.1f minutes",
                time_until_expiry / 60,
                delay_seconds / 60,
            )

        # Schedule the next refresh
        async_call_later(hass, delay_seconds, update_token)

    async def update_token(now: dt_util.dt.datetime | None = None) -> None:
        """Refresh access token and schedule next refresh."""
        _LOGGER.debug("update_token - Refreshing access token at: %s", now)
        try:
            (
                access_token,
                refresh_token,
                access_token_expires_on,
            ) = await refresh_access_token(data)
            _LOGGER.debug(
                "update_token - Token refresh successful. Expires on: %s",
                access_token_expires_on,
            )
            data["access_token"] = access_token
            data["refresh_token"] = refresh_token
            data["access_token_expires_on"] = access_token_expires_on
            hass.config_entries.async_update_entry(config_entry, data=data)

            # Schedule next refresh based on new expiration time
            schedule_token_refresh()

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "update_token - Failed to refresh access token: %s", e, exc_info=True
            )
            # Retry in 5 minutes on failure
            _LOGGER.info("update_token - Retrying token refresh in 5 minutes")
            async_call_later(hass, 300, update_token)

    # Do initial token refresh at startup
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
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
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
