"""Local inverter switch controls."""
from homeassistant.components.switch import SwitchEntity

from .settings import SolarSettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "switch", SolarInverterSwitch)


class SolarInverterSwitch(SolarSettingEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.value

    async def async_turn_on(self, **kwargs):
        await self.write(True)

    async def async_turn_off(self, **kwargs):
        await self.write(False)
