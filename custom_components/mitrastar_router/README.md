# MitraStar GPT-2841GX4X5 — integración personalizada para Home Assistant

> **Aviso de independencia:** Esta integración comunitaria está destinada a funcionar con routers MitraStar GPT-2841GX4X5 utilizados en redes Movistar. Es un proyecto independiente y no oficial, sin afiliación, patrocinio ni respaldo de Telefónica/Movistar ni de MitraStar. Los nombres de marcas y modelos se utilizan únicamente para identificar la compatibilidad prevista.

Versión 1.4.1. Actualiza el icono de la integración; mantiene la consulta de dispositivos, la monitorización de conectividad y los controles de reinicio.

## Seguridad y comportamiento
- Comprueba TCP/53 contra 1.1.1.1 y 8.8.8.8 cada 60 segundos; declara fallo solo si fallan ambos.
- Umbral: 3 fallos consecutivos.
- El reinicio automático está desactivado por defecto; se habilita con el interruptor de Home Assistant.
- El mecanismo usa POST `/cgi-bin/reboot.cgi` con `restoreFlag=1` y `RestartBtn=RESTART`, reutilizando la sesión autenticada.
- Antes de enviar la orden, comprueba el acceso local al router.
- Guarda el último intento y el bloqueo en almacenamiento persistente de Home Assistant.
- Si se intenta un reinicio, no repite durante el mismo episodio; exige 5 minutos de Internet estable para desbloquear un nuevo episodio.
- Espera hasta 10 minutos para verificar administración local e Internet. Si no se recupera, queda bloqueado y registra el error.


## Instalación
Copia la carpeta `mitrastar_router` a `/config/custom_components/mitrastar_router/`, reinicia Home Assistant y recarga la integración. Haz copia de seguridad de la carpeta anterior antes de sustituirla.

## Limitaciones
El reinicio remoto todavía requiere una prueba controlada en el firmware concreto. Mantén el interruptor apagado hasta verificar la monitorización y habilítalo solo cuando aceptes que puede reiniciar el router si ambos destinos externos fallan durante tres ciclos. La comprobación TCP puede fallar si la red bloquea TCP/53; no se basa en ping ICMP.


### Reinicio manual del router

La entidad de botón **Reinicio manual del router** permite solicitar un reinicio explícito sin activar el interruptor de reinicio automático. Al pulsarla, la integración comprueba primero que la administración del router responde, envía la petición HTTP de reinicio usada por el watchdog y verifica durante un máximo de 10 minutos que vuelven la administración local y la conectividad a Internet. El resultado se refleja en el estado de recuperación y en el sensor de último intento.

**Advertencia:** al pulsar este botón el router se reinicia realmente y la conexión se interrumpe temporalmente. La prueba no demuestra por sí sola que el firmware no interprete de forma diferente los parámetros HTTP. Mantén desactivado el reinicio automático hasta completar la prueba.


## Agrupar varias MAC como un único dispositivo

En Home Assistant, abre **Ajustes → Dispositivos y servicios → Mitrastar Router → Configurar** (opciones).
En el campo **Asociaciones de MAC**, añade una línea por cada dirección MAC, con el formato:

`AA:BB:CC:DD:EE:FF=iPhone de David`

Se pueden asociar varias MAC al mismo nombre, una por línea:

`AA:BB:CC:DD:EE:FF=iPhone de David`
`11:22:33:44:55:66=iPhone de David`

Las MAC agrupadas se muestran como una única entidad lógica de presencia. El sensor **Dispositivos conectados** cuenta cada grupo una sola vez; **Lista de dispositivos** conserva el inventario físico del router, incluidas las MAC individuales.


## Versión 1.3.6

- Añadido el atributo `ip_address` a los sensores binarios de dispositivos individuales.
- En los sensores de dispositivos agrupados, `ip_address` muestra las IP activas separadas por comas. Se mantienen los atributos anteriores, incluidos `ip` e `ips_conectadas`, para no romper automatizaciones existentes.
- No se han modificado el intervalo de consulta (60 segundos), las comprobaciones de Internet ni la lógica de reinicio.


## Versión 1.3.7

- Añade sensores de texto `Dirección IP` asociados a cada dispositivo de red.
- Para dispositivos agrupados por MAC, el sensor muestra las direcciones IPv4 activas separadas por comas.
- Los sensores IP reutilizan los datos obtenidos en el sondeo existente; no añaden peticiones al router.


## Versión 1.3.9

- Nombre visible de la integración: **MitraStar GPT-2841GX4X5**.
- Incluye un icono propio del router en `brand/icon.png`.
- Añadido aviso de proyecto comunitario no oficial y sin afiliación ni respaldo de Telefónica/Movistar o MitraStar.
- Conserva los sensores IP y el resto de la funcionalidad de la versión 1.3.8.
- Retirado el control de modo de prueba de conectividad.
- Renombrado el botón a «Reinicio manual del router».


## Versión 1.4.1

- Actualizado el icono del router en `brand/icon.png`, conservando la transparencia y la proporción de la imagen.
- Sin cambios en la lógica de monitorización, presencia ni reinicio respecto a la versión 1.4.0.

## Versión 1.4.0

- Retirada la entidad «Modo de prueba de conectividad (sin reinicio)» y su lógica asociada.
- Limpieza automática y acotada de la entidad antigua en el registro de Home Assistant, únicamente para esta configuración de la integración.
- Se conservan «Reinicio automático por fallo de Internet» y «Reinicio manual del router».
- Se mantiene el icono en `brand/icon.png`.
