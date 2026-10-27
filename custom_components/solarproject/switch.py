"""Local inverter controls and read-only BMS charge/discharge switches."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from . import get_coordinator
from .const import BIN_BMS_CHG, BIN_BMS_DISCHG, BMS_SLOTS, has_bms, is_mq_profile
from .entity import SolarEntityNaming, entity_unique_id
from .sensor import _device_info
from .settings import SolarSettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "switch", SolarInverterSwitch)
    if not has_bms(entry):
        return
    coordinator = get_coordinator(hass, entry)
    async_add_entities([
        SolarBmsStateSwitch(coordinator, entry, key.format(n=slot),
                            f"bms{slot} {name}", icon)
        for slot in BMS_SLOTS
        for key, name, icon in (
            (BIN_BMS_CHG, "charging", "mdi:battery-charging"),
            (BIN_BMS_DISCHG, "discharging", "mdi:power-plug"),
        )
    ])


class SolarInverterSwitch(SolarSettingEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.value

    async def async_turn_on(self, **kwargs):
        await self.write(True)

    async def async_turn_off(self, **kwargs):
        await self.write(False)


class SolarBmsStateSwitch(SolarEntityNaming, SwitchEntity):
    """Mirror a reported BMS switch state without allowing writes."""

    _attr_should_poll = False

    def __init__(self, coordinator, entry, key, name, icon):
        self._entry = entry
        self._coordinator = coordinator
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = entity_unique_id(coordinator, "switch", key)
        self.entity_id = f"switch.{self.suggested_object_id}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self):
        return self._coordinator.online

    @property
    def is_on(self):
        key = self._key
        if is_mq_profile(self._entry):
            key = key.replace("_dischg", "_native_discharging").replace("_chg", "_native_charging")
        return self._coordinator.data.get(key)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._coordinator.async_add_listener(self.async_write_ha_state)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        self._coordinator.async_remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs):
        raise HomeAssistantError(f"{self.name} is read-only")

    async def async_turn_off(self, **kwargs):
        raise HomeAssistantError(f"{self.name} is read-only")
