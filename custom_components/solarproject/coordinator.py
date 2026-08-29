"""WebSocket coordinator for the SolarProject integration.

Connects to the solardongleweb WebSocket endpoint (/ws/<deviceId>), parses the
pushed messages (snapshot, ivtdata, bmsData, deviceStatus, deviceInfo,
wifiSignal, dongle SN, Lux server IP, switch states) into a flat latest-state
dict, and notifies subscribed entities. Optionally sends a
"requestDataUpdate" message every N seconds so the dongle stays in fast-data
mode and pushes fresh values.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    BMS_SLOTS,
    CONF_DEVICE_ID,
    CONF_FAST_DATA_INTERVAL,
    CONF_SENSOR_PREFIX,
    CONF_SERVER,
    MSG_BMSDATA,
    MSG_DEVICE_INFO,
    MSG_DEVICE_STATUS,
    MSG_DONGLE_SN,
    MSG_FIX_LUX_SERVER_STATE,
    MSG_IVTDATA,
    MSG_LUX_CLOUD_BMS_STATE,
    MSG_LUX_SERVER_IP,
    MSG_LUX_SERVER_STATE,
    MSG_WIFI_SIGNAL,
    WS_RECONNECT_MAX,
    WS_RECONNECT_MIN,
)

_LOGGER = logging.getLogger(__name__)

CellAdder = Callable[[str, list[int]], Awaitable[None]]

_SWITCH_STATE_KEYS = {
    MSG_LUX_SERVER_STATE: "lux_server_state",
    MSG_LUX_CLOUD_BMS_STATE: "lux_cloud_bms_state",
    MSG_FIX_LUX_SERVER_STATE: "fix_lux_server_state",
}


def build_ws_url(server: str, device_id: str) -> str:
    """Convert http(s)://host:port + device id to the WS endpoint URL."""
    if server.startswith("https://"):
        return f"wss://{server[8:]}/ws/{device_id}"
    if server.startswith("http://"):
        return f"ws://{server[7:]}/ws/{device_id}"
    return f"ws://{server}/ws/{device_id}"


def _to_bool(value: Any) -> bool:
    """Normalize ON/OFF/1/true style switch values to a bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().upper() in ("ON", "TRUE", "YES", "1")
    return False


class SolarProjectCoordinator:
    """Maintains the latest state of one solar dongle."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self.hass = hass
        self.server = config[CONF_SERVER]
        self.device_id = config[CONF_DEVICE_ID]
        self.fast_data_interval = int(config.get(CONF_FAST_DATA_INTERVAL) or 0)
        self.prefix = str(config.get(CONF_SENSOR_PREFIX) or self.device_id)

        # Flat latest-state map: "pdc1" -> value, "bms1_soc" -> value, ...
        self.data: dict[str, Any] = {}
        self.online = False

        self._listeners: set[Callable[[], None]] = set()
        self._cell_adder: CellAdder | None = None
        self._created_cells: set[str] = set()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._close_event = asyncio.Event()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def async_start(self) -> None:
        """Start the WebSocket worker task."""
        self._close_event.clear()
        self._task = self.hass.async_create_task(
            self._run(), name=f"solarproject-ws-{self.device_id}"
        )

    async def async_stop(self) -> None:
        """Stop the WebSocket worker task and close the connection."""
        self._close_event.set()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ── listener registry ─────────────────────────────────────────────────────
    def async_add_listener(self, update_callback: Callable[[], None]) -> None:
        self._listeners.add(update_callback)

    def async_remove_listener(self, update_callback: Callable[[], None]) -> None:
        self._listeners.discard(update_callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 - listener must never break the loop
                _LOGGER.exception("Error in coordinator listener")

    # ── dynamic BMS cell entities ─────────────────────────────────────────────
    def register_cell_adder(self, adder: CellAdder) -> None:
        """Register the sensor platform's async_add_entities wrapper."""
        self._cell_adder = adder
        for slot in BMS_SLOTS:
            count = self.data.get(f"bms{slot}_cell_count", 0)
            if count:
                self._maybe_create_cells(str(slot), count)

    def _maybe_create_cells(self, slot: str, count: int) -> None:
        if not slot.startswith("bms"):
            slot = f"bms{slot}"
        if not self._cell_adder:
            return
        missing = [
            i for i in range(1, count + 1) if f"{slot}_{i}" not in self._created_cells
        ]
        if not missing:
            return
        for i in missing:
            self._created_cells.add(f"{slot}_{i}")
        self.hass.async_create_task(self._cell_adder(slot, missing))

    # ── worker loop ───────────────────────────────────────────────────────────
    async def _run(self) -> None:
        backoff = WS_RECONNECT_MIN
        while not self._close_event.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "SolarProject %s WebSocket error: %s", self.device_id, err
                )
            self._set_online(False)
            _LOGGER.debug(
                "SolarProject %s reconnecting in %ss", self.device_id, backoff
            )
            try:
                await asyncio.wait_for(self._close_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, WS_RECONNECT_MAX)

    async def _connect_and_listen(self) -> None:
        url = build_ws_url(self.server, self.device_id)
        session = async_get_clientsession(self.hass, verify_ssl=False)
        _LOGGER.info("SolarProject %s connecting to %s", self.device_id, url)
        async with session.ws_connect(
            url, heartbeat=30, max_msg_size=1024 * 1024
        ) as ws:
            self._ws = ws
            self._set_online(False)
            fastdata_task = None
            if self.fast_data_interval >= 5:
                fastdata_task = self.hass.async_create_task(self._fastdata_loop(ws))
            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            self._process_message(json.loads(msg.data))
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "SolarProject %s failed to parse WS message",
                                self.device_id,
                            )
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
            finally:
                self._ws = None
                if fastdata_task:
                    fastdata_task.cancel()
                    try:
                        await fastdata_task
                    except asyncio.CancelledError:
                        pass

    async def _fastdata_loop(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> None:
        """Request fast data from the dongle every configured interval."""
        interval = self.fast_data_interval
        while not self._close_event.is_set():
            try:
                await asyncio.wait_for(
                    self._close_event.wait(), timeout=interval
                )
                return
            except asyncio.TimeoutError:
                pass
            if ws.closed:
                return
            try:
                await ws.send_json(
                    {"type": "requestDataUpdate", "deviceId": self.device_id}
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "SolarProject %s fastdata request failed", self.device_id
                )
                return

    # ── state helpers ─────────────────────────────────────────────────────────
    def _set_online(self, online: bool) -> None:
        if self.online != online:
            self.online = online
            self._notify()

    # ── message parsing ───────────────────────────────────────────────────────
    def _process_message(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        msg_type = payload.get("type")

        if msg_type is None and isinstance(payload.get("data"), dict):
            # Initial cached-state snapshot pushed on connect (no "type").
            self._merge_data(payload["data"])
            self._set_online(True)
            self._notify()
            return

        if msg_type == MSG_IVTDATA:
            if isinstance(payload.get("data"), dict):
                self._merge_data(payload["data"])
            self._set_online(True)
            self._notify()
            return

        if msg_type == MSG_BMSDATA:
            slot = str(payload.get("bmsType") or "bms1")
            if isinstance(payload.get("data"), dict):
                self._merge_bms(slot, payload["data"])
            self._set_online(True)
            self._notify()
            return

        if msg_type == MSG_DEVICE_STATUS:
            self._set_online(payload.get("status") == "online")
            self._notify()
            return

        if msg_type == MSG_DEVICE_INFO:
            info = payload.get("data") or {}
            if isinstance(info, dict):
                for key in (
                    "name",
                    "version",
                    "project_name",
                    "project_version",
                    "ip",
                    "mac",
                ):
                    if key in info:
                        self.data[f"device_info_{key}"] = info[key]
                self._notify()
            return

        if msg_type == MSG_WIFI_SIGNAL:
            signal = (payload.get("data") or {}).get("signal")
            if isinstance(signal, (int, float)):
                self.data["wifi_signal"] = float(signal)
                self._notify()
            return

        if msg_type == MSG_DONGLE_SN:
            self.data["dongle_sn"] = payload.get("value")
            self._notify()
            return

        if msg_type == MSG_LUX_SERVER_IP:
            self.data["lux_server_ip"] = payload.get("value")
            self._notify()
            return

        if msg_type in _SWITCH_STATE_KEYS:
            self.data[_SWITCH_STATE_KEYS[msg_type]] = _to_bool(
                payload.get("state")
            )
            self._notify()
            return

        if msg_type.startswith("bms") and msg_type.endswith("ConnectionState"):
            slot = msg_type.replace("ConnectionState", "").replace("bms", "")
            self.data[f"bms{slot}_connected"] = _to_bool(payload.get("state"))
            self._notify()
            return

    def _merge_data(self, data: dict[str, Any]) -> None:
        """Merge inverter live/statistic fields into the latest-state map."""
        for key, value in data.items():
            if key == "timestamp" or key == "ble":
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.data[key] = value
            elif isinstance(value, str):
                self.data[key] = value

    def _merge_bms(self, slot: str, data: dict[str, Any]) -> None:
        """Merge one BMS slot payload into the latest-state map."""
        for key, value in data.items():
            if key == "vcells":
                if not isinstance(value, list):
                    continue
                self.data[f"{slot}_cell_count"] = len(value)
                for i, cell in enumerate(value, 1):
                    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                        self.data[f"{slot}_vcells_{i}"] = cell
                self._maybe_create_cells(slot, len(value))
            elif key in ("chg", "dischg"):
                self.data[f"{slot}_{key}"] = value in (1, "ON", True)
            elif key == "mac":
                self.data[f"{slot}_mac"] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                self.data[f"{slot}_{key}"] = value