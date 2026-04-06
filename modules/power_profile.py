import os
import re
import subprocess
import threading
import time

PLATFORM_PROFILE_PATH = "/sys/firmware/acpi/platform_profile"
PLATFORM_PROFILE_CHOICES_PATH = "/sys/firmware/acpi/platform_profile_choices"


class PowerProfileManager:
    """
    Aplica un platform_profile y un refresh rate distintos según si el equipo
    está conectado a la corriente o en batería.

    Escucha eventos de UPower vía D-Bus (system bus) para detectar cambios de
    AC en tiempo real. También consulta el estado al arrancar.

    Config esperada (en config.yaml):

        power_profiles:
          on_ac:
            profile: performance     # quiet | balanced | performance
            refresh_rate: 120        # Hz, o null para no cambiar
          on_battery:
            profile: balanced
            refresh_rate: 60
    """

    def __init__(self, config, session_runner):
        self.config = config
        self.run_session = session_runner
        self.user = config['system']['username']

        pp_cfg = config.get('power_profiles', {}) or {}
        self.ac_cfg = pp_cfg.get('on_ac', {}) or {}
        self.bat_cfg = pp_cfg.get('on_battery', {}) or {}

        self.choices = self._read_choices()
        self._current_state = None  # 'ac' | 'battery'
        self._lock = threading.Lock()

    def _read_choices(self):
        try:
            with open(PLATFORM_PROFILE_CHOICES_PATH) as f:
                return f.read().strip().split()
        except Exception:
            return []

    def start(self):
        # Aplicar el estado inicial inmediatamente.
        self._apply_for_state(self._read_ac_state())
        # Lanzar watcher de cambios.
        thread = threading.Thread(target=self._watch_loop, daemon=True)
        thread.start()

    def _read_ac_state(self):
        """Devuelve 'ac' o 'battery' leyendo /sys/class/power_supply/AC*/online."""
        for entry in os.listdir('/sys/class/power_supply'):
            path = f"/sys/class/power_supply/{entry}/online"
            if not os.path.exists(path):
                continue
            try:
                with open(path) as f:
                    if f.read().strip() == '1':
                        return 'ac'
            except Exception:
                pass
        return 'battery'

    def _apply_for_state(self, state):
        with self._lock:
            if state == self._current_state:
                return
            self._current_state = state

        cfg = self.ac_cfg if state == 'ac' else self.bat_cfg
        label = 'AC' if state == 'ac' else 'BATERÍA'
        print(f"\n[POWER] → {label}")

        profile = cfg.get('profile')
        if profile:
            self._set_profile(profile)

        rate = cfg.get('refresh_rate')
        if rate:
            self._set_refresh_rate(rate)

    def _set_profile(self, profile):
        if self.choices and profile not in self.choices:
            print(f"[POWER] Perfil '{profile}' no disponible. Opciones: {self.choices}")
            return
        try:
            with open(PLATFORM_PROFILE_PATH, 'w') as f:
                f.write(profile)
            print(f"[POWER] platform_profile → {profile}")
        except PermissionError:
            print(f"[ERROR POWER] Sin permisos para {PLATFORM_PROFILE_PATH}")
        except Exception as e:
            print(f"[ERROR POWER] No se pudo aplicar perfil: {e}")

    def _set_refresh_rate(self, rate):
        """
        Cambia la tasa de refresco del display superior. No tocamos el inferior:
        si está activo, el RotationManager o el dock controller lo reaplicarán
        a la siguiente rotación; si está apagado, no queremos re-encenderlo.
        """
        top = self.config['displays']['top']
        scale = self.config['displays'].get('scale', 2)
        script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "core", "gnome_randr.py"
        )
        cmd = (
            f"python3 {script} "
            f"--output {top} --auto --scale {scale} --rate {rate}"
        )
        try:
            self.run_session(cmd, self.user)
            print(f"[POWER] refresh rate → {rate} Hz")
        except Exception as e:
            print(f"[POWER] No se pudo cambiar refresh rate: {e}")

    def _watch_loop(self):
        """
        Suscribe a PropertiesChanged de UPower (system bus) para detectar
        cambios de AC. Reinicia el monitor si muere.
        """
        cmd = [
            'dbus-monitor', '--system',
            "type='signal',interface='org.freedesktop.DBus.Properties',"
            "path='/org/freedesktop/UPower'",
        ]
        while True:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
            for line in iter(process.stdout.readline, ''):
                # UPower emite PropertiesChanged con OnBattery cuando cambia
                # el estado. Re-leemos el estado real para evitar parsear
                # tipos D-Bus complejos.
                if 'OnBattery' in line or 'LidIsClosed' in line:
                    state = self._read_ac_state()
                    self._apply_for_state(state)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
            print("[POWER] dbus-monitor terminó, reintentando en 3s...")
            time.sleep(3)
