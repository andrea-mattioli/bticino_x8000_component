#!/usr/bin/env python3
"""
Script to manage (list and delete) C2C subscriptions on the Bticino server.
Usage: python3 manage_c2c_subscriptions.py
"""

import asyncio
import sys
from pathlib import Path

# Add the custom_components directory to the path FIRST
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

# Now import from the custom component
from bticino_x8000.api import BticinoX8000Api  # noqa: E402


async def list_and_manage_subscriptions(
    access_token: str,
    subscription_key: str,
):
    """List all C2C subscriptions and allow user to delete them."""
    print("=" * 70)
    print("🔍 Fetching all C2C subscriptions from Bticino server...")
    print("=" * 70)
    print()

    # Create API instance
    api = BticinoX8000Api(
        client_id="",
        client_secret="",
        subscription_key=subscription_key,
        access_token=access_token,
        refresh_token="",
    )

    # Get all subscriptions
    response = await api.get_subscriptions_c2c_notifications()

    if response.get("status_code") != 200:
        print(f"❌ Failed to fetch subscriptions: {response}")
        return

    all_subscriptions = response.get("data", [])

    if not all_subscriptions:
        print("✅ No C2C subscriptions found on the server.")
        return

    print(f"📋 Found {len(all_subscriptions)} subscription(s):\n")

    # Display all subscriptions with numbers
    for idx, sub in enumerate(all_subscriptions, start=1):
        sub_id = sub.get("subscriptionId")
        endpoint = sub.get("EndPointUrl", "N/A")
        plant_id = sub.get("plantId", "N/A")

        # Determine if it's a Home Assistant subscription
        is_ha = "/api/webhook/" in endpoint
        marker = "🏠 [Home Assistant]" if is_ha else "🔗 [Other App]"

        print(f"{idx}. {marker}")
        print(f"   Subscription ID: {sub_id}")
        print(f"   Plant ID: {plant_id}")
        print(f"   Endpoint: {endpoint}")
        print()

    # Ask user what to delete
    print("=" * 70)
    print("⚠️  OPTIONS:")
    print("   - Enter subscription numbers to delete (comma-separated, e.g. 1,3,5)")
    print("   - Enter 'all' to delete ALL Home Assistant subscriptions")
    print("   - Enter 'q' to quit without deleting")
    print("=" * 70)

    choice = input("\nYour choice: ").strip().lower()

    if choice == 'q':
        print("👋 Exiting without changes.")
        return

    to_delete = []

    if choice == 'all':
        # Delete all HA subscriptions
        to_delete = [
            (idx, sub) for idx, sub in enumerate(all_subscriptions, start=1)
            if "/api/webhook/" in sub.get("EndPointUrl", "")
        ]
        if not to_delete:
            print("ℹ️  No Home Assistant subscriptions to delete.")
            return
        print(f"\n🗑️  Deleting {len(to_delete)} Home Assistant subscription(s)...")
    else:
        # Parse user input
        try:
            indices = [int(x.strip()) for x in choice.split(",")]
            to_delete = [
                (idx, all_subscriptions[idx - 1])
                for idx in indices
                if 1 <= idx <= len(all_subscriptions)
            ]
            if not to_delete:
                print("❌ No valid subscription numbers provided.")
                return
        except (ValueError, IndexError):
            print("❌ Invalid input. Please enter valid numbers.")
            return

    # Confirm deletion
    print("\n⚠️  You are about to delete:")
    for idx, sub in to_delete:
        print(f"   {idx}. {sub.get('subscriptionId')} ({sub.get('EndPointUrl', 'N/A')})")

    confirm = input("\nAre you sure? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("👋 Deletion cancelled.")
        return

    # Delete subscriptions
    print()
    for idx, sub in to_delete:
        sub_id = sub.get("subscriptionId")
        plant_id = sub.get("plantId")

        print(f"🗑️  Deleting subscription {idx}: {sub_id}...")

        delete_response = await api.delete_subscribe_c2c_notifications(
            plant_id, sub_id
        )

        if delete_response.get("status_code") == 200:
            print(f"   ✅ Deleted successfully")
        else:
            print(f"   ❌ Failed: {delete_response}")
        print()

    print("=" * 70)
    print("✅ Operation completed!")
    print("=" * 70)


async def main():
    """Main function."""
    print("=" * 70)
    print("🛠️  Bticino X8000 - C2C Subscription Manager")
    print("=" * 70)
    print()
    print("This script helps you list and delete C2C subscriptions.")
    print("You'll need your access_token and subscription_key from Home Assistant.")
    print()

    # Get credentials
    access_token = input("Enter your access_token (from config_entries): ").strip()
    if not access_token:
        print("❌ Access token is required")
        return

    subscription_key = input("Enter your subscription_key (from config_entries): ").strip()
    if not subscription_key:
        print("❌ Subscription key is required")
        return

    print()
    await list_and_manage_subscriptions(access_token, subscription_key)


if __name__ == "__main__":
    asyncio.run(main())

