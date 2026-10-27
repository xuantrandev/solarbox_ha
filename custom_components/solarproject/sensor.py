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
    BMS_NATIVE_KEYS,
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
    MQ_FIELDS,
    MQ_NATIVE_POWER_KEYS,
    MQ_TEXT_FIELDS,
    is_mq_profile,
    mq_native_fields,
)
from .coordinator import SolarProjectCoordinator
from .entity import SolarEntityNaming, entity_unique_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one dongle config entry."""
    coordinator = get_coordinator(hass, entry)
    entities: list[SensorEntity] = []

    if is_mq_profile(entry):
        numeric = {**MQ_FIELDS, **mq_native_fields()}
        texts = {
            **{key: spec for key, spec in TEXT_FIELDS.items() if key.startswith("device_info_")},
            **MQ_TEXT_FIELDS,
            **mq_native_fields(text=True),
        }
        wifi_spec = WIFI_SIGNAL_DEF._replace(name="Dongle WiFi Signal Strength")
    else:
        numeric = {**INVERTER_FIELDS, **STATISTIC_FIELDS}
        texts = TEXT_FIELDS
        wifi_spec = WIFI_SIGNAL_DEF
    for key, spec in numeric.items():
        entities.append(SolarSensorEntity(coordinator, key, entry, spec=spec))
    for key, spec in texts.items():
        entities.append(SolarTextSensor(coordinator, key, entry, spec=spec))
    entities.append(SolarSensorEntity(coordinator, "wifi_signal", entry, spec=wifi_spec))
    for slot in BMS_SLOTS:
        for key in BMS_FIELDS:
            if is_mq_profile(entry) and key == "t5":
                continue  # The reference has four probes plus MOSFET temperature.
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


class _SolarSensorBase(SolarEntityNaming, SensorEntity):
    """Base entity bound to the coordinator's latest-state map."""

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
        precision: int = 3,
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
        self._precision = precision
        self._attr_unique_id = entity_unique_id(coordinator, "sensor", key)
        self.entity_id = f"sensor.{self.suggested_object_id}"
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
        native_key = MQ_NATIVE_POWER_KEYS.get(self._key)
        if native_key and native_key in self._coordinator.data:
            value = self._coordinator.data[native_key]
            return round(float(value), 3) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        key = self._key[3:] if self._key.startswith("mq_") else self._key
        value = self._coordinator.data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return round(float(value) * self._scale, self._precision)


class SolarSensorEntity(_SolarSensorBase):
    """Entity for inverter live / statistics fields and total PV power."""

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
            precision=spec.precision,
        )

    @property
    def native_value(self) -> float | None:
        if self._key != "pv_power":
            return super().native_value
        powers = [
            value
            for key in ("pdc1", "pdc2", "pdc3")
            if isinstance(value := self._coordinator.data.get(key), (int, float))
            and not isinstance(value, bool)
        ]
        return round(float(sum(powers)), 3) if powers else None


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
        self._field = key
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
            precision=spec.precision,
        )

    @property
    def native_value(self) -> float | None:
        if self._field not in ("charging_power", "discharging_power"):
            if is_mq_profile(self._entry) and self._field in BMS_NATIVE_KEYS:
                native = BMS_NATIVE_KEYS[self._field]
                value = self._coordinator.data.get(f"bms{self._slot}_native_{native}")
                return round(float(value), 3) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            return super().native_value
        power_key = f"bms{self._slot}_native_power" if is_mq_profile(self._entry) else f"bms{self._slot}_p"
        power = self._coordinator.data.get(power_key)
        if not isinstance(power, (int, float)) or isinstance(power, bool):
            return None
        if self._field == "discharging_power":
            power = -power
        return round(max(0.0, float(power)), 3)


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


    @property
    def native_value(self) -> float | None:
        if is_mq_profile(self._entry) and self._cell_index <= 16:
            value = self._coordinator.data.get(f"{self._slot}_native_cell_voltage_{self._cell_index}")
            return round(float(value), 3) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        return super().native_value


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
        key = self._key.replace("_mac", "_native_mac") if is_mq_profile(self._entry) else self._key
        value = self._coordinator.data.get(key)
        if value is None:
            return None
        return str(value)


class SolarTextSensor(_SolarSensorBase):
    """Read-only string field (inverter type, serial, IPs, device info)."""

    def __init__(
        self, coordinator: SolarProjectCoordinator, key: str, entry: ConfigEntry,
        *, spec: SensorDef | None = None,
    ) -> None:
        spec = spec or TEXT_FIELDS[key]
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
        key = self._key[3:] if self._key.startswith("mq_") else self._key
        value: Any = self._coordinator.data.get(key)
        if value is None:
            return None
        return str(value)
