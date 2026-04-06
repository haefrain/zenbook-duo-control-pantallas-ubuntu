"""
Captura las teclas Fn vendor-specific del teclado Bluetooth ASUS Zenbook Duo
(0B05:1B2D) que el kernel NO mapea automáticamente.

Linux entrega los reports HID vendor-specific (Report ID 0x5A, page 0xFF31)
de este teclado como eventos EV_ABS / ABS_MISC sobre uno de los inputs del
teclado, en lugar de mapearlos a keycodes XF86. Este módulo escucha esos
eventos y los traduce a acciones reales (subir/bajar brillo, mute mic, etc).

Mapeo descubierto experimentalmente con evtest sobre /dev/input/eventNN:
    0x10 (16)   → bajar brillo de pantalla
    0x20 (32)   → subir brillo de pantalla
    0x7c (124)  → toggle mute del micrófono
    0xc7 (199)  → ciclo brillo del teclado retroiluminado (no actuamos:
                  el teclado no responde por BT y no hay endpoint output
                  conocido para escribir el backlight)
    0x00 (0)    → release de cualquier tecla (se ignora)

Pasos por pulsación de brillo: 10%.
"""

import os
import subprocess
import threading
import time

import evdev
from evdev import ecodes


# Códigos vendor del teclado ASUS Zenbook Duo BT (segundo byte del report 0x5A).
KEY_BRIGHTNESS_DOWN = 0x10
KEY_BRIGHTNESS_UP = 0x20
KEY_MIC_MUTE = 0x7c
KEY_KBD_BACKLIGHT_CYCLE = 0xc7
KEY_RELEASE = 0x00

# Cuánto sube/baja el brillo por pulsación.
BRIGHTNESS_STEP = 10

# Nombre del teclado tal como lo expone uhid (BT). Coincide con
# /proc/bus/input/devices > N: Name="ASUS Zenbook Duo Keyboard".
KEYBOARD_NAME = "ASUS Zenbook Duo Keyboard"


class FnKeysManager:
    """
    Lee los endpoints vendor del teclado BT y traduce los códigos del
    report 0x5A a acciones del sistema.

    El daemon corre como root, así que tiene permisos para leer
    /dev/input/eventNN directamente sin udev rules adicionales.
    """

    def __init__(self, brightness_manager=None, session_runner=None, username=None):
        self._brightness = brightness_manager
        self._run_session = session_runner
        self._username = username
        self._stop = threading.Event()
        self._threads = []
        # ID de la última notificación creada por este módulo. Usamos
        # uno solo (no uno por categoría) para que CUALQUIER tecla Fn
        # nueva reemplace la notificación anterior, sea brillo o mic:
        # así el usuario nunca acumula toasts ni se pierde el feedback
        # actual.
        self._last_notification_id = 0

    def start(self):
        """Lanza el watcher en un thread daemon. No bloquea."""
        thread = threading.Thread(target=self._run_loop, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _find_vendor_devices(self):
        """
        Busca los inputs del teclado BT cuyo capability set tiene EV_ABS
        pero NO EV_KEY: esos son los endpoints vendor del HID compuesto
        donde aparecen los códigos del report 0x5A como ABS_MISC.

        Devuelve una lista de InputDevice (puede tener 0, 1 o más).
        """
        candidates = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except Exception:
                continue
            if dev.name != KEYBOARD_NAME:
                dev.close()
                continue
            caps = dev.capabilities()
            has_abs = ecodes.EV_ABS in caps
            has_key = ecodes.EV_KEY in caps
            if has_abs and not has_key:
                candidates.append(dev)
            else:
                dev.close()
        return candidates

    def _run_loop(self):
        """
        Loop principal: descubre los devices candidatos, los escucha en
        paralelo, y reintenta si el teclado se desconecta o el set de
        devices cambia.
        """
        while not self._stop.is_set():
            devices = self._find_vendor_devices()
            if not devices:
                # Teclado no conectado todavía. Reintentar en 5s.
                time.sleep(5)
                continue

            print(f"[FN-KEYS] Escuchando {len(devices)} endpoint(s) vendor "
                  f"del teclado BT: {[d.path for d in devices]}", flush=True)

            try:
                self._listen(devices)
            except OSError as e:
                # Device desconectado (errno 19 = ENODEV típico).
                print(f"[FN-KEYS] Endpoint cayó ({e}); reintentando...",
                      flush=True)
            finally:
                for d in devices:
                    try:
                        d.close()
                    except Exception:
                        pass

            time.sleep(2)

    def _listen(self, devices):
        """
        Multiplexa los devices con select() de evdev. Procesa eventos
        ABS_MISC y los traduce a acciones.
        """
        from select import select
        fd_to_device = {d.fd: d for d in devices}

        while not self._stop.is_set():
            r, _, _ = select(fd_to_device, [], [], 1.0)
            for fd in r:
                dev = fd_to_device[fd]
                for event in dev.read():
                    if event.type != ecodes.EV_ABS:
                        continue
                    if event.code != ecodes.ABS_MISC:
                        continue
                    self._handle_code(event.value)

    def _handle_code(self, code):
        if code == KEY_RELEASE:
            return  # release: no actuar
        if code == KEY_BRIGHTNESS_DOWN:
            self._step_brightness(-BRIGHTNESS_STEP)
        elif code == KEY_BRIGHTNESS_UP:
            self._step_brightness(+BRIGHTNESS_STEP)
        elif code == KEY_MIC_MUTE:
            self._toggle_mic_mute()
        elif code == KEY_KBD_BACKLIGHT_CYCLE:
            # El firmware del teclado emite el evento pero no actúa: no
            # hay forma conocida de escribir al backlight del teclado por
            # BT. Solo loguear para no sorprender al usuario.
            print("[FN-KEYS] tecla bucle backlight teclado (sin acción "
                  "soportada por BT)", flush=True)
        else:
            print(f"[FN-KEYS] código vendor desconocido: 0x{code:02x}",
                  flush=True)

    def _step_brightness(self, delta_pct):
        """Sube o baja el brillo en pasos. Activa el override manual."""
        if self._brightness is None:
            print("[FN-KEYS] BrightnessManager no disponible; ignoro "
                  f"step {delta_pct:+d}%", flush=True)
            return
        new_pct = self._brightness.step_brightness(delta_pct)
        if new_pct is not None:
            print(f"[FN-KEYS] brillo {delta_pct:+d}% → {new_pct}%",
                  flush=True)
            self._notify(
                title="Brillo de pantalla",
                body=f"{new_pct}%",
                icon="display-brightness-symbolic",
                value=new_pct,
            )

    def _toggle_mic_mute(self):
        """
        Toggle del mute del micrófono usando wpctl (PipeWire).
        Después del toggle, lee el estado real con wpctl get-volume y
        notifica acordemente con el icono correcto.
        """
        if self._username is None:
            print("[FN-KEYS] username no disponible; ignoro mic mute",
                  flush=True)
            return
        try:
            uid = subprocess.check_output(
                f"id -u {self._username}", shell=True,
            ).decode().strip()
            env_prefix = (
                f"sudo -u {self._username} "
                f"env XDG_RUNTIME_DIR=/run/user/{uid} "
                f"WAYLAND_DISPLAY=wayland-0 "
            )
            # 1) Toggle
            subprocess.run(
                f"{env_prefix} wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle",
                shell=True, check=True, timeout=5,
            )
            # 2) Leer el estado nuevo
            result = subprocess.run(
                f"{env_prefix} wpctl get-volume @DEFAULT_AUDIO_SOURCE@",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            is_muted = "MUTED" in result.stdout
            # 3) Notificar con el icono correcto
            if is_muted:
                self._notify(
                    title="Micrófono",
                    body="Silenciado",
                    icon="microphone-disabled-symbolic",
                )
            else:
                self._notify(
                    title="Micrófono",
                    body="Activo",
                    icon="audio-input-microphone-symbolic",
                )
            print(f"[FN-KEYS] mic mute toggled → "
                  f"{'silenciado' if is_muted else 'activo'}", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[FN-KEYS] error al toggle mic mute: {e}", flush=True)
        except Exception as e:
            print(f"[FN-KEYS] error inesperado en mic mute: {e}", flush=True)

    def _notify(self, title, body, icon, value=None):
        """
        Envía una notificación al escritorio del usuario via notify-send.

        Reemplaza siempre la última notificación que mostramos (sin
        importar el tipo) usando --replace-id con el ID guardado.
        Capturamos el ID nuevo con --print-id para reusarlo en la
        próxima llamada. Esto evita que el usuario acumule toasts y
        siempre vea el feedback más reciente.
        """
        if self._username is None:
            return
        try:
            uid = subprocess.check_output(
                f"id -u {self._username}", shell=True,
            ).decode().strip()
            env_prefix = (
                f"sudo -u {self._username} "
                f"env XDG_RUNTIME_DIR=/run/user/{uid} "
                f"WAYLAND_DISPLAY=wayland-0 "
            )
            replace_arg = (
                f"--replace-id={self._last_notification_id}"
                if self._last_notification_id else ""
            )
            value_arg = (
                f"-h int:value:{int(value)}" if value is not None else ""
            )
            cmd = (
                f"{env_prefix} notify-send --print-id "
                f"{replace_arg} {value_arg} "
                f"-i {icon} '{title}' '{body}'"
            )
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=5,
            )
            new_id = result.stdout.strip()
            if new_id.isdigit():
                self._last_notification_id = int(new_id)
        except Exception as e:
            print(f"[FN-KEYS] error en notify-send: {e}", flush=True)
