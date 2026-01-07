"""Webhook handler for Bticino X8000."""

import logging

from aiohttp.web import Request, Response
from homeassistant.components.webhook import async_register as webhook_register
from homeassistant.components.webhook import async_unregister as webhook_unregister
from homeassistant.core import HomeAssistant

from .const import DOMAIN
# Type checking import only to avoid circular dependency at runtime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .coordinator import BticinoCoordinator

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
        # 1. Parse Data
        try:
            data = await request.json()
        except ValueError as err:
            _LOGGER.error("Error parsing webhook JSON: %s", err)
            return Response(text="Bad Request", status=400)

        _LOGGER.debug("WEBHOOK RECEIVED: %s", data)

        # 2. Update Coordinators
        # Instead of using dispatcher, we push data directly to the coordinator.
        # We iterate over all loaded entries for this domain because the webhook
        # does not carry the config_entry_id, but the coordinator filters by topology_id.
        
        if DOMAIN in hass.data:
            found_coordinator = False
            for entry_id, coordinator in hass.data[DOMAIN].items():
                # coordinator is an instance of BticinoCoordinator
                if hasattr(coordinator, "update_from_webhook"):
                    coordinator.update_from_webhook(data)
                    found_coordinator = True
            
            if not found_coordinator:
                _LOGGER.warning("Received webhook but no active coordinator found to handle it.")
        else:
            _LOGGER.warning("Received webhook but Bticino integration is not loaded.")

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
        _LOGGER.info("Unregistering webhook: %s", self.webhook_id)
        try:
            webhook_unregister(self.hass, self.webhook_id)
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Failed to unregister webhook %s: %s",
                self.webhook_id,
                e,
                exc_info=True,
            )
