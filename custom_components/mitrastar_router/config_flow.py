import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_MAC_GROUPS, DEFAULT_HOST
from .coordinator import MitrastarCoordinator, InvalidAuth

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    pass


def _stored_value(entry, key: str) -> str:
    """Return a connection setting, preferring options over entry data.

    The coordinator reads host, username and password from options first
    because the options form stores them there.
    """
    return entry.options.get(key) or entry.data.get(key) or ""


class MitrastarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().rstrip("/")
            data = {**user_input, CONF_HOST: host}
            try:
                await MitrastarCoordinator.async_test_connection(self.hass, data)
            except InvalidAuth:
                _LOGGER.warning("El router MitraStar rechazó la autenticación para %s", host)
                errors["base"] = "invalid_auth"
            except Exception as err:
                # Keep the UI message generic, but retain the traceback in the
                # Home Assistant log so cannot_connect is diagnosable.
                _LOGGER.exception(
                    "No se pudo validar la conexión con el router MitraStar en %s (%s)",
                    host,
                    type(err).__name__,
                )
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"Mitrastar ({host})", data=data)

        schema = vol.Schema({
            vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data):
        """Start reauthentication after the router rejects the stored password.

        entry_data is the config entry data. The options flow can store a
        newer username and password, so the confirm step reads the entry.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Ask for the current password and store it where the coordinator reads it."""
        errors = {}
        entry = self._get_reauth_entry()
        host = _stored_value(entry, CONF_HOST)
        username = _stored_value(entry, CONF_USERNAME)

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            data = {
                CONF_HOST: host,
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            }
            try:
                await MitrastarCoordinator.async_test_connection(self.hass, data)
            except InvalidAuth:
                _LOGGER.warning(
                    "El router MitraStar rechazó la reautenticación para %s", host
                )
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception(
                    "No se pudo validar la reautenticación con el router MitraStar en %s (%s)",
                    host,
                    type(err).__name__,
                )
                errors["base"] = "cannot_connect"
            else:
                # data_updates always refreshes the original entry. When the
                # options form has stored credentials, those override data, so
                # the new password has to be written there as well.
                update_kwargs = {"data_updates": {CONF_PASSWORD: password}}
                if entry.options.get(CONF_PASSWORD) or entry.options.get(CONF_USERNAME):
                    update_kwargs["options"] = {
                        **entry.options,
                        CONF_PASSWORD: password,
                    }
                return self.async_update_reload_and_abort(
                    entry,
                    reason="reauth_successful",
                    **update_kwargs,
                )

        schema = vol.Schema({
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        })
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"username": username},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MitrastarOptionsFlow(config_entry)


class MitrastarOptionsFlow(config_entries.OptionsFlow):
    """Configure logical groups for private MAC addresses."""

    def __init__(self, config_entry):
        self._config_entry = config_entry

    @property
    def config_entry(self):
        return self._config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema({
            vol.Optional(CONF_HOST, default=self._config_entry.options.get(CONF_HOST, self._config_entry.data.get(CONF_HOST, DEFAULT_HOST))): str,
            vol.Optional(CONF_USERNAME, default=self._config_entry.options.get(CONF_USERNAME, self._config_entry.data.get(CONF_USERNAME, ""))): str,
            vol.Optional(CONF_PASSWORD, default=self._config_entry.options.get(
                CONF_PASSWORD, self._config_entry.data.get(CONF_PASSWORD, "")
            )): str,
            vol.Optional(
                CONF_MAC_GROUPS,
                description={"suggested_value": self._config_entry.options.get(CONF_MAC_GROUPS, "")},
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
