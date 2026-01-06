"""DataUpdateCoordinator for Bticino X8000."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
# Import for direct notifications to ensure visibility during boot
from homeassistant.components import persistent_notification

from .api import BticinoX8000Api, RateLimitError, AuthError, BticinoApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Standard update interval (normal operation)
# Set to 5 minutes to ensure data freshness while respecting standard API limits.
NORMAL_INTERVAL = timedelta(minutes=5)

# Extended interval when Rate Limit (429) is hit (Cool Down mode)
# If we get banned, we wait 60 minutes to allow the server-side quota to reset completely.
COOL_DOWN_INTERVAL = timedelta(minutes=60)

# Global ID for persistent notifications to avoid stacking multiple alerts.
# If a new error occurs, the existing notification is updated/overwritten.
NOTIFICATION_ID = "bticino_rate_limit_alert"

class BticinoCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Bticino data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: BticinoX8000Api,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self.entry = entry
        self.plant_map: dict[str, list[str]] = {}
        
        # Build a map of Plant IDs to Topology IDs (Thermostats) 
        # based on the user selection stored in the config entry.
        # This allows us to iterate specifically over the devices the user cares about.
        if "selected_thermostats" in entry.data:
            for plant_data in entry.data["selected_thermostats"]:
                plant_id = list(plant_data.keys())[0]
                thermo_data = list(plant_data.values())[0]
                topology_id = thermo_data.get("id")
                
                if plant_id not in self.plant_map:
                    self.plant_map[plant_id] = []
                self.plant_map[plant_id].append(topology_id)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=NORMAL_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch data from API sequentially.
        
        This method implements a 'Fail-Fast' logic: if a critical error (like Auth or Rate Limit)
        occurs on ONE device, the entire update cycle is aborted immediately.
        This prevents 'hammering' the API with further requests that would guaranteed fail.
        """
        data = {}
        
        # FAIL FAST CHECK 1:
        # Check if authentication is known to be broken from previous attempts.
        if self.api.auth_broken:
            _LOGGER.error("Auth is broken. Aborting update cycle.")
            raise UpdateFailed("Authentication broken")

        _LOGGER.debug("Starting sequential update for %s plants", len(self.plant_map))

        for plant_id, topology_ids in self.plant_map.items():
            for topology_id in topology_ids:
                
                # FAIL FAST CHECK 2:
                # Double check inside the loop in case auth broke during the previous iteration.
                if self.api.auth_broken:
                    raise UpdateFailed("Authentication broke during update")

                try:
                    # Request status from API
                    response = await self.api.get_chronothermostat_status(plant_id, topology_id)
                    
                    status_code = response.get("status_code")
                    
                    # 1. Handle Rate Limit returned as status code (Legacy/Fallback check)
                    # This catches cases where the API returns 429 without raising an exception.
                    if status_code == 429:
                        self._trigger_rate_limit_abort(plant_id, topology_id, "HTTP 429 Status Code returned")

                    if status_code == 200:
                        # SUCCESS: Check if we need to recover from Cool Down mode
                        if self.update_interval == COOL_DOWN_INTERVAL:
                            _LOGGER.info("API request successful. Resetting update interval to 5 minutes.")
                            self.update_interval = NORMAL_INTERVAL
                            # Dismiss the global persistent notification automatically if we recovered
                            persistent_notification.dismiss(self.hass, notification_id=NOTIFICATION_ID)

                        chrono_list = response.get("data", {}).get("chronothermostats", [])
                        if chrono_list:
                            # Save data using the flat topology_id key
                            data[topology_id] = chrono_list[0]
                    else:
                        _LOGGER.warning(
                            "Update failed for %s. Status code: %s", 
                            topology_id, 
                            status_code
                        )
                
                # 2. Handle Custom Exceptions from api.py (Robust & Typed handling)
                except RateLimitError as err:
                    # Dedicated handler for our custom RateLimitError exception
                    self._trigger_rate_limit_abort(plant_id, topology_id, str(err))

                except AuthError as err:
                    _LOGGER.error("Authentication error on %s: %s. Aborting updates.", topology_id, err)
                    # Explicitly flag auth as broken to prevent future retries until restart
                    self.api.auth_broken = True
                    raise UpdateFailed(f"Auth Error: {err}")

                except BticinoApiError as err:
                    _LOGGER.error("API Error on %s: %s", topology_id, err)
                    # For generic API errors (e.g. 500, timeout), we log but continue
                    # to the next device, as it might be a temporary single-device glitch.
                
                except Exception as err:
                    # 3. SAFETY NET: Catch generic exceptions that look like Rate Limits.
                    # This fixes the issue where the loop continued if the exception type wasn't perfect
                    # but the message clearly indicated a 429 error.
                    err_msg = str(err)
                    if "429" in err_msg or "Rate Limit" in err_msg:
                         self._trigger_rate_limit_abort(plant_id, topology_id, f"Generic Exception: {err_msg}")
                    
                    # Catch-all for truly unexpected crashes to prevent the loop from dying silently
                    _LOGGER.exception("Unexpected exception updating %s", topology_id)
        
        if not data:
            # Debug level to avoid noise during known outages
            _LOGGER.debug("Update cycle finished but no data was retrieved.")
            
        return data

    def _trigger_rate_limit_abort(self, plant_id: str, topology_id: str, message: str):
        """
        Helper to handle Rate Limit logic: Log, Fire Event, Notify, Set Interval, Raise Exception.
        
        This method is responsible for 'killing' the update loop efficiently and notifying the user.
        """
        _LOGGER.warning(
            "Rate Limit detected on %s: %s. Switching to 60 min interval and aborting.", 
            topology_id, message
        )
        
        # 1. Fire Event for User Notification (Home Assistant Bus)
        # This is useful for advanced automations.
        self.hass.bus.async_fire(
            f"{DOMAIN}_event",
            {
                "type": "rate_limit_exceeded",
                "plant_id": plant_id,
                "topology_id": topology_id,
                "message": message,
                "cooldown_minutes": 60
            }
        )

        # 2. Create Persistent Notification (Directly visible in Dashboard)
        # We use a GLOBAL ID (NOTIFICATION_ID) so we don't spam the user with multiple alerts.
        # This ensures the user sees the alert even if automations haven't loaded yet during boot.
        persistent_notification.async_create(
            self.hass,
            title="⛔ Bticino API Paused",
            message=(
                f"Rate Limit (429) detected.\n"
                f"Integration paused for 60 minutes.\n\n"
                f"Device: {topology_id}\n"
                f"Error: {message}"
            ),
            notification_id=NOTIFICATION_ID
        )

        # 3. Set Cooldown Interval (60 minutes)
        # The next update will not happen for an hour, letting the ban expire.
        self.update_interval = COOL_DOWN_INTERVAL
        
        # 4. RAISE EXCEPTION TO KILL THE LOOP IMMEDIATELY
        # Raising UpdateFailed tells Home Assistant that the update failed.
        # This stops the 'for' loop in _async_update_data and marks entities as Unavailable.
        raise UpdateFailed(f"Rate Limit Abort: {message}")

    def update_from_webhook(self, webhook_data: dict[str, Any]) -> None:
        """
        Update internal data from webhook.
        
        This allows the integration to react instantly to changes pushed by the server,
        without waiting for the next polling interval.
        """
        if not self.data:
            self.data = {}
            
        try:
            chronothermostats = webhook_data.get("data", [])
            updated_count = 0
            
            for wrapper in chronothermostats:
                # Flexible handling of webhook structure (sometimes nested differently)
                inner_data = wrapper.get("data", {})
                inner_chronos = []
                
                if "chronothermostats" in inner_data:
                    inner_chronos = inner_data["chronothermostats"]
                elif "chronothermostats" in wrapper:
                    inner_chronos = wrapper["chronothermostats"]
                
                for chrono in inner_chronos:
                    plant_data = chrono.get("sender", {}).get("plant", {})
                    topology_id = plant_data.get("module", {}).get("id")
                    
                    if topology_id:
                        _LOGGER.debug("Webhook received for topology ID: %s", topology_id)
                        self.data[topology_id] = chrono
                        updated_count += 1
            
            if updated_count > 0:
                _LOGGER.info("Updated %s entities from Webhook data", updated_count)
                # Notify listeners (sensors/climate) that data has changed
                self.async_set_updated_data(self.data)
                
        except Exception as e:
            _LOGGER.error("Error parsing webhook data: %s", e)