import subprocess

class BluetoothManager:
    def __init__(self, mac_address):
        self.mac_address = mac_address

    def force_connect(self):
        if not self.mac_address:
            return
            
        print(f"\n[BLUETOOTH] 🔵 Forzando reconexión del teclado ({self.mac_address})...")
        try:
            # 1. Aseguramos que el adaptador Bluetooth no esté bloqueado por software
            subprocess.run(["rfkill", "unblock", "bluetooth"], check=False)
            
            # 2. Enviamos el comando de conexión usando bluetoothctl
            # Usamos Popen para lanzarlo asíncronamente y no frenar el encendido de la pantalla
            cmd = f"echo 'connect {self.mac_address}' | bluetoothctl"
            subprocess.Popen(
                cmd, 
                shell=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[ERROR BLUETOOTH] No se pudo forzar la conexión: {e}")