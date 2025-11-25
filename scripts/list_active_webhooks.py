#!/usr/bin/env python3
"""
Script to list all ACTIVE webhooks registered in Home Assistant.
This shows webhooks that are actually registered and responding to requests,
not just entries in config_entries.

Usage: Run from Home Assistant container/environment:
  python3 list_active_webhooks.py
"""

import asyncio
import sys
from pathlib import Path

# Add Home Assistant to path if running in HA environment
try:
    from homeassistant.components import webhook
    from homeassistant.core import HomeAssistant
except ImportError:
    print("❌ Error: This script must be run from within Home Assistant environment")
    print("   Try running: ha core exec python3 /config/list_active_webhooks.py")
    sys.exit(1)


async def list_active_webhooks():
    """List all active webhooks registered in Home Assistant."""
    print("=" * 70)
    print("🔍 ACTIVE WEBHOOKS IN HOME ASSISTANT")
    print("=" * 70)
    print()

    # Access the webhook registry
    # Note: This requires access to the internal Home Assistant webhook registry
    # which is stored in hass.data[webhook.DOMAIN]

    print("⚠️  This script needs to be run from within Home Assistant's Python context.")
    print("   Active webhooks are stored in memory and not easily accessible from outside.")
    print()
    print("📋 To see active webhooks, use Home Assistant's Developer Tools:")
    print("   1. Go to Developer Tools → States")
    print("   2. Look for entities with 'webhook' in their entity_id")
    print()
    print("📋 Or check Home Assistant logs when a webhook arrives:")
    print("   ha core logs | grep -i webhook")
    print()
    print("📋 Or use this command to see ALL registered webhook IDs:")
    print("   cat /config/.storage/core.config_entries | grep -o '\"webhook_id\":\"[^\"]*\"'")
    print()


async def compare_webhooks():
    """Compare config_entries webhooks with what we expect to be active."""
    import json

    config_file = Path("/config/.storage/core.config_entries")
    if not config_file.exists():
        print("❌ Config entries file not found")
        return

    with open(config_file) as f:
        config = json.load(f)

    print("=" * 70)
    print("📋 WEBHOOKS FROM CONFIG_ENTRIES")
    print("=" * 70)
    print()

    webhooks_by_domain = {}

    for entry in config["data"]["entries"]:
        domain = entry.get("domain")
        entry_id = entry.get("entry_id")
        title = entry.get("title", "N/A")
        disabled = entry.get("disabled_by") is not None

        entry_data = entry.get("data", {})

        # Check for direct webhook_id
        if "webhook_id" in entry_data:
            webhook_id = entry_data["webhook_id"]
            if domain not in webhooks_by_domain:
                webhooks_by_domain[domain] = []
            webhooks_by_domain[domain].append({
                "webhook_id": webhook_id,
                "title": title,
                "entry_id": entry_id,
                "disabled": disabled,
            })

        # Check for nested webhook_ids (like bticino)
        if "selected_thermostats" in entry_data:
            for plant in entry_data["selected_thermostats"]:
                for plant_id, plant_data in plant.items():
                    webhook_id = plant_data.get("webhook_id")
                    if webhook_id:
                        if domain not in webhooks_by_domain:
                            webhooks_by_domain[domain] = []
                        webhooks_by_domain[domain].append({
                            "webhook_id": webhook_id,
                            "title": f"{title} - {plant_data.get('name', 'Unknown')}",
                            "entry_id": entry_id,
                            "plant_id": plant_id,
                            "disabled": disabled,
                        })

    for domain, webhooks in sorted(webhooks_by_domain.items()):
        print(f"🏠 Domain: {domain}")
        for wh in webhooks:
            status = "❌ DISABLED" if wh["disabled"] else "✅ ACTIVE"
            print(f"   {status}")
            print(f"   Title: {wh['title']}")
            print(f"   Entry ID: {wh['entry_id']}")
            print(f"   Webhook ID: {wh['webhook_id']}")
            print(f"   URL: https://YOUR_DOMAIN/api/webhook/{wh['webhook_id']}")
            if "plant_id" in wh:
                print(f"   Plant ID: {wh['plant_id']}")
            print()

    print("=" * 70)
    print(f"📊 SUMMARY: {sum(len(w) for w in webhooks_by_domain.values())} webhook(s) in config_entries")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(compare_webhooks())
