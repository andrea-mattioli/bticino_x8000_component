import logging
import secrets
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from urllib.parse import urlparse, parse_qs
from homeassistant.helpers import network
from .api import BticinoX8000Api
from .auth import exchange_code_for_tokens
from .const import (
    DOMAIN,
    DEFAULT_AUTH_BASE_URL,
    AUTH_URL_ENDPOINT,
    DEFAULT_REDIRECT_URI,
    DEFAULT_API_BASE_URL,
    AUTH_CHECK_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class BticinoX8000ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        try:
            external_url = network.get_url(
                self.hass,
                allow_internal=False,
                allow_ip=False,
                require_ssl=True,
                require_standard_port=True,
            )
        except network.NoURLAvailableError:
            _LOGGER.warning("network.NoURLAvailableError")
            external_url = "My HA external url ex: https://pippo.duckdns.com:8123 (specify the port if is not standard 443)"

        # Check if there are existing entries, and if so, abort the setup
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "client_id",
                            description="Client ID",
                            default="Client ID",
                        ): str,
                        vol.Required(
                            "client_secret",
                            description="Client Secret",
                            default="Client Secret",
                        ): str,
                        vol.Required(
                            "subscription_key",
                            description="Subscription Key",
                            default="Subscription Key",
                        ): str,
                        vol.Required(
                            "external_url",
                            description="HA external_url",
                            default=external_url,
                        ): str,
                    }
                ),
            )

        # Save user input data
        #   self.data = user_input
        authorization_url = self.get_authorization_url(user_input)
        message = (
            f"Click the link below to authorize Bticino X8000. After authorization, paste the browser URL here.\n\n"
            f"{authorization_url}"
        )
        return self.async_show_form(
            step_id="get_authorize_code",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "browser_url",
                        description="Paste here the browser URL",
                        default="Paste here the browser URL",
                    ): str,
                }
            ),
            errors={"base": message},
        )

    def get_authorization_url(self, user_input):
        state = secrets.token_hex(16)
        return (
            f"{DEFAULT_AUTH_BASE_URL}{AUTH_URL_ENDPOINT}?"
            + f"client_id={user_input['client_id']}"
            + "&response_type=code"
            + f"&state={state}"
            + f"&redirect_uri={DEFAULT_REDIRECT_URI}"
        )

    async def async_step_get_authorize_code(self, user_input=None):
        if user_input is not None:
            try:
                parsed_url = urlparse(user_input["browser_url"])
                _LOGGER.info(f"Parsed URL: {parsed_url}")
                query_params = parse_qs(parsed_url.query)
                _LOGGER.info(f"Query Parameters: {query_params}")
                code = query_params.get("code", [""])[0]
                state = query_params.get("state", [""])[0]

                if not code or not state:
                    raise ValueError(
                        "Unable to identify the Authorize Code or State. Please make sure to provide a valid URL."
                    )

                # Save authorization code in the data dictionary
                self.data["code"] = code

                # Use the auth module to exchange the code for tokens
                (
                    access_token,
                    refresh_token,
                    access_token_expires_on,
                ) = await exchange_code_for_tokens(
                    self.data["client_id"],
                    self.data["client_secret"],
                    DEFAULT_REDIRECT_URI,
                    code,
                )

                # Save the tokens in the data dictionary
                self.data["access_token"] = access_token
                self.data["refresh_token"] = refresh_token
                self.data["access_token_expires_on"] = access_token_expires_on
                print("config_flow_data:", self.data)
                bticino_api = BticinoX8000Api(self.data)

                # Check the health of the API endpoint
                if not await bticino_api.check_api_endpoint_health():
                    return self.async_abort(reason="Auth Failed!")

                return self.async_create_entry(
                    title="Bticino X8000 Configuration",
                    data=self.data,
                )

            except ValueError as error:
                _LOGGER.error(error)
                return await self.async_step_get_authorize_code()
        return await self.async_step_user(self.data)
