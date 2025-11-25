# C2C Subscription Cleanup Utility

## 🎯 Purpose

This utility helps diagnose and cleanup orphaned C2C (Cloud-to-Cloud) webhook subscriptions that can cause `409 Conflict` errors when setting up the Bticino X8000 Home Assistant integration.

## 🔍 Problem

When you see this error:
```
add_c2c_subscription - Failed to subscribe C2C. plant_id: xxx, status: 409, response: {'status_code': 409, 'text': {'statusCode': 409, 'message': 'Conflict'}}
```

It means there's already a C2C subscription registered with Bticino for that plant, and it's blocking new registrations.

**Common causes:**
- Previous Home Assistant installation not properly removed
- Integration removed without uninstalling
- Home Assistant crashed during uninstall
- Testing/development leaving subscriptions behind

## 🛠️ What This Script Does

1. **Lists ALL C2C subscriptions** for all your plants
2. **Identifies which subscriptions belong to Home Assistant** by checking the webhook URL pattern (`/api/webhook/`)
3. **Separates HA subscriptions from other apps** (e.g., official Bticino app, other integrations)
4. **Allows safe deletion** with confirmation:
   - Delete all HA subscriptions at once
   - Delete selectively (one by one)
   - Exit without changes

## 📋 Prerequisites

You need the following credentials from your Bticino developer account:

- **Client ID**
- **Client Secret**
- **Subscription Key**
- **Refresh Token** (from a working integration or recent authentication)

### How to Get Refresh Token

**Option 1: From Home Assistant config**
```bash
# Find your config entry file
cat /config/.storage/core.config_entries | grep -A 50 "bticino_x8000"
```

Look for `"refresh_token"` in the JSON output.

**Option 2: From integration logs**
Enable debug logging and check recent authentication:
```yaml
logger:
  logs:
    custom_components.bticino_x8000: debug
```

## 🚀 Usage

### Step 1: Run the Script

```bash
cd /workspaces/bticino_x8000_component/scripts
python3 cleanup_c2c_subscriptions.py
```

### Step 2: Enter Credentials

The script will ask for:
```
Client ID: <your-client-id>
Client Secret: <your-client-secret>
Subscription Key: <your-subscription-key>
Refresh Token: <your-refresh-token>
```

### Step 3: Review Subscriptions

The script will display:

```
🏠 HOME ASSISTANT SUBSCRIPTIONS (2):
----------------------------------------------------------------------

[1] Subscription ID: abc123...
    Plant: Home Mattiols
    Endpoint: https://my.home-assistant.io/api/webhook/xyz
    Created: 2025-11-20 15:30:45

[2] Subscription ID: def456...
    Plant: Home Mattiols
    Endpoint: https://192.168.1.100:8123/api/webhook/abc
    Created: 2025-11-22 10:15:20

⚠️  OTHER SUBSCRIPTIONS (1):
----------------------------------------------------------------------
(These are NOT from Home Assistant addon - probably other apps)

[1] Subscription ID: ghi789...
    Plant: Home Mattiols
    Endpoint: https://app.example.com/webhook/123
    Created: 2025-11-15 08:00:00
```

### Step 4: Choose Action

```
🗑️  CLEANUP OPTIONS:
1. Delete ALL Home Assistant subscriptions
2. Delete subscriptions one by one (interactive)
3. Exit without deleting anything

Your choice (1/2/3):
```

**Option 1 - Delete All HA Subscriptions:**
- Quick cleanup of all Home Assistant subscriptions
- Requires confirmation with "yes"
- **Safe**: Only deletes subscriptions with `/api/webhook/` pattern

**Option 2 - Interactive Mode:**
- Review each subscription before deleting
- Useful for selective cleanup
- More control

**Option 3 - Exit:**
- Just review, no changes
- Useful for investigation

## 📊 Example Output

```
✅ Found 3 plant(s)

🔍 Fetching C2C subscriptions...
✅ Found 5 subscription(s)

======================================================================

🏠 HOME ASSISTANT SUBSCRIPTIONS (3):
[Home Assistant integrations identified]

⚠️  OTHER SUBSCRIPTIONS (2):
[Other apps - will NOT be touched]

======================================================================

🗑️  CLEANUP OPTIONS:
1. Delete ALL Home Assistant subscriptions
2. Delete subscriptions one by one (interactive)
3. Exit without deleting anything

Your choice (1/2/3): 1

⚠️  WARNING: This will delete ALL Home Assistant subscriptions!
Type 'yes' to confirm: yes

🗑️  Deleting Home Assistant subscriptions...
✅ Deleted: abc123... (Plant: Home Mattiols)
✅ Deleted: def456... (Plant: Home Mattiols)
✅ Deleted: xyz789... (Plant: Office)

✅ Cleanup complete!

======================================================================
Done! You can now restart your Home Assistant addon.
======================================================================
```

## ⚠️ Safety Features

1. **Pattern Matching**: Only identifies HA subscriptions by `/api/webhook/` URL pattern
2. **Non-Destructive by Default**: Lists everything first, asks for confirmation
3. **Separate Categories**: Clearly separates HA vs. other app subscriptions
4. **User Confirmation**: Requires explicit "yes" for bulk deletions
5. **Detailed Reporting**: Shows what was deleted and what failed

## 🔧 Troubleshooting

### "Failed to refresh token"

Your refresh token might be expired. Get a new one:
1. Remove and re-add the integration in HA
2. Extract the new refresh token from config

### "Failed to get plants"

- Check your credentials are correct
- Verify subscription key is valid
- Check internet connection

### "Failed to delete subscription"

- The subscription might already be deleted
- API might be temporarily unavailable
- Check the subscription ID is correct

## 🤝 When to Use This Script

**Use BEFORE installing the integration if:**
- You previously had the integration installed
- You're getting `409 Conflict` errors
- You want to start fresh

**Use AFTER uninstalling the integration if:**
- You want to verify clean removal
- You're troubleshooting webhook issues
- You're switching Home Assistant instances

**Use for DEBUGGING if:**
- Integration setup fails with 409 errors
- You suspect orphaned subscriptions
- You want to see what's registered

## 🔄 Typical Workflow

1. **Backup**: Note your current integration settings
2. **Remove**: Remove Bticino integration from HA
3. **Cleanup**: Run this script to remove orphaned subscriptions
4. **Verify**: Check script reports 0 HA subscriptions
5. **Reinstall**: Add integration back to HA
6. **Verify**: Integration should now work without 409 errors

## 📝 Notes

- Script requires Python 3.7+
- Uses `aiohttp` (should be installed with Home Assistant)
- Safe to run multiple times
- **Does NOT delete subscriptions from other apps**
- All deletions are logged for audit trail

## 🆘 Need Help?

If you encounter issues:
1. Run the script in "Exit without changes" mode to just see subscriptions
2. Copy the full output
3. Open an issue on GitHub with the output
4. Include any error messages from Home Assistant logs

---

**Remember**: This script only cleans up webhook subscriptions. It does NOT affect your thermostat settings, programs, or temperatures!

