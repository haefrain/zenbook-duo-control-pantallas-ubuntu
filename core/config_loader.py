import yaml
import os

FEATURE_DEFAULTS = {
    'auto_rotate': True,
    'auto_brightness': True,
    'battery_protection': True,
    'display_dock': True,
    'touchscreen_mapping': True,
    'power_profile': True,
    'oled_care': True,
    'keyboard_backlight': True,
}

def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Falta el archivo {config_path}. Copia config.yaml.example y ajusta tus IDs.")

    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    # Aplicar defaults para features no definidas
    config.setdefault('features', {})
    for key, val in FEATURE_DEFAULTS.items():
        config['features'].setdefault(key, val)

    return config