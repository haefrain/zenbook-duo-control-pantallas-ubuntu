import subprocess
import threading
import time
import os

# Debounce para coalescer eventos rápidos del accelerómetro. Cuando giras
# el equipo, el sensor pasa por orientaciones intermedias antes de
# estabilizarse. Sin esto se encolan applys de monitores en cascada.
ROTATION_DEBOUNCE_SECONDS = 0.4


class RotationManager:
    def __init__(self, config, session_runner, is_docked_callback, brightness_manager=None, rotation_enabled=True):
        self.config = config
        self.run_session = session_runner
        self.is_docked = is_docked_callback
        self.current_state = "normal"
        self.brightness = brightness_manager
        self._rotation_enabled = rotation_enabled
        # Lock para serializar applys (sensor + watchdog + refresh manual).
        self._apply_lock = threading.Lock()
        # Debounce del sensor.
        self._pending_orientation = None
        self._pending_timer = None
        self._pending_lock = threading.Lock()

    def start(self):
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()

    def refresh(self):
        """Fuerza la aplicación de la orientación actual (bypass config_changed)."""
        self._apply_orientation(self.current_state, force=True, force_apply=True)

    def _schedule_orientation(self, orientation):
        """Coalescea múltiples eventos del sensor en un único apply."""
        with self._pending_lock:
            self._pending_orientation = orientation
            if self._pending_timer is not None:
                self._pending_timer.cancel()
            self._pending_timer = threading.Timer(
                ROTATION_DEBOUNCE_SECONDS, self._flush_orientation
            )
            self._pending_timer.daemon = True
            self._pending_timer.start()

    def _flush_orientation(self):
        with self._pending_lock:
            orientation = self._pending_orientation
            self._pending_orientation = None
            self._pending_timer = None
        if orientation is not None:
            self._apply_orientation(orientation)

    def _monitor_loop(self):
        while True:
            process = subprocess.Popen(
                ['monitor-sensor'], stdout=subprocess.PIPE, text=True,
            )
            for line in iter(process.stdout.readline, ''):
                if self._rotation_enabled and "Accelerometer orientation changed:" in line:
                    orientation = line.split(":")[-1].strip()
                    self._schedule_orientation(orientation)
                elif self.brightness and "Light changed:" in line:
                    try:
                        lux = float(line.split("Light changed:")[-1].split()[0])
                        self.brightness.apply_lux(lux)
                    except (ValueError, IndexError):
                        pass
            # monitor-sensor murió: reintentar tras pausa.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
            print("[ROTACIÓN] monitor-sensor terminó, reintentando en 3s...")
            time.sleep(3)

    def _apply_orientation(self, orientation, force=False, force_apply=False):
        if orientation == self.current_state and not force:
            return

        # Serializa applys: evita que sensor + watchdog + dock se pisen.
        with self._apply_lock:
            top_dp = self.config['displays']['top']
            bot_dp = self.config['displays']['bottom']
            scale = self.config['displays'].get('scale', 2)
            user = self.config['system']['username']
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "gnome_randr.py")

            docked = self.is_docked()
            cmd = f"python3 {script}"
            if force_apply:
                cmd += " --force"

            # MODO PORTÁTIL (Vertical)
            if orientation in ["normal", "bottom-up"]:
                print(f"\n[ROTACIÓN] 💻 Aplicando Modo Portátil (Docked: {docked})")
                cmd += f" --output {top_dp} --rotate normal --auto --scale {scale}"
                if not docked:
                    cmd += f" --output {bot_dp} --rotate normal --auto --scale {scale} --below {top_dp}"

            # MODO LIBRO (Horizontal)
            elif orientation in ["right-up", "left-up"]:
                print(f"\n[ROTACIÓN] 📖 Aplicando Modo Libro ({orientation}).")
                # Invertimos rotaciones para que no queden de cabeza
                rot_dir = "right" if orientation == "right-up" else "left"

                cmd += f" --output {top_dp} --rotate {rot_dir} --auto --scale {scale}"
                if not docked:
                    cmd += f" --output {bot_dp} --rotate {rot_dir} --auto --scale {scale} --right-of {top_dp}"

            try:
                self.run_session(cmd, user)
                self.current_state = orientation
            except Exception as e:
                print(f"[ERROR] Fallo al aplicar configuración: {e}")