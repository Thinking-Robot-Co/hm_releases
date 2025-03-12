#!/usr/bin/env python3
import subprocess
import time
import bluetooth
import threading
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import gi

gi.require_version('GLib', '2.0')
from gi.repository import GLib

AGENT_INTERFACE = "org.bluez.Agent1"

########################################
# 1) AUTO-ACCEPT AGENT IMPLEMENTATION
########################################
class AutoAgent(dbus.service.Object):
    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        print("[Agent] Release called")
        pass

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def Cancel(self, device_path):
        print(f"[Agent] Cancel called for {device_path}")
        pass

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[Agent] AuthorizeService: {device}, UUID={uuid} -> auto-accept")
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        # Return a fixed PIN for pairing.
        print(f"[Agent] RequestPinCode for {device} -> returning '0000'")
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"[Agent] RequestPasskey for {device} -> returning 0")
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"[Agent] DisplayPasskey: {device}, passkey={passkey}, entered={entered}")

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[Agent] RequestConfirmation: {device}, passkey={passkey} -> auto-confirm")
        return

def run_auto_agent():
    """
    Initializes the D-Bus event loop and registers the auto-accept agent.
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    system_bus = dbus.SystemBus()

    # Use "DisplayYesNo" to allow auto-confirmation
    agent_path = "/test/auto_agent"
    capability = "DisplayYesNo"  # This mode will display a passkey, then auto-confirm it

    agent = AutoAgent(system_bus, agent_path)
    agent_manager = dbus.Interface(
        system_bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.AgentManager1"
    )
    agent_manager.RegisterAgent(agent_path, capability)
    print(f"[Agent] Registered with capability: {capability}")
    agent_manager.RequestDefaultAgent(agent_path)
    print("[Agent] Auto-accept agent is now the default.")

    loop = GLib.MainLoop()
    loop.run()

########################################
# 2) RFCOMM SERVER LOGIC
########################################
def setup_bluetooth():
    # Optional: register SPP with sdptool
    print("[Setup] Registering Serial Port Profile (SP) with sdptool...")
    try:
        subprocess.run(["sudo", "sdptool", "add", "SP"], check=True)
    except subprocess.CalledProcessError as e:
        print("[Setup] sdptool error (can often be ignored):", e)

    # Configure bluetoothctl settings.
    bt_commands = "\n".join([
        "agent off",          # Turn off any built-in agent since we use our custom one
        "default-agent",
        "power on",
        "pairable on",
        "discoverable on",
        "quit"
    ])
    print("[Setup] Configuring bluetoothctl...")
    try:
        subprocess.run(["bluetoothctl"], input=bt_commands, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("[Setup] bluetoothctl config error:", e)
    print("[Setup] Bluetooth adapter should now be powered, pairable, and discoverable.")
    time.sleep(2)

def start_rfcomm_server():
    # Create an RFCOMM Bluetooth socket.
    server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
    server_sock.bind(("", bluetooth.PORT_ANY))
    server_sock.listen(1)

    port = server_sock.getsockname()[1]
    print(f"[RFCOMM] Server listening on RFCOMM channel {port}")

    # Advertise the service so that your phone sees a Serial Port Profile.
    try:
        bluetooth.advertise_service(
            server_sock,
            "MyAutoAgentSPP",
            service_classes=[bluetooth.SERIAL_PORT_CLASS],
            profiles=[bluetooth.SERIAL_PORT_PROFILE]
        )
    except Exception as e:
        print("[RFCOMM] Warning: Service advertisement failed:", e)

    print("[RFCOMM] Waiting for an RFCOMM connection from your phone...")
    client_sock, client_info = server_sock.accept()
    print("[RFCOMM] Accepted connection from:", client_info)

    try:
        while True:
            data = client_sock.recv(1024)
            if not data:
                break
            command = data.decode('utf-8').strip()
            print("[RFCOMM] Received command:", command)
            # Insert logic here to handle commands (e.g., control your camera)
    except OSError as e:
        print("[RFCOMM] Connection error:", e)
    finally:
        print("[RFCOMM] Closing connection.")
        client_sock.close()
        server_sock.close()

########################################
# 3) MAIN ENTRY POINT
########################################
def main():
    # Start the auto-agent in a background thread.
    agent_thread = threading.Thread(target=run_auto_agent, daemon=True)
    agent_thread.start()

    # Give the agent time to register.
    time.sleep(2)

    # Setup Bluetooth adapter settings.
    setup_bluetooth()

    # Start the RFCOMM server.
    start_rfcomm_server()

if __name__ == "__main__":
    main()
