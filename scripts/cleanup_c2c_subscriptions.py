#!/usr/bin/env python3
"""
Bticino X8000 C2C Subscription Cleanup Utility

This script helps identify and cleanup orphaned C2C webhook subscriptions.
It can:
- List all active subscriptions for all plants
- Identify which subscriptions belong to Home Assistant addon
- Safely delete subscriptions (with user confirmation)

Usage:
    python3 cleanup_c2c_subscriptions.py
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Any


# API Configuration
DEFAULT_API_BASE_URL = "https://api.developer.legrand.com"
THERMOSTAT_API_ENDPOINT = "/smarther/v2.0"
TOKEN_ENDPOINT = "https://partners-login.eliotbylegrand.com/token"


class BticinoC2CManager:
    """Manager for Bticino C2C subscriptions."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        subscription_key: str,
        access_token: str = None,
    ):
        """Initialize the manager."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.subscription_key = subscription_key
        self.access_token = access_token
        self.header = None

        if access_token:
            self._set_header(access_token)

    def _set_header(self, access_token: str) -> None:
        """Set authorization header."""
        self.header = {
            "Authorization": f"Bearer {access_token}",
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Content-Type": "application/json",
        }

    async def get_access_token_from_refresh(self, refresh_token: str) -> dict[str, Any]:
        """Get new access token using refresh token."""
        print("🔑 Refreshing access token...")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    TOKEN_ENDPOINT, data=data
                ) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        self.access_token = token_data["access_token"]
                        self._set_header(self.access_token)
                        print("✅ Access token refreshed successfully\n")
                        return token_data
                    else:
                        error_text = await response.text()
                        print(f"❌ Failed to refresh token: {response.status}")
                        print(f"   Error: {error_text}\n")
                        return None
            except Exception as e:
                print(f"❌ Exception during token refresh: {e}\n")
                return None

    async def get_plants(self) -> list[dict[str, Any]]:
        """Get all plants."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/plants"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("plants", [])
                    else:
                        print(f"❌ Failed to get plants: {response.status}")
                        return []
            except Exception as e:
                print(f"❌ Exception getting plants: {e}")
                return []

    async def get_subscriptions(self) -> dict[str, Any]:
        """Get all C2C subscriptions."""
        url = f"{DEFAULT_API_BASE_URL}{THERMOSTAT_API_ENDPOINT}/subscription"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    if status_code == 200:
                        return {
                            "status_code": status_code,
                            "data": json.loads(content),
                        }
                    else:
                        return {
                            "status_code": status_code,
                            "error": content,
                        }
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": str(e),
                }

    async def delete_subscription(
        self, plant_id: str, subscription_id: str
    ) -> dict[str, Any]:
        """Delete a specific C2C subscription."""
        url = (
            f"{DEFAULT_API_BASE_URL}"
            f"{THERMOSTAT_API_ENDPOINT}"
            f"/plants/{plant_id}/subscription/{subscription_id}"
        )

        async with aiohttp.ClientSession() as session:
            try:
                async with session.delete(url, headers=self.header) as response:
                    status_code = response.status
                    content = await response.text()

                    return {
                        "status_code": status_code,
                        "text": content,
                    }
            except Exception as e:
                return {
                    "status_code": 500,
                    "error": str(e),
                }

    @staticmethod
    def is_homeassistant_subscription(endpoint_url: str) -> bool:
        """Check if subscription belongs to Home Assistant addon."""
        # Home Assistant webhook URLs contain "/api/webhook/"
        if not endpoint_url:
            return False
        return "/api/webhook/" in endpoint_url

    @staticmethod
    def format_datetime(dt_str: str) -> str:
        """Format datetime string for display."""
        if not dt_str:
            return "N/A"
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return dt_str or "N/A"


async def interactive_cleanup():
    """Interactive cleanup session."""
    print("=" * 70)
    print("🧹 Bticino X8000 C2C Subscription Cleanup Utility")
    print("=" * 70)
    print()

    # Get credentials
    print("📋 Enter your Bticino API credentials:\n")
    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()
    subscription_key = input("Subscription Key: ").strip()
    refresh_token = input("Refresh Token: ").strip()
    print()

    # Initialize manager
    manager = BticinoC2CManager(client_id, client_secret, subscription_key)

    # Get access token
    token_data = await manager.get_access_token_from_refresh(refresh_token)
    if not token_data:
        print("❌ Cannot proceed without valid access token. Exiting.")
        return

    # Get plants
    print("🔍 Fetching plants...")
    plants = await manager.get_plants()

    if not plants:
        print("❌ No plants found or error fetching plants. Exiting.")
        return

    print(f"✅ Found {len(plants)} plant(s)\n")

    # Create plant lookup
    plant_lookup = {plant["id"]: plant["name"] for plant in plants}

    # Get all subscriptions
    print("🔍 Fetching C2C subscriptions...")
    subscriptions_response = await manager.get_subscriptions()

    if subscriptions_response["status_code"] != 200:
        print(f"❌ Failed to get subscriptions: {subscriptions_response}")
        return

    # Handle both list and dict responses
    subscriptions_data = subscriptions_response.get("data", [])
    if isinstance(subscriptions_data, list):
        all_subscriptions = subscriptions_data
    else:
        all_subscriptions = subscriptions_data.get("subscriptions", [])

    if not all_subscriptions:
        print("✅ No active C2C subscriptions found. Nothing to cleanup!")
        return

    print(f"✅ Found {len(all_subscriptions)} subscription(s)\n")
    print("=" * 70)

    # Analyze and display subscriptions
    ha_subscriptions = []
    other_subscriptions = []

    for sub in all_subscriptions:
        if manager.is_homeassistant_subscription(sub.get("EndPointUrl", "")):
            ha_subscriptions.append(sub)
        else:
            other_subscriptions.append(sub)

    # Display Home Assistant subscriptions
    if ha_subscriptions:
        print(f"\n🏠 HOME ASSISTANT SUBSCRIPTIONS ({len(ha_subscriptions)}):")
        print("-" * 70)

        for idx, sub in enumerate(ha_subscriptions, 1):
            sub_id = sub.get("subscriptionId", "unknown")
            plant_id = sub.get("plantId", "unknown")
            plant_name = plant_lookup.get(plant_id, f"Unknown ({plant_id})")
            endpoint = sub.get("EndPointUrl", "unknown")
            created = manager.format_datetime(sub.get("createdOn", ""))

            print(f"\n[{idx}] Subscription ID: {sub_id}")
            print(f"    Plant: {plant_name}")
            print(f"    Endpoint: {endpoint}")
            print(f"    Created: {created}")

    # Display other subscriptions
    if other_subscriptions:
        print(f"\n⚠️  OTHER SUBSCRIPTIONS ({len(other_subscriptions)}):")
        print("-" * 70)
        print("(These are NOT from Home Assistant addon - probably other apps)")

        for idx, sub in enumerate(other_subscriptions, 1):
            sub_id = sub.get("subscriptionId", "unknown")
            plant_id = sub.get("plantId", "unknown")
            plant_name = plant_lookup.get(plant_id, f"Unknown ({plant_id})")
            endpoint = sub.get("EndPointUrl", "unknown")
            created = manager.format_datetime(sub.get("createdOn", ""))

            print(f"\n[{idx}] Subscription ID: {sub_id}")
            print(f"    Plant: {plant_name}")
            print(f"    Endpoint: {endpoint}")
            print(f"    Created: {created}")

    print("\n" + "=" * 70)

    # Cleanup options
    if ha_subscriptions:
        print("\n🗑️  CLEANUP OPTIONS:")
        print("1. Delete ALL Home Assistant subscriptions")
        print("2. Delete subscriptions one by one (interactive)")
        print("3. Exit without deleting anything")

        choice = input("\nYour choice (1/2/3): ").strip()

        if choice == "1":
            # Delete all HA subscriptions
            print("\n⚠️  WARNING: This will delete ALL Home Assistant subscriptions!")
            confirm = input("Type 'yes' to confirm: ").strip().lower()

            if confirm == "yes":
                print("\n🗑️  Deleting Home Assistant subscriptions...")

                for sub in ha_subscriptions:
                    sub_id = sub.get("subscriptionId")
                    plant_id = sub.get("plantId")
                    plant_name = plant_lookup.get(plant_id, plant_id)

                    result = await manager.delete_subscription(plant_id, sub_id)

                    if result["status_code"] == 200:
                        print(f"✅ Deleted: {sub_id} (Plant: {plant_name})")
                    else:
                        print(f"❌ Failed to delete: {sub_id} - {result}")

                print("\n✅ Cleanup complete!")
            else:
                print("\n❌ Deletion cancelled.")

        elif choice == "2":
            # Interactive deletion
            print("\n🗑️  Interactive deletion mode:")

            for idx, sub in enumerate(ha_subscriptions, 1):
                sub_id = sub.get("subscriptionId")
                plant_id = sub.get("plantId")
                plant_name = plant_lookup.get(plant_id, plant_id)
                endpoint = sub.get("EndPointUrl", "")

                print(f"\n[{idx}/{len(ha_subscriptions)}]")
                print(f"Subscription ID: {sub_id}")
                print(f"Plant: {plant_name}")
                print(f"Endpoint: {endpoint}")

                delete = input("Delete this subscription? (y/N): ").strip().lower()

                if delete == "y":
                    result = await manager.delete_subscription(plant_id, sub_id)

                    if result["status_code"] == 200:
                        print("✅ Deleted successfully")
                    else:
                        print(f"❌ Failed to delete: {result}")
                else:
                    print("⏭️  Skipped")

            print("\n✅ Interactive cleanup complete!")

        else:
            print("\n👋 Exiting without changes.")

    else:
        print("\n✅ No Home Assistant subscriptions found. Nothing to cleanup!")

    print("\n" + "=" * 70)
    print("Done! You can now restart your Home Assistant addon.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(interactive_cleanup())
    except KeyboardInterrupt:
        print("\n\n👋 Cancelled by user. Exiting...")
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

