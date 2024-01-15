import logging
import aiohttp
from aiohttp.web import Request, HTTPBadRequest, Response
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN
from homeassistant.components.webhook import (
    async_register as webhook_register,
    async_unregister as webhook_unregister,
)

_LOGGER = logging.getLogger(__name__)


class BticinoX8000WebhookHandler:
    def __init__(
        self,
        hass: HomeAssistant,
        webhook_id,
    ):
        self.hass = hass
        self.webhook_id = webhook_id

    async def handle_webhook(self, hass: HomeAssistant, webhook_id, request) -> None:
        try:
            data = await request.json()
        except ValueError as err:
            _LOGGER.error("Error in data: %s", err)
            data = {}
        # Aggiungi un log per l'esito della gestione del webhook
        _LOGGER.debug("Got webhook with id: %s and data: %s", webhook_id, data)

        # Dispatch an event to update climate entities with webhook data
        # self.hass.bus.async_fire(f"{DOMAIN}_webhook_update", {"data": data})
        async_dispatcher_send(hass, f"{DOMAIN}_webhook_update", {"data": data})

        # Restituisci una risposta HTTP OK
        return Response(text="OK", status=200)

    async def async_register_webhook(self):
        """Register the webhook."""
        webhook_register(
            self.hass,
            DOMAIN,
            "Bticino_X8000",
            self.webhook_id,
            self.handle_webhook,
            local_only=False,
        )

    async def async_remove_webhook(self):
        """Remove the webhook."""
        webhook_unregister(self.hass, self.webhook_id)
