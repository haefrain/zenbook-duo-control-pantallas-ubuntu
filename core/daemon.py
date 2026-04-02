import time
import subprocess
import os
from core.config_loader import load_config
from modules.battery import BatteryManager
from modules.display_dock import DockMonitor
from modules.bluetooth import BluetoothManager
from modules.auto_rotate import RotationManager
from modules.auto_brightness import BrightnessManager
from modules.touchscreen_mapping import TouchscreenMapper


def run_in_user_session(command, username):
    """
    Cruza el puente de seguridad entre root y Wayland.
    Inyecta las variables de entorno necesarias para que el comando
    afecte la sesión gráfica del usuario.
    """
    try:
        uid = subprocess.check_output(f"id -u {username}", shell=True).decode().strip()
        full_command = (
            f"sudo -u {username} "
            f"env XDG_RUNTIME_DIR=/run/user/{uid} "
            f"WAYLAND_DISPLAY=wayland-0 "
            f"{command}"
        )
        subprocess.run(full_command, shell=True, check=True)
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

    # --- Detección de teclado / dock ---
    dock_monitor = None
    if features.get('display_dock', True):
        vid = config['keyboard']['vendor_id']
        pid = config['keyboard']['product_id']
        bt_mac = config['keyboard']['mac_address']
        bt_manager = BluetoothManager(mac_address=bt_mac)

        def on_undock_actions():
            encender_pantalla_inferior(config)
            bt_manager.force_connect()

        dock_monitor = DockMonitor(
            vendor_id=vid,
            product_id=pid,
            on_dock_callback=lambda: apagar_pantalla_inferior(config),
            on_undock_callback=on_undock_actions,
        )
        dock_monitor.start()
        print(f"[DOCK] Monitoreando teclado {vid}:{pid}")

    is_docked = dock_monitor.is_docked if dock_monitor is not None else lambda: False

    # --- Brillo automático ---
    brightness_manager = None
    if features.get('auto_brightness', True):
        brightness_manager = BrightnessManager(
            session_runner=run_in_user_session,
            username=user,
        )
        brightness_manager.start()
        print("[BRILLO] Brillo automático activado (sincronización manual en paralelo)")

    # --- Rotación automática (el loop también alimenta auto_brightness) ---
    rotation_enabled = features.get('auto_rotate', True)
    if rotation_enabled or brightness_manager:
        rot_manager = RotationManager(
            config=config,
            session_runner=run_in_user_session,
            is_docked_callback=is_docked,
            brightness_manager=brightness_manager,
            rotation_enabled=rotation_enabled,
        )
        rot_manager.start()
        if rotation_enabled:
            print("[ROTACIÓN] Auto-rotación activada")

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
