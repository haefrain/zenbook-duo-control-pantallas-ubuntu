import os

class BatteryManager:
    def __init__(self, charge_limit=80):
        self.charge_limit = str(charge_limit) # Aseguramos que sea string para la lectura/escritura
        
        # Añadimos rutas alternativas (BATC, BATT, y la ruta madre del firmware asus-wmi)
        self.sysfs_paths = [
            "/sys/class/power_supply/BAT0/charge_control_end_threshold",
            "/sys/class/power_supply/BAT1/charge_control_end_threshold",
            "/sys/class/power_supply/BATC/charge_control_end_threshold",
            "/sys/devices/platform/asus-nb-wmi/charge_control_end_threshold"
        ]

    def set_charge_limit(self):
        for path in self.sysfs_paths:
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r') as file:
                    current = file.read().strip()

                if current == self.charge_limit:
                    print(f"\n[BATERÍA] 🔋 El límite ya estaba correctamente fijado al {self.charge_limit}% en {path}")
                    return

                with open(path, 'w') as file:
                    file.write(self.charge_limit)

                # Verificar para detectar rechazos silenciosos del firmware.
                with open(path, 'r') as file:
                    verify = file.read().strip()

                if verify == self.charge_limit:
                    print(f"\n[BATERÍA] 🔋 Límite actualizado y VERIFICADO al {self.charge_limit}% ({path})")
                    return
                else:
                    print(f"\n[ERROR BATERÍA] Rechazo silencioso. Se escribió {self.charge_limit} en {path}, pero el hardware reporta {verify}.")
                    return

            except PermissionError:
                print(f"\n[ERROR BATERÍA] Sin permisos para {path}. El demonio requiere sudo.")
            except Exception as e:
                print(f"\n[ERROR BATERÍA] Excepción inesperada en {path}: {e}")

        print("\n[ADVERTENCIA] No se encontró ningún path de batería compatible. ¿Tienes TLP instalado que pueda estar sobrescribiendo la configuración?")