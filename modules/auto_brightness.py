import os
import re
import subprocess
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

    def start(self):
        """Inicia el hilo que sincroniza eDP-2 cuando el brillo cambia manualmente."""
        thread = threading.Thread(target=self._manual_sync_loop, daemon=True)
        thread.start()

    def apply_lux(self, lux):
        target = self._lux_to_pct(lux)
        with self._lock:
            if target == self._current_pct:
                return
            print(f"\n[BRILLO] {lux:.1f} lux → {target}%")
            self._apply_both(target)
            self._current_pct = target

    def _apply_both(self, pct):
        """Aplica el brillo a ambas pantallas en paralelo."""
        t1 = threading.Thread(target=self._set_gnome_brightness, args=(pct,))
        t2 = threading.Thread(target=self._set_screenpad_brightness, args=(pct,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

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

    def _manual_sync_loop(self):
        """
        Monitorea cambios de brillo en eDP-1 via D-Bus (teclas de brillo del teclado)
        y los replica en tiempo real a eDP-2.
        """
        uid = subprocess.check_output(
            f"id -u {self._username}", shell=True
        ).decode().strip()

        cmd = (
            f"sudo -u {self._username} "
            f"env XDG_RUNTIME_DIR=/run/user/{uid} "
            f"WAYLAND_DISPLAY=wayland-0 "
            f"gdbus monitor --session "
            f"--dest org.gnome.SettingsDaemon.Power "
            f"--object-path /org/gnome/SettingsDaemon/Power"
        )
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, text=True)
        for line in iter(process.stdout.readline, ''):
            match = re.search(r"'Brightness':\s*<(\d+)>", line)
            if match:
                pct = int(match.group(1))
                with self._lock:
                    if pct == self._current_pct:
                        continue
                    self._current_pct = pct
                print(f"[BRILLO] Tecla → {pct}% (sincronizando eDP-2)")
                self._set_screenpad_brightness(pct)
