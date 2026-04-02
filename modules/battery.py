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
        applied = False
        
        for path in self.sysfs_paths:
            if os.path.exists(path):
                try:
                    # 1. Leer el estado actual
                    with open(path, 'r') as file:
                        current = file.read().strip()
                    
                    if current == self.charge_limit:
                        print(f"\n[BATERÍA] 🔋 El límite ya estaba correctamente fijado al {self.charge_limit}% en {path}")
                        applied = True
                        continue

                    # 2. Escribir el nuevo límite
                    with open(path, 'w') as file:
                        file.write(self.charge_limit)
                    
                    # 3. VERIFICAR: Leer inmediatamente después para detectar rechazos silenciosos
                    with open(path, 'r') as file:
                        verify = file.read().strip()
                    
                    if verify == self.charge_limit:
                        print(f"\n[BATERÍA] 🔋 Límite actualizado y VERIFICADO al {self.charge_limit}% ({path})")
                        applied = True
                    else:
                        print(f"\n[ERROR BATERÍA] Rechazo silencioso. Se escribió {self.charge_limit} en {path}, pero el hardware reporta {verify}.")
                        
                except PermissionError:
                    print(f"\n[ERROR BATERÍA] Sin permisos para {path}. El demonio requiere sudo.")
                except Exception as e:
                    print(f"\n[ERROR BATERÍA] Excepción inesperada en {path}: {e}")
        
        if not applied:
            print("\n[ADVERTENCIA] No se pudo verificar el límite. ¿Tienes TLP instalado que pueda estar sobrescribiendo la configuración?")