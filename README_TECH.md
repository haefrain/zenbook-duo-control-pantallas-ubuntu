# Especificación Técnica — Zenbook Duo Control

---

## Arquitectura general

El proyecto corre como un **servicio systemd de root** (`zenbook-duo.service`) que arranca tras la sesión gráfica del usuario. El daemon principal orquesta módulos independientes, cada uno en su propio hilo, y comparte un único proceso `monitor-sensor` para los eventos del acelerómetro y el sensor de luz.

```
systemd (root)
└── core/daemon.py
    ├── TouchscreenMapper          → dconf sesión usuario (mapeo táctil por conector
    │                                  con 4º elemento del array como tie-breaker)
    ├── BatteryManager              → sysfs directo (root)
    ├── KeyboardBacklightManager    → ioctl HIDIOCSFEATURE sobre /dev/hidraw* (root)
    ├── DockMonitor                 → udev netlink (root)
    │   ├── BluetoothManager        → busctl org.bluez.Device1.Connect
    │   │   └── hilo unlock_watcher → dbus-monitor logind Session.Unlock
    │   └── re-aplica KeyboardBacklight tras dock (en thread con retry)
    ├── BrightnessManager           → D-Bus GNOME (sesión usuario) + sysfs (root)
    │   ├── hilo manual_sync        → gdbus monitor (debounce + mute de eco propio)
    │   └── acquire_screenpad/release → coordinación con OledCareManager
    ├── RotationManager             → monitor-sensor subprocess (con auto-restart)
    │   ├── orientación (debounce)  → gnome_randr.py vía D-Bus GNOME
    │   └── lux                     → BrightnessManager.apply_lux()
    ├── PowerProfileManager         → dbus-monitor UPower → platform_profile +
    │                                  gnome_randr.py --rate
    └── OledCareManager              → select() sobre /dev/input/event* del eDP-2 →
                                       acquire_screenpad + dim
```

### Puente root ↔ sesión Wayland

GNOME en Wayland no acepta conexiones D-Bus de procesos root. El daemon resuelve esto con `run_in_user_session()` (`core/daemon.py`), que ejecuta comandos como el usuario con las variables de entorno necesarias:

```python
f"sudo -u {username} env XDG_RUNTIME_DIR=/run/user/{uid} WAYLAND_DISPLAY=wayland-0 {command}"
```

Esto permite que procesos root controlen la sesión gráfica del usuario sin necesidad de un servidor D-Bus separado.

---

## Estructura de archivos

```
/opt/zenbook-duo/                  ← directorio de instalación
├── config.yaml                    ← configuración activa
├── core/
│   ├── daemon.py                  ← punto de entrada, orquestador
│   ├── config_loader.py           ← carga YAML con defaults de features
│   └── gnome_randr.py             ← cliente D-Bus para Mutter DisplayConfig
├── modules/
│   ├── auto_rotate.py             ← RotationManager
│   ├── auto_brightness.py         ← BrightnessManager
│   ├── battery.py                 ← BatteryManager
│   ├── display_dock.py            ← DockMonitor (udev)
│   ├── bluetooth.py               ← BluetoothManager
│   ├── touchscreen_mapping.py     ← TouchscreenMapper
│   ├── power_profile.py           ← PowerProfileManager
│   ├── oled_care.py               ← OledCareManager
│   └── keyboard_backlight.py      ← KeyboardBacklightManager
└── venv/                          ← entorno Python aislado
```

```
/etc/systemd/system/
└── zenbook-duo.service            ← unit de systemd

/sys/class/backlight/
├── intel_backlight/                ← eDP-1: controlado por GNOME vía D-Bus
├── card1-eDP-2-backlight/          ← eDP-2 DRM: NO escrito por el daemon
│                                     (causaba loop de retroalimentación con
│                                     gnome-settings-daemon que lo monitorea)
└── asus_screenpad/                 ← eDP-2: control ASUS nativo (root, sysfs directo)

/sys/class/power_supply/
├── BAT0/charge_control_end_threshold ← límite de carga (root, sysfs directo)
└── AC0/online                      ← estado AC (lectura para PowerProfile)

/sys/firmware/acpi/
├── platform_profile                ← perfil activo (escribe PowerProfileManager)
└── platform_profile_choices        ← perfiles disponibles (lectura)

/sys/class/hidraw/hidrawN/           ← teclado dock USB (KeyboardBacklight)
└── /dev/hidrawN                    ← target de ioctl HIDIOCSFEATURE

/dev/input/eventN                   ← touchscreens del eDP-2 (lectura por OledCare)
```

---

## Módulos

### `core/daemon.py` — Orquestador

Punto de entrada del proceso. Lee `config.yaml`, instancia los módulos activos según la sección `features` y mantiene el proceso vivo en un bucle `while True / sleep(1)`.

La función `run_in_user_session(command, username)` actúa como capa de transporte para todos los módulos que necesitan interactuar con la sesión gráfica.

**Lógica de interdependencia de features:**
- Si `auto_rotate: false` pero `auto_brightness: true`, `RotationManager` se instancia igualmente (para correr el loop de `monitor-sensor`) pero con `rotation_enabled=False`.
- Si `display_dock: false`, la callback `is_docked` que recibe `RotationManager` es `lambda: False` (siempre modo sin teclado).

---

### `modules/auto_rotate.py` — RotationManager

**Dependencia de sistema:** `iio-sensor-proxy` (paquete `iio-sensor-proxy`)

Lanza `monitor-sensor` como subproceso y lee su stdout línea a línea en un hilo daemon. Detecta dos tipos de eventos:

| Línea de monitor-sensor | Acción |
|---|---|
| `Accelerometer orientation changed: <orientación>` | Programa `_schedule_orientation()` (debounce) |
| `Light changed: <valor> (lux)` | Llama a `BrightnessManager.apply_lux()` |

**Orientaciones manejadas:**

| Valor del sensor | Modo | Rotación aplicada |
|---|---|---|
| `normal`, `bottom-up` | Portátil (vertical) | `normal` |
| `right-up` | Libro (horizontal) | `right` |
| `left-up` | Libro (horizontal) | `left` |

**Debounce de orientación:** cuando giras el equipo, el accelerómetro reporta varias orientaciones intermedias en milisegundos. `_schedule_orientation()` guarda la última orientación recibida y reprograma un `threading.Timer` con `ROTATION_DEBOUNCE_SECONDS` (0.4 s). Sólo se aplica el último valor cuando el timer dispara, evitando una cascada de `ApplyMonitorsConfig` síncronos que pueden colgar el compositor.

**Lock de aplicación:** `_apply_orientation()` corre dentro de `_apply_lock` para serializar applys procedentes de fuentes concurrentes (sensor, watchdog, dock).

**Auto-restart:** el loop `_monitor_loop()` reinicia `monitor-sensor` con un retraso de 3 s si el subproceso muere.

La rotación se aplica vía `gnome_randr.py` en la sesión del usuario. El posicionamiento usa relaciones (`--below`, `--right-of`) en lugar de coordenadas absolutas para ser compatible con la lógica de `monmap` de `gnome_randr.py`.

**Gestión de estado:** `current_state` se actualiza solo si el comando `gnome_randr.py` termina sin excepción. Si falla, el estado se mantiene para reintentar en el próximo evento.

---

### `core/gnome_randr.py` — Cliente D-Bus Mutter

Interfaz de línea de comandos para `org.gnome.Mutter.DisplayConfig` (D-Bus). Llama a `GetCurrentState` para leer el estado actual de los monitores y a `ApplyMonitorsConfig` para aplicar cambios.

**Fix aplicado en este proyecto:** La lectura inicial del estado desde D-Bus devuelve las dimensiones físicas del panel (`w=2880, h=1800`) independientemente de la rotación actual. Cuando el display está en rotación de 90° (`left=1` o `right=3`), las dimensiones se preajustan a las efectivas para que el swap de `output_set_trans` funcione correctamente en ambas direcciones:

```python
# En __init_output_config y output_set_mode_by_res:
if lm[3] in [1, 3]:   # left=1, right=3
    conf['w'] = h      # dimensión efectiva tras rotación
    conf['h'] = w
```

Sin este fix, la segunda rotación producía posiciones incorrectas (`y=2880`) y el error `Logical monitors not adjacent`.

---

### `modules/auto_brightness.py` — BrightnessManager

Convierte lecturas de lux (del sensor de luz de `iio-sensor-proxy`) a porcentajes de brillo mediante una tabla de rangos. El cambio solo se aplica cuando el porcentaje objetivo difiere del actual, evitando llamadas innecesarias al sistema.

**Tabla de rangos de brillo:**

| Rango (lux) | Entorno típico | Brillo |
|---|---|---|
| 0 – 5 | Oscuridad total | 5% |
| 5 – 25 | Luz muy tenue | 15% |
| 25 – 45 | Interior tenue | 30% |
| 45 – 250 | Interior normal | 50% |
| 250 – 600 | Cerca de ventana | 70% |
| 600 – 2000 | Exterior nublado | 85% |
| > 2000 | Luz solar directa | 100% |

Los rangos amplios actúan como histéresis natural: el brillo no cambia hasta salir claramente del rango actual.

**Control de pantallas — ajuste automático (sensor):**

`apply_lux()` llama a `_apply_both()`, que lanza `_set_gnome_brightness` y `_set_screenpad_brightness` en dos hilos paralelos (`threading.Thread`) para que ambas pantallas cambien simultáneamente sin que una bloquee a la otra.

- **eDP-1 (`intel_backlight`):** vía D-Bus GNOME (`org.gnome.SettingsDaemon.Power.Screen`, propiedad `Brightness`). Acepta un entero 0–100 (porcentaje directo). Requiere sesión gráfica activa.
- **eDP-2 (`asus_screenpad`):** escritura directa a sysfs. Requiere root. El valor se escala proporcionalmente al `max_brightness`. Antes de escribir se verifica `bl_power == 0` (pantalla encendida).
  - **Importante:** anteriormente se escribía también en `card1-eDP-2-backlight` (DRM), pero `gnome-settings-daemon` lo monitorea como un backlight más y emitía `PropertiesChanged` por cada write. El watcher interpretaba esos eventos como "tecla de brillo" y volvía a escribir, creando un loop visible (99 → 100 → 99 → 100 en logs en menos de un segundo). La solución fue eliminar la escritura al backlight DRM.

**Sincronización con teclas de brillo (`start()` / `_manual_sync_loop`):**

`start()` lanza un hilo daemon que ejecuta `gdbus monitor` en la sesión del usuario apuntando a `org.gnome.SettingsDaemon.Power`. Cada línea de salida se examina con una regex que extrae el nuevo valor de `Brightness`. Cuando GNOME cambia el brillo de eDP-1 (por tecla, brillo automático del propio GNOME, o cualquier otra fuente), el hilo captura el evento y, tras debouncing, llama a `_set_screenpad_brightness()` para sincronizar eDP-2.

**Anti-loop / coalescing en el watcher:**

GNOME no aplica los cambios de brillo de un salto: los anima en pasos de 1% (e.g. de 95% a 100% emite 5 eventos `PropertiesChanged`). Sin protección, cada uno provoca una escritura al screenpad. Dos mecanismos resuelven esto:

1. **Self-write mute (`SELF_WRITE_MUTE_SECONDS = 0.40`):** después de cada `apply_lux()` o `_flush_pending()` propio, cualquier evento del bus que llegue dentro de los 400 ms siguientes se descarta. Silencia ecos del propio escribir.

2. **Debounce coalescing (`DEBOUNCE_SECONDS = 0.15`):** los eventos del bus se guardan en `_pending_pct` y se reprograma un `threading.Timer`. Sólo el último valor recibido en la ventana de 150 ms se aplica al screenpad mediante `_flush_pending()`.

**Coordinación con OledCareManager:**

`acquire_screenpad()` / `release_screenpad()` mantienen un counter `_screenpad_external_holders`. Mientras el counter sea > 0, `_set_screenpad_brightness()` no escribe — el control queda cedido a otro módulo (típicamente el `OledCareManager` durante el idle dim). Esto evita que el sync con las teclas de brillo sobrescriba el dim activo.

**Auto-restart:** el `_manual_sync_loop()` reinicia `gdbus monitor` tras 3 s si el subproceso muere.

---

### `modules/touchscreen_mapping.py` — TouchscreenMapper

El Zenbook Duo tiene dos touchscreens ELAN apuntando a dos paneles OLED con EDID **byte a byte idéntico** (mismo modelo de panel SDC, vendor `0x419d`, serial `0x00000000`). El matching estándar de Mutter por `(vendor, product, serial)` no puede distinguirlos: ambos terminan asignados al primer monitor que coincida — siempre `eDP-1`.

**Solución:** Mutter ≥ 42 (verificado leyendo `meta-input-mapper.c` de la rama `gnome-46`) soporta un **cuarto elemento** en el array dconf `output`, que es el nombre del conector. Cuando `monitor_has_twin()` detecta monitores con EDID duplicado, usa ese 4º elemento como tie-breaker:

```c
if (match && n_values >= 4 && monitor_has_twin (monitor, monitors)) {
    output = meta_monitor_get_main_output (monitor);
    match = g_strcmp0 (meta_output_get_name (output), edid[3]) == 0;
}
```

Este 4º elemento **no está documentado** en la descripción de la clave dconf; sólo existe en el código. `apply()` lo aprovecha leyendo el EDID real (vendor/product/serial) vía `org.gnome.Mutter.DisplayConfig.GetCurrentState` y luego escribiendo arrays de 4 elementos para AMBOS dispositivos:

```
/org/gnome/desktop/peripherals/touchscreens/04f3:425b/output
  → ['SDC', '0x419d', '0x00000000', 'eDP-1']

/org/gnome/desktop/peripherals/touchscreens/04f3:425a/output
  → ['SDC', '0x419d', '0x00000000', 'eDP-2']
```

El path dconf usa el `vendor:product` HID del dispositivo de entrada (no del panel). Mutter usa el formato `/org/gnome/desktop/peripherals/touchscreens/{VENDOR}:{PRODUCT}/` (sin componente serial trailing).

**Caveat de re-aplicación:** Mutter sólo lee este setting cuando el dispositivo se añade. La primera escritura del daemon NO se aplica en vivo: requiere un re-login (o desconexión/reconexión del touchscreen) para que tome efecto.

Los valores `top_device` y `bottom_device` son configurables en `config.yaml`. La opción `swap: true` intercambia ambos dispositivos sin necesidad de editar los IDs manualmente, útil si el mapeo queda invertido.

---

### `modules/battery.py` — BatteryManager

Escribe el límite de carga en las siguientes rutas (en orden, usa la primera que exista):

```
/sys/class/power_supply/BAT0/charge_control_end_threshold
/sys/class/power_supply/BAT1/charge_control_end_threshold
/sys/class/power_supply/BATC/charge_control_end_threshold
/sys/devices/platform/asus-nb-wmi/charge_control_end_threshold
```

Incluye verificación post-escritura: lee el valor inmediatamente después de escribirlo para detectar rechazos silenciosos del driver (algunos kernels ignoran valores fuera de rango sin error).

---

### `modules/display_dock.py` — DockMonitor

**Dependencia de sistema:** `pyudev`

Escucha eventos del subsistema `usb` vía netlink usando `pyudev.MonitorObserver` (hilo interno de pyudev). Compara `ID_VENDOR_ID` e `ID_MODEL_ID` de cada evento con los valores del config.

Al arrancar, escanea los dispositivos USB actuales (`context.list_devices`) para sincronizar el estado inicial sin esperar a un evento.

**Estado interno:** `active_device_paths` es un `set` de rutas de dispositivo. `is_docked()` retorna `len(active_device_paths) > 0`.

**Debounce:** `_dispatch()` rechaza acciones duplicadas dentro de `DEBOUNCE_SECONDS = 0.6` para evitar las cascadas de eventos add/remove que ocurren al re-enumerar el bus. Cuando se docka, además del callback principal se reaplica el `KeyboardBacklightManager` en un thread con retry (porque el hidraw del teclado puede tardar unos ms en aparecer tras el evento `add` de udev).

**Callbacks:**
- `on_dock`: apaga eDP-2 vía `gnome_randr.py --output eDP-2 --off` + reaplica el backlight del teclado
- `on_undock`: enciende eDP-2 con `gnome_randr.py --output eDP-2 --auto --below eDP-1` + reconexión Bluetooth

---

### `modules/bluetooth.py` — BluetoothManager

Soporta múltiples MACs (`mac_addresses`) además de la del teclado. Conecta dispositivos llamando directamente a BlueZ vía `busctl call org.bluez /org/bluez/hci0/dev_<MAC> org.bluez.Device1 Connect` (más rápido que invocar `bluetoothctl` y sin tener que parsear su REPL). Previo a la conexión ejecuta `rfkill unblock bluetooth`.

**Watcher de desbloqueo:** `start_unlock_watcher()` lanza un hilo daemon que escucha la señal `org.freedesktop.login1.Session.Unlock` en el system bus vía `dbus-monitor`. Cuando el usuario desbloquea la pantalla, todos los dispositivos configurados se reconectan en paralelo. Si `dbus-monitor` muere, el loop lo reinicia tras 3 s.

---

### `modules/power_profile.py` — PowerProfileManager

Aplica un `platform_profile` y un refresh rate distintos según el estado de carga (AC vs batería). Escucha cambios de UPower vía D-Bus en el system bus.

**Detección de estado:** `_read_ac_state()` itera `/sys/class/power_supply/*/online`. Devuelve `'ac'` si encuentra cualquier `online == 1`, `'battery'` en caso contrario.

**Aplicación del perfil:** `_set_profile()` valida el nombre contra `/sys/firmware/acpi/platform_profile_choices` (evita errores si el firmware no soporta el perfil pedido) y luego escribe en `/sys/firmware/acpi/platform_profile`. En el Zenbook Duo el ASUS WMI driver mapea esto a `throttle_thermal_policy` internamente:

| platform_profile | throttle_thermal_policy | Modo ASUS |
|---|---|---|
| `balanced` | 0 | DEFAULT |
| `performance` | 1 | OVERBOOST |
| `quiet` | 2 | SILENT |

**Aplicación del refresh rate:** `_set_refresh_rate()` invoca `gnome_randr.py --output <top> --auto --scale <scale> --rate <rate>` **sólo sobre la pantalla superior**. No toca el inferior intencionadamente: si está activo, será reaplicado por el siguiente evento del `RotationManager`; si está apagado por undock, no queremos re-encenderlo. La invocación pasa por `run_in_user_session()` para acceder a la sesión gráfica.

**Watcher de UPower:** `_watch_loop()` ejecuta `dbus-monitor --system` filtrando `PropertiesChanged` sobre `/org/freedesktop/UPower`. Cuando ve `OnBattery` o `LidIsClosed` en una línea, re-lee el estado real de AC (más simple que parsear los tipos D-Bus complejos del payload) y lo aplica. Auto-restart con 3 s si el subproceso muere.

**Reentrancy:** `_apply_for_state()` cortocircuita si el estado es el mismo que el último aplicado. Esto evita que un PropertiesChanged sin cambio real (por ejemplo el `Percentage` que UPower emite cada minuto) gatille writes innecesarios.

---

### `modules/oled_care.py` — OledCareManager

Atenúa el screenpad de eDP-2 tras un periodo de inactividad táctil, para preservar el panel OLED contra burn-in cuando muestra contenido estático. **No hace pixel shift por reposicionamiento de logical_monitors** porque eso produciría parpadeos visibles cada vez (el compositor recalcula todo el layout). El idle dim es la medida con mejor relación coste/beneficio.

**Localización de los event devices:** `_find_event_devices()` itera `/sys/class/input/event*` y compara `id/vendor` e `id/product` contra `oled_care.bottom_vendor` / `oled_care.bottom_product`. Devuelve **todos** los event devices que matchean (un mismo touchscreen ELAN expone varios: principal, stylus, touchpad). Si los devices no existen al boot, reintenta hasta 20 veces con 1 s entre intentos (los devices i2c-HID pueden tardar tras suspend/resume).

**Loop de inactividad:** `_idle_loop()` abre todos los event devices en `O_RDONLY | O_NONBLOCK` y entra en un bucle con `select.select()`:

- **Estado activo (no atenuado):** `timeout = idle_seconds - elapsed`. Si `select()` retorna sin lecturas, llama a `_dim()`. Si retorna con lecturas, drena los buffers (`os.read` en loop hasta `BlockingIOError`) y resetea el timestamp.
- **Estado atenuado:** `timeout = None` (espera indefinida). Cualquier evento dispara `_restore()`.

**Coordinación con BrightnessManager:**

Antes de atenuar, `_dim()` llama a `brightness_manager.acquire_screenpad()` y guarda el `_saved_pct = brightness_manager.get_last_pct()`. Mientras esté atenuado, el `BrightnessManager` no escribe al screenpad aunque el usuario presione las teclas de brillo. `_restore()` libera el lock con `release_screenpad()` y reescribe el nivel guardado.

La escritura del valor de dim/restore va directamente al sysfs de `asus_screenpad` (no usa `BrightnessManager` porque ese justo está silenciado).

**Why not pixel shift:** se evaluó pero descartó. Mover los logical_monitors ±1 px requiere `ApplyMonitorsConfig`, que en GNOME 46 produce un breve flash visible cada vez. El flash sería más molesto que el burn-in que pretende prevenir. La alternativa de mover sólo el wallpaper no protege la barra superior ni los elementos UI estáticos del shell.

---

### `modules/keyboard_backlight.py` — KeyboardBacklightManager

Controla el backlight del teclado dock (separable). El teclado del Zenbook Duo no es soportado por el módulo `hid-asus` del kernel (su producto `0B05:1B2C` no está en la lista de aliases), por lo que no expone `/sys/class/leds/asus::kbd_backlight`. El control sólo es accesible vía un HID feature report propietario.

**Formato del feature report (16 bytes):**

```
byte 0:    0x5A          (report ID)
byte 1..3: BA C5 C4      (cabecera fija ASUS)
byte 4:    0..3          (nivel: 0=off, 3=máximo)
byte 5..15: 0x00         (padding)
```

Origen del formato: ingeniería inversa del proyecto `alesya-h/zenbook-duo-2024-ux8406ma-linux`, verificado contra el report descriptor del teclado (donde aparece el report ID `0x5A` como Feature de 15 bytes en la Usage Page Vendor Defined `0xFF31`).

**Mecanismo de envío:** `ioctl HIDIOCSFEATURE(16)` sobre `/dev/hidrawN`. El número de ioctl se calcula desde el header `linux/hidraw.h`:

```python
# _IOC(dir=READ|WRITE=3, type='H'=0x48, nr=0x06, size=16)
HIDIOCSFEATURE_16 = (3 << 30) | (16 << 16) | (0x48 << 8) | 0x06  # = 0xC0104806
```

Verificado idéntico al valor que produce `HIDIOCSFEATURE(16)` en C compilando con `linux/hidraw.h`. La ventaja sobre el control transfer USB que usa el script de referencia: **no requiere desvincular el driver del kernel**, funciona con el teclado bound a `hid-generic`.

**Localización del hidraw:** `_find_hidraw()` itera `/sys/class/hidraw/hidraw*/device/uevent` buscando una línea `HID_ID=BUS:VENDOR:PRODUCT` donde vendor y product matcheen los valores del config padded a 8 hex chars (formato exacto del kernel).

**Flujo de aplicación:**

1. Al arrancar el daemon: `apply()` se llama una vez. Si el teclado ya está dockeado, aplica el nivel del config inmediatamente.
2. Al evento de dock (vía `DockMonitor.on_dock`): se reaplica en un thread con retries (3 intentos × 0.5 s) porque el hidraw puede tardar en aparecer tras el evento `add` de udev.
3. Si no está dockeado: el `_find_hidraw()` retorna `None` tras los retries y el módulo loggea un mensaje informativo (no es un error).

**Caveat de Bluetooth:** cuando el teclado está despegado y conectado por BT (product `0B05:1B2D` con bus type `0x0005` en lugar de USB `0x0003`), no aplicamos backlight aunque técnicamente expone los mismos reports vía HID-over-GATT. Razón: en BT el teclado está físicamente debajo de la pantalla inferior, así que iluminarlo no aporta nada.

---

## Servicio systemd

```ini
[Unit]
After=graphical.target
Wants=graphical.target
```

El servicio arranca tras `graphical.target` y espera activamente en `ExecStartPre` a que el socket Wayland del usuario esté disponible (`/run/user/<UID>/wayland-0`). Esto evita fallos por race condition entre el inicio de sesión y el daemon.

```ini
[Service]
User=root
Restart=on-failure
RestartSec=10
```

Corre como root para tener acceso a sysfs. En caso de fallo se reinicia tras 10 segundos.

---

## Flujo de arranque

```
Boot
 └─ systemd activa zenbook-duo.service (tras graphical.target)
     └─ ExecStartPre espera /run/user/<UID>/wayland-0
         └─ daemon.py arranca
             ├─ TouchscreenMapper.apply()                 (dconf sesión, inmediato)
             ├─ BatteryManager.set_charge_limit()         (sysfs, inmediato)
             ├─ BluetoothManager(macs)
             │   └─ start_unlock_watcher()                (hilo: dbus-monitor logind)
             ├─ KeyboardBacklightManager.apply()          (ioctl HIDIOCSFEATURE si hay dock)
             ├─ DockMonitor._sincronizar_estado_inicial()
             │   ├─ teclado presente → apaga eDP-2 + reaplica backlight (thread)
             │   └─ teclado ausente  → enciende eDP-2, conecta BT
             ├─ BrightnessManager.start()
             │   └─ hilo: gdbus monitor (sync con debounce + mute eco)
             ├─ Aviso GNOME ambient-enabled (si auto_brightness=false y GNOME lo tiene on)
             ├─ RotationManager.start()
             │   └─ hilo: monitor-sensor (auto-restart si muere)
             │       ├─ evento orientación → debounce → gnome_randr.py (con lock)
             │       └─ evento lux → BrightnessManager.apply_lux()
             │                           └─ _apply_both() en 2 hilos paralelos
             ├─ PowerProfileManager.start()
             │   ├─ _apply_for_state(estado_inicial)      (perfil + rate inmediato)
             │   └─ hilo: dbus-monitor UPower
             ├─ OledCareManager.start()
             │   └─ hilo: select() sobre /dev/input/event* del touchscreen inferior
             │       ├─ inactivo idle_minutes → acquire_screenpad + dim
             │       └─ touch detectado → release_screenpad + restore
             └─ (opt-in) Watchdog refresh display si watchdog.display_refresh_minutes > 0
```

---

## Dependencias

| Paquete | Uso |
|---|---|
| `iio-sensor-proxy` | Expone acelerómetro y sensor de luz; binario `monitor-sensor` |
| `python3-dbus` | D-Bus requerido por `gnome_randr.py` (dbus-python) |
| `python3-yaml` (PyYAML) | Parsing de `config.yaml` |
| `pyudev` | Eventos udev para detección del teclado en `DockMonitor` |
| `bluetooth` / `bluez` | `busctl`, `rfkill` para reconexión de dispositivos BT |
| `dbus-monitor` (`dbus`) | Listener de UPower y `logind Session.Unlock` |
| `upower` | Fuente de eventos de cambio AC/batería para `PowerProfileManager` |

---

## Consideraciones de seguridad

- El daemon corre como **root** por necesidad (sysfs de batería y backlight, udev, hidraw).
- Los comandos que afectan la sesión gráfica se ejecutan como el **usuario no-privilegiado** via `sudo -u <user>`.
- `run_in_user_session()` aplica un timeout de 15 s a cada subproceso para evitar que un Mutter colgado bloquee al daemon completo.
- No hay escritura de archivos fuera de `/opt/zenbook-duo/`, `/sys/class/`, `/sys/firmware/acpi/platform_profile` y `/dev/hidraw*`.
- El `config.yaml` no contiene secretos, pero sí la MAC del teclado Bluetooth.

---

## Decisiones de tuning del sistema operativo

Estas decisiones no son del daemon pero se documentan aquí porque afectan el rendimiento real del equipo y forman parte del setup recomendado.

### `pcie_aspm=performance` en GRUB

Por defecto el firmware de UEFI de ASUS deja PCIe ASPM en `default`, que ata cada bridge a la política conservadora del firmware (estados L1 agresivos). Para workloads que dependen de latencia consistente del bus (NVMe en particular), se recomienda forzar el modo `performance`:

```
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash pcie_aspm=performance"
```

Verificación post-reboot: `cat /sys/module/pcie_aspm/parameters/policy` debe mostrar `[performance]` entre corchetes.

### El cargador como cuello de botella real

El SoC Core Ultra 9 185H tiene PL1 sostenido por encima de 60 W bajo carga real y PL2 hasta ~115 W. La negociación USB-C PD del Zenbook Duo se puede leer indirectamente desde:

```bash
sensors | grep -A1 ucsi_source_psy
# curr1: <amps>   ← multiplicar por 20 V (rail típico para >60W) para obtener W
```

**Si el cargador entrega <90 W**, el firmware del EC permite que la batería supla el déficit hasta cierto umbral; cuando éste se cruza, **reduce TDP del CPU agresivamente** sin importar `platform_profile`. Resultado: pierdes turbo sostenido por hardware antes que por SO. Detección práctica:

```bash
stress-ng --cpu 0 --timeout 120s &
watch -n1 'cat /sys/class/power_supply/BAT0/status /sys/class/power_supply/AC0/online'
```

Si `BAT0/status` cambia a `Discharging` mientras `AC0/online` es 1, el cargador es insuficiente.

### Cosas que **no** se aplican en este chip

- **Undervolt vía MSR**: Intel bloqueó esta vía a partir de Plundervolt (12th gen+). En Meteor Lake (Core Ultra) está confirmadamente cerrado. La única opción es BIOS modeada — fuera de scope.
- **`mitigations=off`**: en Meteor Lake la mayoría de vulnerabilidades reportan `Not affected` (ver `/sys/devices/system/cpu/vulnerabilities/`). La ganancia esperable es 1-3% a costa de eliminar las pocas mitigaciones reales (`spec_store_bypass`, `vmscape`). No vale la pena.
- **Custom fan curves**: el embedded controller del Zenbook Duo no expone PWMs editables al kernel. Imposible sin BIOS modeada.
- **Forzar `scaling_governor=performance`**: marginal frente a la combinación actual (`powersave + EPP=performance`), que es la combinación correcta para `intel_pstate` moderno.
- **Driver `xe` en lugar de `i915`** para el GPU Arc: técnicamente más reciente y diseñado para Meteor Lake, pero a fecha de escribir esto, en kernel 6.17 sigue marcado experimental y puede romper suspend/resume. Descartado del setup recomendado.
