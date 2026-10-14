"""Button to manually reboot the MitraStar router."""
from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MitrastarManualRebootButton(coordinator, entry)])


class MitrastarManualRebootButton(CoordinatorEntity, ButtonEntity):
    """A one-shot, user-initiated router reboot."""

    _attr_has_entity_name = True
    _attr_name = "Reinicio manual del router"
    _attr_icon = "mdi:restart-alert"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_manual_reboot_test"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Mitrastar Router",
            "manufacturer": "Mitrastar",
            "model": "GPT-2841GX4X5",
        }

    async def async_press(self):
        try:
            await self.coordinator.async_request_manual_reboot()
        except Exception as err:
            raise HomeAssistantError(str(err)) from err
