import pyudev

def sniffer_teclado():
    # Inicializamos el contexto de udev
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    
    # Filtramos por el subsistema USB (común para teclados con pines pogo)
    monitor.filter_by(subsystem='usb')
    
    print("Escuchando eventos del kernel...")
    print("Por favor, acopla y desacopla el teclado de la pantalla inferior.\n")

    # Bucle infinito escuchando eventos
    for action, device in monitor:
        # Solo nos interesan las conexiones y desconexiones
        if action in ['add', 'remove']:
            print(f"[{action.upper()}] Evento detectado:")
            print(f"  Subsistema: {device.subsystem}")
            print(f"  Nodo de dispositivo: {device.device_node}")
            print(f"  Vendor ID: {device.get('ID_VENDOR_ID')}")
            print(f"  Product ID: {device.get('ID_MODEL_ID')}")
            print(f"  Nombre: {device.get('ID_MODEL')}")
            print("-" * 50)

if __name__ == "__main__":
    sniffer_teclado()