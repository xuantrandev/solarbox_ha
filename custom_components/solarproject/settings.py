"""Shared discovery and entities for the local inverter settings protocol."""
from __future__ import annotations

from homeassistant.helpers.entity import Entity, EntityCategory

from . import get_coordinator
from .entity import SolarEntityNaming, entity_unique_id
from .sensor import _device_info


def setup_controls(hass, entry, async_add_entities, platform, entity_class):
    """Listen before or after the first catalog; add each key once per platform load."""
    coordinator = get_coordinator(hass, entry)
    created = set()

    def discover():
        entities = []
        for key, spec in coordinator.settings_catalog.items():
            if spec["platform"] == platform and key not in created:
                created.add(key)
                entities.append(entity_class(coordinator, entry, key))
        if entities:
            async_add_entities(entities)

    coordinator.async_add_listener(discover)
    entry.async_on_unload(lambda: coordinator.async_remove_listener(discover))
    discover()


class SolarSettingEntity(SolarEntityNaming, Entity):
    """A control whose state is exclusively inverter readback."""
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, key):
        self._coordinator = coordinator
        self._key = key
        self._platform = self.spec["platform"]
        self._attr_unique_id = entity_unique_id(coordinator, self._platform, key)
        self.entity_id = f"{self._platform}.{self.suggested_object_id}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def spec(self):
        return self._coordinator.settings_catalog.get(self._key, {})

    @property
    def name(self):
        return self.spec.get("name", self._key)

    @property
    def icon(self):
        return self.spec.get("icon") or None

    @property
    def available(self):
        return (self._coordinator.online and self._coordinator.settings_available
                and self.spec.get("platform") == self._platform
                and self._key in self._coordinator.settings_state)

    @property
    def value(self):
        return self._coordinator.settings_state.get(self._key)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._coordinator.async_add_listener(self.async_write_ha_state)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        self._coordinator.async_remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()

    async def write(self, value):
        await self._coordinator.async_write_setting(self._key, value)
