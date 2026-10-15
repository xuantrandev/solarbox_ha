"""Sensor platform for the SolarProject integration.

Creates one entity per known field of the solardongleweb payload: inverter
live data, lifetime statistics, BMS scalars per slot, dynamic BMS cell
voltages, and read-only text fields. Entities stay "unknown" until their
field first arrives over the WebSocket.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_coordinator
from .const import (
    BMS_CELL_DEF,
    BMS_FIELDS,
    BMS_MAC_TEXT_DEF,
    BMS_MAX_CELLS,
    BMS_SLOTS,
    CONF_DEVICE_ID,
    DOMAIN,
    INVERTER_FIELDS,
    STATISTIC_FIELDS,
    TEXT_FIELDS,
    WIFI_SIGNAL_DEF,
    SensorDef,
)
from .coordinator import SolarProjectCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one dongle config entry."""
    coordinator = get_coordinator(hass, entry)
    entities: list[SensorEntity] = []

    for key in INVERTER_FIELDS:
        entities.append(SolarSensorEntity(coordinator, key, entry))
    for key in STATISTIC_FIELDS:
        entities.append(SolarSensorEntity(coordinator, key, entry))
    for key in TEXT_FIELDS:
        entities.append(SolarTextSensor(coordinator, key, entry))
    entities.append(
        SolarSensorEntity(coordinator, "wifi_signal", entry, spec=WIFI_SIGNAL_DEF)
    )
    for slot in BMS_SLOTS:
        for key in BMS_FIELDS:
            entities.append(BmsScalarSensor(coordinator, slot, key, entry))
        entities.append(BmsMacSensor(coordinator, slot, entry))

    async_add_entities(entities)

    async def add_cells(slot: str, indices: list[int]) -> None:
        async_add_entities(
            [BmsCellSensor(coordinator, slot, i, entry) for i in indices]
        )

    coordinator.register_cell_adder(add_cells)


def _device_info(coordinator: SolarProjectCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Device registry info for the dongle."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=entry.data.get(CONF_NAME) or coordinator.device_id,
        manufacturer="solarbox.uk",
        model=f"Solar Dongle ({coordinator.device_id})",
        sw_version=coordinator.data.get("device_info_version"),
        configuration_url=f"{coordinator.server}/{coordinator.device_id}",
    )


class _SolarSensorBase(SensorEntity):
    """Base entity bound to the coordinator's latest-state map."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: SolarProjectCoordinator,
        key: str,
        entry: ConfigEntry,
        *,
        name: str,
        unit: str | None = None,
        device_class: str | None = None,
        state_class: str | None = None,
        icon: str | None = None,
        scale: float = 1.0,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._entry = entry
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._scale = scale
        self._attr_unique_id = f"{DOMAIN}_{coordinator.prefix}_{key}"
        self._attr_device_info = _device_info(coordinator, entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._coordinator.async_add_listener(self._handle_update)
        self._handle_update()

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.async_remove_listener(self._handle_update)
        await super().async_will_remove_from_hass()

    @property
    def available(self):
        return self._coordinator.online

    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        value = self._coordinator.data.get(self._key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return round(float(value) * self._scale, 3)


class SolarSensorEntity(_SolarSensorBase):
    """Entity for a flat field (inverter live / statistics)."""

    def __init__(
        self,
        coordinator: SolarProjectCoordinator,
        key: str,
        entry: ConfigEntry,
        *,
        spec: SensorDef | None = None,
    ) -> None:
        if spec is None:
            spec = INVERTER_FIELDS.get(key) or STATISTIC_FIELDS.get(key)
        super().__init__(
            coordinator,
            key,
            entry,
            name=spec.name,
            unit=spec.unit,
            device_class=spec.device_class,
            state_class=spec.state_class,
            icon=spec.icon,
            scale=spec.scale,
        )


class BmsScalarSensor(_SolarSensorBase):
    """Entity for one scalar field of one BMS slot (bms1/bms2/bms3)."""

    def __init__(
        self,
        coordinator: SolarProjectCoordinator,
        slot: int,
        key: str,
        entry: ConfigEntry,
    ) -> None:
        spec = BMS_FIELDS[key]
        self._slot = slot
        super().__init__(
            coordinator,
            f"bms{slot}_{key}",
            entry,
            name=spec.name.format(n=slot),
            unit=spec.unit,
            device_class=spec.device_class,
            state_class=spec.state_class,
            icon=spec.icon,
            scale=spec.scale,
        )


class BmsCellSensor(_SolarSensorBase):
    """Entity for one BMS cell voltage (created dynamically on first data)."""

    def __init__(
        self,
        coordinator: SolarProjectCoordinator,
        slot: str,
        cell_index: int,
        entry: ConfigEntry,
    ) -> None:
        if cell_index > BMS_MAX_CELLS:
            raise ValueError(f"Cell index {cell_index} exceeds {BMS_MAX_CELLS}")
        if slot.startswith("bms"):
            slot_num = slot[3:]
            slot_key = slot
        else:
            slot_num = slot
            slot_key = f"bms{slot}"
        self._slot = slot_key
        self._cell_index = cell_index
        super().__init__(
            coordinator,
            f"{slot_key}_vcells_{cell_index}",
            entry,
            name=BMS_CELL_DEF.name.format(n=slot_num, i=cell_index),
            unit=BMS_CELL_DEF.unit,
            device_class=BMS_CELL_DEF.device_class,
            state_class=BMS_CELL_DEF.state_class,
            icon=BMS_CELL_DEF.icon,
            scale=BMS_CELL_DEF.scale,
        )


class BmsMacSensor(_SolarSensorBase):
    """Entity for one BMS slot's MAC address (text)."""

    def __init__(
        self,
        coordinator: SolarProjectCoordinator,
        slot: int,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            coordinator,
            f"bms{slot}_mac",
            entry,
            name=BMS_MAC_TEXT_DEF.name.format(n=slot),
            unit=None,
            device_class=None,
            state_class=None,
            icon=BMS_MAC_TEXT_DEF.icon,
            scale=1.0,
        )

    @property
    def native_value(self) -> str | None:
        value = self._coordinator.data.get(self._key)
        if value is None:
            return None
        return str(value)


class SolarTextSensor(_SolarSensorBase):
    """Read-only string field (inverter type, serial, IPs, device info)."""

    def __init__(
        self, coordinator: SolarProjectCoordinator, key: str, entry: ConfigEntry
    ) -> None:
        spec = TEXT_FIELDS[key]
        super().__init__(
            coordinator,
            key,
            entry,
            name=spec.name,
            unit=None,
            device_class=None,
            state_class=None,
            icon=spec.icon,
            scale=1.0,
        )

    @property
    def native_value(self) -> str | None:
        value: Any = self._coordinator.data.get(self._key)
        if value is None:
            return None
        return str(value)