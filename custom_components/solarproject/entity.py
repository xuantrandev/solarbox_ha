"""Shared entity naming and migration of prefix-based registry identities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.util import slugify

from .const import (
    BIN_BMS_CHG,
    BIN_BMS_CONNECTED,
    BIN_BMS_DISCHG,
    BIN_FIX_LUX_SERVER,
    BIN_LUX_SERVER,
    BIN_ONLINE,
    BMS_CELL_DEF,
    BMS_FIELDS,
    BMS_MAC_TEXT_DEF,
    BMS_MAX_CELLS,
    BMS_SLOTS,
    DOMAIN,
    INVERTER_FIELDS,
    STATISTIC_FIELDS,
    TEXT_FIELDS,
    WIFI_SIGNAL_DEF,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import SolarProjectCoordinator

_LOGGER = logging.getLogger(__name__)


def entity_object_id(prefix: str, name: str) -> str:
    """Use the configured prefix independently of the device/friendly name."""
    return slugify(f"{prefix}_{name}")


class SolarEntityNaming:
    """Suggest IDs for new entities without changing their friendly names."""

    # Constructors also set entity_id explicitly: HA 2026.10 treats a plain
    # suggested_object_id as a base to which it can prepend the device name.

    _attr_has_entity_name = False

    @property
    def suggested_object_id(self) -> str:
        return entity_object_id(self._coordinator.prefix, self.name)


def entity_unique_id(
    coordinator: SolarProjectCoordinator, platform: str, key: str
) -> str:
    """Reuse a registry identity when a prefix migration encountered a conflict."""
    return coordinator.entity_unique_ids.get(
        (platform, key), f"{DOMAIN}_{coordinator.prefix}_{key}"
    )


def _known_names() -> dict[str, dict[str, str]]:
    """Map stable telemetry keys, including not-yet-discovered cells, to names."""
    sensors = {
        key: spec.name
        for fields in (INVERTER_FIELDS, STATISTIC_FIELDS, TEXT_FIELDS)
        for key, spec in fields.items()
    }
    sensors["wifi_signal"] = WIFI_SIGNAL_DEF.name
    binary = {
        BIN_ONLINE: "Online",
        BIN_LUX_SERVER: "Lux Cloud",
        BIN_FIX_LUX_SERVER: "Lux Cloud Fix",
    }
    switches = {}
    for slot in BMS_SLOTS:
        sensors.update({
            f"bms{slot}_{key}": spec.name.format(n=slot)
            for key, spec in BMS_FIELDS.items()
        })
        sensors[f"bms{slot}_mac"] = BMS_MAC_TEXT_DEF.name.format(n=slot)
        sensors.update({
            f"bms{slot}_vcells_{index}": BMS_CELL_DEF.name.format(n=slot, i=index)
            for index in range(1, BMS_MAX_CELLS + 1)
        })
        binary.update({
            BIN_BMS_CONNECTED.format(n=slot): f"bms{slot} online status",
            BIN_BMS_CHG.format(n=slot): f"bms{slot} charging",
            BIN_BMS_DISCHG.format(n=slot): f"bms{slot} discharging",
        })
        switches.update({
            BIN_BMS_CHG.format(n=slot): f"bms{slot} charging",
            BIN_BMS_DISCHG.format(n=slot): f"bms{slot} discharging",
        })
    return {"sensor": sensors, "binary_sensor": binary, "switch": switches}


def _identity(
    registered: entity_registry.RegistryEntry, names: dict[str, dict[str, str]]
) -> tuple[str, str, str | None] | None:
    """Recover the old prefix and stable key; leave ambiguous identities alone."""
    if not registered.unique_id.startswith(f"{DOMAIN}_"):
        return None
    identity = registered.unique_id[len(DOMAIN) + 1:]
    platform = registered.domain
    matches = []
    for key, name in names.get(platform, {}).items():
        suffix = f"_{key}"
        if identity.endswith(suffix) and (prefix := identity[:-len(suffix)]):
            matches.append((prefix, key, name))
    if matches:
        named_matches = [match for match in matches if match[2] == registered.original_name]
        candidates = named_matches or matches
        return candidates[0] if len(candidates) == 1 else None
    if platform in ("number", "select", "switch") and identity.count("_ctl_") == 1:
        prefix, _, suffix = identity.partition("_ctl_")
        if prefix and suffix and len(suffix) + 4 <= 64:
            return prefix, f"ctl_{suffix}", registered.original_name
    return None


@callback
def async_migrate_entity_ids(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SolarProjectCoordinator
) -> None:
    """Migrate this entry before platform setup, preserving registry records."""
    registry = entity_registry.async_get(hass)
    devices = device_registry.async_get(hass)
    names = _known_names()
    for registered in entity_registry.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        if registered.platform != DOMAIN:
            continue
        identity = _identity(registered, names)
        if identity is None:
            continue
        old_prefix, key, name = identity
        platform = registered.domain
        unique_id = f"{DOMAIN}_{coordinator.prefix}_{key}"
        if unique_id != registered.unique_id:
            occupied = registry.async_get_entity_id(platform, DOMAIN, unique_id)
            if occupied is not None:
                _LOGGER.warning(
                    "Skipping unique ID migration for %s: %s already uses %s",
                    registered.entity_id, occupied, unique_id,
                )
                # Do not create a third entity or take over another entry's entity.
                if registry.async_get(occupied).config_entry_id != entry.entry_id:
                    coordinator.entity_unique_ids[(platform, key)] = registered.unique_id
                continue
            registered = registry.async_update_entity(
                registered.entity_id, new_unique_id=unique_id
            )

        if not name:
            continue
        device = devices.async_get(registered.device_id) if registered.device_id else None
        prefixes = {
            old_prefix, coordinator.prefix, coordinator.device_id,
            entry.data.get(CONF_NAME),
        }
        if device is not None:
            prefixes.update((device.name, device.name_by_user))
        old_names = {name, registered.original_name} - {None, ""}
        generated_ids = {f"{platform}.{slugify(old_name)}" for old_name in old_names}
        generated_ids.update(
            f"{platform}.{entity_object_id(prefix, old_name)}"
            for prefix in prefixes if prefix
            for old_name in old_names
        )
        target = f"{platform}.{entity_object_id(coordinator.prefix, name)}"
        if registered.entity_id == target or registered.entity_id not in generated_ids:
            continue
        if registry.async_get(target) is not None or not hass.states.async_available(target):
            _LOGGER.warning(
                "Skipping entity ID migration for %s: %s is occupied",
                registered.entity_id, target,
            )
            continue
        registry.async_update_entity(registered.entity_id, new_entity_id=target)
