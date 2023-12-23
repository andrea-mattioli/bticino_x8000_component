# Bticino Home Assistant Integration
Chronothermostat Bticino X8000 Integration

[![stable](https://badges.github.io/stability-badges/dist/stable.svg)](https://github.com/badges/stability-badges)

[![Sponsor Mattiols via GitHub Sponsors](https://raw.githubusercontent.com/andrea-mattioli/bticino_X8000_rest_api/test/screenshots/sponsor.png)](https://github.com/sponsors/andrea-mattioli)

🍻 [![Sponsor Mattiols via paypal](https://www.paypalobjects.com/webstatic/mktg/logo/pp_cc_mark_37x23.jpg)](http://paypal.me/mattiols)

### Italian support: [![fully supported](https://raw.githubusercontent.com/andrea-mattioli/bticino_X8000_rest_api/test/screenshots/telegram_logo.png)](https://t.me/HassioHelp)

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
Public Url = https://github.com/andrea-mattioli/bticino_x8000_custom_component
```
```
First Reply Url = https://my.home-assistant.io/
```
![Alt text](https://github.com/andrea-mattioli/bticino_X8000_rest_api/raw/test/screenshots/app2.png?raw=true "App Register")

## 2. CONFIGURATION

### 2.1. Update your config
```
client_id: recived via email
client_secret: recived via email
subscription_key: subscription key
domain: my home assistant public domain ex: https//pippo.duckdns.com:8123 (specify the port if is not standard 443)
```
## 3. START
