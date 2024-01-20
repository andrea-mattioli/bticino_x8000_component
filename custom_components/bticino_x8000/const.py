"""Constant."""

DOMAIN = "bticino_x8000"
WEBHOOK_ID = "bticino_x8000_webhook"
DEFAULT_AUTH_BASE_URL: str = "https://partners-login.eliotbylegrand.com"
DEFAULT_API_BASE_URL: str = "https://api.developer.legrand.com"
DEFAULT_REDIRECT_URI: str = "https://my.home-assistant.io/"
CLIENT_ID = "Client id"
CLIENT_SECRET = "Client secret"
SUBSCRIPTION_KEY = "Subscription key"
################################
# Do not change! Will be set by release workflow
INTEGRATION_VERSION = "main"  # git tag will be used
MIN_REQUIRED_HA_VERSION = "2024.1.0b0"  # set min required version in hacs.json
################################

# Endpoints
AUTH_REQ_ENDPOINT = "/token"
AUTH_URL_ENDPOINT = "/authorize"
AUTH_CHECK_ENDPOINT = "/echo/resource"
THERMOSTAT_API_ENDPOINT: str = "/smarther/v2.0"
PLANTS = "/plants"
TOPOLOGY = "/topology"

# Attributes
ATTR_END_DATETIME = "end_datetime"
ATTR_TARGET_TEMPERATURE = "target_temperature"
ATTR_TIME_PERIOD = "time_period"
ATTR_TIME_BOOST_MODE = "boost_time"
ATTR_BOOST_MODE = "boost_mode"

# services
SERVICE_SET_BOOST_MODE = "set_boost_mode"
SERVICE_SET_TEMPERATURE_WITH_END_DATETIME = "set_temperature_with_end_datetime"
SERVICE_SET_TEMPERATURE_WITH_TIME_PERIOD = "set_temperature_with_time_period"
SERVICE_CLEAR_TEMPERATURE_SETTING = "clear_temperature_setting"
