import logging
import aiohttp
from aiohttp.web import Request, HTTPBadRequest, Response
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
        api,
        plantId,
        webhook_url,
        webhook_id,
        subscription_id,
    ):
        self.hass = hass
        self.api = api
        self.plantId = plantId
        self.webhook_url = webhook_url
        self.webhook_id = webhook_id
        self.subscription_id = subscription_id

    async def handle_webhook(self, hass: HomeAssistant, webhook_id, request) -> None:
        try:
            data = await request.json()
        except ValueError as err:
            _LOGGER.error("Error in data: %s", err)
            data = {}
        # Aggiungi un log per l'esito della gestione del webhook
        _LOGGER.debug("Got webhook data: %s", data)

        # Dispatch an event to update climate entities with webhook data
        # self.hass.bus.async_fire(f"{DOMAIN}_webhook_update", {"data": data})
        async_dispatcher_send(hass, f"{DOMAIN}_webhook_update", {"data": data})

        # Restituisci una risposta HTTP OK
        return Response(text="OK", status=200)

    async def async_register_webhook(self):
        """Register the webhook."""
        webhook_path = "/api/webhook/"
        webhook_endpoint = self.webhook_url + webhook_path + self.webhook_id
        webhook_register(
            self.hass,
            DOMAIN,
            "Bticino_X8000",
            self.webhook_id,
            self.handle_webhook,
            local_only=False,
        )

        _LOGGER.info("Webhook URL: %s", webhook_endpoint)

        response = await self.api.set_subscribe_C2C_notifications(
            self.plantId, {"EndPointUrl": webhook_endpoint}
        )
        if response["status_code"] == 201:
            print("Webhook subscription registrata con successo!")
            return response["text"]["subscriptionId"]

    async def async_remove_webhook(self):
        """Remove the webhook."""
        response = await self.api.delete_subscribe_C2C_notifications(
            self.plantId, self.subscription_id
        )
        if response["status_code"] == 200:
            print("Webhook subscription rimossa con successo!")
        else:
            print(f"Errore durante la rimozione della webhook subscription: {response}")
        webhook_unregister(self.hass, self.webhook_id)
