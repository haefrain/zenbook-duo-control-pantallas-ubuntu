import os
import select
import threading
import time

INPUT_BY_ID = "/sys/class/input"
SCREENPAD_PATH = "/sys/class/backlight/asus_screenpad"


class OledCareManager:
    """
    Cuidado pasivo de la pantalla OLED inferior (eDP-2): si no hay actividad
    táctil durante un tiempo configurable, atenúa el screenpad a un nivel
    mínimo. Al primer toque, restaura el nivel previo.

    No reproduce un "pixel shift" porque en GNOME Wayland eso requiere
    reposicionar logical_monitors, lo cual produce parpadeos visibles cada
    vez. El idle dim es la medida con mejor relación coste/beneficio para
    preservar la pantalla cuando muestra contenido estático mucho tiempo.

    Config (config.yaml):

        oled_care:
          idle_dim_enabled: true
          idle_minutes: 5         # tras N min sin touch, atenuar
          dim_percent: 5          # nivel al que se baja
          bottom_vendor: "04f3"   # vendor del touchscreen inferior
          bottom_product: "425a"  # product
    """

    def __init__(self, config, brightness_manager):
        self.config = config
        self.brightness = brightness_manager

        oc = config.get('oled_care', {}) or {}
        self.enabled = oc.get('idle_dim_enabled', True)
        self.idle_seconds = int(oc.get('idle_minutes', 5)) * 60
        self.dim_pct = int(oc.get('dim_percent', 5))
        self.vendor = oc.get('bottom_vendor', '04f3').lower()
        self.product = oc.get('bottom_product', '425a').lower()

        self._dimmed = False
        self._saved_pct = None
        self._lock = threading.Lock()

    def start(self):
        if not self.enabled:
            print("[OLED] idle dim desactivado")
            return
        thread = threading.Thread(target=self._idle_loop, daemon=True)
        thread.start()
        print(f"[OLED] idle dim activo: {self.idle_seconds//60} min → {self.dim_pct}%")

    def _find_event_devices(self):
        """Devuelve la lista de paths /dev/input/eventN del touchscreen inferior."""
        devices = []
        try:
            entries = os.listdir(INPUT_BY_ID)
        except Exception:
            return devices

        for entry in entries:
            if not entry.startswith('event'):
                continue
            try:
                vendor_path = f"{INPUT_BY_ID}/{entry}/device/id/vendor"
                product_path = f"{INPUT_BY_ID}/{entry}/device/id/product"
                with open(vendor_path) as f:
                    vendor = f.read().strip().lower()
                with open(product_path) as f:
                    product = f.read().strip().lower()
                if vendor == self.vendor and product == self.product:
                    devices.append(f"/dev/input/{entry}")
            except Exception:
                continue
        return devices

    def _read_screenpad_max(self):
        try:
            with open(f"{SCREENPAD_PATH}/max_brightness") as f:
                return int(f.read().strip())
        except Exception:
            return 255

    def _write_screenpad_pct(self, pct):
        """Escribe directamente al sysfs del screenpad (bypass BrightnessManager)."""
        try:
            max_val = self._read_screenpad_max()
            val = max(1, int(max_val * pct / 100))
            with open(f"{SCREENPAD_PATH}/brightness", 'w') as f:
                f.write(str(val))
        except Exception as e:
            print(f"[OLED] No se pudo escribir screenpad: {e}")

    def _dim(self):
        with self._lock:
            if self._dimmed:
                return
            self._saved_pct = self.brightness.get_last_pct()
            self.brightness.acquire_screenpad()
            self._dimmed = True
        print(f"[OLED] inactividad → atenuando eDP-2 a {self.dim_pct}% (estaba {self._saved_pct}%)")
        self._write_screenpad_pct(self.dim_pct)

    def _restore(self):
        with self._lock:
            if not self._dimmed:
                return
            saved = self._saved_pct or 100
            self._dimmed = False
            self.brightness.release_screenpad()
        print(f"[OLED] actividad → restaurando eDP-2 a {saved}%")
        self._write_screenpad_pct(saved)

    def _idle_loop(self):
        """
        Mantiene un poll() sobre los event devices del touchscreen inferior.
        select() con timeout = idle_seconds: si retorna sin lecturas, atenuamos.
        Si retorna con lecturas, drenamos y reseteamos.
        """
        # Esperar a que los devices existan (al boot pueden tardar).
        devices = []
        for _ in range(20):
            devices = self._find_event_devices()
            if devices:
                break
            time.sleep(1)

        if not devices:
            print(f"[OLED] No encontré touchscreen {self.vendor}:{self.product}, "
                  f"idle dim deshabilitado")
            return

        print(f"[OLED] monitoreando {len(devices)} input device(s) del eDP-2")

        fds = []
        for path in devices:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                fds.append((fd, path))
            except Exception as e:
                print(f"[OLED] No se pudo abrir {path}: {e}")

        if not fds:
            return

        last_activity = time.monotonic()

        try:
            while True:
                # Si ya estamos atenuados, esperamos indefinidamente a que
                # llegue actividad. Si no, esperamos hasta que toque atenuar.
                if self._dimmed:
                    timeout = None
                else:
                    elapsed = time.monotonic() - last_activity
                    timeout = max(0.5, self.idle_seconds - elapsed)

                rlist, _, _ = select.select([fd for fd, _ in fds], [], [], timeout)

                if rlist:
                    # Drenar todos los eventos disponibles.
                    for fd in rlist:
                        try:
                            while True:
                                data = os.read(fd, 4096)
                                if not data:
                                    break
                        except BlockingIOError:
                            pass
                        except Exception:
                            pass
                    last_activity = time.monotonic()
                    if self._dimmed:
                        self._restore()
                else:
                    # Sin eventos en el timeout: hora de atenuar.
                    if not self._dimmed:
                        self._dim()
        finally:
            for fd, _ in fds:
                try:
                    os.close(fd)
                except Exception:
                    pass
