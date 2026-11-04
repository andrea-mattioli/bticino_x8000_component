"""Init."""

import copy
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import BticinoX8000Api
from .const import DOMAIN
from .webhook import BticinoX8000WebhookHandler

PLATFORMS = [Platform.CLIMATE, Platform.SELECT, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


def get_api(hass: HomeAssistant, config_entry: ConfigEntry) -> BticinoX8000Api:
    """Return the API client shared by every entity of this config entry."""
    api: BticinoX8000Api = hass.data[DOMAIN][config_entry.entry_id]
    return api


def _webhook_endpoint(external_url: str, webhook_id: str) -> str:
    """Build the public webhook URL that Legrand will call."""
    return f"{external_url.rstrip('/')}/api/webhook/{webhook_id}"


async def async_setup_entry(  # pylint: disable=too-many-statements,too-many-locals
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> bool:
    """Set up the Bticino_X8000 component."""
    # deepcopy: config_entry.data must never share objects with the dict we mutate,
    # otherwise async_update_entry sees no change and never saves to disk.
    data: dict[str, Any] = copy.deepcopy(dict(config_entry.data))
    bticino_api = BticinoX8000Api(data)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = bticino_api

    def save_entry_data() -> None:
        """Persist the current tokens and subscription ids."""
        hass.config_entries.async_update_entry(config_entry, data=copy.deepcopy(data))

    async def add_c2c_subscription(  # pylint: disable=too-many-branches,too-many-nested-blocks
        plant_id: str, webhook_id: str
    ) -> str | None:
        """Subscribe C2C with automatic cleanup of orphaned subscriptions."""
        webhook_endpoint = _webhook_endpoint(data["external_url"], webhook_id)
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
                subscription_id: str = response["text"]["subscriptionId"]
                _LOGGER.info(
                    "C2C subscription created successfully for plant: %s, "
                    "subscription_id: %s",
                    plant_id,
                    subscription_id,
                )
                return subscription_id

            if response["status_code"] != 409:
                _LOGGER.error(
                    "add_c2c_subscription - Failed to subscribe C2C. "
                    "plant_id: %s, endpoint: %s, status: %s, response: %s",
                    plant_id,
                    webhook_endpoint,
                    response.get("status_code"),
                    response,
                )
                return None

            # 409 Conflict - a subscription already exists
            _LOGGER.info(
                "C2C subscription conflict (409) for plant %s. "
                "Cleaning up orphaned subscriptions...",
                plant_id,
            )
            subscriptions_response = (
                await bticino_api.get_subscriptions_c2c_notifications()
            )
            if subscriptions_response.get("status_code") not in (200, 204):
                _LOGGER.error(
                    "Failed to get subscriptions for cleanup: %s",
                    subscriptions_response,
                )
                return None

            ha_subscriptions = [
                sub
                for sub in subscriptions_response.get("data") or []
                if sub.get("plantId") == plant_id
                and "/api/webhook/" in sub.get("EndPointUrl", "")
            ]
            if not ha_subscriptions:
                _LOGGER.warning(
                    "No Home Assistant subscriptions found for cleanup. "
                    "409 conflict may be from another source."
                )
                return None

            _LOGGER.info(
                "Found %d Home Assistant subscription(s) for plant %s",
                len(ha_subscriptions),
                plant_id,
            )
            # Delete all HA subscriptions for this plant, then recreate ours
            for sub in ha_subscriptions:
                sub_id = sub.get("subscriptionId")
                _LOGGER.debug(
                    "Deleting orphaned subscription: %s (endpoint: %s)",
                    sub_id,
                    sub.get("EndPointUrl", ""),
                )
                delete_response = await bticino_api.delete_subscribe_c2c_notifications(
                    plant_id, sub_id
                )
                if delete_response.get("status_code") == 200:
                    _LOGGER.info("Deleted orphaned subscription: %s", sub_id)
                else:
                    _LOGGER.warning(
                        "Failed to delete subscription %s: %s",
                        sub_id,
                        delete_response,
                    )

            _LOGGER.info(
                "Retrying C2C subscription after cleanup for plant %s...", plant_id
            )
            retry_response = await bticino_api.set_subscribe_c2c_notifications(
                plant_id, {"EndPointUrl": webhook_endpoint}
            )
            if retry_response.get("status_code") == 201:
                subscription_id = retry_response["text"]["subscriptionId"]
                _LOGGER.info(
                    "C2C subscription created after cleanup: %s", subscription_id
                )
                return subscription_id

            _LOGGER.error(
                "Failed to create subscription after cleanup. "
                "plant_id: %s, status: %s, response: %s",
                plant_id,
                retry_response.get("status_code"),
                retry_response,
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

    # Only one refresh timer may be pending; it is cancelled on unload so that
    # reloading the integration never leaves orphaned refresh loops behind.
    cancel_refresh: list[Callable[[], None]] = []

    def cancel_pending_refresh() -> None:
        while cancel_refresh:
            cancel_refresh.pop()()

    def schedule_refresh(delay_seconds: float) -> None:
        cancel_pending_refresh()
        cancel_refresh.append(async_call_later(hass, delay_seconds, update_token))

    config_entry.async_on_unload(cancel_pending_refresh)

    def schedule_token_refresh() -> None:
        """Schedule the next token refresh based on expiration time."""
        expires_on = data.get("access_token_expires_on")
        if expires_on is None:
            _LOGGER.warning(
                "schedule_token_refresh - No expiration time found, using default 50 minutes"
            )
            delay_seconds = 3000.0  # 50 minutes fallback
        else:
            time_until_expiry = (expires_on - dt_util.utcnow()).total_seconds()
            # Refresh 5 minutes before expiration
            delay_seconds = max(time_until_expiry - 300, 60)
            _LOGGER.info(
                "TOKEN REFRESH SCHEDULED - Expires in %.1f min, "
                "will refresh in %.1f min (at %s)",
                time_until_expiry / 60,
                delay_seconds / 60,
                dt_util.now() + dt_util.dt.timedelta(seconds=delay_seconds),
            )
        schedule_refresh(delay_seconds)

    async def update_token(now: dt_util.dt.datetime | None = None) -> None:
        """Refresh access token and schedule next refresh."""
        cancel_refresh.clear()  # the timer that called us has already fired
        _LOGGER.info(
            "TOKEN UPDATE INVOKED at %s - Starting token refresh...",
            now or dt_util.now(),
        )
        try:
            await bticino_api.async_refresh_token()
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("update_token - Failed to refresh access token: %s", e)
            _LOGGER.info("update_token - Retrying token refresh in 5 minutes")
            schedule_refresh(300)
            return
        _LOGGER.info(
            "TOKEN REFRESH SUCCESSFUL - New token expires on: %s",
            data["access_token_expires_on"],
        )
        save_entry_data()
        schedule_token_refresh()

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
    save_entry_data()
    _LOGGER.debug("selected_thermostats: %s", data["selected_thermostats"])
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Unload Entry and cleanup ALL C2C subscriptions for this integration."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    bticino_api: BticinoX8000Api = hass.data.get(DOMAIN, {}).pop(
        config_entry.entry_id, None
    ) or BticinoX8000Api(copy.deepcopy(dict(config_entry.data)))
    data = bticino_api.data

    external_url = data.get("external_url", "").rstrip("/")

    for plant_data in data["selected_thermostats"]:
        plant_id = list(plant_data.keys())[0]
        plant_data = list(plant_data.values())[0]
        webhook_id = plant_data.get("webhook_id")
        subscription_id = plant_data.get("subscription_id")

        _LOGGER.info(
            "Cleaning up C2C subscriptions for plant %s during addon removal...",
            plant_id,
        )

        try:
            subscriptions_response = (
                await bticino_api.get_subscriptions_c2c_notifications()
            )

            if subscriptions_response.get("status_code") in (200, 204):
                # Filter for ALL Home Assistant subscriptions (current and orphaned)
                ha_subscriptions = [
                    sub
                    for sub in subscriptions_response.get("data") or []
                    if sub.get("plantId") == plant_id
                    and "/api/webhook/" in sub.get("EndPointUrl", "")
                    and external_url in sub.get("EndPointUrl", "")
                ]

                _LOGGER.info(
                    "Found %d Home Assistant subscription(s) to delete for plant %s",
                    len(ha_subscriptions),
                    plant_id,
                )

                for sub in ha_subscriptions:
                    sub_id = sub.get("subscriptionId")
                    endpoint = sub.get("EndPointUrl", "")

                    if not sub_id:
                        _LOGGER.warning(
                            "Skipping subscription with missing ID (endpoint: %s)",
                            endpoint,
                        )
                        continue

                    _LOGGER.debug(
                        "Deleting subscription: %s (endpoint: %s)", sub_id, endpoint
                    )
                    delete_response = (
                        await bticino_api.delete_subscribe_c2c_notifications(
                            plant_id, sub_id
                        )
                    )

                    status = delete_response.get("status_code")
                    if status == 200:
                        _LOGGER.info("Deleted subscription: %s", sub_id)
                    elif status == 404:
                        _LOGGER.warning(
                            "Subscription %s not found (already deleted?)", sub_id
                        )
                    elif status == 400:
                        _LOGGER.error(
                            "Bad request deleting subscription %s - "
                            "Invalid subscription_id or plant_id? Response: %s",
                            sub_id,
                            delete_response,
                        )
                    else:
                        _LOGGER.error(
                            "Failed to delete subscription %s (status %s): %s",
                            sub_id,
                            status,
                            delete_response,
                        )
            else:
                _LOGGER.warning(
                    "Could not fetch subscriptions for cleanup: %s",
                    subscriptions_response,
                )

                # Fallback: try to delete the known subscription_id
                if subscription_id and subscription_id != "None":
                    _LOGGER.info(
                        "Attempting fallback deletion of known subscription_id: %s",
                        subscription_id,
                    )
                    response = await bticino_api.delete_subscribe_c2c_notifications(
                        plant_id, subscription_id
                    )
                    status = response.get("status_code")
                    if status == 200:
                        _LOGGER.info(
                            "Deleted current subscription: %s", subscription_id
                        )
                    else:
                        _LOGGER.warning(
                            "Fallback deletion failed (status %s): %s",
                            status,
                            response,
                        )
                else:
                    _LOGGER.warning("No valid subscription_id to delete in fallback")

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error during subscription cleanup: %s", e, exc_info=True)

        # Remove webhook
        webhook_handler = BticinoX8000WebhookHandler(hass, webhook_id)
        await webhook_handler.async_remove_webhook()
        _LOGGER.info("Webhook %s removed", webhook_id)

    _LOGGER.info("Bticino X8000 addon unloaded and cleaned up successfully")
    return unload_ok
