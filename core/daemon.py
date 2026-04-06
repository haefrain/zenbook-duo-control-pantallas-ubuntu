import time
import subprocess
import threading
import os
from core.config_loader import load_config
from modules.battery import BatteryManager
from modules.display_dock import DockMonitor
from modules.bluetooth import BluetoothManager
from modules.auto_rotate import RotationManager
from modules.auto_brightness import BrightnessManager
from modules.touchscreen_mapping import TouchscreenMapper
from modules.power_profile import PowerProfileManager
from modules.oled_care import OledCareManager
from modules.keyboard_backlight import KeyboardBacklightManager
from modules.fn_keys import FnKeysManager


# Timeout máximo para comandos en la sesión del usuario.
# Si Mutter cuelga aplicando una config, sin timeout el daemon entero se cuelga.
SESSION_CMD_TIMEOUT = 15


def run_in_user_session(command, username, timeout=SESSION_CMD_TIMEOUT):
    """
    Cruza el puente de seguridad entre root y Wayland.
    Inyecta las variables de entorno necesarias para que el comando
    afecte la sesión gráfica del usuario. Aplica un timeout para evitar
    bloquear el daemon si Mutter no responde.
    """
    try:
        uid = subprocess.check_output(f"id -u {username}", shell=True).decode().strip()
        full_command = (
            f"sudo -u {username} "
            f"env XDG_RUNTIME_DIR=/run/user/{uid} "
            f"WAYLAND_DISPLAY=wayland-0 "
            f"{command}"
        )
        subprocess.run(full_command, shell=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Comando excedió {timeout}s: {command[:80]}...")
        raise
    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar comando en la sesión gráfica: {e}")
        raise


def apagar_pantalla_inferior(config):
    print("\n[ACCIÓN] Apagando pantalla OLED inferior...")
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gnome_randr.py")
    pantalla = config['displays']['bottom']
    user = config['system']['username']
    run_in_user_session(f"python3 {script_path} --output {pantalla} --off", user)


def encender_pantalla_inferior(config):
    print("\n[ACCIÓN] Restaurando pantalla OLED inferior...")
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gnome_randr.py")
    pantalla_bottom = config['displays']['bottom']
    pantalla_top = config['displays']['top']
    escala = config['displays'].get('scale', 1)
    user = config['system']['username']
    cmd = f"python3 {script_path} --output {pantalla_bottom} --auto --scale {escala} --below {pantalla_top}"
    run_in_user_session(cmd, user)


def main():
    print("Iniciando Zenbook Duo Daemon...")
    config = load_config()
    features = config.get('features', {})
    user = config['system']['username']

    # --- Mapeo de touchscreens ---
    if features.get('touchscreen_mapping', True):
        TouchscreenMapper(config=config, session_runner=run_in_user_session).apply()
        print("[TOUCH] Mapeo de touchscreens aplicado")

    # --- Protección de batería ---
    if features.get('battery_protection', True):
        limite = config.get('battery', {}).get('charge_limit', 80)
        battery_manager = BatteryManager(charge_limit=limite)
        battery_manager.set_charge_limit()
        print(f"[BATERÍA] Límite de carga: {limite}%")

    # --- Bluetooth: combinar MAC del teclado + dispositivos extra ---
    bt_config = config.get('bluetooth', {})
    bt_macs = []
    keyboard_mac = config.get('keyboard', {}).get('mac_address', '')
    if keyboard_mac:
        bt_macs.append(keyboard_mac)
    bt_macs.extend(bt_config.get('devices', []))

    bt_manager = BluetoothManager(mac_addresses=bt_macs)

    # Watcher de desbloqueo de pantalla
    if bt_config.get('reconnect_on_unlock', True) and bt_macs:
        bt_manager.start_unlock_watcher(bt_manager.force_connect)
        print(f"[BLUETOOTH] Watcher de desbloqueo activado ({len(bt_macs)} dispositivo(s))")

    # --- Backlight del teclado dock ---
    kbd_backlight = None
    if features.get('keyboard_backlight', True):
        kbd_backlight = KeyboardBacklightManager(config=config)
        # Aplicación inicial: si ya está dockeado, ponemos el nivel guardado.
        kbd_backlight.apply()

    # --- Detección de teclado / dock ---
    dock_monitor = None
    if features.get('display_dock', True):
        vid = config['keyboard']['vendor_id']
        pid = config['keyboard']['product_id']

        def on_dock_actions():
            apagar_pantalla_inferior(config)
            # Reaplicar el nivel del backlight: el teclado se resetea al
            # reconectarse. Se hace en thread porque _find_hidraw puede
            # tener que esperar a que el device aparezca.
            if kbd_backlight is not None:
                threading.Thread(
                    target=kbd_backlight.apply, daemon=True
                ).start()

        def on_undock_actions():
            encender_pantalla_inferior(config)
            bt_manager.force_connect()

        dock_monitor = DockMonitor(
            vendor_id=vid,
            product_id=pid,
            on_dock_callback=on_dock_actions,
            on_undock_callback=on_undock_actions,
        )
        dock_monitor.start()
        print(f"[DOCK] Monitoreando teclado {vid}:{pid}")
    elif bt_manager.mac_address:
        # Sin display_dock pero con MAC del teclado: solo registrar bt_manager
        pass

    is_docked = dock_monitor.is_docked if dock_monitor is not None else lambda: False

    # --- Brillo: sync de teclas siempre activo; sensor solo si auto_brightness: true ---
    auto_brightness = features.get('auto_brightness', True)
    brightness_manager = BrightnessManager(
        session_runner=run_in_user_session,
        username=user,
    )
    brightness_manager.start()  # arranca el hilo de sync manual (teclas → eDP-2)
    if auto_brightness:
        print("[BRILLO] Brillo automático activado (sensor + sync de teclas en paralelo)")
    else:
        print("[BRILLO] Sync de teclas de brillo activado (sensor desactivado)")

    # Aviso si GNOME tiene su propio brillo automático activado: en ese caso
    # GNOME bajará el brillo de eDP-1 según el sensor IIO independientemente
    # de nuestra config y nuestro sync lo replicará al screenpad. El usuario
    # lo percibe como "el script baja el brillo solo".
    if not auto_brightness:
        try:
            ambient = subprocess.check_output(
                f"sudo -u {user} env XDG_RUNTIME_DIR=/run/user/$(id -u {user}) "
                f"gsettings get org.gnome.settings-daemon.plugins.power ambient-enabled",
                shell=True, text=True, timeout=3,
            ).strip()
            if ambient == 'true':
                print("[AVISO] GNOME tiene 'ambient-enabled' = true: el sistema "
                      "operativo bajará el brillo según el sensor de luz aunque "
                      "auto_brightness esté en false en config.yaml. Para "
                      "desactivarlo: gsettings set "
                      "org.gnome.settings-daemon.plugins.power ambient-enabled false")
        except Exception:
            pass

    # --- Rotación automática (el loop también alimenta auto_brightness) ---
    rotation_enabled = features.get('auto_rotate', True)
    rot_manager = None
    if rotation_enabled or auto_brightness:
        rot_manager = RotationManager(
            config=config,
            session_runner=run_in_user_session,
            is_docked_callback=is_docked,
            brightness_manager=brightness_manager if auto_brightness else None,
            rotation_enabled=rotation_enabled,
        )
        rot_manager.start()
        if rotation_enabled:
            print("[ROTACIÓN] Auto-rotación activada")

    # --- Power profile + refresh rate por estado de carga ---
    if features.get('power_profile', True):
        ppm = PowerProfileManager(config=config, session_runner=run_in_user_session)
        ppm.start()

    # --- OLED care: idle dim de la pantalla inferior ---
    if features.get('oled_care', True):
        oled = OledCareManager(config=config, brightness_manager=brightness_manager)
        oled.start()

    # --- Teclas Fn vendor del teclado BT (brillo, mute mic, etc) ---
    if features.get('fn_keys', True):
        fn_keys = FnKeysManager(
            brightness_manager=brightness_manager,
            session_runner=run_in_user_session,
            username=user,
        )
        fn_keys.start()
        print("[FN-KEYS] Watcher de teclas Fn vendor activado")

    # --- Watchdog: refresh periódico de pantalla (OPT-IN) ---
    # Desactivado por defecto: hacer ApplyMonitorsConfig --force periódicamente
    # NO previene congelamientos del compositor, y puede producir parpadeos
    # innecesarios. Sólo se activa si watchdog.display_refresh_minutes está
    # explícitamente puesto a un entero > 0 en config.yaml.
    watchdog_cfg = config.get('watchdog') or {}
    watchdog_minutes = watchdog_cfg.get('display_refresh_minutes', 0)
    if rot_manager is not None and isinstance(watchdog_minutes, int) and watchdog_minutes > 0:
        def _display_watchdog():
            while True:
                time.sleep(watchdog_minutes * 60)
                print(f"[WATCHDOG] Refresh preventivo de pantalla...")
                rot_manager.refresh()
        threading.Thread(target=_display_watchdog, daemon=True).start()
        print(f"[WATCHDOG] Refresh de pantalla cada {watchdog_minutes} min")

    print(f"\nDaemon corriendo. Usuario: {user}")
    print("Logs: journalctl -u zenbook-duo -f\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDeteniendo demonio...")
        if dock_monitor:
            dock_monitor.stop()


if __name__ == "__main__":
    main()
