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
        try:
            data = await request.json()
        except ValueError as err:
            _LOGGER.error("Error in data: %s", err)
            data = {}
        _LOGGER.debug("Got webhook with id: %s and data: %s", webhook_id, data)

        # Dispatch an event to update climate entities with webhook data
        async_dispatcher_send(hass, f"{DOMAIN}_webhook_update", {"data": data})  # type: ignore
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
        _LOGGER.debug("Unregister webhook with id: %s ", self.webhook_id)
        webhook_unregister(self.hass, self.webhook_id)
