from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    grouped_macs = set()

    # Una entidad estable por grupo lógico, incluso si el iPhone está desconectado.
    for key, group in coordinator.mac_groups.items():
        grouped_macs.update(group["macs"])
        entities.append(
            MitrastarLogicalDeviceSensor(coordinator, entry, key, group["name"], group["macs"])
        )

    # Las MAC que no estén asociadas a un grupo siguen funcionando como antes.
    seen = set()
    for device in coordinator.data or []:
        mac = device["mac"].upper()
        if mac in grouped_macs or mac in seen:
            continue
        seen.add(mac)
        entities.append(MitrastarOnlineSensor(coordinator, entry, mac))

    async_add_entities(entities + [MitrastarInternetBinarySensor(coordinator, entry)])

    # Añadir nuevas MAC no agrupadas que aparezcan en futuras actualizaciones.
    known_entities = {e._mac for e in entities if isinstance(e, MitrastarOnlineSensor)}

    def add_new_devices():
        new_entities = []
        current_grouped_macs = set()
        for group in coordinator.mac_groups.values():
            current_grouped_macs.update(group["macs"])
        for device in coordinator.data or []:
            mac = device["mac"].upper()
            if mac in current_grouped_macs or mac in known_entities:
                continue
            known_entities.add(mac)
            new_entities.append(MitrastarOnlineSensor(coordinator, entry, mac))
        if new_entities:
            async_add_entities(new_entities)

    unsub = coordinator.async_add_listener(add_new_devices)
    entry.async_on_unload(unsub)


class MitrastarLogicalDeviceSensor(CoordinatorEntity, BinarySensorEntity):
    """Presence sensor representing one physical device with one or more MACs."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name, macs):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._macs = {mac.upper() for mac in macs}
        self._attr_unique_id = f"{entry.entry_id}_logical_device_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "logical", key)},
            "name": name,
            "manufacturer": "Apple" if name.lower().startswith("iphone") else "Personalizado",
            "model": "Dispositivo lógico agrupado",
            "via_device": (DOMAIN, entry.entry_id),
        }

    @property
    def is_on(self):
        return self.coordinator.logical_device_is_online(self._macs)

    @property
    def extra_state_attributes(self):
        current = {
            d["mac"].upper(): d for d in (self.coordinator.data or [])
        }
        online = [current[mac] for mac in sorted(self._macs) if mac in current]
        connected_ips = [d["ip"] for d in online]
        return {
            # Para un grupo lógico, se muestran todas las IP activas en un único
            # atributo de texto; ips_conectadas se conserva por compatibilidad.
            "ip_address": ", ".join(connected_ips) if connected_ips else None,
            "macs_asociadas": sorted(self._macs),
            "macs_conectadas": [d["mac"] for d in online],
            "ips_conectadas": connected_ips,
            "cantidad_macs_conectadas": len(online),
        }


class MitrastarOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = None

    def __init__(self, coordinator, entry, mac):
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{entry.entry_id}_device_{mac.replace(':', '').lower()}"
        self._attr_name = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, mac)},
            "name": self._device_name,
            "manufacturer": "Mitrastar",
            "model": "Dispositivo de red",
            "via_device": (DOMAIN, entry.entry_id),
        }

    @property
    def _device(self):
        for item in self.coordinator.data or []:
            if item["mac"].upper() == self._mac:
                return item
        return None

    @property
    def _device_name(self):
        device = self._device
        return device["name"] if device else self._mac

    @property
    def name(self):
        return self._device_name

    @property
    def is_on(self):
        return self._device is not None

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self):
        device = self._device
        if not device:
            return {"mac": self._mac}
        return {
            "mac": device["mac"],
            "ip": device["ip"],
            "ip_address": device["ip"],
            "ipv6_link_local": device.get("ipv6_link_local"),
            "ipv6_global": device.get("ipv6_global"),
        }


class MitrastarInternetBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Internet disponible"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_internet_available"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Mitrastar Router",
            "manufacturer": "Mitrastar",
            "model": "GPT-2841GX4X5",
        }

    @property
    def is_on(self):
        return self.coordinator.internet_ok is True

    @property
    def available(self):
        return self.coordinator.internet_ok is not None

    @property
    def extra_state_attributes(self):
        return {
            "fallos_consecutivos": self.coordinator.internet_failures,
            "estado_recuperacion": self.coordinator.recovery_state,
        }
