import subprocess


class TouchscreenMapper:
    """
    Mapea cada touchscreen a su pantalla correcta en GNOME Wayland.

    El Zenbook Duo tiene dos pantallas táctiles con EDID idéntico, por lo que
    GNOME no puede distinguirlas automáticamente. Este módulo usa las rutas
    dconf por dispositivo con nombre de conector para forzar el mapeo correcto.

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

        top_display    = self.config['displays']['top']
        bottom_display = self.config['displays']['bottom']

        if swap:
            top_device, bottom_device = bottom_device, top_device

        user = self.config['system']['username']
        self._set_output(top_device,    top_display,    user)
        self._set_output(bottom_device, bottom_display, user)
        print(f"[TOUCH] {top_device} → {top_display} | {bottom_device} → {bottom_display}")

    def _set_output(self, device_id, connector, username):
        path = f"{self.DCONF_BASE}/{device_id}:/output"
        value = f"['', '{connector}', '']"
        try:
            self.run_session(f"dconf write {path} \"{value}\"", username)
        except Exception as e:
            print(f"[TOUCH] Error al mapear {device_id} → {connector}: {e}")
