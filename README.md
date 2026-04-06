# Zenbook Duo Control — Ubuntu

> Read this in English: [README_EN.md](README_EN.md)

Control de hardware para el ASUS Zenbook Duo con doble pantalla OLED en Ubuntu 24. ASUS no proporciona soporte oficial para estas funciones en Linux, por lo que este proyecto las implementa directamente.

## Funciones

| Función | Descripción |
|---|---|
| **Auto-rotación** | Rota ambas pantallas al girar el equipo (modo portátil ↔ modo libro), con debounce para coalescer eventos rápidos del acelerómetro |
| **Brillo automático** | Ajusta el brillo de ambas pantallas en paralelo según el sensor de luz ambiental integrado; sincroniza eDP-2 cuando se usan las teclas de brillo, con debounce y mute de eco propio para evitar loops de retroalimentación |
| **Protección de batería** | Limita la carga máxima para prolongar la vida útil de la batería |
| **Control de pantalla inferior** | Apaga la pantalla inferior al acoplar el teclado y la enciende al retirarlo; reconecta el teclado Bluetooth y otros dispositivos al desbloquear pantalla |
| **Mapeo de touchscreens** | Asigna cada pantalla táctil a su pantalla correcta en GNOME Wayland (resuelve el problema de EDID idéntico entre ambos paneles usando el 4º elemento del dconf que Mutter ≥ 42 acepta como nombre de conector) |
| **Power profile automático** | Aplica `platform_profile` y refresh rate distintos según AC/batería (e.g. `performance @ 120 Hz` enchufado, `balanced @ 60 Hz` en batería) escuchando eventos de UPower |
| **OLED care** | Atenúa el screenpad inferior tras inactividad táctil configurable, para preservar el panel OLED frente a contenido estático |
| **Backlight del teclado dock** | Reaplica el nivel del backlight del teclado USB cuando se acopla, mediante un HID feature report propietario de ASUS |

---

## Requisitos

- Ubuntu 24.04 o superior con GNOME y Wayland
- ASUS Zenbook Duo (probado en el modelo con doble pantalla OLED 2.8K)
- Python 3.10+
- Ejecutar el instalador con `sudo`

---

## Instalación rápida

```bash
git clone https://github.com/haefrain/zenbook-duo-control-pantallas-ubuntu
cd zenbook-duo-control-pantallas-ubuntu
sudo ./install.sh
```

El instalador hace todo automáticamente:
1. Detecta tu usuario
2. Instala las dependencias del sistema (`iio-sensor-proxy`, `python3-dbus`, etc.)
3. Te pregunta qué funciones quieres activar — responde **`s`** (o `S`/`y`/`Y`) para sí, **`n`** (o `N`) para no; pulsa **Enter** para aceptar el valor por defecto que aparece entre corchetes
4. Crea `/opt/zenbook-duo/config.yaml` con tu configuración
5. Instala y activa el servicio `zenbook-duo` en systemd

---

## Reconfigurar sin reinstalar

Si ya tienes el proyecto instalado y quieres cambiar qué funciones están activas o ajustar cualquier valor:

```bash
sudo ./configure.sh
```

El configurador:
1. Muestra el estado actual de cada función
2. Te pregunta una a una — pulsa **Enter** para mantener el valor actual, **`s`** para activar, **`n`** para desactivar
3. Actualiza `/opt/zenbook-duo/config.yaml`
4. Reinicia el servicio automáticamente

---

## Instalación manual

Si el instalador no pudo completarse o prefieres hacerlo paso a paso:

### 1. Instalar dependencias del sistema

```bash
sudo apt-get install -y \
    iio-sensor-proxy \
    python3-dbus \
    python3-yaml \
    python3-pip \
    python3-venv \
    bluetooth \
    bluez
```

### 2. Copiar los archivos

```bash
sudo mkdir -p /opt/zenbook-duo
sudo cp -r core modules requirements.txt /opt/zenbook-duo/
```

### 3. Crear el entorno Python

```bash
sudo python3 -m venv /opt/zenbook-duo/venv
sudo /opt/zenbook-duo/venv/bin/pip install -r /opt/zenbook-duo/requirements.txt
```

### 4. Crear la configuración

```bash
sudo cp config.yaml.example /opt/zenbook-duo/config.yaml
sudo nano /opt/zenbook-duo/config.yaml
```

Rellena los valores según tu equipo (ver [Referencia de config.yaml](#referencia-de-configyaml)).

### 5. Instalar el servicio systemd

Sustituye `TU_USUARIO` por tu nombre de usuario:

```bash
sed "s/__USERNAME__/TU_USUARIO/g" zenbook-duo.service \
    | sudo tee /etc/systemd/system/zenbook-duo.service

sudo systemctl daemon-reload
sudo systemctl enable zenbook-duo
sudo systemctl start zenbook-duo
```

---

## Referencia de `config.yaml`

```yaml
system:
  username: "tu_usuario"            # resultado de: whoami

features:
  auto_rotate: true                 # Rotación automática de pantallas
  auto_brightness: true             # Brillo por sensor de luz ambiental
  battery_protection: true          # Límite de carga de la batería
  display_dock: true                # Control de pantalla inferior con el teclado
  touchscreen_mapping: true         # Mapear cada touchscreen a su pantalla correcta
  power_profile: true               # Cambiar perfil + refresh rate según AC/batería
  oled_care: true                   # Atenuar la pantalla inferior tras inactividad
  keyboard_backlight: true          # Reaplicar el backlight del teclado al dockar

keyboard:
  vendor_id: "0b05"                 # Ver con: lsusb | grep -i asus
  product_id: "1b2c"                # Producto USB del teclado cuando está dockeado
  mac_address: "XX:XX:XX:XX:XX:XX"  # Ver con: bluetoothctl devices
  backlight_level: 1                # 0 = apagado, 1..3 = niveles de retroiluminación
  backlight_vendor: "0b05"
  backlight_product: "1b2c"         # El backlight sólo aplica con el teclado dockeado

displays:
  top: "eDP-1"                      # Nombre de la pantalla superior
  bottom: "eDP-2"                   # Nombre de la pantalla inferior
  scale: 2                          # Factor de escala HiDPI (2 en OLED 2.8K)

battery:
  charge_limit: 80                  # Porcentaje máximo de carga

bluetooth:
  devices:                          # MACs adicionales a reconectar al desbloqueo
    - "YY:YY:YY:YY:YY:YY"
  reconnect_on_unlock: true

watchdog:
  display_refresh_minutes: 0        # 0 = desactivado (recomendado). >0 fuerza un
                                    # ApplyMonitorsConfig --force cada N minutos.
                                    # No previene congelamientos del compositor.

touchscreen:
  top_device: "04f3:425b"           # HID vendor:product del touchscreen superior (ELAN9008)
  bottom_device: "04f3:425a"        # HID vendor:product del touchscreen inferior (ELAN9009)
  swap: false                       # Cambiar a true si los touchscreens quedan invertidos

power_profiles:
  on_ac:
    profile: performance            # quiet | balanced | performance
    refresh_rate: 120               # Hz; usa null para no tocarlo
  on_battery:
    profile: balanced
    refresh_rate: 60

oled_care:
  idle_dim_enabled: true            # Atenuar eDP-2 tras inactividad táctil
  idle_minutes: 5                   # Minutos sin tocar para considerarla "ociosa"
  dim_percent: 5                    # Nivel al que se atenúa
  bottom_vendor: "04f3"             # Debe coincidir con touchscreen.bottom_device
  bottom_product: "425a"
```

### Cómo obtener cada valor

**Tu nombre de usuario:**
```bash
whoami
```

**Vendor ID y Product ID del teclado** (con el teclado acoplado):
```bash
lsusb | grep -i asus
# Ejemplo: Bus 003 Device 004: ID 0b05:1b2c ASUSTek Computer...
#                                   ^^^^ ^^^^
#                                   VID  PID
```

**MAC Bluetooth del teclado:**
```bash
bluetoothctl devices
# Ejemplo: Device E4:6E:92:D8:01:DF ASUS Keyboard
```

**Nombres de las pantallas:**
```bash
sudo -u TU_USUARIO env \
    XDG_RUNTIME_DIR=/run/user/$(id -u TU_USUARIO) \
    WAYLAND_DISPLAY=wayland-0 \
    python3 /opt/zenbook-duo/core/gnome_randr.py
# Busca las líneas "associated physical monitors: eDP-X"
```

---

## Gestión del servicio

```bash
# Reconfigurar funciones y ajustes (interactivo)
sudo ./configure.sh

# Estado actual
systemctl status zenbook-duo

# Logs en tiempo real
journalctl -u zenbook-duo -f

# Reiniciar tras cambiar config.yaml manualmente
sudo systemctl restart zenbook-duo

# Detener temporalmente
sudo systemctl stop zenbook-duo

# Deshabilitar del inicio automático
sudo systemctl disable zenbook-duo
```

---

## Solución de problemas

### El servicio no arranca

```bash
journalctl -u zenbook-duo -n 50
```

**Wayland no disponible:** el servicio espera 60 segundos a que `/run/user/<UID>/wayland-0` exista. Si necesitas más tiempo:

```bash
sudo nano /etc/systemd/system/zenbook-duo.service
# Cambia `seq 60` por `seq 120` en la línea ExecStartPre
sudo systemctl daemon-reload && sudo systemctl restart zenbook-duo
```

**`config.yaml` no encontrado:**
```bash
ls /opt/zenbook-duo/config.yaml
# Si no existe, créalo:
sudo cp config.yaml.example /opt/zenbook-duo/config.yaml
sudo nano /opt/zenbook-duo/config.yaml
```

**Error de importación Python:**
```bash
sudo /opt/zenbook-duo/venv/bin/pip install -r /opt/zenbook-duo/requirements.txt
```

---

### La auto-rotación no funciona

**1. Verifica que iio-sensor-proxy esté activo:**
```bash
systemctl status iio-sensor-proxy
sudo systemctl enable --now iio-sensor-proxy   # si no estaba activo
```

**2. Comprueba que el sensor responde:**
```bash
monitor-sensor
# Debes ver algo como:
# === Has accelerometer (orientation: normal)
# Accelerometer orientation changed: right-up
```

**3. Verifica la config:**
```bash
grep auto_rotate /opt/zenbook-duo/config.yaml
# Debe mostrar: auto_rotate: true
```

---

### El brillo automático no cambia la pantalla principal (eDP-1)

El brillo de eDP-1 se controla vía D-Bus de GNOME. Prueba manualmente:

```bash
sudo -u TU_USUARIO env \
    XDG_RUNTIME_DIR=/run/user/$(id -u TU_USUARIO) \
    WAYLAND_DISPLAY=wayland-0 \
    gdbus call --session \
    --dest org.gnome.SettingsDaemon.Power \
    --object-path /org/gnome/SettingsDaemon/Power \
    --method org.freedesktop.DBus.Properties.Set \
    'org.gnome.SettingsDaemon.Power.Screen' 'Brightness' '<int32 50>'
```

Si el comando falla, comprueba que `gnome-settings-daemon` está corriendo:
```bash
pgrep -a gsd-power
```

---

### El brillo automático no cambia la pantalla inferior (eDP-2 / screenpad)

La pantalla inferior se controla **únicamente** vía `/sys/class/backlight/asus_screenpad/` (requiere root). Anteriormente el daemon también escribía en `card1-eDP-2-backlight`, pero eso causaba un loop de retroalimentación con `gnome-settings-daemon` (que monitorea ese DRM backlight) — fue eliminado.

```bash
# ¿La interfaz existe?
ls /sys/class/backlight/asus_screenpad/

# Prueba manual como root:
echo 120 | sudo tee /sys/class/backlight/asus_screenpad/brightness
```

---

### El brillo no cambia en eDP-2 al pulsar las teclas de brillo

El daemon monitorea el D-Bus de GNOME para detectar cambios manuales de brillo y replicarlos al screenpad con debouncing (coalesce de la animación interpolada de GNOME en pasos de 1%). Si no funciona, verifica que el servicio esté corriendo y que `gnome-settings-daemon` esté activo:

```bash
pgrep -a gsd-power
journalctl -u zenbook-duo -f   # busca líneas "[BRILLO] Sync →"
```

---

### El brillo se baja solo aunque `auto_brightness` esté en `false`

Probablemente GNOME tiene activado su propio brillo automático por sensor de luz, independiente del de este proyecto. El daemon te avisa al arrancar si lo detecta. Para desactivarlo:

```bash
gsettings set org.gnome.settings-daemon.plugins.power ambient-enabled false
```

Si lo prefieres dejar activo en GNOME, ten en cuenta que nuestro `BrightnessManager` replicará esos cambios al screenpad (es el comportamiento esperado).

---

### Los touchscreens no responden en la pantalla correcta

**1. Verifica que el mapeo se aplicó:**
```bash
dconf dump /org/gnome/desktop/peripherals/touchscreens/
# Debe mostrar arrays de 4 elementos (vendor, product, serial, conector):
# [04f3:425b]
# output=['SDC', '0x419d', '0x00000000', 'eDP-1']
#
# [04f3:425a]
# output=['SDC', '0x419d', '0x00000000', 'eDP-2']
```

> **Nota técnica:** los dos paneles del Zenbook Duo reportan EDID idéntico
> (mismo `vendor`, `product` y `serial`), por lo que el matching estándar de
> Mutter no puede distinguirlos. Mutter ≥ 42 acepta un cuarto elemento en el
> array `output` que es el nombre del conector (`eDP-1`/`eDP-2`) y lo usa
> específicamente como tie-breaker cuando hay monitores duplicados. El
> daemon escribe los 4 elementos al arrancar; **el cambio sólo lo lee Mutter
> al añadir el dispositivo, así que la primera vez requiere re-login**.

**2. Si el mapeo está invertido** (el touch de eDP-2 actúa sobre eDP-1 y viceversa), activa `swap` en el config:
```bash
sudo nano /opt/zenbook-duo/config.yaml
# Cambia:  swap: false  →  swap: true
sudo systemctl restart zenbook-duo
```

**3. Si los IDs de dispositivo son distintos en tu equipo:**
```bash
cat /proc/bus/input/devices | grep -A3 "ELAN"
# Anota los Vendor/Product de cada touchscreen y actualiza top_device y bottom_device
```

---

### La protección de batería no se aplica

El límite se escribe en la primera ruta sysfs disponible. Comprueba cuál existe en tu equipo:

```bash
ls /sys/class/power_supply/BAT*/charge_control_end_threshold 2>/dev/null
ls /sys/devices/platform/asus-nb-wmi/charge_control_end_threshold 2>/dev/null

# Aplicar manualmente:
echo 80 | sudo tee /sys/class/power_supply/BAT0/charge_control_end_threshold
```

> **Nota:** Si tienes **TLP** instalado, puede estar sobreescribiendo el límite. Configúralo en `/etc/tlp.conf` con `STOP_CHARGE_THRESH_BAT0=80`.

---

### El control de pantalla inferior no detecta el teclado

**1. Verifica que el teclado aparece en USB con el teclado acoplado:**
```bash
lsusb | grep -i asus
```

**2. Si el VID/PID no coincide, actualiza la config:**
```bash
sudo nano /opt/zenbook-duo/config.yaml
sudo systemctl restart zenbook-duo
```

**3. Verifica que el daemon corre como root:**
```bash
systemctl show zenbook-duo --property=User
# Debe mostrar: User=root
```

---

### El power profile automático no cambia al desconectar el cargador

```bash
# Verifica el perfil activo:
cat /sys/firmware/acpi/platform_profile

# Verifica que el feature está habilitada y que UPower emite eventos:
grep power_profile /opt/zenbook-duo/config.yaml
journalctl -u zenbook-duo -f | grep POWER
```

Si UPower no responde, asegúrate de que `upower.service` esté corriendo:
```bash
systemctl status upower
```

---

### El backlight del teclado no se enciende al dockar

**1. Verifica que el teclado USB aparece tras dockar:**
```bash
lsusb | grep 0b05
```

Si no aparece nada, el teclado no se está enumerando como USB; el backlight sólo es controlable cuando está acoplado físicamente (en modo Bluetooth no aplica porque el teclado queda debajo de la pantalla inferior).

**2. Verifica que el hidraw existe:**
```bash
for h in /sys/class/hidraw/hidraw*; do
  cat "$h/device/uevent" 2>/dev/null | grep -i 1B2C && echo "  → $(basename $h)"
done
```

**3. Cambia el nivel manualmente** editando `keyboard.backlight_level` (0–3) en `config.yaml` y reinicia el servicio:
```bash
sudo nano /opt/zenbook-duo/config.yaml
sudo systemctl restart zenbook-duo
```

---

### El idle dim del OLED no se activa

```bash
# Verifica que el daemon ve los devices del touchscreen inferior:
journalctl -u zenbook-duo | grep OLED
# Debe mostrar: "[OLED] monitoreando N input device(s) del eDP-2"
```

Si dice `No encontré touchscreen…`, revisa que `oled_care.bottom_vendor` y `oled_care.bottom_product` coincidan con los IDs reales:
```bash
for d in /sys/class/input/event*/device; do
  v=$(cat $d/id/vendor 2>/dev/null)
  p=$(cat $d/id/product 2>/dev/null)
  n=$(cat $d/name 2>/dev/null)
  [[ "$n" == *ELAN* ]] && echo "$v:$p $n"
done
```

---

### Diagnóstico completo de un tirón

```bash
echo "=== Servicio ===" && systemctl status zenbook-duo --no-pager
echo "=== Últimos logs ===" && journalctl -u zenbook-duo -n 30 --no-pager
echo "=== Sensor ===" && systemctl status iio-sensor-proxy --no-pager
echo "=== Backlight eDP-1 ===" && cat /sys/class/backlight/intel_backlight/brightness
echo "=== Backlight eDP-2 ===" && cat /sys/class/backlight/asus_screenpad/brightness
echo "=== Batería ===" && cat /sys/class/power_supply/BAT0/charge_control_end_threshold 2>/dev/null || echo "ruta no encontrada"
echo "=== Power profile ===" && cat /sys/firmware/acpi/platform_profile
echo "=== AC online ===" && cat /sys/class/power_supply/AC0/online
echo "=== Touchscreens dconf ===" && dconf dump /org/gnome/desktop/peripherals/touchscreens/
```

---

## Ajustes opcionales del sistema (rendimiento)

Estos ajustes no son del daemon, sino del sistema operativo. Son seguros para el hardware (no causan daño físico, las protecciones de Tjmax/PL/VRM siempre quedan activas) y reversibles editando un archivo de texto.

### PCIe ASPM en `performance`

Por defecto el firmware deja PCIe ASPM en estados conservadores que añaden latencia al bus (afecta a NVMe entre otros). Forzarlo a `performance` lo deja siempre activo. Coste: ~1-2 W más en idle.

```bash
# 1. Backup
sudo cp /etc/default/grub /etc/default/grub.bak.$(date +%Y%m%d-%H%M%S)

# 2. Añadir el parámetro al cmdline
sudo nano /etc/default/grub
# Cambia:  GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
# Por:     GRUB_CMDLINE_LINUX_DEFAULT="quiet splash pcie_aspm=performance"

# 3. Regenerar grub.cfg y reiniciar
sudo update-grub
sudo reboot

# 4. Tras reiniciar, verificar:
cat /sys/module/pcie_aspm/parameters/policy
# Debe mostrar: default performance [performance] powersave powersupersave
```

Para revertir: edita `/etc/default/grub`, quita el parámetro, `sudo update-grub`, reinicia.

### Monitoreo de temperaturas (`lm-sensors`)

Sólo lectura, no modifica nada. Útil para verificar si hay throttling térmico real bajo carga.

```bash
sudo apt install -y lm-sensors
sudo sensors-detect --auto
sensors
```

Sensores que verás en este equipo:
- `coretemp-isa-0000`: temperaturas por core (Tjmax = 110 °C)
- `nvme-pci-e100`: temperaturas del SSD NVMe
- `asus-isa-0000` / `acpi_fan-isa-0000`: RPM del ventilador
- `BAT0-acpi-0`: voltaje y consumo instantáneo de la batería
- `ucsi_source_psy_USBC*`: corriente negociada del cargador USB-C
- `acpitz-acpi-0`: **ignora este**, en los Zenbook Duo el firmware ACPI lo expone como un valor constante (≈100 °C) que no es un sensor real

---

## Rendimiento bajo carga sostenida — el cargador es clave

El Core Ultra 9 185H del Zenbook Duo puede pedir hasta ~115 W de boost (PL2) y un PL1 sostenido por encima de 60 W bajo carga real. **Si tu cargador USB-C no entrega al menos 90-100 W, el equipo descargará la batería para suplir el déficit y, cuando ésta baje, el firmware reducirá el TDP del CPU agresivamente** — pierdes turbo sostenido por culpa del cargador, no del SO.

Para verificar el wattage real que negocia tu cargador:

```bash
# Mira la corriente del puerto USB-C que está activo
sensors | grep -A1 ucsi_source_psy
# curr1: 3.25 A → en USB-C PD a 20 V son 65 W
# curr1: 5.00 A → 100 W (lo deseable)
```

Para confirmar que el cargador es tu cuello de botella, corre una carga sostenida y mira si la batería pasa a `Discharging` con AC enchufado:

```bash
sudo apt install -y stress-ng
stress-ng --cpu 0 --timeout 120s &
watch -n1 'echo "===" && cat /sys/class/power_supply/BAT0/status && grep MHz /proc/cpuinfo | head -3 && sensors | grep Package'
```

Si `BAT0/status` cambia a `Discharging` mientras `AC0/online` es 1, el cargador es insuficiente y un cargador PD de 100 W o más mejorará el rendimiento sostenido entre **20-40 %**, muy por encima de cualquier tweak de software.

---

## Actualización

```bash
cd zenbook-duo-control-pantallas-ubuntu
git pull
sudo ./install.sh
```

El instalador es idempotente: si ya está instalado, actualiza los archivos y reinicia el servicio.

> Si solo quieres cambiar la configuración sin actualizar el código, usa `sudo ./configure.sh` en lugar de reinstalar.

---

## Desinstalación

```bash
sudo systemctl stop zenbook-duo
sudo systemctl disable zenbook-duo
sudo rm /etc/systemd/system/zenbook-duo.service
sudo rm -rf /opt/zenbook-duo
sudo systemctl daemon-reload
```
