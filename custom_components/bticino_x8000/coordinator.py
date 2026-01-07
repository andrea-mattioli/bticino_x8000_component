"""DataUpdateCoordinator for Bticino X8000."""

import logging
from datetime import timedelta
from time import monotonic  # Added for debounce logic
from typing import Any

# Import for direct notifications to ensure visibility during boot
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util  # Added for diagnostic timestamps

from .api import AuthError, BticinoApiError, BticinoX8000Api, RateLimitError
from .const import (  # NEW: Imports for dynamic configuration keys and defaults
    CONF_COOL_DOWN,
    CONF_DEBOUNCE,
    CONF_NOTIFY_ERRORS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_COOL_DOWN,
    DEFAULT_DEBOUNCE,
    DEFAULT_NOTIFY_ERRORS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# REMOVED: Static constants NORMAL_INTERVAL and COOL_DOWN_INTERVAL
# are now dynamic properties of the class (self.normal_interval, self.cool_down_interval).

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

        # --- NEW: Load Dynamic Configuration (Architecture as Data) ---

        # 1. Update Interval (Normal polling)
        # Read from Options (user settings), fallback to Default (15 min)
        update_minutes = entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        self.normal_interval = timedelta(minutes=update_minutes)

        # 2. Cool Down Interval (Wait time after Ban)
        # Read from Options, fallback to Default (60 min)
        cool_down_minutes = entry.options.get(CONF_COOL_DOWN, DEFAULT_COOL_DOWN)
        self.cool_down_interval = timedelta(minutes=cool_down_minutes)

        # 3. Webhook Debounce (Traffic Control)
        # Read from Options, fallback to Default (1.0 sec)
        self.debounce_time = entry.options.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE)

        # 4. Error Notifications (User Experience)
        # Read from Options, fallback to Default (True/ON)
        self.notify_errors = entry.options.get(
            CONF_NOTIFY_ERRORS, DEFAULT_NOTIFY_ERRORS
        )

        # ---------------------------------------------------------------

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
            # UPDATED: Use the dynamic variable, not the static constant
            update_interval=self.normal_interval,
        )

        # Debounce and Diagnostics initialization
        self._last_webhook_mono = 0.0
        self._last_webhook_time = None

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
                    response = await self.api.get_chronothermostat_status(
                        plant_id, topology_id
                    )

                    status_code = response.get("status_code")

                    # 1. Handle Rate Limit returned as status code (Legacy/Fallback check)
                    # This catches cases where the API returns 429 without raising an exception.
                    if status_code == 429:
                        self._trigger_rate_limit_abort(
                            plant_id, topology_id, "HTTP 429 Status Code returned"
                        )

                    if status_code == 200:
                        # SUCCESS: Check if we need to recover from Cool Down mode
                        # UPDATED: Check against dynamic self.cool_down_interval
                        if self.update_interval == self.cool_down_interval:
                            _LOGGER.info(
                                "API request successful. Resetting update interval."
                            )
                            # UPDATED: Restore user-configured normal interval
                            self.update_interval = self.normal_interval
                            # Dismiss the global persistent notification automatically if we recovered
                            persistent_notification.dismiss(
                                self.hass, notification_id=NOTIFICATION_ID
                            )

                        chrono_list = response.get("data", {}).get(
                            "chronothermostats", []
                        )
                        if chrono_list:
                            # Save data using the flat topology_id key
                            data[topology_id] = chrono_list[0]
                    else:
                        _LOGGER.warning(
                            "Update failed for %s. Status code: %s",
                            topology_id,
                            status_code,
                        )

                # 2. Handle Custom Exceptions from api.py (Robust & Typed handling)
                except RateLimitError as err:
                    # Dedicated handler for our custom RateLimitError exception
                    self._trigger_rate_limit_abort(plant_id, topology_id, str(err))

                except AuthError as err:
                    _LOGGER.error(
                        "Authentication error on %s: %s. Aborting updates.",
                        topology_id,
                        err,
                    )
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
                        self._trigger_rate_limit_abort(
                            plant_id, topology_id, f"Generic Exception: {err_msg}"
                        )

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
            "Rate Limit detected on %s: %s. Switching to Cool Down interval and aborting.",
            topology_id,
            message,
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
                "cooldown_minutes": self.cool_down_interval.total_seconds() / 60,
            },
        )

        # 2. Create Persistent Notification (Directly visible in Dashboard)
        # UPDATED: Only show if enabled in configuration
        if self.notify_errors:
            # We use a GLOBAL ID (NOTIFICATION_ID) so we don't spam the user with multiple alerts.
            # This ensures the user sees the alert even if automations haven't loaded yet during boot.
            persistent_notification.async_create(
                self.hass,
                title="⛔ Bticino API Paused",
                message=(
                    f"Rate Limit (429) detected.\n"
                    f"Integration paused for Cool Down period.\n\n"
                    f"Device: {topology_id}\n"
                    f"Error: {message}"
                ),
                notification_id=NOTIFICATION_ID,
            )

        # 3. Set Cooldown Interval (Dynamic)
        # The next update will not happen for X minutes, letting the ban expire.
        # UPDATED: Use the dynamic variable from configuration
        self.update_interval = self.cool_down_interval

        # 4. RAISE EXCEPTION TO KILL THE LOOP IMMEDIATELY
        # Raising UpdateFailed tells Home Assistant that the update failed.
        # This stops the 'for' loop in _async_update_data and marks entities as Unavailable.
        raise UpdateFailed(f"Rate Limit Abort: {message}")

    async def async_force_token_refresh(self) -> None:
        """
        Public method to force a token refresh manually (e.g. via Button entity).
        This is useful if the token seems valid but the API is rejecting requests.
        """
        _LOGGER.info("Forcing manual token refresh requested by user.")
        # We call the internal method in api.py
        success = await self.api._handle_token_refresh()
        if success:
            _LOGGER.info("Manual token refresh successful.")
            # Reset broken flag just in case
            self.api.auth_broken = False
        else:
            _LOGGER.error("Manual token refresh failed.")

    def update_from_webhook(self, webhook_data: dict[str, Any]) -> None:
        """
        Update internal data from webhook payload defensively.

        Improvements:
        1. Debounce: Prevents flooding if multiple webhooks arrive in < 1s.
        2. Hybrid Lookup: Flattens plant_map for O(1) checks.
        3. Diagnostics: Tracks last successful update time.
        """
        # 1. Debounce Check
        # If webhooks arrive too fast (e.g., burst of slider movements), ignore them to save CPU.
        now = monotonic()
        # UPDATED: Use dynamic debounce time from configuration
        if now - self._last_webhook_mono < self.debounce_time:
            _LOGGER.debug("Webhook ignored (debounce active)")
            return
        self._last_webhook_mono = now

        # 2. Validation
        if not isinstance(webhook_data, dict):
            _LOGGER.warning(
                "Webhook payload is not a dictionary: %s", type(webhook_data)
            )
            return

        # 3. Optimization: Hybrid Lookup
        # Flatten plant_map {plant_id: [ids]} into a simple set {id1, id2} for instant O(1) lookup.
        # This avoids nested loops for every webhook received.
        watched_topologies = set()
        for ids in self.plant_map.values():
            watched_topologies.update(ids)

        # 4. Extraction
        chronothermostats = self._extract_chronothermostats(webhook_data)
        if not chronothermostats:
            _LOGGER.debug("No valid chronothermostats list found in webhook")
            return

        # 5. Initialization
        # Ensure internal data store is ready before the loop
        if self.data is None:
            self.data = {}

        updated_count = 0

        # 6. Processing Loop
        for chrono in chronothermostats:
            if not isinstance(chrono, dict):
                continue

            # Refactored: Use helper to extract ID cleanly
            topology_id = self._get_topology_id(chrono)

            if not topology_id:
                _LOGGER.debug("Could not extract valid topology_id from item")
                continue

            # Filter: Only update if this device is in our configuration
            if topology_id not in watched_topologies:
                _LOGGER.debug(
                    "Ignoring webhook for unmonitored topology_id: %s", topology_id
                )
                continue

            # Update Data
            self.data[topology_id] = chrono
            updated_count += 1
            _LOGGER.debug("Updated via webhook -> %s", topology_id)

        # 7. Finalize
        if updated_count > 0:
            # Update diagnostic timestamp
            self._last_webhook_time = dt_util.utcnow()
            _LOGGER.info("Webhook updated %d entities", updated_count)
            # Notify listeners
            self.async_set_updated_data(self.data)
        else:
            _LOGGER.debug("Webhook received but no relevant updates applied")

    def _get_topology_id(self, chrono: dict) -> str | None:
        """Helper to extract topology_id from a chrono object safely."""
        # Standard path: sender -> plant -> module -> id
        path = chrono.get("sender", {}).get("plant", {}).get("module", {}).get("id")
        if path and isinstance(path, str):
            return path

        # Legacy/Fallback path: receiver -> oid
        oid = chrono.get("receiver", {}).get("oid")
        return oid if isinstance(oid, str) else None

    def _extract_chronothermostats(self, payload: Any) -> list[dict]:
        """
        Defensive helper to extract the chronothermostats list.
        It handles different nesting levels often seen in Legrand APIs.
        """
        if not isinstance(payload, dict):
            return []

        # Scenario A: Standard structure { "data": { "chronothermostats": [...] } }
        data = payload.get("data", {})
        if "chronothermostats" in data:
            ch = data["chronothermostats"]
            return ch if isinstance(ch, list) else [ch] if isinstance(ch, dict) else []

        # Scenario B: Direct structure { "chronothermostats": [...] }
        if "chronothermostats" in payload:
            ch = payload["chronothermostats"]
            return ch if isinstance(ch, list) else [ch] if isinstance(ch, dict) else []

        return []
