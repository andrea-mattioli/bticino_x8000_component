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

PLATFORMS = [Platform.CLIMATE, Platform.SELECT, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(  # pylint: disable=too-many-statements
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> bool:
    """Set up the Bticino_X8000 component."""
    data = dict(config_entry.data)
    bticino_api = BticinoX8000Api(data)
    hass.data.setdefault(DOMAIN, {})

    async def add_c2c_subscription(  # pylint: disable=too-many-branches,too-many-nested-blocks
        plant_id: str, webhook_id: str
    ) -> str | None:
        """Subscribe C2C with automatic cleanup of orphaned subscriptions."""
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
                    _LOGGER.info(
                        "✅ C2C subscription created successfully for plant: %s, "
                        "subscription_id: %s",
                        plant_id,
                        response["text"]["subscriptionId"],
                    )
                    subscription_id: str = response["text"]["subscriptionId"]
                    return subscription_id

                # Handle 409 Conflict - subscription already exists
                if response["status_code"] == 409:
                    _LOGGER.warning(
                        "⚠️ C2C subscription conflict (409) for plant %s. "
                        "Attempting automatic cleanup of orphaned subscriptions...",
                        plant_id,
                    )

                    # Get all existing subscriptions
                    subscriptions_response = (
                        await bticino_api.get_subscriptions_c2c_notifications()
                    )

                    if subscriptions_response.get("status_code") == 200:
                        all_subscriptions = subscriptions_response.get("data", [])

                        # Filter Home Assistant subscriptions for this plant
                        ha_subscriptions = [
                            sub
                            for sub in all_subscriptions
                            if sub.get("plantId") == plant_id
                            and "/api/webhook/" in sub.get("EndPointUrl", "")
                        ]

                        if ha_subscriptions:
                            _LOGGER.info(
                                "🔍 Found %d Home Assistant subscription(s) for plant %s",
                                len(ha_subscriptions),
                                plant_id,
                            )

                            # Delete all HA subscriptions for this plant
                            # (we'll recreate the correct one after)
                            for sub in ha_subscriptions:
                                sub_id = sub.get("subscriptionId")
                                endpoint = sub.get("EndPointUrl", "")
                                _LOGGER.debug(
                                    "🗑️  Deleting orphaned subscription: %s (endpoint: %s)",
                                    sub_id,
                                    endpoint,
                                )

                                delete_response = await bticino_api.delete_subscribe_c2c_notifications(  # pylint: disable=line-too-long
                                    plant_id, sub_id
                                )

                                if delete_response.get("status_code") == 200:
                                    _LOGGER.info(
                                        "✅ Deleted orphaned subscription: %s", sub_id
                                    )
                                else:
                                    _LOGGER.warning(
                                        "⚠️ Failed to delete subscription %s: %s",
                                        sub_id,
                                        delete_response,
                                    )

                            # Retry subscription after cleanup
                            _LOGGER.info(
                                "🔄 Retrying C2C subscription after cleanup for plant %s...",
                                plant_id,
                            )

                            retry_response = (
                                await bticino_api.set_subscribe_c2c_notifications(
                                    plant_id, {"EndPointUrl": webhook_endpoint}
                                )
                            )

                            if retry_response.get("status_code") == 201:
                                subscription_id = retry_response["text"][
                                    "subscriptionId"
                                ]
                                _LOGGER.info(
                                    "✅ C2C subscription created after cleanup: %s",
                                    subscription_id,
                                )
                                return subscription_id

                            _LOGGER.error(
                                "❌ Failed to create subscription after cleanup. "
                                "plant_id: %s, status: %s, response: %s",
                                plant_id,
                                retry_response.get("status_code"),
                                retry_response,
                            )
                        else:
                            _LOGGER.warning(
                                "No Home Assistant subscriptions found for cleanup. "
                                "409 conflict may be from another source."
                            )
                    else:
                        _LOGGER.error(
                            "Failed to get subscriptions for cleanup: %s",
                            subscriptions_response,
                        )

                # Log other errors
                if response["status_code"] != 409:
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

            _LOGGER.info(
                "⏰ TOKEN REFRESH SCHEDULED - Expires in %.1f min, "
                "will refresh in %.1f min (at %s)",
                time_until_expiry / 60,
                delay_seconds / 60,
                dt_util.now() + dt_util.dt.timedelta(seconds=delay_seconds),
            )

        # Schedule the next refresh
        async_call_later(hass, delay_seconds, update_token)
        _LOGGER.debug("schedule_token_refresh - async_call_later configured")

    async def update_token(now: dt_util.dt.datetime | None = None) -> None:
        """Refresh access token and schedule next refresh."""
        _LOGGER.info(
            "🔑 TOKEN UPDATE INVOKED at %s - Starting token refresh...",
            now or dt_util.now(),
        )
        try:
            (
                access_token,
                refresh_token,
                access_token_expires_on,
            ) = await refresh_access_token(data)
            _LOGGER.info(
                "✅ TOKEN REFRESH SUCCESSFUL - New token expires on: %s",
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


async def async_unload_entry(  # pylint: disable=too-many-locals
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Unload Entry and cleanup ALL C2C subscriptions for this integration."""
    data = dict(config_entry.data)
    bticino_api = BticinoX8000Api(data)
    await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    external_url = data.get("external_url", "")

    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        webhook_id = plant_data.get("webhook_id")
        subscription_id = plant_data.get("subscription_id")

        _LOGGER.info(
            "🧹 Cleaning up C2C subscriptions for plant %s during addon removal...",
            plant_id,
        )

        # Get all subscriptions for this plant
        try:
            subscriptions_response = (
                await bticino_api.get_subscriptions_c2c_notifications()
            )

            if subscriptions_response.get("status_code") == 200:
                all_subscriptions = subscriptions_response.get("data", [])

                # Filter for ALL Home Assistant subscriptions (current and orphaned)
                ha_subscriptions = [
                    sub
                    for sub in all_subscriptions
                    if sub.get("plantId") == plant_id
                    and "/api/webhook/" in sub.get("EndPointUrl", "")
                    and external_url in sub.get("EndPointUrl", "")
                ]

                _LOGGER.info(
                    "Found %d Home Assistant subscription(s) to delete for plant %s",
                    len(ha_subscriptions),
                    plant_id,
                )

                # Delete ALL HA subscriptions for this plant
                for sub in ha_subscriptions:
                    sub_id = sub.get("subscriptionId")
                    endpoint = sub.get("EndPointUrl", "")

                    _LOGGER.debug(
                        "🗑️  Deleting subscription: %s (endpoint: %s)", sub_id, endpoint
                    )

                    delete_response = (
                        await bticino_api.delete_subscribe_c2c_notifications(
                            plant_id, sub_id
                        )
                    )

                    if delete_response.get("status_code") == 200:
                        _LOGGER.info("✅ Deleted subscription: %s", sub_id)
                    else:
                        _LOGGER.error(
                            "❌ Failed to delete subscription %s: %s",
                            sub_id,
                            delete_response,
                        )
            else:
                _LOGGER.warning(
                    "Could not fetch subscriptions for cleanup: %s",
                    subscriptions_response,
                )

                # Fallback: try to delete the known subscription_id
                if subscription_id:
                    response = await bticino_api.delete_subscribe_c2c_notifications(
                        plant_id, subscription_id
                    )
                    if response.get("status_code") == 200:
                        _LOGGER.info(
                            "✅ Deleted current subscription: %s", subscription_id
                        )

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error during subscription cleanup: %s", e, exc_info=True)

        # Remove webhook
        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_remove_webhook()
        _LOGGER.info("🗑️  Webhook %s removed", webhook_id)

    _LOGGER.info("✅ Bticino X8000 addon unloaded and cleaned up successfully")
    return True
