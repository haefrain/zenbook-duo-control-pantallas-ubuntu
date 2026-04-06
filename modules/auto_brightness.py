import os
import re
import subprocess
import threading
import time

# Sólo escribimos en el backlight propio de ASUS (asus_screenpad).
# No escribimos en card1-eDP-2-backlight (DRM) porque GNOME lo monitorea
# como un backlight más y eso crea un loop de retroalimentación: cada
# escritura dispara PropertiesChanged en gnome-settings-daemon, que el
# _manual_sync_loop interpreta como "tecla" y vuelve a escribir.
BACKLIGHT_BOT_SCREENPAD = "/sys/class/backlight/asus_screenpad"

# Tiempo en segundos durante el cual ignoramos eventos de brillo del bus
# después de aplicar nosotros mismos un cambio (silencia ecos del propio
# escribir y la animación intermedia que GNOME emite paso a paso).
SELF_WRITE_MUTE_SECONDS = 0.40

# Tiempo en segundos para coalescer múltiples eventos de brillo en uno.
# GNOME anima el brillo en pasos de 1% — sin debounce escribimos N veces
# al screenpad por cada cambio del usuario.
DEBOUNCE_SECONDS = 0.15

# Cuántos segundos pausar el brillo automático tras un cambio manual.
# Sin esto, el sensor de luz revertiría el cambio del usuario en pocos
# segundos. 60s da margen razonable y luego el sensor recupera control.
MANUAL_OVERRIDE_SECONDS = 60.0

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
        # Timestamp del último write propio (para silenciar ecos).
        self._last_self_write = 0.0
        # Pendiente para debouncing del watcher.
        self._pending_pct = None
        self._pending_timer = None
        # Counter de controladores externos del screenpad. Mientras > 0,
        # no escribimos al asus_screenpad: otro módulo (e.g. OledCareManager
        # haciendo idle dim) tiene control temporal.
        self._screenpad_external_holders = 0
        # Hasta cuándo está en pausa el control automático del brillo
        # (por una intervención manual del usuario via teclas Fn).
        self._manual_override_until = 0.0

    def acquire_screenpad(self):
        """Reserva el control del screenpad. BrightnessManager dejará de tocarlo."""
        with self._lock:
            self._screenpad_external_holders += 1

    def release_screenpad(self):
        """Devuelve el control del screenpad."""
        with self._lock:
            if self._screenpad_external_holders > 0:
                self._screenpad_external_holders -= 1

    def get_last_pct(self):
        """Último porcentaje conocido (para que un controlador externo pueda restaurar)."""
        with self._lock:
            return self._current_pct or 100

    def start(self):
        """Inicia el hilo que sincroniza eDP-2 cuando el brillo cambia manualmente."""
        thread = threading.Thread(target=self._manual_sync_loop, daemon=True)
        thread.start()

    def apply_lux(self, lux):
        target = self._lux_to_pct(lux)
        with self._lock:
            # Mientras esté activo el override manual, el sensor no
            # toca el brillo (el usuario lo acaba de ajustar a mano).
            if time.monotonic() < self._manual_override_until:
                return
            if target == self._current_pct:
                return
            self._current_pct = target
            self._last_self_write = time.monotonic()
        print(f"\n[BRILLO] {lux:.1f} lux → {target}%", flush=True)
        self._apply_both(target)

    def step_brightness(self, delta_pct):
        """
        Sube o baja el brillo en pasos absolutos (delta_pct puede ser
        +10, -10, etc). Aplica el cambio inmediatamente y activa el
        override manual para que el sensor no lo revierta enseguida.

        Devuelve el nuevo porcentaje aplicado, o None si no se pudo.
        """
        with self._lock:
            base = self._current_pct if self._current_pct is not None else 50
            new_pct = max(1, min(100, base + delta_pct))
            if new_pct == self._current_pct:
                return new_pct
            self._current_pct = new_pct
            self._last_self_write = time.monotonic()
            self._manual_override_until = (
                time.monotonic() + MANUAL_OVERRIDE_SECONDS
            )
        self._apply_both(new_pct)
        return new_pct

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
        """Controla eDP-2 via sysfs (requiere root). Sólo escribe en asus_screenpad."""
        # Si otro controlador (e.g. OLED idle dim) tiene reservado el screenpad,
        # respetamos su control y no escribimos.
        with self._lock:
            if self._screenpad_external_holders > 0:
                return
        if not self._screenpad_is_on():
            return
        path = BACKLIGHT_BOT_SCREENPAD
        try:
            max_val = int(open(os.path.join(path, "max_brightness")).read().strip())
            val = max(1, int(max_val * pct / 100))
            with open(os.path.join(path, "brightness"), 'w') as f:
                f.write(str(val))
        except Exception as e:
            print(f"[ERROR] No se pudo escribir brillo en {path}: {e}")

    def _flush_pending(self):
        """Aplica el último valor pendiente del watcher tras el debounce."""
        with self._lock:
            pct = self._pending_pct
            self._pending_pct = None
            self._pending_timer = None
            if pct is None or pct == self._current_pct:
                return
            self._current_pct = pct
            self._last_self_write = time.monotonic()
        print(f"[BRILLO] Sync → {pct}% (eDP-2)")
        self._set_screenpad_brightness(pct)

    def _manual_sync_loop(self):
        """
        Monitorea cambios de brillo en eDP-1 vía D-Bus (teclas de brillo o
        brillo automático de GNOME) y los replica al screenpad. Se aplica
        debouncing para coalescer la animación de GNOME y se silencian los
        ecos del propio script (writes que hacemos por apply_lux).
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
        while True:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, text=True,
            )
            for line in iter(process.stdout.readline, ''):
                match = re.search(r"'Brightness':\s*<(\d+)>", line)
                if not match:
                    continue
                pct = int(match.group(1))
                now = time.monotonic()
                with self._lock:
                    # Eco de un write propio: ignorar.
                    if now - self._last_self_write < SELF_WRITE_MUTE_SECONDS:
                        continue
                    if pct == self._current_pct:
                        continue
                    # Coalescer: guardar el último valor y reprogramar timer.
                    self._pending_pct = pct
                    if self._pending_timer is not None:
                        self._pending_timer.cancel()
                    self._pending_timer = threading.Timer(
                        DEBOUNCE_SECONDS, self._flush_pending
                    )
                    self._pending_timer.daemon = True
                    self._pending_timer.start()
            # Si llegamos aquí, gdbus monitor murió. Reintentar tras pausa.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
            print("[BRILLO] gdbus monitor terminó, reintentando en 3s...")
            time.sleep(3)
