"""Local inverter number controls."""
from homeassistant.components.number import NumberEntity, NumberMode

from .settings import SolarSettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "number", SolarInverterNumber)


class SolarInverterNumber(SolarSettingEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    @property
    def native_value(self):
        return self.value

    @property
    def native_min_value(self):
        return self.spec.get("min", 0)

    @property
    def native_max_value(self):
        return self.spec.get("max", 0)

    @property
    def native_step(self):
        return self.spec.get("step", 1)

    @property
    def native_unit_of_measurement(self):
        return self.spec.get("unit") or None

    async def async_set_native_value(self, value):
        await self.write(value)
