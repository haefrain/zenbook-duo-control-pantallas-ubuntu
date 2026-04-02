import re
import subprocess


class TouchscreenMapper:
    """
    Mapea cada touchscreen a su pantalla correcta en GNOME Wayland.

    El Zenbook Duo tiene dos pantallas táctiles con EDID idéntico (SDC/0x419d),
    por lo que GNOME no puede distinguirlas automáticamente.

    Estrategia: fijar el top_device al EDID exacto del monitor (explicit claim),
    y dejar el bottom_device en auto ['','',''] para que Mutter lo asigne al
    display que quede libre. El mapeo se lee en el momento de añadir el
    dispositivo, por lo que requiere un re-login para aplicarse por primera vez.

    Dispositivos:
      ELAN9008:00 04F3:425B  →  pantalla superior (eDP-1 por defecto)
      ELAN9009:00 04F3:425A  →  pantalla inferior (eDP-2 por defecto)
    """

    DCONF_BASE = "/org/gnome/desktop/peripherals/touchscreens"

    def __init__(self, config, session_runner):
        self.config = config
        self.run_session = session_runner

    def apply(self):
        ts_config = self.config.get('touchscreen', {})
        top_device    = ts_config.get('top_device',    '04f3:425b')
        bottom_device = ts_config.get('bottom_device', '04f3:425a')
        swap          = ts_config.get('swap', False)

        if swap:
            top_device, bottom_device = bottom_device, top_device

        user = self.config['system']['username']

        # Obtener el EDID real de la pantalla superior desde Mutter vía D-Bus
        vendor, product, serial = self._get_display_edid(
            self.config['displays']['top'], user
        )

        # top_device → EDID explícito (reclama el primer monitor coincidente)
        # bottom_device → auto ['','',''] (Mutter asigna el que quede libre)
        self._set_output(top_device,    f"['{vendor}', '{product}', '{serial}']", user)
        self._set_output(bottom_device, "['', '', '']",                           user)
        print(f"[TOUCH] {top_device} → EDID {vendor}/{product} | {bottom_device} → auto")
        print("[TOUCH] Nota: el mapeo se aplica al iniciar sesión (re-login si es la primera vez)")

    def _get_display_edid(self, connector, username):
        """Consulta el vendor/product/serial EDID del conector dado vía Mutter D-Bus."""
        try:
            uid = subprocess.check_output(
                f"id -u {username}", shell=True
            ).decode().strip()
            cmd = (
                f"sudo -u {username} "
                f"env XDG_RUNTIME_DIR=/run/user/{uid} WAYLAND_DISPLAY=wayland-0 "
                f"gdbus call --session "
                f"--dest org.gnome.Mutter.DisplayConfig "
                f"--object-path /org/gnome/Mutter/DisplayConfig "
                f"--method org.gnome.Mutter.DisplayConfig.GetCurrentState"
            )
            out = subprocess.check_output(cmd, shell=True, text=True)
            # Buscar la tupla (connector, vendor, product, serial)
            match = re.search(
                rf"\('{re.escape(connector)}',\s*'([^']+)',\s*'([^']+)',\s*'([^']*)'\)",
                out
            )
            if match:
                return match.group(1), match.group(2), match.group(3)
        except Exception as e:
            print(f"[TOUCH] No se pudo leer EDID de {connector}: {e}")
        # Fallback a los valores conocidos del Zenbook Duo
        return 'SDC', '0x419d', '0x00000000'

    def _set_output(self, device_id, value, username):
        path = f"{self.DCONF_BASE}/{device_id}:/output"
        try:
            self.run_session(f"dconf write {path} \"{value}\"", username)
        except Exception as e:
            print(f"[TOUCH] Error al escribir {device_id}: {e}")
