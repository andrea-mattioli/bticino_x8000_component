# ---

**📑 Master Technical Report: Bticino X8000 Refactoring (v2026.2)**

Status: 🟢 Stable / Event-Driven  
Objective: Transformation from a legacy codebase to a resilient, fail-safe architecture capable of handling API instability, autonomously managing Rate Limits (429), and proactively notifying the user of service interruptions.

## ---

**1\. Executive Summary**

The integration was previously suffering from critical stability issues caused by aggressive retry loops that triggered the vendor's (Legrand) Rate Limiting mechanism. Furthermore, failures were silent, leaving the user unaware of why the system wasn't working.

The refactoring implemented four strategic pillars:

1. **Fail-Fast Logic:** Operations abort immediately upon the first sign of a critical error.
2. **Smart Backoff:** Wait times increase exponentially (2s \-\> 4s \-\> 8s) to respect server load.
3. **Self-Healing:** The system automatically switches to a "Cool Down" mode (60-minute interval) during bans.
4. **Proactive Observability:** **(NEW)** The system now fires a specific Home Assistant Event (bticino_x8000_event) when a limit is hit, enabling real-time push notifications to the user via Automations.

## ---

**2\. Core Architectural Changes**

### **A. The "Fail-Fast" Mechanism**

- **Legacy:** If Thermostat A failed, the code continued to hammer the API for Thermostat B, C, etc., extending the ban.
- **New:** If **any** single request fails with a critical error (RateLimitError or AuthError), the entire update cycle is **aborted immediately**.

### **B. Dynamic "Cool Down" Strategy**

- **Normal Operation:** Polling every **5 minutes**.
- **Crisis Operation (429):** Upon detecting a Rate Limit, the Coordinator switches to a **60-minute** interval.
- **Automatic Recovery:** As soon as a successful request occurs, the interval reverts to **5 minutes**.

### **C. Strict Data Invalidation**

- **New Behavior:** When a cycle is aborted, the system raises UpdateFailed. This forces all entities to become **"Unavailable"** in the UI, correctly reflecting that the displayed data is not live.

### **D. Event-Driven Alerts (New Feature)**

- **Logic:** Instead of just logging an error in the background, the integration now broadcasts an event onto the Home Assistant Event Bus.
- **Payload:** The event contains specific details: which device caused the error, the error message, and the duration of the cooldown.
- **Benefit:** Users can create Automations (e.g., Push to Mobile) to be notified instantly when the integration pauses itself.

## ---

**3\. Detailed Component Refactoring**

### **⚙️ api.py (Communication Layer)**

_The engine of HTTP requests._

- **Typed Exceptions:** Introduced RateLimitError (for HTTP 429\) and AuthError to allow precise reaction by the Coordinator.
- **Exponential Backoff:** Smart retry loop (2s ➔ 4s ➔ 8s) before failing.
- **Shared Session:** Optimized resource usage via async_get_clientsession(hass).
- **Lock Semantics:** Renamed locks to \_token_refresh_lock for clarity.

### **🧠 coordinator.py (State Manager)**

_The orchestrator. Now capable of firing events._

- **Event Bus Integration:** Added self.hass.bus.async_fire(f"{DOMAIN}\_event", ...) inside the RateLimitError catch block.
- **Logic Abort:** Catching RateLimitError immediately stops the loop.
- **Dynamic Interval:** Manages the switch between NORMAL_INTERVAL and COOL_DOWN_INTERVAL.
- **Data Invalidation:** Forces "Unavailable" state during outages.

### **🌡️ climate.py (Control Entity)**

- **Safe Initialization:** Prevents boot crashes by initializing attributes to safe defaults (None/OFF).
- **Typo Fixes:** Corrected Python name mangling issues (\_\_attr\_ vs \_attr\_).

### **📊 sensor.py (Telemetry)**

- **Config-Based Creation:** Sensors are created from the config entry, ensuring they always exist in the registry even if the API is down.
- **Robust Parsing:** Safe extraction of nested JSON data.

### **🔐 auth.py (Security)**

- **Error Propagation:** Ensures token failures bubble up to trigger the Fail-Fast logic.

## ---

**4\. User Configuration (Automation)**

To utilize the new **Proactive Observability**, the user can add the following automation to Home Assistant:

YAML

alias: "Bticino X8000: Rate Limit Alert"  
trigger:  
 \- platform: event  
 event_type: bticino_x8000_event  
 event_data:  
 type: "rate_limit_exceeded"  
action:  
 \- service: notify.mobile_app_iphone  
 data:  
 title: "⚠️ Bticino Paused"  
 message: "API Rate Limit hit on {{ trigger.event.data.topology\_id }}. Pausing for {{ trigger.event.data.cooldown\_minutes }} min."
