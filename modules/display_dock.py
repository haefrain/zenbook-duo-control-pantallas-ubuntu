import pyudev

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
        self.active_device_paths = set()

        # 1. Al arrancar, verificamos si el teclado ya está puesto
        self._sincronizar_estado_inicial()

    def _sincronizar_estado_inicial(self):
        """Escanea los dispositivos USB actuales para setear el estado inicial."""
        teclado_encontrado = False
        
        for device in self.context.list_devices(subsystem='usb'):
            vid = device.get('ID_VENDOR_ID')
            pid = device.get('ID_MODEL_ID')
            
            if vid == self.vendor_id and pid == self.product_id:
                self.active_device_paths.add(device.device_path)
                print(f"[INIT] Teclado detectado en el arranque en: {device.device_path}")
                teclado_encontrado = True
                self.on_dock()
                # Como ya lo encontramos, podemos salir del bucle
                break 

        # Si terminó de escanear y no encontró el teclado, forzamos el encendido
        if not teclado_encontrado:
            print("[INIT] Teclado NO detectado en el arranque. Asegurando que la pantalla 2 esté encendida...")
            self.on_undock()

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
                self.active_device_paths.add(dev_path)
                self.on_dock()
                
        elif action == 'remove':
            if dev_path in self.active_device_paths:
                self.active_device_paths.remove(dev_path)
                self.on_undock()
                
    def is_docked(self):
        """Devuelve True si el teclado físico está acoplado."""
        return len(self.active_device_paths) > 0