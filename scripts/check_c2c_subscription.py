#!/usr/bin/env python3
"""
Script to check if a specific C2C subscription exists on the Bticino server.
Usage: python3 check_c2c_subscription.py
"""

import asyncio
import sys
from pathlib import Path

# Add the custom_components directory to the path FIRST
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

# Now import from the custom component
from bticino_x8000.api import BticinoX8000Api  # noqa: E402


async def check_subscription(
    access_token: str,
    subscription_key: str,
    subscription_id: str,
    plant_id: str,
):
    """Check if a specific subscription exists."""
    print(f"🔍 Checking subscription on Bticino server...")
    print(f"   Plant ID: {plant_id}")
    print(f"   Subscription ID: {subscription_id}")
    print()

    # Create API instance
    api = BticinoX8000Api(
        client_id="",  # Not needed for read-only operations
        client_secret="",
        subscription_key=subscription_key,
        access_token=access_token,
        refresh_token="",
    )

    # Get all subscriptions
    print("📡 Fetching all C2C subscriptions from Bticino API...")
    response = await api.get_subscriptions_c2c_notifications()

    if response.get("status_code") != 200:
        print(f"❌ Failed to fetch subscriptions: {response}")
        return False

    all_subscriptions = response.get("data", [])
    print(f"✅ Found {len(all_subscriptions)} total subscription(s)\n")

    # Find our subscription
    found = False
    for sub in all_subscriptions:
        sub_id = sub.get("subscriptionId")
        endpoint = sub.get("EndPointUrl")
        sub_plant_id = sub.get("plantId")

        if sub_id == subscription_id:
            found = True
            print(f"✅ SUBSCRIPTION FOUND!")
            print(f"   Subscription ID: {sub_id}")
            print(f"   Plant ID: {sub_plant_id}")
            print(f"   Endpoint URL: {endpoint}")
            print()
            print("✅ The subscription is correctly registered on Bticino server!")
            print()
            print("If webhooks are not arriving, the issue is likely:")
            print("  1. Network/firewall blocking incoming requests")
            print("  2. Reverse proxy (Nginx/Traefik) not forwarding to Home Assistant")
            print("  3. SSL certificate issues")
            print()
            print("Test your webhook URL manually:")
            print(f"  curl -X POST {endpoint} -H 'Content-Type: application/json' -d '{{\"test\":\"manual\"}}' -v")
            return True

    if not found:
        print(f"❌ SUBSCRIPTION NOT FOUND!")
        print(f"   The subscription ID '{subscription_id}' is saved in Home Assistant,")
        print(f"   but it does NOT exist on the Bticino server.")
        print()
        print("This is a 'ghost' subscription. Webhooks will NOT work.")
        print()
        print("🔧 Solution:")
        print("   1. Remove and re-add the Bticino X8000 integration in Home Assistant")
        print("   2. This will create a new, working subscription")
        print()
        print("Other subscriptions found on the server:")
        for sub in all_subscriptions:
            print(f"  - ID: {sub.get('subscriptionId')}")
            print(f"    Plant: {sub.get('plantId')}")
            print(f"    Endpoint: {sub.get('EndPointUrl')}")
            print()

    return False


async def main():
    """Main function."""
    print("=" * 70)
    print("🔍 Bticino X8000 - C2C Subscription Checker")
    print("=" * 70)
    print()

    # Configuration from the production system
    # REPLACE THESE VALUES WITH YOUR OWN
    access_token = input("Enter your access_token (from config_entries): ").strip()
    if not access_token:
        print("❌ Access token is required")
        return

    subscription_key = input(
        "Enter your subscription_key (from config_entries): "
    ).strip()
    if not subscription_key:
        print("❌ Subscription key is required")
        return

    subscription_id = input(
        "Enter the subscription_id to check (from config_entries): "
    ).strip()
    if not subscription_id:
        print("❌ Subscription ID is required")
        return

    plant_id = input(
        "Enter your plant_id (from config_entries): "
    ).strip()
    if not plant_id:
        print("❌ Plant ID is required")
        return

    print()

    await check_subscription(
        access_token=access_token,
        subscription_key=subscription_key,
        subscription_id=subscription_id,
        plant_id=plant_id,
    )


if __name__ == "__main__":
    asyncio.run(main())
