import fcntl
import os
import time

# El feature report viene del análisis del proyecto
# alesya-h/zenbook-duo-2024-ux8406ma-linux. El teclado del Zenbook Duo
# (UX8406, vendor 0B05) acepta un report de 16 bytes:
#
#   byte 0: report ID 0x5A
#   byte 1..3: BA C5 C4 (cabecera fija ASUS)
#   byte 4: nivel 0..3 (apagado .. máximo)
#   byte 5..15: padding 0x00
#
# Sólo aplica cuando el teclado está físicamente acoplado (USB,
# product 0x1B2C). En modo Bluetooth (product 0x1B2D, después de
# desacoplarlo) el teclado queda físicamente debajo de la pantalla
# inferior, así que el backlight no tiene utilidad ahí.

REPORT_ID = 0x5A
HEADER = bytes([0xBA, 0xC5, 0xC4])
PAYLOAD_LEN = 16  # report ID + 15 bytes

# ioctl HIDIOCSFEATURE(len) = _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
# direction = 3 (read|write), type = 'H' = 0x48, nr = 0x06
def _hidiocsfeature(length):
    return (3 << 30) | (length << 16) | (0x48 << 8) | 0x06


HIDIOCSFEATURE_16 = _hidiocsfeature(PAYLOAD_LEN)


class KeyboardBacklightManager:
    """
    Controla el backlight del teclado dock del Zenbook Duo.

    Config (config.yaml):

        keyboard:
          backlight_level: 1     # 0..3 (0 = apagado)
          backlight_vendor: "0b05"
          backlight_product: "1b2c"   # USB cuando está dock
    """

    def __init__(self, config):
        self.config = config
        kb_cfg = config.get('keyboard', {}) or {}
        self.level = int(kb_cfg.get('backlight_level', 1))
        self.vendor = kb_cfg.get('backlight_vendor', '0b05').lower()
        self.product = kb_cfg.get('backlight_product', '1b2c').lower()
        self.level = max(0, min(3, self.level))

    def _find_hidraw(self):
        """
        Busca el /dev/hidrawN del teclado dock (USB, vendor:product
        especificados). Devuelve la ruta o None.

        El uevent expone HID_ID=BUS:VENDOR:PRODUCT con cada componente en
        hex zero-padded a 4/8/8 (e.g. '0003:00000B05:00001B2C').
        """
        sys_dir = "/sys/class/hidraw"
        if not os.path.isdir(sys_dir):
            return None

        target = (
            f":{self.vendor.upper().zfill(8)}:"
            f"{self.product.upper().zfill(8)}"
        )

        for entry in sorted(os.listdir(sys_dir)):
            uevent = f"{sys_dir}/{entry}/device/uevent"
            try:
                with open(uevent) as f:
                    contents = f.read().upper()
            except Exception:
                continue
            if target in contents:
                return f"/dev/{entry}"
        return None

    def apply(self, level=None, retries=3, retry_delay=0.5):
        """
        Aplica el nivel de backlight al teclado dock. Si el teclado todavía
        no está enumerado en hidraw (típico justo tras dockar), reintenta
        un par de veces.
        """
        target = self.level if level is None else max(0, min(3, int(level)))

        for attempt in range(retries):
            hidraw = self._find_hidraw()
            if hidraw:
                if self._send(hidraw, target):
                    print(f"[KBD-LIGHT] Nivel {target} aplicado en {hidraw}")
                    return True
                # Si la escritura falló pero el device existe, no insistas.
                return False
            time.sleep(retry_delay)

        print(f"[KBD-LIGHT] No se encontró hidraw del teclado "
              f"({self.vendor}:{self.product}). ¿Está dockeado?")
        return False

    def _send(self, hidraw_path, level):
        payload = bytearray(PAYLOAD_LEN)
        payload[0] = REPORT_ID
        payload[1:4] = HEADER
        payload[4] = level
        try:
            fd = os.open(hidraw_path, os.O_RDWR)
            try:
                fcntl.ioctl(fd, HIDIOCSFEATURE_16, bytes(payload))
                return True
            finally:
                os.close(fd)
        except PermissionError:
            print(f"[KBD-LIGHT] Sin permisos para {hidraw_path} (necesita root)")
        except OSError as e:
            print(f"[KBD-LIGHT] Error al escribir feature report: {e}")
        return False
