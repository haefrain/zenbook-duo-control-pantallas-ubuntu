# Especificación Técnica — Zenbook Duo Control

---

## Arquitectura general

El proyecto corre como un **servicio systemd de root** (`zenbook-duo.service`) que arranca tras la sesión gráfica del usuario. El daemon principal orquesta módulos independientes, cada uno en su propio hilo, y comparte un único proceso `monitor-sensor` para los eventos del acelerómetro y el sensor de luz.

```
systemd (root)
└── core/daemon.py
    ├── BatteryManager          → sysfs directo (root)
    ├── DockMonitor             → udev netlink (root)
    │   └── BluetoothManager    → bluetoothctl subprocess
    ├── BrightnessManager       → D-Bus GNOME (sesión usuario) + sysfs (root)
    └── RotationManager         → monitor-sensor subprocess
        ├── orientación         → gnome_randr.py vía D-Bus GNOME (sesión usuario)
        └── lux                 → BrightnessManager.apply_lux()
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
/opt/zenbook-duo/               ← directorio de instalación
├── config.yaml                 ← configuración activa
├── core/
│   ├── daemon.py               ← punto de entrada, orquestador
│   ├── config_loader.py        ← carga YAML con defaults de features
│   └── gnome_randr.py          ← cliente D-Bus para Mutter DisplayConfig
├── modules/
│   ├── auto_rotate.py          ← RotationManager
│   ├── auto_brightness.py      ← BrightnessManager
│   ├── battery.py              ← BatteryManager
│   ├── display_dock.py         ← DockMonitor (udev)
│   └── bluetooth.py            ← BluetoothManager
└── venv/                       ← entorno Python aislado
```

```
/etc/systemd/system/
└── zenbook-duo.service         ← unit de systemd

/sys/class/backlight/
├── intel_backlight/            ← eDP-1: controlado por GNOME vía D-Bus
├── card1-eDP-2-backlight/      ← eDP-2: DRM backlight (root, sysfs directo)
└── asus_screenpad/             ← eDP-2: control ASUS nativo (root, sysfs directo)

/sys/class/power_supply/
└── BAT0/charge_control_end_threshold   ← límite de carga (root, sysfs directo)
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
| `Accelerometer orientation changed: <orientación>` | Llama a `_apply_orientation()` |
| `Light changed: <valor> (lux)` | Llama a `BrightnessManager.apply_lux()` |

**Orientaciones manejadas:**

| Valor del sensor | Modo | Rotación aplicada |
|---|---|---|
| `normal`, `bottom-up` | Portátil (vertical) | `normal` |
| `right-up` | Libro (horizontal) | `right` |
| `left-up` | Libro (horizontal) | `left` |

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

**Control de pantallas:**

- **eDP-1 (`intel_backlight`):** vía D-Bus GNOME (`org.gnome.SettingsDaemon.Power.Screen`, propiedad `Brightness`). Acepta un entero 0–100 (porcentaje directo). Requiere sesión gráfica activa.
- **eDP-2 (`card1-eDP-2-backlight` y `asus_screenpad`):** escritura directa a sysfs. Requiere root. El valor se escala proporcionalmente al `max_brightness` de cada interfaz. Antes de escribir se verifica `bl_power == 0` (pantalla encendida).

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

**Callbacks:**
- `on_dock`: apaga eDP-2 vía `gnome_randr.py --output eDP-2 --off`
- `on_undock`: enciende eDP-2 con `gnome_randr.py --output eDP-2 --auto --below eDP-1` + reconexión Bluetooth

---

### `modules/bluetooth.py` — BluetoothManager

Lanza `bluetoothctl` con `connect <MAC>` como subproceso asíncrono (`Popen` sin esperar resultado) para no bloquear el encendido de la pantalla inferior. Previo a la conexión, ejecuta `rfkill unblock bluetooth`.

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
             ├─ BatteryManager.set_charge_limit()   (sysfs, inmediato)
             ├─ DockMonitor._sincronizar_estado_inicial()
             │   ├─ teclado presente → apaga eDP-2
             │   └─ teclado ausente  → enciende eDP-2, conecta BT
             ├─ BrightnessManager (instancia, sin acción inmediata)
             └─ RotationManager.start()
                 └─ hilo: monitor-sensor
                     ├─ evento orientación → gnome_randr.py
                     └─ evento lux → BrightnessManager.apply_lux()
```

---

## Dependencias

| Paquete | Uso |
|---|---|
| `iio-sensor-proxy` | Expone acelerómetro y sensor de luz; binario `monitor-sensor` |
| `python3-dbus` | D-Bus requerido por `gnome_randr.py` (dbus-python) |
| `python3-yaml` (PyYAML) | Parsing de `config.yaml` |
| `pyudev` | Eventos udev para detección del teclado en `DockMonitor` |
| `bluetooth` / `bluez` | `bluetoothctl` y `rfkill` para reconexión del teclado |

---

## Consideraciones de seguridad

- El daemon corre como **root** por necesidad (sysfs de batería y backlight, udev).
- Los comandos que afectan la sesión gráfica se ejecutan como el **usuario no-privilegiado** via `sudo -u <user>`.
- No hay escritura de archivos fuera de `/opt/zenbook-duo/` y `/sys/class/`.
- El `config.yaml` no contiene secretos, pero sí la MAC del teclado Bluetooth.
