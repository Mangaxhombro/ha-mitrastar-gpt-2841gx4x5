from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MitrastarAutoRebootSwitch(coordinator, entry)])


class MitrastarAutoRebootSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Reinicio automático por fallo de Internet"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_auto_reboot"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Mitrastar Router",
            "manufacturer": "Mitrastar",
            "model": "GPT-2841GX4X5",
        }

    @property
    def is_on(self):
        return self.coordinator.auto_reboot_enabled

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_auto_reboot(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_auto_reboot(False)
