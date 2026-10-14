# MitraStar GPT-2841GX4X5 — integración personalizada para Home Assistant

> **Aviso de independencia:** Esta integración comunitaria está destinada a funcionar con routers MitraStar GPT-2841GX4X5 utilizados en redes Movistar. Es un proyecto independiente y no oficial, sin afiliación, patrocinio ni respaldo de Telefónica/Movistar ni de MitraStar. Los nombres de marcas y modelos se utilizan únicamente para identificar la compatibilidad prevista.

Esta integración permite conectar Home Assistant con el router MitraStar GPT-2841GX4X5 (Router Smart WiFi 6 de Movistar) para realizar dos funciones:

- Dar de alta en Home Assistant, como sensores binarios, todos los dispositivos conectados al roter. Muestra los dispositivos como conectado o no y adicionalmente muestra la dirección IP de cada uno de ellos. Esto permite, entre otras cosas, gestionar un robusto sistema de control de presencia asociado a la conexión a las redes Wifi de los dispositivos móviles.
- Control de conexión a internet. En caso de que la instalación pierda la conexión a internet, después de realizar tres comprobaciones (con una separación de 60 segundos entre cada una de ellas), detectando tres fallos consecutivos, la integración lanza un reinicio controlado por software del router. Además dispone de un botón para poder realizar un reinicio manual del router.

## Seguridad y comportamiento

- Comprueba TCP/53 contra 1.1.1.1 y 8.8.8.8 cada 60 segundos; declara fallo solo si fallan ambos.
- Umbral: 3 fallos consecutivos.
- El reinicio automático está desactivado por defecto; se habilita con el interruptor de Home Assistant.
- El mecanismo usa POST `/cgi-bin/reboot.cgi` con `restoreFlag=1` y `RestartBtn=RESTART`, reutilizando la sesión autenticada.
- Antes de enviar la orden, comprueba el acceso local al router.
- Guarda el último intento y el bloqueo en almacenamiento persistente de Home Assistant.
- Si se intenta un reinicio, no repite durante el mismo episodio; exige 5 minutos de Internet estable para desbloquear un nuevo episodio.
- Espera hasta 10 minutos para verificar administración local e Internet. Si no se recupera, queda bloqueado y registra el error.

## Instalación mediante HACS

1. Abre **HACS → Integraciones** en Home Assistant.
2. Abre el menú de los tres puntos y selecciona **Repositorios personalizados**.
3. Añade `https://github.com/Mangaxhombro/ha-mitrastar-gpt-2841gx4x5` como repositorio de categoría **Integración**.
4. Busca **MitraStar GPT-2841GX4X5** e instálala.
5. Reinicia Home Assistant.
6. Ve a **Ajustes → Dispositivos y servicios → Añadir integración** y busca **MitraStar GPT-2841GX4X5**.
7. Sigue el asistente de configuración.

La instalación mediante repositorio personalizado no implica que esta integración esté incluida en el catálogo predeterminado de HACS.

## Instalación manual

Copia la carpeta `mitrastar_router` a `/config/custom_components/mitrastar_router/`, reinicia Home Assistant y recarga la integración. Haz copia de seguridad de la carpeta anterior (si la hubiera) antes de sustituirla.

## Limitaciones

El reinicio remoto todavía requiere una prueba controlada en el firmware concreto. Mantén el interruptor apagado hasta verificar la monitorización y habilítalo solo cuando aceptes que puede reiniciar el router si ambos destinos externos fallan durante tres ciclos. La comprobación TCP puede fallar si la red bloquea TCP/53; no se basa en ping ICMP.


### Reinicio manual del router

La entidad de botón **Reinicio manual del router** permite solicitar un reinicio explícito sin activar el interruptor de reinicio automático. Al pulsarla, la integración comprueba primero que la administración del router responde, envía la petición HTTP de reinicio usada por el watchdog y verifica durante un máximo de 10 minutos que vuelven la administración local y la conectividad a Internet. El resultado se refleja en el estado de recuperación y en el sensor de último intento.

**Advertencia:** al pulsar este botón el router se reinicia realmente y la conexión se interrumpe temporalmente. La prueba no demuestra por sí sola que el firmware no interprete de forma diferente los parámetros HTTP. Mantén desactivado el reinicio automático hasta completar la prueba.


## Agrupar varias MAC como un único dispositivo

En Home Assistant, abre **Ajustes → Dispositivos y servicios → Mitrastar Router → Configurar** (opciones).
En el campo **Asociaciones de MAC**, añade una línea por cada dirección MAC, con el formato:

`AA:BB:CC:DD:EE:FF=iPhone de Mangaxhombro`

Se pueden asociar varias MAC al mismo nombre, una por línea:

`AA:BB:CC:DD:EE:FF=iPhone de Mangaxhombro`
`11:22:33:44:55:66=iPhone de Mangaxhombro`

Las MAC agrupadas se muestran como una única entidad lógica de presencia. El sensor **Dispositivos conectados** cuenta cada grupo una sola vez; **Lista de dispositivos** conserva el inventario físico del router, incluidas las MAC individuales.
