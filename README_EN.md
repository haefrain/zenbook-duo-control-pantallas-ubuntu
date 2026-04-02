# Zenbook Duo Control — Ubuntu

Hardware control for the ASUS Zenbook Duo with dual OLED screens on Ubuntu 24. ASUS provides no official Linux support for these features, so this project implements them directly.

## Features

| Feature | Description |
|---|---|
| **Auto-rotation** | Rotates both screens when the device is turned (laptop mode ↔ book mode) |
| **Auto-brightness** | Adjusts brightness on both screens using the built-in ambient light sensor |
| **Battery protection** | Caps the maximum charge level to extend battery lifespan |
| **Secondary screen control** | Turns off the lower screen when the keyboard is attached and turns it back on when detached; automatically reconnects the Bluetooth keyboard |

---

## Requirements

- Ubuntu 24.04 or later with GNOME and Wayland
- ASUS Zenbook Duo (tested on the model with dual 2.8K OLED screens)
- Python 3.10+
- Run the installer with `sudo`

---

## Quick install

```bash
git clone https://github.com/haefrain/zenbook-duo-control-pantallas-ubuntu
cd zenbook-duo-control-pantallas-ubuntu
sudo ./install.sh
```

The installer handles everything automatically:
1. Detects your username
2. Installs system dependencies (`iio-sensor-proxy`, `python3-dbus`, etc.)
3. Asks which features to enable — type **`y`** (or `Y`/`s`/`S`) for yes, **`n`** (or `N`) for no; press **Enter** to accept the default shown in brackets
4. Creates `/opt/zenbook-duo/config.yaml` with your settings
5. Installs and enables the `zenbook-duo` systemd service

---

## Reconfigure without reinstalling

If the project is already installed and you want to toggle features or update any value:

```bash
sudo ./configure.sh
```

The configurator:
1. Shows the current state of each feature
2. Asks one by one — press **Enter** to keep the current value, **`y`** to enable, **`n`** to disable
3. Updates `/opt/zenbook-duo/config.yaml`
4. Restarts the service automatically

---

## Manual installation

If the installer did not complete or you prefer to do it step by step:

### 1. Install system dependencies

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

### 2. Copy the files

```bash
sudo mkdir -p /opt/zenbook-duo
sudo cp -r core modules requirements.txt /opt/zenbook-duo/
```

### 3. Create the Python environment

```bash
sudo python3 -m venv /opt/zenbook-duo/venv
sudo /opt/zenbook-duo/venv/bin/pip install -r /opt/zenbook-duo/requirements.txt
```

### 4. Create the configuration file

```bash
sudo cp config.yaml.example /opt/zenbook-duo/config.yaml
sudo nano /opt/zenbook-duo/config.yaml
```

Fill in the values for your device (see [config.yaml reference](#configyaml-reference)).

### 5. Install the systemd service

Replace `YOUR_USERNAME` with your actual username:

```bash
sed "s/__USERNAME__/YOUR_USERNAME/g" zenbook-duo.service \
    | sudo tee /etc/systemd/system/zenbook-duo.service

sudo systemctl daemon-reload
sudo systemctl enable zenbook-duo
sudo systemctl start zenbook-duo
```

---

## `config.yaml` reference

```yaml
system:
  username: "your_user"             # result of: whoami

features:
  auto_rotate: true                 # Automatic screen rotation
  auto_brightness: true             # Brightness from ambient light sensor
  battery_protection: true          # Battery charge limit
  display_dock: true                # Lower screen control with keyboard

keyboard:
  vendor_id: "0b05"                 # See: lsusb | grep -i asus
  product_id: "1b2c"
  mac_address: "XX:XX:XX:XX:XX:XX" # See: bluetoothctl devices

displays:
  top: "eDP-1"                      # Name of the top screen
  bottom: "eDP-2"                   # Name of the bottom screen
  scale: 2                          # HiDPI scale factor (2 on 2.8K OLED)

battery:
  charge_limit: 80                  # Maximum charge percentage
```

### How to find each value

**Your username:**
```bash
whoami
```

**Keyboard Vendor ID and Product ID** (with keyboard attached):
```bash
lsusb | grep -i asus
# Example: Bus 003 Device 004: ID 0b05:1b2c ASUSTek Computer...
#                                   ^^^^ ^^^^
#                                   VID  PID
```

**Keyboard Bluetooth MAC address:**
```bash
bluetoothctl devices
# Example: Device E4:6E:92:D8:01:DF ASUS Keyboard
```

**Screen names:**
```bash
sudo -u YOUR_USERNAME env \
    XDG_RUNTIME_DIR=/run/user/$(id -u YOUR_USERNAME) \
    WAYLAND_DISPLAY=wayland-0 \
    python3 /opt/zenbook-duo/core/gnome_randr.py
# Look for lines "associated physical monitors: eDP-X"
```

---

## Service management

```bash
# Reconfigure features and settings (interactive)
sudo ./configure.sh

# Current status
systemctl status zenbook-duo

# Live logs
journalctl -u zenbook-duo -f

# Restart after manually editing config.yaml
sudo systemctl restart zenbook-duo

# Stop temporarily
sudo systemctl stop zenbook-duo

# Disable from autostart
sudo systemctl disable zenbook-duo
```

---

## Troubleshooting

### The service does not start

```bash
journalctl -u zenbook-duo -n 50
```

**Wayland not available:** the service waits up to 60 seconds for `/run/user/<UID>/wayland-0` to exist. If your login takes longer:

```bash
sudo nano /etc/systemd/system/zenbook-duo.service
# Change `seq 60` to `seq 120` in the ExecStartPre line
sudo systemctl daemon-reload && sudo systemctl restart zenbook-duo
```

**`config.yaml` not found:**
```bash
ls /opt/zenbook-duo/config.yaml
# If missing, create it:
sudo cp config.yaml.example /opt/zenbook-duo/config.yaml
sudo nano /opt/zenbook-duo/config.yaml
```

**Python import error:**
```bash
sudo /opt/zenbook-duo/venv/bin/pip install -r /opt/zenbook-duo/requirements.txt
```

---

### Auto-rotation does not work

**1. Check that iio-sensor-proxy is running:**
```bash
systemctl status iio-sensor-proxy
sudo systemctl enable --now iio-sensor-proxy   # if not active
```

**2. Check that the sensor responds:**
```bash
monitor-sensor
# You should see something like:
# === Has accelerometer (orientation: normal)
# Accelerometer orientation changed: right-up
```

**3. Check the config:**
```bash
grep auto_rotate /opt/zenbook-duo/config.yaml
# Should show: auto_rotate: true
```

---

### Auto-brightness does not change the main screen (eDP-1)

eDP-1 brightness is controlled via the GNOME D-Bus interface. Test manually:

```bash
sudo -u YOUR_USERNAME env \
    XDG_RUNTIME_DIR=/run/user/$(id -u YOUR_USERNAME) \
    WAYLAND_DISPLAY=wayland-0 \
    gdbus call --session \
    --dest org.gnome.SettingsDaemon.Power \
    --object-path /org/gnome/SettingsDaemon/Power \
    --method org.freedesktop.DBus.Properties.Set \
    'org.gnome.SettingsDaemon.Power.Screen' 'Brightness' '<int32 50>'
```

If the command fails, check that `gnome-settings-daemon` is running:
```bash
pgrep -a gsd-power
```

---

### Auto-brightness does not change the lower screen (eDP-2 / screenpad)

The lower screen uses two sysfs interfaces that require root. The daemon must run as a service (not manually without sudo).

```bash
# Do the interfaces exist?
ls /sys/class/backlight/card1-eDP-2-backlight/
ls /sys/class/backlight/asus_screenpad/

# Manual test as root:
echo 120 | sudo tee /sys/class/backlight/asus_screenpad/brightness
echo 200 | sudo tee /sys/class/backlight/card1-eDP-2-backlight/brightness
```

---

### Battery protection is not applied

The charge limit is written to the first available sysfs path. Check which one exists on your device:

```bash
ls /sys/class/power_supply/BAT*/charge_control_end_threshold 2>/dev/null
ls /sys/devices/platform/asus-nb-wmi/charge_control_end_threshold 2>/dev/null

# Apply manually:
echo 80 | sudo tee /sys/class/power_supply/BAT0/charge_control_end_threshold
```

> **Note:** If you have **TLP** installed, it may be overwriting the limit. Configure it in `/etc/tlp.conf` with `STOP_CHARGE_THRESH_BAT0=80`.

---

### Keyboard dock detection does not work

**1. Check that the keyboard appears in USB when attached:**
```bash
lsusb | grep -i asus
```

**2. If the VID/PID does not match, update the config:**
```bash
sudo nano /opt/zenbook-duo/config.yaml
sudo systemctl restart zenbook-duo
```

**3. Verify the daemon runs as root:**
```bash
systemctl show zenbook-duo --property=User
# Should show: User=root
```

---

### Full one-shot diagnostic

```bash
echo "=== Service ===" && systemctl status zenbook-duo --no-pager
echo "=== Last logs ===" && journalctl -u zenbook-duo -n 30 --no-pager
echo "=== Sensor ===" && systemctl status iio-sensor-proxy --no-pager
echo "=== Backlight eDP-1 ===" && cat /sys/class/backlight/intel_backlight/brightness
echo "=== Backlight eDP-2 ===" && cat /sys/class/backlight/asus_screenpad/brightness
echo "=== Battery ===" && cat /sys/class/power_supply/BAT0/charge_control_end_threshold 2>/dev/null || echo "path not found"
```

---

## Update

```bash
cd zenbook-duo-control-pantallas-ubuntu
git pull
sudo ./install.sh
```

The installer is idempotent: if already installed, it updates the files and restarts the service.

> If you only want to change settings without updating the code, use `sudo ./configure.sh` instead of reinstalling.

---

## Uninstall

```bash
sudo systemctl stop zenbook-duo
sudo systemctl disable zenbook-duo
sudo rm /etc/systemd/system/zenbook-duo.service
sudo rm -rf /opt/zenbook-duo
sudo systemctl daemon-reload
```
