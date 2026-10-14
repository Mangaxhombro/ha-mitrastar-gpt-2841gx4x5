import asyncio
import hashlib
import logging
import re
import socket
import time
from datetime import timedelta
from html import unescape

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_MAC_GROUPS, DEFAULT_SCAN_INTERVAL, INTERNET_FAILURE_THRESHOLD, REBOOT_LOCKOUT_SECONDS, RECOVERY_TIMEOUT_SECONDS)

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """Router credentials or session were rejected."""



def _clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _parse_mac_groups(raw: str) -> dict[str, dict]:
    """Parse one MAC=logical name association per line."""
    groups = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            _LOGGER.warning("Ignorando asociación MAC sin '=': %s", line)
            continue
        mac, name = (part.strip() for part in line.split("=", 1))
        mac = mac.upper().replace("-", ":")
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac) or not name:
            _LOGGER.warning("Ignorando asociación MAC no válida: %s", line)
            continue
        key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or mac.replace(":", "").lower()
        groups.setdefault(key, {"name": name, "macs": set()})["macs"].add(mac)
    return groups


def _parse_devices(html: str) -> list[dict]:
    if "window.parent.location.href" in html and "login_advance.cgi" in html:
        raise InvalidAuth("Router session is not authenticated")
    if "Device Name" not in html or "MAC Address" not in html:
        raise UpdateFailed("Router response did not contain the expected device table")

    devices = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        if "table_font" not in row:
            continue
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if len(cells) < 6:
            continue
        name = _clean_html(cells[1])
        ip = _clean_html(cells[2])
        ipv6_link = _clean_html(cells[3])
        ipv6_global = _clean_html(cells[4])
        mac = _clean_html(cells[5]).upper()
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
            m = re.search(
                r"doModifyRule\([^,]*,[^,]*,[^,]*,[^,]*,'([^']*)','((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})'",
                row,
            )
            if m:
                if not ip:
                    ip = m.group(1)
                mac = m.group(2).upper()
        if not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", ip):
            continue
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
            mac_match = re.search(r"'((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})'", row)
            if mac_match:
                mac = mac_match.group(1).upper()
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
            continue
        devices.append({
            "name": name or "Dispositivo sin nombre",
            "ip": ip,
            "mac": mac,
            "ipv6_link_local": ipv6_link if ipv6_link and ipv6_link != "N/A" else None,
            "ipv6_global": ipv6_global if ipv6_global and ipv6_global != "N/A" else None,
        })
    unique = {device["mac"]: device for device in devices}
    return list(unique.values())


class MitrastarCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry):
        self.entry = entry
        self.host = (entry.options.get(CONF_HOST) or entry.data[CONF_HOST]).rstrip("/")
        self.username = entry.options.get(CONF_USERNAME) or entry.data[CONF_USERNAME]
        self.password = entry.options.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
        self._session = None
        self._logged_in = False
        self.internet_ok = None
        self.internet_failures = 0
        self.recovery_state = "monitorizando"
        self.auto_reboot_enabled = False
        self.last_reboot = None
        self.last_reboot_result = "Nunca ejecutado"
        self._reboot_in_progress = False
        self._reboot_attempted_episode = False
        self._recovery_success_since = None
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_watchdog")
        self._monitor_unsub = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def mac_groups(self) -> dict[str, dict]:
        raw = self.entry.options.get(
            CONF_MAC_GROUPS,
            self.entry.data.get(CONF_MAC_GROUPS, ""),
        )
        return _parse_mac_groups(raw)

    def logical_device_key(self, mac: str) -> str:
        mac = mac.upper()
        for key, group in self.mac_groups.items():
            if mac in group["macs"]:
                return f"group_{key}"
        return f"mac_{mac.replace(':', '').lower()}"

    def logical_device_name(self, mac: str, fallback: str) -> str:
        mac = mac.upper()
        for group in self.mac_groups.values():
            if mac in group["macs"]:
                return group["name"]
        return fallback

    def logical_device_is_online(self, macs: set[str]) -> bool:
        current = {d["mac"].upper() for d in (self.data or [])}
        return bool(current.intersection({m.upper() for m in macs}))

    @classmethod
    async def async_test_connection(cls, hass: HomeAssistant, data: dict):
        obj = cls.__new__(cls)
        obj.hass = hass
        obj.host = data[CONF_HOST].rstrip("/")
        obj.username = data[CONF_USERNAME]
        obj.password = data[CONF_PASSWORD]
        obj._session = None
        obj._logged_in = False
        try:
            await obj._async_fetch_devices()
        finally:
            await obj.async_close()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0"},
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )

    async def _async_login(self):
        await self._ensure_session()
        login_url = f"{self.host}/cgi-bin/login_advance.cgi"
        async with self._session.get(login_url) as response:
            html = await response.text(errors="replace")
            response.raise_for_status()
        match = re.search(r"var\s+sid\s*=\s*['\"]([^'\"]+)['\"]", html)
        if not match:
            raise UpdateFailed("No se encuentra el desafío sid del router")
        sid = match.group(1)
        password_hash = hashlib.md5(f"{self.password}:{sid}".encode("utf-8")).hexdigest()
        payload = {
            "Loginuser": self.username,
            "fake_username": "",
            "fake_pass": "",
            "LoginPasswordValue": password_hash,
            "submitValue": "1",
            "LoginSidValue": sid,
            "Prestige_Login": "Login",
        }
        async with self._session.post(
            login_url,
            data=payload,
            headers={"Referer": login_url},
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            await response.text(errors="replace")
        self._logged_in = True

    async def _async_fetch_devices(self):
        await self._ensure_session()
        devices_url = f"{self.host}/cgi-bin/connection_table_list.cgi"
        for attempt in range(2):
            if not self._logged_in:
                await self._async_login()
            async with self._session.get(
                devices_url,
                headers={
                    "Referer": f"{self.host}/cgi-bin/naviView_partialLoad.cgi",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ) as response:
                html = await response.text(errors="replace")
                response.raise_for_status()
            if "window.parent.location.href" in html and "login_advance.cgi" in html:
                self._logged_in = False
                if attempt == 0:
                    continue
                raise InvalidAuth("El router ha rechazado la sesión; revisa las credenciales")
            devices = _parse_devices(html)
            if not devices:
                raise UpdateFailed("La respuesta no contiene dispositivos interpretables")
            return devices
        raise InvalidAuth("No se pudo autenticar con el router")

    async def async_load_watchdog_state(self):
        saved = await self._store.async_load() or {}
        self.auto_reboot_enabled = bool(saved.get("auto_reboot_enabled", False))
        self.last_reboot = saved.get("last_reboot")
        self.last_reboot_result = saved.get("last_reboot_result", "Nunca ejecutado")
        self._reboot_attempted_episode = bool(saved.get("reboot_attempted_episode", False))
        self._recovery_success_since = saved.get("recovery_success_since")

    async def _save_watchdog_state(self):
        await self._store.async_save({
            "auto_reboot_enabled": self.auto_reboot_enabled,
            "last_reboot": self.last_reboot,
            "last_reboot_result": self.last_reboot_result,
            "reboot_attempted_episode": self._reboot_attempted_episode,
            "recovery_success_since": self._recovery_success_since,
        })

    async def async_start_monitoring(self):
        await self.async_load_watchdog_state()
        if self._monitor_unsub is None:
            self._monitor_unsub = async_track_time_interval(
                self.hass, self._async_monitor_tick, timedelta(seconds=DEFAULT_SCAN_INTERVAL)
            )
        await self._async_monitor_tick(None)

    async def async_set_auto_reboot(self, enabled: bool):
        self.auto_reboot_enabled = bool(enabled)
        await self._save_watchdog_state()
        self.async_update_listeners()

    async def _probe_tcp(self, host: str, port: int = 53) -> bool:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=4)
            return True
        except (OSError, asyncio.TimeoutError):
            return False
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def _check_internet(self) -> bool:
        results = await asyncio.gather(
            self._probe_tcp("1.1.1.1", 53), self._probe_tcp("8.8.8.8", 53)
        )
        # Considera caída solo si fallan ambos destinos.
        return any(results)

    async def _router_admin_reachable(self) -> bool:
        try:
            await self._async_fetch_devices()
            return True
        except (InvalidAuth, UpdateFailed, aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def _send_software_reboot(self):
        await self._ensure_session()
        if not self._logged_in:
            await self._async_login()
        url = f"{self.host}/cgi-bin/reboot.cgi"
        try:
            async with self._session.post(
                url,
                data={"restoreFlag": "1", "RestartBtn": "RESTART"},
                headers={
                    "Referer": f"{self.host}/cgi-bin/indexmain.cgi",
                    "X-Requested-With": "XMLHttpRequest",
                },
                allow_redirects=False,
            ) as response:
                # Un HTTP 5xx es un error explícito. Un cierre de conexión se trata
                # aparte abajo porque este firmware puede cortar la sesión al reiniciar.
                if response.status >= 500:
                    raise UpdateFailed(
                        f"El router respondió HTTP {response.status} al reinicio"
                    )
                try:
                    await asyncio.wait_for(response.read(), timeout=3)
                except (asyncio.TimeoutError, aiohttp.ClientError):
                    pass
        except aiohttp.ServerDisconnectedError:
            # La desconexión por sí sola no confirma éxito ni fracaso. El llamador
            # debe verificar que la administración y la conectividad vuelven.
            _LOGGER.warning(
                "El router cerró la conexión al solicitar el reinicio; "
                "se comprobará la recuperación antes de determinar el resultado"
            )

    async def async_request_manual_reboot(self):
        """Start an explicitly requested manual reboot, independent of auto-reboot."""
        if self._reboot_in_progress:
            raise UpdateFailed("Ya hay un reinicio en curso")
        if not await self._router_admin_reachable():
            self.last_reboot_result = "No enviado: administración local no responde"
            self.recovery_state = "Reinicio manual cancelada: router inaccesible"
            self.async_update_listeners()
            raise UpdateFailed("La administración del router no responde; no se ha enviado el reinicio")

        # The explicit button is a one-shot manual action. It does not turn on
        # the automatic watchdog switch.
        self._reboot_in_progress = True
        self._reboot_attempted_episode = True
        self.last_reboot = time.time()
        self.last_reboot_result = "Reinicio manual solicitada; verificando recuperación"
        self.recovery_state = "Reinicio manual: enviando reinicio por software"
        await self._save_watchdog_state()
        self.async_update_listeners()
        self.hass.async_create_task(self._async_run_manual_reboot_test())

    async def _async_run_manual_reboot_test(self):
        """Send one manual reboot request and verify router and Internet recovery."""
        try:
            await self._send_software_reboot()
            recovered = False
            deadline = time.time() + RECOVERY_TIMEOUT_SECONDS
            while time.time() < deadline:
                await asyncio.sleep(15)
                if await self._router_admin_reachable() and await self._check_internet():
                    recovered = True
                    break
            if recovered:
                self.internet_ok = True
                self.internet_failures = 0
                self.last_reboot_result = "Reinicio manual: recuperación verificada"
                self.recovery_state = "Reinicio manual completada; router e Internet recuperados"
                self._recovery_success_since = time.time()
            else:
                self.last_reboot_result = "Reinicio manual: sin recuperación en 10 minutos; requiere revisión"
                self.recovery_state = "Reinicio manual fallida; reinicio automático bloqueado"
        except Exception as err:
            self.last_reboot_result = f"Reinicio manual: resultado incierto ({type(err).__name__})"
            self.recovery_state = "Reinicio manual: resultado incierto; reinicio automático bloqueado"
            _LOGGER.error("Fallo en reinicio manual de reinicio Mitrastar: %s", err)
        finally:
            self._reboot_in_progress = False
            await self._save_watchdog_state()
            self.async_update_listeners()

    async def _async_monitor_tick(self, now):
        if self._reboot_in_progress:
            return
        try:
            online = await self._check_internet()
        except Exception as err:
            _LOGGER.warning("No se pudo comprobar Internet: %s", err)
            return
        self.internet_ok = online
        if online:
            self.internet_failures = 0
            self.recovery_state = "Internet disponible"
            if self._reboot_attempted_episode:
                if self._recovery_success_since is None:
                    self._recovery_success_since = time.time()
                elif time.time() - float(self._recovery_success_since) >= 300:
                    self._reboot_attempted_episode = False
                    self._recovery_success_since = None
                    self.recovery_state = "Recuperado; reinicio desbloqueado"
                    await self._save_watchdog_state()
            else:
                self._recovery_success_since = None
        else:
            self.internet_failures += 1
            self._recovery_success_since = None
            self.recovery_state = f"Sin Internet ({self.internet_failures}/{INTERNET_FAILURE_THRESHOLD})"
            if self.internet_failures >= INTERNET_FAILURE_THRESHOLD:
                if self._reboot_attempted_episode:
                    self.recovery_state = "Fallo persistente; reinicio ya intentado"
                elif not self.auto_reboot_enabled:
                    self.recovery_state = "Fallo persistente; reinicio automático desactivado"
                elif time.time() - (float(self.last_reboot or 0)) < REBOOT_LOCKOUT_SECONDS:
                    self.recovery_state = "Reinicio bloqueado durante periodo de seguridad"
                else:
                    # Marcar y persistir ANTES de la orden para impedir bucles incluso
                    # si Home Assistant se reinicia o la respuesta HTTP es ambigua.
                    self._reboot_attempted_episode = True
                    self._reboot_in_progress = True
                    self.last_reboot = time.time()
                    self.last_reboot_result = "Orden enviada; verificando recuperación"
                    self.recovery_state = "Reiniciando router"
                    await self._save_watchdog_state()
                    self.async_update_listeners()
                    try:
                        if not await self._router_admin_reachable():
                            self.last_reboot_result = "No enviado: administración local no responde"
                            self.recovery_state = "Router inaccesible; reinicio no enviado"
                        else:
                            await self._send_software_reboot()
                            recovered = False
                            deadline = time.time() + RECOVERY_TIMEOUT_SECONDS
                            while time.time() < deadline:
                                await asyncio.sleep(15)
                                if await self._router_admin_reachable() and await self._check_internet():
                                    recovered = True
                                    break
                            if recovered:
                                self.internet_ok = True
                                self.internet_failures = 0
                                self.last_reboot_result = "Recuperación verificada"
                                self.recovery_state = "Internet recuperado; estabilizando"
                                self._recovery_success_since = time.time()
                            else:
                                self.last_reboot_result = "No se recuperó en 10 minutos; requiere revisión"
                                self.recovery_state = "Recuperación fallida; reinicio automático bloqueado"
                    except Exception as err:
                        self.last_reboot_result = f"Resultado incierto: {type(err).__name__}"
                        self.recovery_state = "Resultado incierto; reinicio automático bloqueado"
                        _LOGGER.error("Fallo al ejecutar/verificar reinicio Mitrastar: %s", err)
                    finally:
                        self._reboot_in_progress = False
                        await self._save_watchdog_state()
        self.async_update_listeners()

    async def _async_update_data(self):
        try:
            return await self._async_fetch_devices()
        except InvalidAuth:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, UpdateFailed) as err:
            raise UpdateFailed(f"Error consultando el router Mitrastar: {err}") from err

    async def async_close(self):
        if self._monitor_unsub:
            self._monitor_unsub()
            self._monitor_unsub = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
