import subprocess
import threading
import time


class BluetoothManager:
    def __init__(self, mac_address=None, mac_addresses=None):
        # Acepta lista de MACs o una sola (compatibilidad hacia atrás)
        if mac_addresses:
            self.mac_addresses = list(mac_addresses)
        elif mac_address:
            self.mac_addresses = [mac_address]
        else:
            self.mac_addresses = []

        # Propiedad de compatibilidad (usada por DockMonitor)
        self.mac_address = self.mac_addresses[0] if self.mac_addresses else None

    def _connect_device(self, mac):
        """Conecta un dispositivo llamando a BlueZ vía D-Bus directamente (más rápido que bluetoothctl)."""
        mac_path = mac.replace(':', '_')
        try:
            subprocess.Popen(
                ['busctl', '--system', 'call',
                 'org.bluez',
                 f'/org/bluez/hci0/dev_{mac_path}',
                 'org.bluez.Device1',
                 'Connect'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[ERROR BLUETOOTH] No se pudo conectar {mac}: {e}")

    def force_connect(self):
        """Reconecta todos los dispositivos Bluetooth configurados."""
        if not self.mac_addresses:
            return

        n = len(self.mac_addresses)
        print(f"\n[BLUETOOTH] Forzando reconexión de {n} dispositivo(s)...")
        try:
            subprocess.run(["rfkill", "unblock", "bluetooth"], check=False)
            for mac in self.mac_addresses:
                print(f"[BLUETOOTH] Conectando {mac}...")
                self._connect_device(mac)
        except Exception as e:
            print(f"[ERROR BLUETOOTH] {e}")

    def start_unlock_watcher(self, callback):
        """Monitorea el desbloqueo de pantalla (logind system bus) y ejecuta callback."""
        thread = threading.Thread(target=self._watch_unlock, args=(callback,), daemon=True)
        thread.start()

    def _watch_unlock(self, callback):
        while True:
            process = subprocess.Popen(
                ['dbus-monitor', '--system',
                 "type='signal',interface='org.freedesktop.login1.Session',member='Unlock'"],
                stdout=subprocess.PIPE,
                text=True,
            )
            for line in iter(process.stdout.readline, ''):
                if 'member=Unlock' in line:
                    print("[BLUETOOTH] Pantalla desbloqueada — reconectando dispositivos BT...")
                    callback()
            # dbus-monitor murió: reintentar tras pausa.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
            print("[BLUETOOTH] dbus-monitor terminó, reintentando en 3s...")
            time.sleep(3)
