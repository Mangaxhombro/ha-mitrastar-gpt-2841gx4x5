from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import MitrastarCoordinator


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _grouped_macs(entry: ConfigEntry) -> set[str]:
    """Return normalized MAC addresses configured in logical groups."""
    raw = entry.options.get("mac_groups", entry.data.get("mac_groups", ""))
    result = set()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        mac = line.split("=", 1)[0].strip().upper()
        if len(mac.split(":")) == 6:
            result.add(mac)
    return result


async def _async_remove_grouped_individual_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stale individual MitraStar devices/entities for MACs now grouped.

    Only removes devices whose identifier exactly matches this config entry and a
    MAC now included in a logical group. Other integrations and ungrouped devices
    are not touched.
    """
    grouped_macs = _grouped_macs(entry)
    if not grouped_macs:
        return

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    for device in list(device_registry.devices.values()):
        matching_macs = {
            str(identifier[2]).upper()
            for identifier in device.identifiers
            if len(identifier) == 3
            and identifier[0] == DOMAIN
            and identifier[1] == entry.entry_id
            and str(identifier[2]).upper() in grouped_macs
        }
        if not matching_macs:
            continue

        # Remove registry entries tied to this obsolete per-MAC device first.
        for entity in list(entity_registry.entities.values()):
            if entity.device_id == device.id:
                entity_registry.async_remove(entity.entity_id)

        device_registry.async_remove_device(device.id)


async def _async_remove_obsolete_connectivity_test_switch(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the retired connectivity-test switch from this config entry only.

    Older versions registered this switch, so removing its implementation alone
    can leave a stale entity in Home Assistant's entity registry. Match the old
    visible name or known test-oriented unique-id fragments, and never touch
    entities belonging to another config entry.
    """
    entity_registry = er.async_get(hass)
    old_names = {
        "modo de prueba de conectividad (sin reinicio)",
        "modo de prueba de conectividad",
    }
    old_unique_id_fragments = (
        "connectivity_test",
        "test_connectivity",
        "connectivity_without_reboot",
        "test_mode",
    )

    for entity in list(entity_registry.entities.values()):
        if entity.config_entry_id != entry.entry_id or entity.domain != "switch":
            continue
        names = {
            (getattr(entity, "name", None) or "").strip().casefold(),
            (getattr(entity, "original_name", None) or "").strip().casefold(),
        }
        unique_id = (entity.unique_id or "").casefold()
        if names.intersection(old_names) or any(fragment in unique_id for fragment in old_unique_id_fragments):
            entity_registry.async_remove(entity.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await _async_remove_grouped_individual_devices(hass, entry)
    await _async_remove_obsolete_connectivity_test_switch(hass, entry)

    coordinator = MitrastarCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        await coordinator.async_start_monitoring()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(
            entry, ["sensor", "binary_sensor", "switch", "button"]
        )
    except Exception:
        # Setup can fail before the coordinator is registered in hass.data.
        # Always release its aiohttp session to avoid Unclosed client session.
        await coordinator.async_close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "binary_sensor", "switch", "button"]
    )
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unload_ok
