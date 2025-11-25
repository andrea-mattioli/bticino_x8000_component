"""Webhook."""

import logging

from aiohttp.web import Request, Response
from homeassistant.components.webhook import async_register as webhook_register
from homeassistant.components.webhook import async_unregister as webhook_unregister
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class BticinoX8000WebhookHandler:
    """Webhook Class."""

    def __init__(
        self,
        hass: HomeAssistant,
        webhook_id: str,
    ) -> None:
        """Init."""
        self.hass = hass
        self.webhook_id: str = webhook_id

    async def handle_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: Request
    ) -> Response:
        """Handle webhook."""
        _LOGGER.info(
            "🌐 WEBHOOK RECEIVED - webhook_id: %s, from: %s",
            webhook_id,
            request.remote,
        )
        try:
            data = await request.json()
            _LOGGER.info(
                "📦 WEBHOOK DATA: %s",
                data,
            )
        except ValueError as err:
            _LOGGER.error("❌ Error parsing webhook data: %s", err)
            data = {}

        # Dispatch an event to update climate entities with webhook data
        _LOGGER.info(
            "📡 DISPATCHING webhook event to all entities (climate/select/sensor)"
        )
        async_dispatcher_send(hass, f"{DOMAIN}_webhook_update", {"data": data})  # type: ignore
        _LOGGER.debug("Webhook dispatch completed successfully")
        return Response(text="OK", status=200)

    async def async_register_webhook(self) -> None:
        """Register the webhook."""
        webhook_register(
            self.hass,
            DOMAIN,
            "Bticino_X8000",
            self.webhook_id,
            self.handle_webhook,
            local_only=False,
        )

    async def async_remove_webhook(self) -> None:
        """Remove the webhook."""
        _LOGGER.info("🗑️  Unregistering webhook: %s", self.webhook_id)
        try:
            webhook_unregister(self.hass, self.webhook_id)
            _LOGGER.info("✅ Webhook unregistered successfully: %s", self.webhook_id)
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "❌ Failed to unregister webhook %s: %s",
                self.webhook_id, e, exc_info=True
            )
