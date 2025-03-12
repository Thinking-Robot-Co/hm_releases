#!/usr/bin/env python3
import subprocess
import time
import bluetooth

def setup_bluetooth():
    # 1. Register Serial Port Profile (SPP) so that your device is advertized as a serial port.
    print("Registering Serial Port Profile...")
    try:
        subprocess.run(["sudo", "sdptool", "add", "SP"], check=True)
    except subprocess.CalledProcessError as e:
        print("Error running sdptool:", e)
    
    # 2. Run a series of bluetoothctl commands to configure the adapter.
    #    We use a multi-line command string and pipe it into bluetoothctl.
    bt_commands = "\n".join([
        "agent on",
        "default-agent",
        "power on",
        "pairable on",
        "discoverable on",
        "quit"
    ])
    print("Configuring bluetoothctl settings...")
    try:
        subprocess.run(["sudo", "bluetoothctl"], input=bt_commands, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("Error configuring bluetoothctl:", e)
    
    print("Bluetooth adapter should now be powered, pairable, and discoverable.")
    # Give it a moment to settle
    time.sleep(2)

def start_rfcomm_server():
    # Create an RFCOMM Bluetooth socket and bind it to an available port.
    server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
    # Bind to port ANY (let the OS choose) on all interfaces.
    server_sock.bind(("", bluetooth.PORT_ANY))
    server_sock.listen(1)

    port = server_sock.getsockname()[1]
    print("RFCOMM server listening on channel", port)

    # Advertise the service so that a Serial Terminal app on your phone can see it.
    try:
        bluetooth.advertise_service(
            server_sock,
            "MySerialSPP",
            service_classes=[bluetooth.SERIAL_PORT_CLASS],
            profiles=[bluetooth.SERIAL_PORT_PROFILE]
        )
    except Exception as e:
        # If advertisement fails, you may still be able to connect manually.
        print("Warning: Service advertisement failed:", e)
    
    print("Waiting for an RFCOMM connection from your mobile device...")
    client_sock, client_info = server_sock.accept()
    print("Accepted connection from:", client_info)
    
    try:
        while True:
            data = client_sock.recv(1024)
            if not data:
                break
            command = data.decode('utf-8').strip()
            print("Received command:", command)
            # Here you can add code to act upon commands (e.g., start/stop video, etc.)
    except OSError as e:
        print("Connection error:", e)
    finally:
        print("Closing connection.")
        client_sock.close()
        server_sock.close()

def main():
    print("Setting up Bluetooth...")
    setup_bluetooth()
    print("Starting RFCOMM server...")
    start_rfcomm_server()

if __name__ == "__main__":
    main()
