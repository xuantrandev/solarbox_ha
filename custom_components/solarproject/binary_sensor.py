"""Binary sensor platform for the SolarProject integration.

Exposes the dongle online/offline state, Lux cloud connection, per-BMS
connection states, and the BMS charge/discharge switch states.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_coordinator
from .const import (
    BIN_BMS_CHG,
    BIN_BMS_CONNECTED,
    BIN_BMS_DISCHG,
    BIN_FIX_LUX_SERVER,
    BIN_LUX_SERVER,
    BIN_ONLINE,
    BMS_SLOTS,
)
from .coordinator import SolarProjectCoordinator
from .entity import SolarEntityNaming, entity_unique_id
from .sensor import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for one dongle config entry."""
    coordinator = get_coordinator(hass, entry)
    entities: list[BinarySensorEntity] = [
        SolarBinarySensor(
            coordinator, entry, BIN_ONLINE, "Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ),
        SolarBinarySensor(
            coordinator, entry, BIN_LUX_SERVER, "Lux Cloud",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ),
        SolarBinarySensor(
            coordinator, entry, BIN_FIX_LUX_SERVER, "Lux Cloud Fix",
        ),
    ]
    for slot in BMS_SLOTS:
        entities.append(
            SolarBinarySensor(
                coordinator, entry, BIN_BMS_CONNECTED.format(n=slot),
                f"bms{slot} online status",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            )
        )
        entities.append(
            SolarBinarySensor(
                coordinator, entry, BIN_BMS_CHG.format(n=slot),
                f"bms{slot} charging",
            )
        )
        entities.append(
            SolarBinarySensor(
                coordinator, entry, BIN_BMS_DISCHG.format(n=slot),
                f"bms{slot} discharging",
            )
        )
    async_add_entities(entities)


class SolarBinarySensor(SolarEntityNaming, BinarySensorEntity):
    """Binary sensor backed by a key in the coordinator state map."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: SolarProjectCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        *,
        device_class: str | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_unique_id = entity_unique_id(coordinator, "binary_sensor", key)
        self.entity_id = f"binary_sensor.{self.suggested_object_id}"
        self._attr_device_info = _device_info(coordinator, entry)
        self._attr_icon = "mdi:power-plug" if device_class else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._coordinator.async_add_listener(self._handle_update)
        self._handle_update()

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.async_remove_listener(self._handle_update)
        await super().async_will_remove_from_hass()

    @property
    def available(self):
        return self._key == BIN_ONLINE or self._coordinator.online

    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        if self._key == BIN_ONLINE:
            return self._coordinator.online
        value = self._coordinator.data.get(self._key)
        if value is None:
            return None
        return bool(value)
