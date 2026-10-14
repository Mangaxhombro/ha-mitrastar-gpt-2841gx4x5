from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    ip_entities = _create_ip_sensors(coordinator, entry)
    async_add_entities([
        MitrastarDeviceCountSensor(coordinator, entry),
        MitrastarDeviceListSensor(coordinator, entry),
        MitrastarInternetFailuresSensor(coordinator, entry),
        MitrastarRecoveryStateSensor(coordinator, entry),
        MitrastarLastRebootSensor(coordinator, entry),
    ] + ip_entities)

    # Añadir sensores IP de dispositivos individuales que aparezcan posteriormente.
    known_macs = {
        entity._mac for entity in ip_entities
        if isinstance(entity, MitrastarDeviceIpSensor)
    }
    def add_new_ip_sensors():
        new_entities = []
        grouped = set()
        for group in coordinator.mac_groups.values():
            grouped.update(group["macs"])
        for device in coordinator.data or []:
            mac = device["mac"].upper()
            if mac in grouped or mac in known_macs:
                continue
            known_macs.add(mac)
            new_entities.append(MitrastarDeviceIpSensor(coordinator, entry, mac))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(add_new_ip_sensors))

def _create_ip_sensors(coordinator, entry):
    """Create one IP sensor for each logical group and individual device."""
    entities = []
    grouped_macs = set()
    for key, group in coordinator.mac_groups.items():
        grouped_macs.update(group["macs"])
        entities.append(
            MitrastarLogicalDeviceIpSensor(
                coordinator, entry, key, group["name"], group["macs"]
            )
        )
    seen = set()
    for device in coordinator.data or []:
        mac = device["mac"].upper()
        if mac in grouped_macs or mac in seen:
            continue
        seen.add(mac)
        entities.append(MitrastarDeviceIpSensor(coordinator, entry, mac))
    return entities


class MitrastarDeviceIpSensor(CoordinatorEntity, SensorEntity):
    """Current IPv4 address for one router device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator, entry, mac):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._mac = mac.upper()
        self._attr_unique_id = f"{entry.entry_id}_device_ip_{self._mac.replace(':', '').lower()}"
        self._attr_name = "Dirección IP"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, self._mac)},
            "name": self._device_name,
            "manufacturer": "Mitrastar",
            "model": "Dispositivo de red",
            "via_device": (DOMAIN, entry.entry_id),
        }

    @property
    def _device(self):
        return next(
            (item for item in (self.coordinator.data or [])
             if item["mac"].upper() == self._mac),
            None,
        )

    @property
    def _device_name(self):
        device = self._device
        return device["name"] if device else self._mac

    @property
    def native_value(self):
        device = self._device
        return device.get("ip") if device else None

    @property
    def available(self):
        return self.coordinator.last_update_success


class MitrastarLogicalDeviceIpSensor(CoordinatorEntity, SensorEntity):
    """Current IPv4 addresses for a grouped logical device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator, entry, key, name, macs):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._macs = {mac.upper() for mac in macs}
        self._attr_unique_id = f"{entry.entry_id}_logical_device_ip_{key}"
        self._attr_name = "Dirección IP"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "logical", key)},
            "name": name,
            "manufacturer": "Apple" if name.lower().startswith("iphone") else "Personalizado",
            "model": "Dispositivo lógico agrupado",
            "via_device": (DOMAIN, entry.entry_id),
        }

    @property
    def native_value(self):
        current = {d["mac"].upper(): d for d in (self.coordinator.data or [])}
        ips = [
            current[mac]["ip"] for mac in sorted(self._macs)
            if mac in current and current[mac].get("ip")
        ]
        return ", ".join(ips) if ips else None

    @property
    def available(self):
        return self.coordinator.last_update_success


class MitrastarBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, entry, key, name):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": "Mitrastar Router", "manufacturer": "Mitrastar", "model": "GPT-2841GX4X5"}

class MitrastarDeviceCountSensor(MitrastarBaseSensor):
    def __init__(self, coordinator, entry): super().__init__(coordinator, entry, "device_count", "Dispositivos conectados")
    @property
    def native_value(self):
        devices = self.coordinator.data or []
        grouped = set()
        count = 0
        for device in devices:
            mac = device["mac"].upper()
            key = self.coordinator.logical_device_key(mac)
            if key.startswith("group_"):
                if key not in grouped:
                    grouped.add(key)
                    count += 1
            else:
                count += 1
        return count

class MitrastarDeviceListSensor(MitrastarBaseSensor):
    def __init__(self, coordinator, entry): super().__init__(coordinator, entry, "device_list", "Lista de dispositivos")
    @property
    def native_value(self): return len(self.coordinator.data or [])
    @property
    def extra_state_attributes(self):
        devices = self.coordinator.data or []
        return {"devices": devices, "device_names": [d["name"] for d in devices], "device_ips": [d["ip"] for d in devices], "device_macs": [d["mac"] for d in devices]}

class MitrastarInternetFailuresSensor(MitrastarBaseSensor):
    _attr_native_unit_of_measurement = "fallos"
    def __init__(self, coordinator, entry): super().__init__(coordinator, entry, "internet_failures", "Fallos consecutivos de Internet")
    @property
    def native_value(self): return self.coordinator.internet_failures

class MitrastarRecoveryStateSensor(MitrastarBaseSensor):
    def __init__(self, coordinator, entry): super().__init__(coordinator, entry, "recovery_state", "Estado de recuperación")
    @property
    def native_value(self): return self.coordinator.recovery_state
    @property
    def extra_state_attributes(self):
        return {"internet_available": self.coordinator.internet_ok, "automatic_reboot_enabled": self.coordinator.auto_reboot_enabled, "last_reboot_result": self.coordinator.last_reboot_result}

class MitrastarLastRebootSensor(MitrastarBaseSensor):
    def __init__(self, coordinator, entry): super().__init__(coordinator, entry, "last_reboot", "Último intento de reinicio")
    @property
    def native_value(self): return self.coordinator.last_reboot_result
    @property
    def extra_state_attributes(self): return {"timestamp": self.coordinator.last_reboot}
