# Zenbook Duo Control — Ubuntu

Hardware control for the ASUS Zenbook Duo with dual OLED screens on Ubuntu 24. ASUS provides no official Linux support for these features, so this project implements them directly.

## Features

| Feature | Description |
|---|---|
| **Auto-rotation** | Rotates both screens when the device is turned (laptop mode ↔ book mode), with debouncing to coalesce rapid accelerometer events |
| **Auto-brightness** | Adjusts brightness on both screens in parallel using the built-in ambient light sensor; syncs eDP-2 when brightness keys are used, with debouncing and self-write echo muting to prevent feedback loops |
| **Battery protection** | Caps the maximum charge level to extend battery lifespan |
| **Secondary screen control** | Turns off the lower screen when the keyboard is attached and turns it back on when detached; reconnects the Bluetooth keyboard and other devices on screen unlock |
| **Touchscreen mapping** | Assigns each touchscreen to its correct display in GNOME Wayland (resolves the identical-EDID problem between both panels using the 4th element of the dconf array, which Mutter ≥ 42 accepts as connector name tie-breaker) |
| **Automatic power profile** | Applies different `platform_profile` and refresh rate based on AC/battery state (e.g. `performance @ 120 Hz` plugged in, `balanced @ 60 Hz` on battery) by listening to UPower events |
| **OLED care** | Dims the lower screenpad after a configurable period of touch inactivity, to preserve the OLED panel against static content |
| **Dock keyboard backlight** | Reapplies the keyboard backlight level when the USB keyboard is attached, via a proprietary ASUS HID feature report |

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
  touchscreen_mapping: true         # Map each touchscreen to its correct display
  power_profile: true               # Switch profile + refresh rate per AC/battery
  oled_care: true                   # Dim the lower screen after touch inactivity
  keyboard_backlight: true          # Reapply the keyboard backlight on dock

keyboard:
  vendor_id: "0b05"                 # See: lsusb | grep -i asus
  product_id: "1b2c"                # USB product ID of the keyboard when docked
  mac_address: "XX:XX:XX:XX:XX:XX"  # See: bluetoothctl devices
  backlight_level: 1                # 0 = off, 1..3 = brightness levels
  backlight_vendor: "0b05"
  backlight_product: "1b2c"         # The backlight only applies when docked

displays:
  top: "eDP-1"                      # Name of the top screen
  bottom: "eDP-2"                   # Name of the bottom screen
  scale: 2                          # HiDPI scale factor (2 on 2.8K OLED)

battery:
  charge_limit: 80                  # Maximum charge percentage

bluetooth:
  devices:                          # Extra MACs to reconnect on screen unlock
    - "YY:YY:YY:YY:YY:YY"
  reconnect_on_unlock: true

watchdog:
  display_refresh_minutes: 0        # 0 = disabled (recommended). >0 forces an
                                    # ApplyMonitorsConfig --force every N minutes.
                                    # Does not prevent compositor freezes.

touchscreen:
  top_device: "04f3:425b"           # HID vendor:product of the top touchscreen (ELAN9008)
  bottom_device: "04f3:425a"        # HID vendor:product of the bottom touchscreen (ELAN9009)
  swap: false                       # Set to true if the touchscreens are mapped in reverse

power_profiles:
  on_ac:
    profile: performance            # quiet | balanced | performance
    refresh_rate: 120               # Hz; null to leave it unchanged
  on_battery:
    profile: balanced
    refresh_rate: 60

oled_care:
  idle_dim_enabled: true            # Dim eDP-2 after touch inactivity
  idle_minutes: 5                   # Minutes without touch to consider it idle
  dim_percent: 5                    # Brightness level when dimmed
  bottom_vendor: "04f3"             # Must match touchscreen.bottom_device
  bottom_product: "425a"
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

The lower screen is controlled **only** through `/sys/class/backlight/asus_screenpad/` (root required). Previously the daemon also wrote to `card1-eDP-2-backlight`, but that caused a feedback loop with `gnome-settings-daemon` (which monitors that DRM backlight) — it has been removed.

```bash
# Does the interface exist?
ls /sys/class/backlight/asus_screenpad/

# Manual test as root:
echo 120 | sudo tee /sys/class/backlight/asus_screenpad/brightness
```

---

### Brightness keys do not change eDP-2

The daemon monitors the GNOME D-Bus for brightness changes and replicates them to the screenpad with debouncing (it coalesces GNOME's interpolated 1%-step animation). If it is not working, check that the service is running and that `gnome-settings-daemon` is active:

```bash
pgrep -a gsd-power
journalctl -u zenbook-duo -f   # look for lines "[BRILLO] Sync →"
```

---

### Brightness goes down on its own even when `auto_brightness` is `false`

GNOME most likely has its own automatic brightness via the ambient light sensor enabled, independent of this project. The daemon warns you about this on startup if it detects it. To disable it:

```bash
gsettings set org.gnome.settings-daemon.plugins.power ambient-enabled false
```

If you prefer to leave it on in GNOME, note that `BrightnessManager` will replicate those changes to the screenpad (this is the expected behaviour).

---

### Touchscreens do not respond on the correct screen

**1. Check that the mapping was applied:**
```bash
dconf dump /org/gnome/desktop/peripherals/touchscreens/
# Should show 4-element arrays (vendor, product, serial, connector):
# [04f3:425b]
# output=['SDC', '0x419d', '0x00000000', 'eDP-1']
#
# [04f3:425a]
# output=['SDC', '0x419d', '0x00000000', 'eDP-2']
```

> **Technical note:** both Zenbook Duo panels report identical EDID
> (same `vendor`, `product` and `serial`), so Mutter's standard matching
> cannot tell them apart. Mutter ≥ 42 accepts a fourth element in the
> `output` array which is the connector name (`eDP-1`/`eDP-2`) and uses
> it specifically as a tie-breaker when duplicate monitors are detected.
> The daemon writes all 4 elements at startup; **Mutter only reads the
> setting when the device is added, so the first apply requires a re-login**.

**2. If the mapping is reversed** (eDP-2 touch acts on eDP-1 and vice versa), enable `swap` in the config:
```bash
sudo nano /opt/zenbook-duo/config.yaml
# Change:  swap: false  →  swap: true
sudo systemctl restart zenbook-duo
```

**3. If the device IDs differ on your device:**
```bash
cat /proc/bus/input/devices | grep -A3 "ELAN"
# Note the Vendor/Product of each touchscreen and update top_device and bottom_device
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

### The automatic power profile does not switch when unplugging the charger

```bash
# Check the active profile:
cat /sys/firmware/acpi/platform_profile

# Verify the feature is enabled and that UPower emits events:
grep power_profile /opt/zenbook-duo/config.yaml
journalctl -u zenbook-duo -f | grep POWER
```

If UPower is not responding, make sure `upower.service` is running:
```bash
systemctl status upower
```

---

### The keyboard backlight does not light up on dock

**1. Check that the USB keyboard appears after docking:**
```bash
lsusb | grep 0b05
```

If nothing shows up, the keyboard is not enumerating as USB; the backlight is only controllable when physically attached (in Bluetooth mode the keyboard sits underneath the lower screen, so it does not apply).

**2. Verify the hidraw device exists:**
```bash
for h in /sys/class/hidraw/hidraw*; do
  cat "$h/device/uevent" 2>/dev/null | grep -i 1B2C && echo "  → $(basename $h)"
done
```

**3. Change the level manually** by editing `keyboard.backlight_level` (0–3) in `config.yaml` and restarting the service:
```bash
sudo nano /opt/zenbook-duo/config.yaml
sudo systemctl restart zenbook-duo
```

---

### OLED idle dim does not activate

```bash
# Check that the daemon sees the bottom touchscreen devices:
journalctl -u zenbook-duo | grep OLED
# Should show: "[OLED] monitoreando N input device(s) del eDP-2"
```

If it says `No encontré touchscreen…`, check that `oled_care.bottom_vendor` and `oled_care.bottom_product` match the real IDs:
```bash
for d in /sys/class/input/event*/device; do
  v=$(cat $d/id/vendor 2>/dev/null)
  p=$(cat $d/id/product 2>/dev/null)
  n=$(cat $d/name 2>/dev/null)
  [[ "$n" == *ELAN* ]] && echo "$v:$p $n"
done
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
echo "=== Power profile ===" && cat /sys/firmware/acpi/platform_profile
echo "=== AC online ===" && cat /sys/class/power_supply/AC0/online
echo "=== Touchscreens dconf ===" && dconf dump /org/gnome/desktop/peripherals/touchscreens/
```

---

## Optional system tweaks (performance)

These tweaks are not part of the daemon, they are operating system settings. They are safe for the hardware (no physical damage possible — Tjmax/PL/VRM protections always remain active) and reversible by editing a text file.

### PCIe ASPM in `performance` mode

By default the firmware leaves PCIe ASPM in conservative states that add latency to the bus (affects NVMe among others). Forcing it to `performance` keeps it always active. Cost: ~1-2 W more in idle.

```bash
# 1. Backup
sudo cp /etc/default/grub /etc/default/grub.bak.$(date +%Y%m%d-%H%M%S)

# 2. Add the parameter to the cmdline
sudo nano /etc/default/grub
# Change:  GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
# To:      GRUB_CMDLINE_LINUX_DEFAULT="quiet splash pcie_aspm=performance"

# 3. Regenerate grub.cfg and reboot
sudo update-grub
sudo reboot

# 4. After reboot, verify:
cat /sys/module/pcie_aspm/parameters/policy
# Should show: default performance [performance] powersave powersupersave
```

To revert: edit `/etc/default/grub`, remove the parameter, `sudo update-grub`, reboot.

### Temperature monitoring (`lm-sensors`)

Read-only, modifies nothing. Useful for verifying whether there is real thermal throttling under load.

```bash
sudo apt install -y lm-sensors
sudo sensors-detect --auto
sensors
```

Sensors you'll see on this device:
- `coretemp-isa-0000`: per-core temperatures (Tjmax = 110 °C)
- `nvme-pci-e100`: NVMe SSD temperatures
- `asus-isa-0000` / `acpi_fan-isa-0000`: fan RPM
- `BAT0-acpi-0`: battery voltage and instant power consumption
- `ucsi_source_psy_USBC*`: negotiated current of the USB-C charger
- `acpitz-acpi-0`: **ignore this one**, on Zenbook Duo the ACPI firmware exposes it as a constant value (≈100 °C) that is not a real sensor

---

## Sustained-load performance — the charger is the key

The Zenbook Duo's Core Ultra 9 185H can pull up to ~115 W of boost (PL2) and a sustained PL1 above 60 W under real load. **If your USB-C charger does not deliver at least 90-100 W, the device will discharge the battery to cover the gap and, when the battery drops, the firmware will aggressively reduce CPU TDP** — you lose sustained turbo because of the charger, not because of the OS.

To check the actual wattage your charger negotiates:

```bash
# Look at the current of the active USB-C port
sensors | grep -A1 ucsi_source_psy
# curr1: 3.25 A → at USB-C PD 20 V that is 65 W
# curr1: 5.00 A → 100 W (the desirable target)
```

To confirm whether the charger is your bottleneck, run a sustained load and check whether the battery switches to `Discharging` while AC is plugged:

```bash
sudo apt install -y stress-ng
stress-ng --cpu 0 --timeout 120s &
watch -n1 'echo "===" && cat /sys/class/power_supply/BAT0/status && grep MHz /proc/cpuinfo | head -3 && sensors | grep Package'
```

If `BAT0/status` switches to `Discharging` while `AC0/online` is 1, the charger is insufficient and a 100 W (or higher) PD charger will improve sustained performance by **20-40 %**, well above any software tweak.

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
