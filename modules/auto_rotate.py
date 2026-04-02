import subprocess
import threading
import os

class RotationManager:
    def __init__(self, config, session_runner, is_docked_callback, brightness_manager=None, rotation_enabled=True):
        self.config = config
        self.run_session = session_runner
        self.is_docked = is_docked_callback
        self.current_state = "normal"
        self.brightness = brightness_manager
        self._rotation_enabled = rotation_enabled

    def start(self):
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()

    def refresh(self):
        """Fuerza la aplicación de la orientación actual."""
        self._apply_orientation(self.current_state, force=True)

    def _monitor_loop(self):
        process = subprocess.Popen(['monitor-sensor'], stdout=subprocess.PIPE, text=True)
        for line in iter(process.stdout.readline, ''):
            if self._rotation_enabled and "Accelerometer orientation changed:" in line:
                orientation = line.split(":")[-1].strip()
                self._apply_orientation(orientation)
            elif self.brightness and "Light changed:" in line:
                try:
                    lux = float(line.split("Light changed:")[-1].split()[0])
                    self.brightness.apply_lux(lux)
                except (ValueError, IndexError):
                    pass

    def _apply_orientation(self, orientation, force=False):
        if orientation == self.current_state and not force:
            return
        
        top_dp = self.config['displays']['top']
        bot_dp = self.config['displays']['bottom']
        scale = self.config['displays'].get('scale', 2)
        user = self.config['system']['username']
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "gnome_randr.py")
        
        docked = self.is_docked()
        cmd = f"python3 {script}"

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