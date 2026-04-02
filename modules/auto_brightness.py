import os
import threading

BACKLIGHT_BOT_DRM = "/sys/class/backlight/card1-eDP-2-backlight"
BACKLIGHT_BOT_SCREENPAD = "/sys/class/backlight/asus_screenpad"

# Rangos: (lux_min, lux_max, brillo_%)
# Rangos amplios para evitar cambios bruscos en los límites
BRIGHTNESS_RANGES = [
    (0,    5,    5),    # oscuridad total (cine, dormir)
    (5,    25,   15),   # luz muy tenue (vela, pantalla de tv en cuarto oscuro)
    (25,   45,   30),   # interior tenue (tarde-noche en casa)
    (45,   250,  50),   # interior normal (oficina, habitación con luz)
    (250,  600,  70),   # interior bien iluminado (escritorio cerca de ventana)
    (600,  2000, 85),   # luz exterior indirecta / nublado
    (2000, float('inf'), 100),  # luz solar directa
]


class BrightnessManager:
    def __init__(self, session_runner, username):
        self._run_session = session_runner
        self._username = username
        self._current_pct = None
        self._lock = threading.Lock()

    def apply_lux(self, lux):
        target = self._lux_to_pct(lux)
        with self._lock:
            if target == self._current_pct:
                return
            print(f"\n[BRILLO] {lux:.1f} lux → {target}%")
            self._set_gnome_brightness(target)
            self._set_screenpad_brightness(target)
            self._current_pct = target

    def _lux_to_pct(self, lux):
        for (lo, hi, pct) in BRIGHTNESS_RANGES:
            if lux < hi:
                return pct
        return 100

    def _set_gnome_brightness(self, pct):
        """Controla eDP-1 (intel_backlight) a través del dbus de GNOME."""
        cmd = (
            f"gdbus call --session "
            f"--dest org.gnome.SettingsDaemon.Power "
            f"--object-path /org/gnome/SettingsDaemon/Power "
            f"--method org.freedesktop.DBus.Properties.Set "
            f"'org.gnome.SettingsDaemon.Power.Screen' "
            f"'Brightness' "
            f"'<int32 {pct}>'"
        )
        try:
            self._run_session(cmd, self._username)
        except Exception as e:
            print(f"[ERROR] No se pudo aplicar brillo GNOME: {e}")

    def _screenpad_is_on(self):
        try:
            return int(open(f"{BACKLIGHT_BOT_SCREENPAD}/bl_power").read().strip()) == 0
        except Exception:
            return True  # si no se puede leer, asumimos encendida

    def _set_screenpad_brightness(self, pct):
        """Controla eDP-2 via sysfs (requiere root). Escribe a ambas interfaces."""
        if not self._screenpad_is_on():
            return
        for path in [BACKLIGHT_BOT_DRM, BACKLIGHT_BOT_SCREENPAD]:
            try:
                max_val = int(open(os.path.join(path, "max_brightness")).read().strip())
                val = max(1, int(max_val * pct / 100))
                with open(os.path.join(path, "brightness"), 'w') as f:
                    f.write(str(val))
            except Exception as e:
                print(f"[ERROR] No se pudo escribir brillo en {path}: {e}")
