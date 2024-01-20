# Thermostat Bticino X8000 (NO NETATMO) Home Assistant Integration

[![CodeQL](https://github.com/andrea-mattioli/bticino_x8000_component/actions/workflows/codeql_analysis.yml/badge.svg)](https://github.com/andrea-mattioli/bticino_x8000_component/actions/workflows/codeql_analysis.yml)

[![Sponsor Mattiols via GitHub Sponsors](https://raw.githubusercontent.com/andrea-mattioli/bticino_X8000_rest_api/test/screenshots/sponsor.png)](https://github.com/sponsors/andrea-mattioli)

🍻 [![Sponsor Mattiols via paypal](https://www.paypalobjects.com/webstatic/mktg/logo/pp_cc_mark_37x23.jpg)](http://paypal.me/mattiols)

## 1. First step

### 1.1. Register a Developer account
Sign up for a new Developer account on Works with Legrand website (https://developer.legrand.com/login).

### 1.2. Subscribe to Legrand APIs
Sign in, go to menu "API > Subscriptions" and make sure you have "Starter Kit for Legrand APIs" subscription activated; if not, activate it.

![Alt text](https://github.com/andrea-mattioli/bticino_X8000_rest_api/raw/test/screenshots/subscription.PNG?raw=true "App Register")

### 1.3. Register a new application
Go to menu "User > My Applications" and click on "Create new" to register a new application:
- Insert a **valid public URL** in "First Reply Url".
- Make sure to tick the checkbox near scopes `comfort.read` and `comfort.write`

Submit your request and wait for a response via email from Legrand (it usually takes 1-2 days max).
If your app has been approved, you should find in the email your "Client ID" and "Client Secret" attributes.

```
Public Url = https://github.com/andrea-mattioli/bticino_x8000_component
```
```
First Reply Url = https://my.home-assistant.io/
```
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/app1.png?raw=true "App Register")
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/app2.png?raw=true "App Register")
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/app3.png?raw=true "App Register")
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/app4.png?raw=true "App Register")

### 1.4. Enable third party access

From the official "Thermostat" app go to Account --> Third party access

## 2. CONFIGURATION

### 2.1. Update your config
```
client_id: recived via email
client_secret: recived via email
subscription_key: subscription key
domain: my home assistant public domain ex: https//pippo.duckdns.com:8123 (specify the port if is not standard 443)
```
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/config_entry.png?raw=true "Configuration")

Copy or directly open the proposal link

![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/copy_link.png?raw=true "Configuration")

Accept the scope

![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/accept_legrand.png?raw=true "Configuration")

Copy the url link

![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/copy_url.png?raw=true "Configuration")

Paste

![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/paste_url.png?raw=true "Configuration")

Select thermostats to add as Entity (Default ALL)

![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/d0f46d9f1331f78d9f2c29c7bc0ff44d221b34f9/select_thermo.png?raw=true "Configuration")
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/end.png?raw=true "Configuration")
![Alt text](https://github.com/andrea-mattioli/bticino_x8000_component/blob/b4550e24b0a623c3a5a90627e92d204de1641367/climate.png?raw=true "Configuration")

