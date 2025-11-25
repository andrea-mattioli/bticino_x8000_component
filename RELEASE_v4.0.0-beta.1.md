# Release v4.0.1-beta.1 - Sensor Entities & API Optimization

## ⚠️ BETA RELEASE - Testing Required

This is a beta release with significant improvements and new features. Please test thoroughly before using in production.

---

## 🚨 BREAKING CHANGES

### Fixed Attribute Typo

- **Climate entity attribute renamed**: `boost_time_remainig` → `boost_time_remaining`
- **Action required**: Update your templates/automations if using this attribute
- **Example fix**:

  ```yaml
  # Before (v3.x)
  {{ state_attr('climate.sala', 'boost_time_remainig') }}

  # After (v4.0)
  {{ state_attr('climate.sala', 'boost_time_remaining') }}
  ```

---

## ✨ New Features

### 🎯 Sensor Entities (NEW!)

Added **7 dedicated sensor entities** per thermostat for better integration and easier automation:

#### Temperature & Humidity Sensors

- **`sensor.{name}_temperature`** - Current room temperature (°C)

  - Device Class: `temperature`
  - State Class: `measurement`
  - Real-time updates via webhook

- **`sensor.{name}_humidity`** - Current room humidity (%)

  - Device Class: `humidity`
  - State Class: `measurement`
  - Real-time updates via webhook

- **`sensor.{name}_target_temperature`** - Target temperature / setpoint (°C)
  - Device Class: `temperature`
  - State Class: `measurement`
  - Real-time updates via webhook

#### Program & Mode Sensors

- **`sensor.{name}_current_program`** - Active program name

  - Icon: `mdi:calendar-clock`
  - Values: Program names from API (e.g., "Risparmio", "At Home")

- **`sensor.{name}_mode`** - Operating mode

  - Icon: `mdi:thermostat`
  - Values: `automatic`, `manual`, `boost`, `off`

- **`sensor.{name}_status`** - Heating/cooling status
  - Icon: `mdi:power`
  - Values: `active`, `inactive`

#### Boost Timer Sensor

- **`sensor.{name}_boost_time_remaining`** - Boost time left (minutes)
  - Device Class: `duration`
  - Unit: `minutes`
  - Icon: `mdi:timer`
  - Value: Minutes remaining (0 if boost not active)

**Benefits:**

- ✅ No additional API calls (updates via webhook)
- ✅ Proper device classes for automatic UI handling
- ✅ Historical data tracking in Home Assistant
- ✅ Easier to use in automations and templates
- ✅ Better Google Home / Alexa integration
- ✅ All sensors grouped under the same device

### 📦 Dynamic Select Entities

Added **2 select entities** per thermostat:

- **`select.bticino_{name}_{name}_program`** - Change active program

  - Options: Program names from API
  - Updates in real-time via webhook

- **`select.bticino_{name}_{name}_boost`** - Activate boost mode
  - Options: `off`, `30`, `60`, `90` (minutes)
  - Updates in real-time via webhook

### 🔗 Device Grouping

- All entities (climate, select, sensor) now grouped under the same device in Home Assistant UI
- Device info includes: manufacturer (Legrand), model (X8000)
- Easier navigation and management in the UI

---

## 🐛 Bug Fixes

### Major: API Rate Limiting Prevention

- **Reduced API calls from ~50 to ~2 per component restart** 🎯
- Fixed issue where select entities were calling API on every restart
- Changed `update_before_add=True` to `False` for select entities
- Sensors populate only from existing climate data (no extra calls)
- **Impact**: Users should no longer hit API rate limits during frequent restarts

### Fixed KeyError on Missing Data

- Added robust error handling for missing `chronothermostats` key in API responses
- Component no longer crashes if API returns unexpected response structure
- Better logging for debugging API response issues
- Setup continues for other thermostats even if one fails

### Improved Token Refresh

- **Proactive token refresh**: Now refreshes 5 minutes before expiration (was 1 hour fixed interval)
- Token refresh scheduled dynamically based on `access_token_expires_on` from API
- Added retry logic on token refresh failure (retries after 5 minutes)
- Better error handling to prevent component crash on token issues

### Thread-Safety Fixes

- Fixed `RuntimeError: async_write_ha_state from wrong thread` errors
- All webhook handlers now use `schedule_update_ha_state()` instead of `async_write_ha_state()`
- Affects: climate, select, and sensor entities
- **Impact**: No more crashes or data corruption warnings

### Better Error Handling

- Wrapped all API calls in try-except blocks
- Added checks for expected keys before accessing them
- Graceful degradation: if one plant/thermostat fails, others continue to work
- Improved error messages with full exception info for debugging

---

## 🔍 Improvements

### Enhanced Debug Logging

Added extensive debug logging throughout the component:

- **Authentication**: Token exchange, refresh, expiration times
- **API Calls**: Request URLs, response status codes, content previews
- **Setup Flow**: Plant discovery, topology fetch, program loading
- **Webhook Events**: Event data parsing and entity updates
- **Token Management**: Scheduling, refresh timing, expiration tracking

**Enable debug logging:**

```yaml
logger:
  default: info
  logs:
    custom_components.bticino_x8000: debug
```

### Code Quality

- ✅ Pylint score: **10.00/10**
- ✅ Mypy type checking: All errors resolved
- ✅ Better code organization and documentation
- ✅ Consistent error handling patterns

### Configuration Flow Improvements

- Better error handling during initial setup
- Continues setup even if one plant fails to load
- More informative error messages
- Debug logging for troubleshooting setup issues

---

## 📊 Performance

### API Call Optimization

**Before v4.0:**

- Component restart: ~50 API calls
- Risk of hitting rate limits with frequent restarts

**After v4.0:**

- Component restart: **~2 API calls** (token refresh + get status)
- Sensors: **0 additional API calls**
- Select entities: **0 additional API calls**
- All real-time updates via webhook: **0 API calls**

**Result**: ~95% reduction in API calls! 🎉

### Webhook-Driven Updates

- Climate entity updates → automatically updates all sensors and selects
- Single webhook event → updates all 10+ entities simultaneously
- No polling, no timers, no scheduled updates
- Real-time synchronization with Bticino cloud

---

## 🔧 Technical Details

### Entity Updates Flow

**At Startup:**

1. Climate entity calls `get_chronothermostat_status` (1 API call)
2. Climate entity dispatches data to sensors via webhook mechanism
3. All sensors populate with initial values
4. Total: **1 API call for all entities**

**During Operation (Real-time):**

1. Bticino cloud sends webhook to Home Assistant
2. Webhook handler dispatches event to all entities
3. Climate + Select + Sensor entities all update simultaneously
4. Total: **0 API calls**

### Platform Support

- Home Assistant 2024.1.0+
- Python 3.11+
- Added Platform.SENSOR to integration

### Dependencies

No new dependencies added.

---

## 📦 Installation

### Via HACS (Recommended)

1. Enable "Show beta versions" in HACS settings
2. Search for "Bticino X8000"
3. Install version `v4.0.0-beta.1`
4. Restart Home Assistant

### Manual Installation

1. Download the release from GitHub
2. Copy `custom_components/bticino_x8000` to your config directory
3. Restart Home Assistant

---

## 🧪 Testing Checklist

Please test and report issues on GitHub:

- [ ] Initial setup completes successfully
- [ ] All sensor entities appear and populate
- [ ] Select entities work (program change, boost activation)
- [ ] Climate entity works as before
- [ ] Webhook updates work in real-time
- [ ] No rate limiting errors (429) during normal operation
- [ ] Component restart doesn't cause rate limits
- [ ] Automations with new sensors work correctly
- [ ] UI cards display new sensors correctly

---

## 🔗 Links

- **GitHub Repository**: https://github.com/andrea-mattioli/bticino_x8000_component
- **Report Issues**: https://github.com/andrea-mattioli/bticino_x8000_component/issues
- **HACS**: https://hacs.xyz/

---

## 📝 Migration Guide

### From v3.x to v4.0

1. **Update templates using `boost_time_remainig`**:

   ```yaml
   # Old
   {{ state_attr('climate.sala', 'boost_time_remainig').minutes }}

   # New
   {{ state_attr('climate.sala', 'boost_time_remaining').minutes }}
   # OR use the new sensor:
   {{ states('sensor.sala_boost_time_remaining') }}
   ```

2. **Consider using new sensor entities**:

   ```yaml
   # Instead of:
   {{ state_attr('climate.sala', 'current_temperature') }}

   # Use:
   {{ states('sensor.sala_temperature') }}
   ```

3. **Update automations to use select entities**:

   ```yaml
   # Old (service call):
   service: bticino_x8000.set_schedule
   data:
     entity_id: climate.sala
     program_number: 1

   # New (select entity):
   service: select.select_option
   target:
     entity_id: select.bticino_sala_sala_program
   data:
     option: "Risparmio"
   ```

---

## 👥 Contributors

- @andrea-mattioli - Maintainer
- Thanks to all beta testers and contributors!

---

## 📅 Release Timeline

- **Beta Release**: 2025-11-22
- **Planned Stable Release**: After community testing (1-2 weeks)

---

**Thank you for testing! Please report any issues on GitHub.** 🙏
