"""Local inverter select controls."""
from homeassistant.components.select import SelectEntity

from .settings import SolarSettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "select", SolarInverterSelect)


class SolarInverterSelect(SolarSettingEntity, SelectEntity):
    @property
    def current_option(self):
        return self.value

    @property
    def options(self):
        return self.spec.get("options", [])

    async def async_select_option(self, option):
        await self.write(option)
