# Zenbook Duo Control — Ubuntu

> Read this in English: [README_EN.md](README_EN.md)

Control de hardware para el ASUS Zenbook Duo con doble pantalla OLED en Ubuntu 24. ASUS no proporciona soporte oficial para estas funciones en Linux, por lo que este proyecto las implementa directamente.

## Funciones

| Función | Descripción |
|---|---|
| **Auto-rotación** | Rota ambas pantallas al girar el equipo (modo portátil ↔ modo libro) |
| **Brillo automático** | Ajusta el brillo de ambas pantallas en paralelo según el sensor de luz ambiental integrado; sincroniza eDP-2 cuando se usan las teclas de brillo |
| **Protección de batería** | Limita la carga máxima para prolongar la vida útil de la batería |
| **Control de pantalla inferior** | Apaga la pantalla inferior al acoplar el teclado y la enciende al retirarlo; reconecta el teclado Bluetooth automáticamente |
| **Mapeo de touchscreens** | Asigna cada pantalla táctil a su pantalla correcta en GNOME Wayland (soluciona el problema de EDID idéntico entre ambos paneles) |

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

keyboard:
  vendor_id: "0b05"                 # Ver con: lsusb | grep -i asus
  product_id: "1b2c"
  mac_address: "XX:XX:XX:XX:XX:XX" # Ver con: bluetoothctl devices

displays:
  top: "eDP-1"                      # Nombre de la pantalla superior
  bottom: "eDP-2"                   # Nombre de la pantalla inferior
  scale: 2                          # Factor de escala HiDPI (2 en OLED 2.8K)

battery:
  charge_limit: 80                  # Porcentaje máximo de carga

touchscreen:
  top_device: "04f3:425b"           # HID vendor:product del touchscreen superior (ELAN9008)
  bottom_device: "04f3:425a"        # HID vendor:product del touchscreen inferior (ELAN9009)
  swap: false                       # Cambiar a true si los touchscreens quedan invertidos
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

La pantalla inferior usa dos interfaces sysfs que requieren root. El daemon debe correr como servicio (no manualmente sin sudo).

```bash
# ¿Las interfaces existen?
ls /sys/class/backlight/card1-eDP-2-backlight/
ls /sys/class/backlight/asus_screenpad/

# Prueba manual como root:
echo 120 | sudo tee /sys/class/backlight/asus_screenpad/brightness
echo 200 | sudo tee /sys/class/backlight/card1-eDP-2-backlight/brightness
```

---

### El brillo no cambia en eDP-2 al pulsar las teclas de brillo

El daemon monitorea el D-Bus de GNOME para detectar cambios manuales de brillo y replicarlos a eDP-2. Si no funciona, verifica que el servicio esté corriendo y que `gnome-settings-daemon` esté activo:

```bash
pgrep -a gsd-power
journalctl -u zenbook-duo -f   # busca líneas "[BRILLO] Tecla →"
```

---

### Los touchscreens no responden en la pantalla correcta

**1. Verifica que el mapeo se aplicó:**
```bash
dconf dump /org/gnome/desktop/peripherals/touchscreens/
# Debe mostrar:
# [04f3:425b/]
# output=['', 'eDP-1', '']
#
# [04f3:425a/]
# output=['', 'eDP-2', '']
```

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

### Diagnóstico completo de un tirón

```bash
echo "=== Servicio ===" && systemctl status zenbook-duo --no-pager
echo "=== Últimos logs ===" && journalctl -u zenbook-duo -n 30 --no-pager
echo "=== Sensor ===" && systemctl status iio-sensor-proxy --no-pager
echo "=== Backlight eDP-1 ===" && cat /sys/class/backlight/intel_backlight/brightness
echo "=== Backlight eDP-2 ===" && cat /sys/class/backlight/asus_screenpad/brightness
echo "=== Batería ===" && cat /sys/class/power_supply/BAT0/charge_control_end_threshold 2>/dev/null || echo "ruta no encontrada"
```

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
