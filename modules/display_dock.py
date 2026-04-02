import pyudev
import threading
import time


# Tiempo mínimo entre dos acciones de dock/undock consecutivas (segundos)
DEBOUNCE_SECONDS = 0.6


class DockMonitor:
    def __init__(self, vendor_id, product_id, on_dock_callback, on_undock_callback):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.on_dock = on_dock_callback
        self.on_undock = on_undock_callback

        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='usb')

        self.observer = pyudev.MonitorObserver(self.monitor, self._device_event)

        self._paths_lock = threading.Lock()
        self.active_device_paths = set()

        # Debounce: timestamp de la última acción disparada
        self._last_action_time = 0.0
        self._last_action = None  # "dock" | "undock"

        # 1. Al arrancar, verificamos si el teclado ya está puesto
        self._sincronizar_estado_inicial()

    def _sincronizar_estado_inicial(self):
        """Escanea los dispositivos USB actuales para setear el estado inicial."""
        teclado_encontrado = False

        for device in self.context.list_devices(subsystem='usb'):
            vid = device.get('ID_VENDOR_ID')
            pid = device.get('ID_MODEL_ID')

            if vid == self.vendor_id and pid == self.product_id:
                with self._paths_lock:
                    self.active_device_paths.add(device.device_path)
                print(f"[INIT] Teclado detectado en el arranque en: {device.device_path}")
                teclado_encontrado = True
                self._dispatch("dock")
                break

        if not teclado_encontrado:
            print("[INIT] Teclado NO detectado en el arranque. Asegurando que la pantalla 2 esté encendida...")
            self._dispatch("undock")

    def start(self):
        self.observer.start()

    def stop(self):
        self.observer.stop()

    def _device_event(self, action, device):
        dev_path = device.device_path

        if action == 'add':
            vid = device.get('ID_VENDOR_ID')
            pid = device.get('ID_MODEL_ID')

            if vid == self.vendor_id and pid == self.product_id:
                with self._paths_lock:
                    already_known = dev_path in self.active_device_paths
                    self.active_device_paths.add(dev_path)
                if not already_known:
                    self._dispatch("dock")

        elif action == 'remove':
            with self._paths_lock:
                was_known = dev_path in self.active_device_paths
                self.active_device_paths.discard(dev_path)
                remaining = len(self.active_device_paths)
            if was_known and remaining == 0:
                self._dispatch("undock")

    def _dispatch(self, action):
        """Aplica debounce y lanza el callback en un hilo separado."""
        now = time.monotonic()
        if action == self._last_action and (now - self._last_action_time) < DEBOUNCE_SECONDS:
            print(f"[DOCK] Evento '{action}' ignorado por debounce")
            return

        self._last_action_time = now
        self._last_action = action

        callback = self.on_dock if action == "dock" else self.on_undock
        threading.Thread(target=callback, daemon=True).start()

    def is_docked(self):
        """Devuelve True si el teclado físico está acoplado."""
        with self._paths_lock:
            return len(self.active_device_paths) > 0