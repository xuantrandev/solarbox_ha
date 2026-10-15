"""Config flow for the SolarProject integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_DEVICE_ID,
    CONF_FAST_DATA_INTERVAL,
    CONF_SENSOR_PREFIX,
    CONF_SERVER,
    DEFAULT_FAST_DATA_INTERVAL,
    DEFAULT_SERVER,
    DEVICE_ID_REGEX,
    DOMAIN,
)
from .coordinator import build_ws_url

_LOGGER = logging.getLogger(__name__)


def _normalize_server(raw: str) -> str:
    server = raw.strip().rstrip("/")
    if not server.startswith(("http://", "https://")):
        server = f"http://{server}"
    return server


async def _validate_connection(hass: HomeAssistant, server: str, device_id: str) -> None:
    """Open a WebSocket to the server; raises on failure."""
    url = build_ws_url(server, device_id)
    session = async_get_clientsession(hass, verify_ssl=False)
    try:
        async with asyncio.timeout(8):
            async with session.ws_connect(url, heartbeat=15) as ws:
                if ws.closed:
                    raise ConnectionError("WebSocket closed during handshake")
                # Wait briefly for the first pushed message as a bonus sanity
                # check that the server accepts this device (optional).
                try:
                    await asyncio.wait_for(ws.receive(), timeout=2)
                except asyncio.TimeoutError:
                    pass
    except asyncio.TimeoutError as err:
        raise ConnectionError("Connection timed out") from err
    except aiohttp.ClientError as err:
        raise ConnectionError(str(err)) from err


class SolarProjectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the SolarProject integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            if not DEVICE_ID_REGEX.match(device_id):
                errors[CONF_DEVICE_ID] = "invalid_device_id"
            else:
                server = _normalize_server(user_input[CONF_SERVER])
                try:
                    await _validate_connection(self.hass, server, device_id)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "SolarProject connection test failed: %s", err
                    )
                    errors["base"] = "cannot_connect"

                if not errors:
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                    data = {
                        CONF_SERVER: server,
                        CONF_DEVICE_ID: device_id,
                        CONF_FAST_DATA_INTERVAL: DEFAULT_FAST_DATA_INTERVAL,
                    }
                    if user_input.get(CONF_NAME):
                        data[CONF_NAME] = user_input[CONF_NAME].strip()
                    if user_input.get(CONF_SENSOR_PREFIX):
                        data[CONF_SENSOR_PREFIX] = user_input[
                            CONF_SENSOR_PREFIX
                        ].strip()
                    return self.async_create_entry(
                        title=data.get(CONF_NAME) or device_id,
                        data=data,
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_SERVER, default=DEFAULT_SERVER): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Required(CONF_DEVICE_ID): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Optional(CONF_NAME): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Optional(CONF_SENSOR_PREFIX): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"device_id": "dg-abc123"},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SolarProjectOptionsFlow()


class SolarProjectOptionsFlow(OptionsFlow):
    """Options flow: edit server URL, device name and sensor prefix."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            server = _normalize_server(user_input[CONF_SERVER])
            data = {**self.config_entry.data, CONF_SERVER: server}
            if user_input.get(CONF_NAME):
                data[CONF_NAME] = user_input[CONF_NAME].strip()
            else:
                data.pop(CONF_NAME, None)
            if user_input.get(CONF_SENSOR_PREFIX):
                data[CONF_SENSOR_PREFIX] = user_input[CONF_SENSOR_PREFIX].strip()
            else:
                data.pop(CONF_SENSOR_PREFIX, None)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=data,
            )
            await self.hass.config_entries.async_reload(
                self.config_entry.entry_id
            )
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SERVER, default=current.get(CONF_SERVER, DEFAULT_SERVER)
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Optional(CONF_NAME, default=current.get(CONF_NAME, "")): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_SENSOR_PREFIX, default=current.get(CONF_SENSOR_PREFIX, "")
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)