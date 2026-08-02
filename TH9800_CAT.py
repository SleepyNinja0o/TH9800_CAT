from getpass import getpass
from TH9800_Enums import *
import radio_protocol
from radio_protocol import *
from time import sleep
try:
    import dearpygui.dearpygui as dpg
except ImportError:
    dpg = None  # Headless mode — no GUI
import serial.tools.list_ports,serial_asyncio,asyncio,threading
import logging,datetime,argparse,platform,ctypes,os,sys

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

protocol = None
read_loop_future = None
write_loop_future = None

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.txt")
CONFIG_DEFAULTS = {
    "baud_rate": "19200",
    "device": "FT232R USB UART",
    "host": "",
    "port": "",
    "password": "",
    "auto_start_server": "false",
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(CONFIG_DEFAULTS)
        return dict(CONFIG_DEFAULTS)
    settings = dict(CONFIG_DEFAULTS)
    with open(CONFIG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                if key in settings:
                    settings[key] = value.strip()
    return settings

def save_config(settings):
    with open(CONFIG_PATH, "w") as f:
        for key in CONFIG_DEFAULTS:
            f.write(f"{key}={settings.get(key, '')}\n")

def save_serial_settings():
    existing = load_config()
    comport = dpg.get_value("comport")
    device = ""
    if comport and ": " in comport:
        device = comport.split(": ", 1)[1]
    existing.update({
        "baud_rate": dpg.get_value("baud_rate"),
        "device": device,
    })
    save_config(existing)

def save_tcp_settings():
    existing = load_config()
    existing.update({
        "host": dpg.get_value("tcp_host_text"),
        "port": dpg.get_value("tcp_port_text"),
        "password": dpg.get_value("tcp_pass_text"),
    })
    save_config(existing)

def start_event_loop():
    loop.run_forever()

threading.Thread(target=start_event_loop, daemon=True).start()

def is_user_admin():
    # type: () -> bool
    """Return True if user has admin privileges.

    Raises:
        AdminStateUnknownError if user privileges cannot be determined.
    """
    class AdminStateUnknownError(Exception):
        """Cannot determine whether the user is an admin."""
        pass

    try:
        return os.getuid() == 0
    except AttributeError:
        pass
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() == 1
    except AttributeError:
        raise AdminStateUnknownError

is_user_admin = is_user_admin()

class TCP:
    def __init__(self):
        self.tcpclient = None
        self.tcpclient_server = None
        self.tcpclient_server_stop = False
        self.tcpclient_future = None
        self.tcpclient_ready = False
        self.tcpclient_passw = ""

        self.tcpserver = None
        self.tcpserver_server = None
        self.tcpserver_future = None
        self.tcpserver_ready = False
        self.tcpserver_loggedin = False
        self.tcpserver_login_count = 0
        self.tcpserver_passw = ""

    async def handle_tcpserver_stream(self, reader, writer):
        global protocol
        # Per-connection auth state (not shared — so one client disconnecting
        # doesn't kill auth for other connected clients)
        conn_loggedin = False
        conn_login_count = 0

        async def process_tcp_cmd(cmd, data, writer):
            nonlocal conn_loggedin, conn_login_count
            global protocol
            if cmd != "pass" and cmd != "exit" and conn_loggedin == False:
                return "Unauthorized"

            match cmd:
                case "pass":
                    if conn_login_count > 3:
                        return "returnLogin"
                    if data == self.tcpserver_passw:
                        conn_loggedin = True
                        conn_login_count = 0
                        return "Login Successful"
                    else:
                        conn_login_count += 1
                        return "Login Failed"
                case "data":
                    if not (protocol.transport and not protocol.transport.is_closing()):
                        return "serial not connected"
                    protocol.send_packet(data=bytearray.fromhex(data))
                    return "data sent"
                case "vol":
                    if not (protocol.transport and not protocol.transport.is_closing()):
                        return "serial not connected"
                    # !vol LEFT 50 or !vol RIGHT 75
                    parts = data.split() if data else []
                    if len(parts) == 2:
                        vfo_str = parts[0].upper()
                        vol = int(parts[1])
                        if vfo_str in ("LEFT", "L"):
                            protocol.radio.set_volume(vfo=RADIO_VFO.LEFT, vol=vol)
                        elif vfo_str in ("RIGHT", "R"):
                            protocol.radio.set_volume(vfo=RADIO_VFO.RIGHT, vol=vol)
                        return f"vol {vfo_str} {vol}"
                    return "usage: !vol LEFT|RIGHT 0-100"
                case "rts":
                    if not (protocol.transport and not protocol.transport.is_closing()):
                        return "serial not connected"
                    if data == None or data == "":
                        protocol.toggle_rts()
                    else:
                        protocol.set_rts(data.strip().lower() in ('true', '1', 'on'))
                    return str(protocol.transport.serial.rts)
                case "ptt":
                    if not (protocol.transport and not protocol.transport.is_closing()):
                        return "serial not connected"
                    # !ptt [on|off] — explicit key/unkey; bare !ptt toggles (legacy)
                    radio = protocol.radio
                    action = (data or '').strip().lower()
                    if action == 'on':
                        desired = True
                    elif action == 'off':
                        desired = False
                    else:
                        desired = not radio.mic_ptt
                    if desired != radio.mic_ptt:
                        radio.mic_ptt = desired
                        radio.vfo_memory[radio.vfo_memory['vfo_active']]['ptt'] = 1 if desired else 0
                        radio.exe_cmd(cmd=RADIO_TX_CMD.MIC_PTT)
                    return str(radio.mic_ptt)
                case "dtr":
                    if data == None or data == "":
                        protocol.toggle_dtr()
                    else:
                        protocol.set_dtr(data.strip().lower() in ('true', '1', 'on'))
                    return str(protocol.transport.serial.dtr)
                case "serial":
                    # !serial disconnect / !serial connect — cycle the serial port
                    action = (data or '').strip().lower()
                    if action == 'disconnect':
                        if protocol.transport and not protocol.transport.is_closing():
                            if protocol._read_task and not protocol._read_task.done():
                                protocol._read_task.cancel()
                            if protocol._write_task and not protocol._write_task.done():
                                protocol._write_task.cancel()
                            protocol._read_task = None
                            protocol._write_task = None
                            try:
                                protocol.transport.serial.dtr = False
                            except:
                                pass
                            protocol.transport.close()
                            protocol.ready.clear()
                            while not protocol.receive_queue.empty():
                                try: protocol.receive_queue.get_nowait()
                                except: break
                            while not protocol.transmit_queue.empty():
                                try: protocol.transmit_queue.get_nowait()
                                except: break
                            protocol.buffer.clear()
                            print("Serial disconnected via TCP")
                            show_serial_disconnected_ui(protocol.radio)
                            return "serial disconnected"
                        return "serial not connected"
                    elif action == 'connect':
                        if protocol.transport and not protocol.transport.is_closing():
                            return "serial already connected"
                        # Reconnect using saved config.txt
                        try:
                            import serial_asyncio
                            import serial.tools.list_ports
                            cfg = load_config()
                            device_name = cfg.get('device', '')
                            baudrate = int(cfg.get('baud_rate', 19200))
                            # Find COM port matching device name
                            comport = None
                            for p in serial.tools.list_ports.comports():
                                port_str = f"{p.device}: {p.description}"
                                if device_name and device_name in p.description:
                                    comport = p.device
                                    break
                            if not comport:
                                # Fallback: try first available port
                                ports = serial.tools.list_ports.comports()
                                if ports:
                                    comport = ports[0].device
                            if not comport:
                                return "serial no port found"
                            protocol.reset_ready()
                            loop = asyncio.get_event_loop()
                            transport, _ = await serial_asyncio.create_serial_connection(
                                loop, lambda: protocol, comport, baudrate=baudrate
                            )
                            await protocol.ready.wait()
                            # DTR toggle wakes the radio's serial output
                            # (without this, data_received never fires on first connect)
                            protocol.transport.serial.dtr = False
                            await asyncio.sleep(0.1)
                            protocol.transport.serial.dtr = True
                            saved_rts = SerialProtocol._load_rts_state()
                            protocol.transport.serial.rts = saved_rts
                            protocol.set_rts(saved_rts)
                            await asyncio.sleep(0.5)
                            # Start read/write loops (critical — without these, no data flows)
                            protocol._read_task = asyncio.create_task(read_loop(protocol))
                            protocol._write_task = asyncio.create_task(write_loop(protocol))
                            # STARTUP handshake tells radio to begin sending display data.
                            # STARTUP_2 response handler internally sends L/R_VOLUME_SQUELCH
                            # — that's the normal handshake, not a storm.
                            protocol.radio.connect_process = True
                            protocol.radio.exe_cmd(cmd=RADIO_TX_CMD.STARTUP)
                            await asyncio.sleep(3)
                            print(f"Serial connected via TCP ({comport} @ {baudrate})")
                            show_serial_connected_ui(protocol.radio)
                            return "serial connected"
                        except Exception as e:
                            print(f"Serial connect via TCP failed: {e}")
                            return f"serial error: {e}"
                    elif action == 'status':
                        if protocol.transport and not protocol.transport.is_closing():
                            return "serial connected"
                        return "serial disconnected"
                    return "usage: !serial connect|disconnect|status"
                case "exit":
                    return "return"
                case _:
                    return "Not Found"
            return "..."

        addr = writer.get_extra_info('peername')
        print(f"Connection from {addr}")

        self.tcpserver = writer

        try:
            while True:
                data = await reader.readline()

                if not data:
                    break  # connection closed

                printd(f"Data RCVD: {type(data)} /// {data}")
                data = data[0:-1] #Pull new line character off the end
                
                if type(data) == bytearray or type(data) == bytes: #Data received is a radio packet
                    if data.find(b'\xAA\xFD') != -1:
                        printd(f"Data RCVD(hex): {data.hex().upper()}")
                        if conn_loggedin == True:
                            protocol.send_packet(data=data)
                        else:
                            writer.write("Unauthorized\n".encode())
                            await writer.drain()
                            printd("Received radio packet from UNAUTHORIZED source...Please login")
                        continue
                
                message = data.decode().strip()
                if message == None or message == "":
                    continue

                if message[0] == "!":
                    data = message.find(" ")
                    if data != -1:
                        cmd = str(message[1:data])
                        data = str(message[data+1::])
                        printd(f"CMD RCVD1:{{{cmd}}}:{{{data}}}")
                        response = f"CMD{{{cmd}[{data}]}} "
                    else:
                        cmd = str(message[1::])
                        data = ""
                        printd(f"CMD RCVD2:{{{cmd}}}")
                        response = f"CMD{{{cmd}}} "

                    response2 = await process_tcp_cmd(cmd=cmd, data=data, writer=writer)
                    printd(f"Response2:{response2}")
                    
                    if response2 == "return":
                        response += "Ok\n"
                        writer.write(response.encode())
                        await writer.drain()
                        break
                    elif response2 == "returnLogin":
                        response += "Max login attempts reached\n"
                        writer.write(response.encode())
                        await writer.drain()
                        break
                    elif response2 == "Login Successful":
                        writer.write(f"{response2}\n".encode())
                        await writer.drain()
                        # Do NOT send STARTUP here — the !serial connect handler owns
                        # the STARTUP sequence. Sending it here too causes a double-STARTUP
                        # that overwhelms the radio (RIGHT VFO goes dead).
                        continue
                    else:
                        response += response2
                else:
                    print(f"RCVD:{{{message}}}")
                    response = f"RCVD{{{message}}}"

                # TODO: Handle CAT command here and generate a response
                response += "\n"
                writer.write(response.encode())
                await writer.drain()
        except asyncio.CancelledError:
            print(f"Connection to {addr} cancelled.")
            self.tcpserver_ready = False
        finally:
            print(f"Connection closed: {addr}")
            try:

                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass
            except:
                None

    async def start_tcp_server(self, host='0.0.0.0', port=24, password="", protocol=None):
        self.tcpserver_passw = password
        server = await asyncio.start_server(self.handle_tcpserver_stream, host, port)
        addr = server.sockets[0].getsockname()
        print(f"CAT TCP server running on {addr}")
        self.tcpserver_ready = True
        self.tcpserver_server = server
        async with server:
            await server.serve_forever()
        print("Server has stopped...")
        self.tcpserver_ready = False

    async def handle_tcpclient_stream(self, reader, writer, protocol):
        addr = writer.get_extra_info('peername')
        print(f"Connected to {addr}")
        dpg_notification_window("TCP Server Connection", f"Connected to TCP server {addr} successfully!")

        self.tcpclient = writer

        writer.write(f"!pass {self.tcpclient_passw}\n".encode())
        await writer.drain()

        try:
            while True:
                data = await reader.readline()

                if not data:
                    break  # connection closed

                printd(f"Data RCVD: {type(data)} /// {data}")
                data = data[0:-1] #Pull new line character off the end
                
                if type(data) == bytearray or type(data) == bytes: #Data received is a radio packet
                    if data.find(b'\xAA\xFD') != -1:
                        printd(f"Data RCVD(hex): {data.hex().upper()}")
                        protocol.data_received(data=data)
                        continue
                try:
                    message = data.decode().strip()
                except:
                    continue

                if message == None or message == "":
                    continue

                if message[0] == "!":
                    data = message.find(" ")
                    if data != -1:
                        cmd = str(message[1:data])
                        data = str(message[data+1::])
                        print(f"CMD RCVD:{cmd}:{data}")
                        response = f"CMD{{{cmd}[{data}]}} "
                    else:
                        cmd = str(message[1::])
                        data = ""
                        print(f"CMD RCVD:{cmd}")
                        response = f"CMD{{{cmd}}} "
                elif message[0:3] == "CMD":
                    cmd = message[message.find("{")+1:message.find("}")]
                    data = message.split(" ")[1]
                    print(f"CMD:{{{cmd}}} DATA:{{{data}}}")
                    match cmd:
                        case "exit":
                            self.tcpclient_server_stop = True
                            break
                        case "rts":
                            if dpg:
                                protocol.radio.show_rts_state(data == "True")
                        case "dtr":
                            if dpg:
                                protocol.radio.show_dtr_state(data == "True")
                    continue
                else:
                    print(f"RCVD:{message}")
                    continue
        except (asyncio.IncompleteReadError, ConnectionResetError):
            self.tcpclient = None
            self.tcpclient_ready = False
            print("[Protocol] Disconnected.")
        finally:
            print(f"Connection closed: {addr}")
            if TCP.tcpclient != None:
                sleep(2)
                if TCP.tcpclient_future != None and not TCP.tcpclient_future.done():
                    TCP.tcpclient_future.cancel()
                if read_loop_future != None and not read_loop_future.done():
                    read_loop_future.cancel()
                if write_loop_future != None and not write_loop_future.done():
                    write_loop_future.cancel()
            self.tcpclient = None
            self.tcpclient_ready = False
            writer.close()
            await writer.wait_closed()

    async def start_tcp_client(self, host='127.0.0.1', port=2235, password="", protocol=None):
        while not self.tcpclient_server_stop:
            try:
                reader, writer = await asyncio.open_connection(host, port)
                print(f"[Protocol] Connected to {host}:{port}")
                self.tcpclient_ready = True
                await self.handle_tcpclient_stream(reader, writer, protocol)
            except Exception as e:
                print(f"[Protocol] Connection failed: {e}")
                await asyncio.sleep(5)
                return
        self.tcpclient_server_stop = False

TCP = TCP()

class SerialProtocol(asyncio.Protocol):
    def __init__(self, radio: SerialRadio):
        self.transport = None
        self.ready = asyncio.Event()
        self.receive_queue = asyncio.Queue()
        self.transmit_queue = asyncio.Queue()
        self.buffer = bytearray()
        self.radio = radio
        self._read_task = None
        self._write_task = None

    RTS_STATE_FILE = '/tmp/th9800_rts_state'

    def _save_rts_state(self, state):
        """Persist RTS state so it survives restarts."""
        try:
            with open(self.RTS_STATE_FILE, 'w') as f:
                f.write('1' if state else '0')
        except Exception:
            pass

    @staticmethod
    def _load_rts_state():
        """Load saved RTS state. Returns True (USB Controlled) if no saved state."""
        try:
            with open(SerialProtocol.RTS_STATE_FILE, 'r') as f:
                return f.read().strip() == '1'
        except Exception:
            return True  # default: USB Controlled

    def set_rts(self, state: bool):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!rts {state}".encode())
        else:
            printd(f"RTS state: {self.transport.serial.rts} Setting to {state}")
            self.transport.serial.rts = state
            self._save_rts_state(state)
        self.radio.show_rts_state(state)

    def toggle_rts(self):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!rts".encode())
            return
        else:
            state = not self.transport.serial.rts  #Toggle state
            self.transport.serial.rts = state
            self._save_rts_state(state)
        self.radio.show_rts_state(state)

    def set_dtr(self, state: bool):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!dtr {state}".encode())
        else:
            printd(f"DTR state: {self.transport.serial.dtr} Setting to {state}")
            self.transport.serial.dtr = state
        self.radio.show_dtr_state(state)

    def toggle_dtr(self):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!dtr".encode())
            return
        else:
            state = not self.transport.serial.dtr  #Toggle state
            printd(f"DTR state: {self.transport.serial.dtr} Setting to {state}")
            self.transport.serial.dtr = state
        self.radio.show_dtr_state(state)

    def reset_ready(self):
        self.ready = asyncio.Event()  # Binds to current event loop

    def connection_made(self, transport):
        self.transport = transport
        printd("Connection opened")
        self.ready.set()

    def xor_checksum(self, data):
        cs = 0
        for b in data:
            cs ^= b
        return cs

    def data_received(self, data):
        self.buffer.extend(data)

        while True:
            start_index = self.buffer.find(b'\xAA\xFD')
            if start_index == -1: # No valid start byte found, discard junk before it
                if len(self.buffer) > 2:
                    del self.buffer[:-2]  # Keep last 2 bytes in case start sequence is split
                break

            # Wait for at least 4 bytes (start + length + checksum)
            if len(self.buffer) < start_index + 4:
                break

            length = self.buffer[start_index + 2]
            full_packet_size = 2 + 1 + length + 1  # Start + Len + Payload + Checksum

            if len(self.buffer) < start_index + full_packet_size:
                break # Full packet not yet received

            # Extract the full packet
            packet = self.buffer[start_index:start_index + full_packet_size]
            del self.buffer[:start_index + full_packet_size]

            # Verify checksum
            expected_cs = packet[-1]
            calculated_cs = self.xor_checksum(packet[2:-1])

            if calculated_cs == expected_cs:
                self.receive_queue.put_nowait(packet)
            else:
                printd(f"Checksum mismatch: expected {expected_cs:02X}, calculated {calculated_cs:02X}")
                # Optionally: log, raise alert, or resync buffer here

    def connection_lost(self, exc):
        if exc:
            print(f"Connection lost: {exc}")
        else:
            print("Connection closed")
        try:
            self.transport.serial.dtr = False
        except:
            pass
        self.ready.clear()
        # Cancel read/write loop tasks if they exist
        if hasattr(self, '_read_task') and self._read_task and not self._read_task.done():
            self._read_task.cancel()
        if hasattr(self, '_write_task') and self._write_task and not self._write_task.done():
            self._write_task.cancel()
        # Update UI to reflect disconnected state
        show_serial_disconnected_ui(self.radio)

    def send_packet(self, data: bytes):
        if (self.transport and not self.transport.is_closing()) or TCP.tcpclient_ready == True:
            printd(f"Sending: {data.hex().upper()}")
            self.transmit_queue.put_nowait(data)
            #self.transport.write(data)
        else:
            print("Transport is not available or already closed.")

def tcp_connect_callback(sender, app_data, user_data):
    global TCP,read_loop_future,write_loop_future
    host = dpg.get_value("tcp_host_text")
    port = dpg.get_value("tcp_port_text")
    password = dpg.get_value("tcp_pass_text")
    protocol = user_data['protocol']
    label = user_data['label']

    if password == None:
        password = ""

    save_tcp_settings()

    if label == "Start Server":
        tag = "tcp_startserver_button"
        label = dpg.get_item_label(tag)

        if label == "Start Server":
            TCP.tcpserver_future = asyncio.run_coroutine_threadsafe(
                TCP.start_tcp_server(host=host, port=port, password=password, protocol=protocol),
                loop
            )

            dpg.configure_item(tag, label="Stop Server")
            show_rts_dtr_controls(True)
            dpg.configure_item("tcp_connect_button", show=False)
            dpg.configure_item(tag, show=True)
            dpg.configure_item("connection_window", collapsed=True)
        else:
            if TCP.tcpserver != None:
                try:
                    TCP.tcpserver.close()
                    TCP.tcpserver_ready = False
                    TCP.tcpserver_server.close()
                    asyncio.run_coroutine_threadsafe(TCP.tcpserver_server.wait_closed(), loop)
                    asyncio.run_coroutine_threadsafe(TCP.tcpserver.wait_closed(), loop)
                    if TCP.tcpserver_future != None and not TCP.tcpserver_future.done():
                        TCP.tcpserver_future.cancel()
                except:
                    None
            
            dpg.configure_item("tcp_connect_button", label="Start Server")
            show_rts_dtr_controls(False)
            dpg.configure_item("tcp_connect_button", show=True)
            dpg.configure_item("tcp_startserver_button", show=True)
    elif label == "Connect Host":
        tag = "tcp_connect_button"
        label = dpg.get_item_label(tag)
        TCP.tcpclient_passw = password

        if label == "Connect Host":
            read_loop_future = asyncio.run_coroutine_threadsafe(
                read_loop(protocol),
                loop
            )
            write_loop_future = asyncio.run_coroutine_threadsafe(
                write_loop(protocol),
                loop
            )
            TCP.tcpclient_future = asyncio.run_coroutine_threadsafe(
                TCP.start_tcp_client(host=host, port=port, password=password, protocol=protocol),
                loop
            )

            dpg.configure_item(tag, label="Disconnect Host")
            show_rts_dtr_controls(True)
            dpg.configure_item(tag, show=True)
            dpg.configure_item("tcp_startserver_button", show=False)
            dpg.configure_item("connection_window", collapsed=True)
        else:
            if TCP.tcpclient != None:
                protocol.transmit_queue.put_nowait(f"!exit".encode())
                sleep(2)
            if TCP.tcpclient_future != None and not TCP.tcpclient_future.done():
                TCP.tcpclient_future.cancel()
            if read_loop_future != None and not read_loop_future.done():
                read_loop_future.cancel()
            if write_loop_future != None and not write_loop_future.done():
                write_loop_future.cancel()

            dpg.configure_item("tcp_connect_button", label="Connect Host")
            show_rts_dtr_controls(False)
            dpg.configure_item("tcp_connect_button", show=True)

            dpg.configure_item("tcp_startserver_button", show=True)

def refresh_comports_callback(sender, app_data, user_data):
    ports = []
    available_ports = serial.tools.list_ports.comports()
    for port in available_ports:
        ports.append(f"{port.device}: {port.description}")
        printd(f"{port.device} - {port.manufacturer} - {port.description}")
    dpg.configure_item("comport", items=ports)
    dpg.configure_item("comport", default_value=ports[0] if available_ports else "")

def show_rts_dtr_controls(show: bool):
    dpg.configure_item("rts_button", show=show)
    dpg.configure_item("dtr_button", show=show)
    dpg.configure_item("rts_text", show=show)
    dpg.configure_item("rts_label", show=show)
    dpg.configure_item("fp_rts_button", show=show)
    dpg.configure_item("fp_rts_text", show=show)
    dpg.configure_item("fp_rts_label", show=show)

def show_serial_connected_ui(radio):
    """Show the RTS/DTR controls and flip the connect button to "Disconnect"."""
    if not radio.dpg_enabled:
        return
    dpg.configure_item("connect_button", label="Disconnect")
    show_rts_dtr_controls(True)

def show_serial_disconnected_ui(radio):
    """Hide the RTS/DTR controls and flip the connect button to "Connect"."""
    if not radio.dpg_enabled:
        return
    try:
        dpg.configure_item("connect_button", label="Connect")
        show_rts_dtr_controls(False)
    except:
        pass  # UI items may not exist yet

def cancel_callback(sender, app_data, user_data):
    modal_id = user_data[0] if isinstance(user_data, tuple) else user_data
    dpg.delete_item(modal_id)

def dpg_notification_window(title, message):
    with dpg.window(label=title, modal=True, no_close=True, pos=[22, 100]) as modal_id:
        dpg.add_text(message, wrap=500)
        dpg.add_button(label="Ok", width=75, user_data=(modal_id), callback=cancel_callback)

def button_callback(sender, app_data, user_data):
    label = user_data["label"]
    vfo = user_data["vfo"]
    if vfo == RADIO_VFO.LEFT or vfo == RADIO_VFO.RIGHT or vfo == RADIO_VFO.MIC or vfo == RADIO_VFO.NONE:
        vfo_name = user_data["vfo"]
    else:
        vfo_name = user_data["vfo"]
    protocol = user_data["protocol"]
    radio = protocol.radio

    if label == "Toggle RTS":
        protocol.toggle_rts()
        return
    elif label == "Toggle DTR":
        protocol.toggle_dtr()
        return
    elif label == "Enable Debug":
        debug_label = dpg.get_item_label("debug_button")
        if debug_label == "Enable Debug":
            radio_protocol.debug = True
            dpg.configure_item("debug_button", label="Disable Debug")
            return
        elif debug_label == "Disable Debug":
            radio_protocol.debug = False
            dpg.configure_item("debug_button", label="Enable Debug")
            return

    match label.upper():
        case "SINGLE VFO":
            radio.exe_cmd(cmd=RADIO_TX_CMD.get('L_VOLUME_HOLD'))
            return
        case "GET STATE":
            dpg_notification_window(title="Radio State", message=radio.vfo_memory)
            #radio.get_freq(vfo=RADIO_VFO.LEFT)
            #radio.get_freq(vfo=RADIO_VFO.RIGHT)
            return
        case "SET FREQ":
            if radio.vfo_memory[radio.vfo_memory['vfo_active']]['operating_mode'] == int(RADIO_VFO_TYPE.MEMORY):
                return
            freq = dpg.get_value("setfreq_text").replace(".","").replace("*","").replace("+","").replace("-","").replace("/","")
            if len(freq) < 6:
                freq = f"0{freq}"
            if len(freq) > 6:
                freq = freq[0:6]
                dpg.set_value("setfreq_text",freq)
            if len(freq) < 6:
                return
            printd(f"Set Freq: {freq}")
            radio.set_freq(vfo=radio.vfo_memory['vfo_active'],freq=freq)
            return
        case "VM":
            radio.switch_vfo_op_mode(vfo=vfo)
        case "PTT":
            if radio.mic_ptt == False:
                radio.mic_ptt = True
                radio.vfo_memory[radio.vfo_memory['vfo_active']]['ptt'] = 1
            else:
                radio.mic_ptt = False
                radio.vfo_memory[radio.vfo_memory['vfo_active']]['ptt'] = 0
        case "*":
            label = "STAR"
        case "#":
            label = "POUND"

    if vfo == RADIO_VFO.LEFT or vfo == RADIO_VFO.RIGHT or vfo == RADIO_VFO.MIC or vfo == RADIO_VFO.NONE:
        if len(label) > 2 and label[-1] == "2":
            label = label.replace("2","_HOLD")
        radio.exe_cmd(cmd=RADIO_TX_CMD.get(f"{vfo_name}_{label}"))
    else:
        match label:
            case "HA"|"HB"|"HC"|"HD"|"HE"|"HF":
                radio.exe_cmd(cmd=RADIO_TX_CMD.get(f"HYPER_{label.replace('H','')}"))

    printd(f"Sent {label} button command for {vfo_name} VFO.") #: {packet.hex().upper()}")

def sq_callback(sender, app_data, user_data):
    label = user_data["label"].replace("/","")
    vfo = user_data["vfo"]
    protocol = user_data["protocol"]
    radio = protocol.radio
    
    radio.set_squelch(vfo=vfo,sq=app_data)

def vol_callback(sender, app_data, user_data):
    label = user_data["label"].replace("/","")
    vfo = user_data["vfo"]
    protocol = user_data["protocol"]
    radio = protocol.radio
    
    radio.set_volume(vfo=vfo,vol=app_data)

async def connect_serial_async(protocol, comport, baudrate, auto_dismiss=False):
    global TCP

    radio = protocol.radio
    transport = None

    try:
        if TCP.tcpclient_ready == False:
            transport, _ = await serial_asyncio.create_serial_connection(
                asyncio.get_event_loop(), lambda: protocol, comport, baudrate=baudrate
            )
            await protocol.ready.wait()
            protocol.set_dtr(True)
            # Restore saved RTS state (persists across restarts)
            saved_rts = SerialProtocol._load_rts_state()
            protocol.transport.serial.rts = saved_rts
            protocol.set_rts(saved_rts)  # update UI to match
            await asyncio.sleep(0.5)

        show_serial_connected_ui(radio)
        if radio.dpg_enabled == True:
            dpg.configure_item("radio_window", show=True)
            dpg.configure_item("connection_window", collapsed=True)
        protocol._read_task = asyncio.create_task(read_loop(protocol))
        protocol._write_task = asyncio.create_task(write_loop(protocol))
        if TCP.tcpclient_ready == False:
            radio.connect_process = True

            # Only send STARTUP — the radio's STARTUP_2 response handler
            # automatically sends L/R_VOLUME_SQUELCH internally, so sending
            # them here too creates a command storm that locks up the serial
            radio.exe_cmd(cmd=RADIO_TX_CMD.STARTUP)

        cat_controller = CATController(radio=radio)
        radio.cat = cat_controller
        rigctl_server = RigctlServer(cat_controller)

        if radio.rigctl_server == True:
            dpg.configure_item("getstate_button", show=True)
            radio.get_freq(vfo=RADIO_VFO.LEFT)
            radio.get_freq(vfo=RADIO_VFO.RIGHT)
            await rigctl_server.start()

        await asyncio.sleep(2)

        return transport
    except Exception as e:
        print(f"Connection failed: {e}")
        if auto_dismiss:
            print(f"Auto-connect skipped: {comport} not available")
        elif radio.dpg_enabled == True:
            with dpg.window(label="Connection Failed", modal=True, no_close=True) as modal_id:
                dpg.add_text(e, wrap=300)
                dpg.add_button(label="Ok", width=75, user_data=(modal_id, True), callback=cancel_callback)
            dpg.set_item_pos(modal_id, [120, 100])
        return None

def port_selected_callback(sender, app_data, user_data):
    if len(user_data["available_ports"]) == 0:
        dpg_notification_window(title="Error", message="No COM ports available for connection!")
        return

    label = dpg.get_item_label("connect_button")
    
    protocol = user_data['protocol']
    radio = protocol.radio
    comport = dpg.get_value("comport")
    baudrate = dpg.get_value("baud_rate")
    
    if label == "Disconnect":
        # Cancel read/write loops before closing transport
        if protocol._read_task and not protocol._read_task.done():
            protocol._read_task.cancel()
        if protocol._write_task and not protocol._write_task.done():
            protocol._write_task.cancel()
        protocol._read_task = None
        protocol._write_task = None
        try:
            protocol.transport.serial.dtr = False
        except:
            pass
        protocol.transport.close()
        protocol.ready.clear()
        # Drain any stale data from queues
        while not protocol.receive_queue.empty():
            try: protocol.receive_queue.get_nowait()
            except: break
        while not protocol.transmit_queue.empty():
            try: protocol.transmit_queue.get_nowait()
            except: break
        protocol.buffer.clear()
        print(f"{comport} disconnected.\n")
        show_serial_disconnected_ui(radio)
        return

    try:
        comport = comport[0:comport.index(":")]
    except:
        with dpg.window(label="Error", modal=True, no_close=True) as modal_id:
            dpg.add_text("Error occured connecting to COM port!")
            dpg.add_button(label="Ok", width=75, user_data=(modal_id, True), callback=cancel_callback)
        dpg.set_item_pos(modal_id, [120, 100])
        return

    save_serial_settings()

    if not loop.is_running():
        threading.Thread(target=start_event_loop, daemon=True).start()
    protocol.reset_ready()

    asyncio.run_coroutine_threadsafe(
        connect_serial_async(protocol, comport, baudrate),
        loop
    )

async def run_dpg():
    while dpg.is_dearpygui_running():
        dpg.render_dearpygui_frame()
        await asyncio.sleep(1/60)

async def read_loop(protocol: SerialProtocol):
    global TCP
    try:
        while True:
            packet = await protocol.receive_queue.get()

            if TCP.tcpserver_ready == True and TCP.tcpserver != None:
                try:
                    TCP.tcpserver.write(packet+b'\n')
                    await TCP.tcpserver.drain()
                except Exception as e:
                    printd(f"Read loop TCP write error: {e}")
                packet_processor = SerialPacket(protocol=protocol).process_rx_packet(packet=packet)
            else:
                printd(f"Read loop: no TCP (ready={TCP.tcpserver_ready}, server={TCP.tcpserver is not None}), pkt={packet[:6].hex()}")
                packet_processor = SerialPacket(protocol=protocol).process_rx_packet(packet=packet)
    except asyncio.CancelledError:
        print("Read loop cancelled")
    except Exception as e:
        print(f"Read loop error: {e}")
        import traceback; traceback.print_exc()

async def write_loop(protocol: SerialProtocol):
    global TCP

    try:
        while True:
            if TCP.tcpclient_ready == True and TCP.tcpclient != None:
                try:
                    data = await asyncio.wait_for(protocol.transmit_queue.get(), timeout=.10)
                    printd(f"Send pkt tcp: {data}:{type(data)}")
                    TCP.tcpclient.write(data+b'\n')
                    await TCP.tcpclient.drain()
                    if data.hex().find("aafd0c84ffffffff") == -1: #If match sq/vol cmd skip sleep
                        await asyncio.sleep(0.15)
                except asyncio.TimeoutError:
                    pass  # Normal timeout, no data to send
                except (ConnectionError, OSError) as e:
                    print(f"Write loop TCP error: {e}")
                    break
            else:
                try:
                    data = await asyncio.wait_for(protocol.transmit_queue.get(), timeout=.10) #FIX FOR LINUX FREEZES ON TRANSMIT (Old: #data = await protocol.transmit_queue.get())
                    if protocol.transport and not protocol.transport.is_closing():
                        protocol.transport.write(data)
                    else:
                        print("Write loop: transport closed, stopping")
                        break
                    if data.hex().find("aafd0c84ffffffff") == -1: #If match sq/vol cmd skip sleep
                        await asyncio.sleep(0.15)
                except asyncio.TimeoutError:
                    pass  # Normal timeout, no data to send
                except (ConnectionError, OSError, serial.SerialException) as e:
                    print(f"Write loop serial error: {e}")
                    break
    except asyncio.CancelledError:
        print("Write loop cancelled")

def handle_key_press(sender, app_data):
    global protocol
    user_data = None
    radio = protocol.radio
    active_vfo = radio.vfo_memory["vfo_active"]
    printd(f"Key Pressed: {app_data}")  # app_data is the key code

    match app_data:
        case dpg.mvKey_Spacebar:
            user_data={"label": "PTT", "protocol": protocol, "vfo": RADIO_VFO.MIC}
        case dpg.mvKey_Up:
            vol = radio.vfo_memory[active_vfo]['volume'] + 2
            radio.set_volume(vfo=active_vfo,vol=vol)
        case dpg.mvKey_Down:
            vol = radio.vfo_memory[active_vfo]['volume'] - 2
            radio.set_volume(vfo=active_vfo,vol=vol)
        case dpg.mvKey_Left:
            sq = radio.vfo_memory[active_vfo]['squelch'] - 2
            radio.set_squelch(vfo=active_vfo,sq=sq)
        case dpg.mvKey_Right:
            sq = radio.vfo_memory[active_vfo]['squelch'] + 2
            radio.set_squelch(vfo=active_vfo,sq=sq)
        case _:
            user_data = None

    if user_data != None:
        button_callback(sender=None,app_data=None,user_data=user_data)

def build_gui(protocol):
    ports = []
    available_ports = serial.tools.list_ports.comports()
    for port in available_ports:
        ports.append(f"{port.device}: {port.description}")
        printd(f"{port.device} - {port.manufacturer} - {port.description}")

    with dpg.theme() as black_text_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (37, 37, 38, 255)) #(255, 0, 0, 255) (37, 37, 38, 255)

    font_dir = os.path.join(os.path.dirname(__file__), "Assets", "Fonts")
    bold_font_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")

    with dpg.font_registry():
        bold_font = dpg.add_font(bold_font_path, 18)

    with dpg.window(tag="radio_window", show=True, label="Radio Front Panel", width=580, height=605, pos=[0,20], no_move=True, no_resize=True, no_close=True, user_data={"protocol": protocol}):
        # === RTS TX Control ===
        with dpg.group(horizontal=True):
            dpg.add_text("RTS TX: ", indent=5, tag="fp_rts_label", show=False)
            dpg.add_text("USB Controlled", tag="fp_rts_text", show=False)
            protocol.radio.set_dpg_theme(tag="fp_rts_text", color="green")
            dpg.add_button(label="Toggle RTS", tag="fp_rts_button", show=False, indent=350, width=100, callback=button_callback, user_data={"label": "Toggle RTS", "protocol": protocol, "vfo": RADIO_VFO.NONE})
        dpg.add_spacer(height=3)
        dpg.add_separator()
        dpg.add_spacer(height=5)

        # === Hyper Mem Buttons A-F ===
        with dpg.group(horizontal=True):
            dpg.add_text("Hyper Memories: ", indent=15)
            for label in ["A", "B", "C", "D", "E", "F"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": f"H{label}", "protocol": protocol, "vfo": RADIO_VFO.NONE})
            dpg.add_spacer(width=10)
            dpg.add_button(label="Single VFO", width=90, callback=button_callback, user_data={"label": "Single VFO", "protocol": protocol, "vfo": RADIO_VFO.NONE})
        dpg.add_spacer(height=5)
        dpg.add_separator()

        # === PREF/SKIP Channel Icons ===
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=60)
            for label in ["PREF", "SKIP"]:
                label_lower = label.lower()
                tag = f"icon_l_{label_lower}"
                dpg.add_text(label, tag=tag)#, show=False)
                dpg.bind_item_theme(tag, black_text_theme)
            
            dpg.add_spacer(width=195)
            
            for label in ["PREF", "SKIP"]:
                label_lower = label.lower()
                tag = f"icon_r_{label_lower}"
                dpg.add_text(label, tag=tag)#, show=False)
                dpg.bind_item_theme(tag, black_text_theme)

        # === VFO Channel Icons ===
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=20)
            for label in ["ENC", "DEC", "POS", "NEG", "TX", "MAIN"]:
                label_lower = label.lower()
                tag = f"icon_l_{label_lower}"
                if label == "POS":
                    label = "+"
                elif label == "NEG":
                    label = "-"
                dpg.add_text(label, tag=tag)#, show=False)
                dpg.bind_item_theme(tag, black_text_theme)
                #dpg.hide_item(tag)
                dpg.add_spacer(width=1)

            dpg.add_spacer(width=67)

            for label in ["ENC", "DEC", "POS", "NEG", "TX", "MAIN"]:
                label_lower = label.lower()
                tag = f"icon_r_{label_lower}"
                if label == "POS":
                    label = "+"
                elif label == "NEG":
                    label = "-"
                dpg.add_text(label,tag=tag)#, show=False)
                dpg.bind_item_theme(tag, black_text_theme)
                #dpg.hide_item(tag)
                dpg.add_spacer(width=1)

        dpg.add_spacer(height=2)
        
        # === VFO Channel # Displays ===
        with dpg.group(horizontal=True):
            dpg.add_text("CH:", indent=31)
            dpg.add_input_text(tag="ch_l_display", readonly=True, width=100, default_value="")
            dpg.add_button(label="UP", width=40, callback=button_callback, user_data={"label": f"DIAL_RIGHT", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=83)
            dpg.add_text("CH:")
            dpg.add_input_text(tag="ch_r_display", readonly=True, width=100, default_value="")
            dpg.add_button(label="UP", width=40, callback=button_callback, user_data={"label": f"DIAL_RIGHT", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
            
        # === VFO CH Name/Frequency Displays ===
        with dpg.group(horizontal=True):
            dpg.add_text("VFO L:", indent=10)
            dpg.add_input_text(tag="vfo_l_display", readonly=True, width=100, default_value="")
            dpg.add_button(label="DOWN", width=40, callback=button_callback, user_data={"label": f"DIAL_LEFT", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_button(label="SEL", width=40, callback=button_callback, user_data={"label": f"DIAL_PRESS", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=14)
            dpg.add_text("VFO R:")
            dpg.add_input_text(tag="vfo_r_display", readonly=True, width=100, default_value="")
            dpg.add_button(label="DOWN", width=40, callback=button_callback, user_data={"label": f"DIAL_LEFT", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
            dpg.add_button(label="SEL", width=40, callback=button_callback, user_data={"label": f"DIAL_PRESS", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})

        dpg.add_spacer(height=2)

        with dpg.group(horizontal=True):
            dpg.add_spacer(width=20)
            for label in ["MT", "MUTE", "DCS", "AM", "L", "M", "H"]:
                label_lower = label.lower()
                tag = f"icon_l_{label_lower}"
                dpg.add_text(label, tag=tag)#, show=False)
                dpg.bind_item_theme(tag, black_text_theme)
                dpg.add_spacer(width=1)

            dpg.add_spacer(width=53)
            for label in ["MT", "MUTE", "DCS", "AM", "L", "M", "H"]:
                label_lower = label.lower()
                tag = f"icon_r_{label_lower}"
                dpg.add_text(label, tag=tag)#, show=False)
                dpg.bind_item_theme(tag, black_text_theme)
                dpg.add_spacer(width=1)

        dpg.add_spacer(height=3)

        # === VFO Volume + Squelch Sliders ===
        with dpg.group(horizontal=True):
            dpg.add_text("SQ:",indent=32)
            dpg.add_slider_int(tag="slider_l_squelch", width=100, default_value=25, max_value=100, callback=sq_callback, user_data={"label": "SQ", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=61)
            dpg.add_text("APO", tag="icon_apo")#, show=False)
            dpg.bind_item_theme("icon_apo", black_text_theme)
            #dpg.add_text("LOCK", tag="icon_lock")#, show=False)
            #dpg.bind_item_theme("icon_lock", black_text_theme)
            dpg.add_spacer(width=32)
            dpg.add_text("SQ:")
            dpg.add_slider_int(tag="slider_r_squelch", width=100, default_value=25, max_value=100, callback=sq_callback, user_data={"label": "SQ", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
        
        with dpg.group(horizontal=True):
            dpg.add_text("VOL:",indent=25)
            dpg.add_slider_int(tag="slider_l_volume", width=100, default_value=25, max_value=100, callback=vol_callback, user_data={"label": "VOL", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=58)
            dpg.add_text("LOCK", tag="icon_lock")#, show=False)
            dpg.bind_item_theme("icon_lock", black_text_theme)
            dpg.add_spacer(width=21)
            dpg.add_text("VOL:")
            dpg.add_slider_int(tag="slider_r_volume", width=100, default_value=25, max_value=100, callback=vol_callback, user_data={"label": "VOL", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
        
        dpg.add_spacer(height=15)

        # === VFO Control Buttons + Center Menu Button ===
        with dpg.group(horizontal=True):
            # VFO Left Buttons
            dpg.add_spacer(width=10)
            for label in ["LOW", "V/M", "HM", "SCN"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label.replace("/",""), "protocol": protocol, "vfo": RADIO_VFO.LEFT})

            dpg.add_spacer(width=10)

            # Center Menu Button
            label = "."
            dpg.add_button(label=label, width=40, height=20, callback=button_callback, user_data={"label": "SET", "protocol": protocol, "vfo": RADIO_VFO.NONE})

            dpg.add_spacer(width=10)

            # VFO Right Buttons
            for label in ["LOW", "V/M", "HM", "SCN"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label.replace("/",""), "protocol": protocol, "vfo": RADIO_VFO.RIGHT})

            dpg.add_text("<KEY2", tag="icon_key2")#, show=False)
            dpg.bind_item_theme("icon_key2", black_text_theme)
        #dpg.add_spacer(height=5)

        # === VFO Control Buttons + Center Menu Button (HOLD Key Function) ===
        with dpg.group(horizontal=True):
            # VFO Left Buttons
            dpg.add_spacer(width=10)
            for label in ["LOW2", "V/M2", "HM2", "SCN2"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label.replace("/",""), "protocol": protocol, "vfo": RADIO_VFO.LEFT})

            dpg.add_spacer(width=10)

            # Center Menu Button
            label = ".2"
            dpg.add_button(label=label, width=40, height=20, callback=button_callback, user_data={"label": "SET2", "protocol": protocol, "vfo": RADIO_VFO.NONE})

            dpg.add_spacer(width=10)

            # VFO Right Buttons
            for label in ["LOW2", "V/M2", "HM2", "SCN2"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label.replace("/",""), "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
        dpg.add_spacer(height=5)
        
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=10)
            dpg.add_progress_bar(default_value=0.0, tag="icon_l_signal", overlay="S0", width=185)
            dpg.add_spacer(width=18)
            dpg.add_text("SET", tag="icon_set")#, show=False)
            dpg.bind_item_theme("icon_set", black_text_theme)
            dpg.add_spacer(width=21)
            dpg.add_progress_bar(default_value=0.0, tag="icon_r_signal", overlay="S0", width=185)

        dpg.add_spacer(height=30)
        dpg.add_separator()
        dpg.add_spacer(height=10)

        # === MICROPHONE Keypad ===
        mic_spacer_width = 20
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["1", "2", "3", "A"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol,"vfo": RADIO_VFO.MIC})
            dpg.add_spacer(width=130)
            dpg.add_button(label="Set Freq", width=80, callback=button_callback, user_data={"label": "Set Freq", "protocol": protocol,"vfo": RADIO_VFO.NONE})
            dpg.add_input_text(tag="setfreq_text", decimal=True, no_spaces=True, width=80, default_value="")
            #protocol.radio.set_dpg_theme_background(tag="setfreq_text",color="darkgray")
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["4", "5", "6", "B"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.MIC})
            dpg.add_spacer(width=130)
            dpg.add_button(label="Get State", tag="getstate_button", width=80, show=True, callback=button_callback, user_data={"label": "Get State", "protocol": protocol,"vfo": RADIO_VFO.NONE})
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["7", "8", "9", "C"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.MIC})
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["*", "0", "#", "D"]:
                if label == "#":
                    label = " # "
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label.replace(" ",""), "protocol": protocol, "vfo": RADIO_VFO.MIC})
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["P1", "P2", "P3", "P4"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.MIC})

        dpg.add_button(label="PTT", pos=(0,443), width=60, height=60, indent=255, callback=button_callback, user_data={"label": "PTT", "protocol": protocol, "vfo": RADIO_VFO.MIC})

     # === Connection Window ===
    with dpg.window(label="Connection", width=660, height=620, tag="connection_window", no_move=True, no_resize=True, no_close=True):
        dpg.add_spacer(height=5)
        with dpg.group(horizontal=True):
            dpg.add_combo(
                    indent=5,
                    tag="comport",
                    items=ports,
                    label="Select Port",
                    default_value=ports[0] if available_ports else ""
                )
        dpg.add_spacer(height=5)
        
        # === Baud Rate Selector ===
        with dpg.group(horizontal=True):
            dpg.add_text("Baud Rate:", indent=5)
            dpg.add_combo(
                tag="baud_rate",
                items=["4800", "9600", "19200", "38400", "57600", "115200"],
                default_value="19200",
                width=100
            )
            dpg.add_spacer(width=85)
            dpg.add_button(label="Refresh COM Ports", width=150, callback=refresh_comports_callback)
        dpg.add_spacer(height=15)
        
        with dpg.group(horizontal=True):
            # dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
            comport = ""
            baudrate = ""
            comport = dpg.get_value("comport")
            baudrate = dpg.get_value("baud_rate")

            dpg.add_button(label="Connect", tag="connect_button", indent=5, width=100, callback=port_selected_callback, user_data={"available_ports": available_ports, "comport": comport, "baudrate": baudrate, "protocol": protocol})
            dpg.add_button(label="Toggle RTS", tag="rts_button", show=False, width=100, callback=button_callback, user_data={"label": "Toggle RTS", "protocol": protocol, "vfo": RADIO_VFO.NONE})
            dpg.add_button(label="Enable Debug", tag="debug_button", indent=284, show=True, width=120, callback=button_callback, user_data={"label": "Enable Debug", "protocol": protocol, "vfo": RADIO_VFO.NONE})

        #dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Toggle DTR", tag="dtr_button", indent=284, show=False, width=120, callback=button_callback, user_data={"label": "Toggle DTR", "protocol": protocol, "vfo": RADIO_VFO.NONE})

        dpg.add_spacer(height=15)
        with dpg.group(horizontal=True):
            dpg.add_text("RTS TX: ", indent=5, tag="rts_label", show=False)
            dpg.add_text("USB Controlled", tag="rts_text", show=False)
            protocol.radio.set_dpg_theme(tag="rts_text",color="green")

        dpg.add_spacer(height=50)
        with dpg.group(horizontal=False):
            dpg.add_text("TCP Client/Server Connection", tag="tcp_client_connection", indent=5, show=True)
            dpg.bind_item_font("tcp_client_connection",bold_font)
        
        dpg.add_spacer(height=5)
        with dpg.group(horizontal=True):
            dpg.add_text("Host/IP:", tag="tcp_host", indent=5, show=True)
            dpg.add_input_text(tag="tcp_host_text", no_spaces=True, indent=75, width=130, default_value="")
        
        with dpg.group(horizontal=True):
            dpg.add_text("Port:", tag="tcp_port", indent=5, show=True)
            dpg.add_input_text(tag="tcp_port_text", no_spaces=True, indent=75, width=130, default_value="")

        with dpg.group(horizontal=True):
            dpg.add_text("Password:", tag="tcp_password", indent=5, show=True)
            dpg.add_input_text(tag="tcp_pass_text", indent=75, width=130, default_value="")

        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Connect Host", tag="tcp_connect_button", indent=5, width=120, callback=tcp_connect_callback, user_data={"protocol": protocol, "label": "Connect Host"})
            dpg.add_button(label="Start Server", tag="tcp_startserver_button", width=120, callback=tcp_connect_callback, user_data={"protocol": protocol, "label": "Start Server"})
        
    with dpg.handler_registry():
        dpg.add_key_press_handler(callback=handle_key_press)

    # Load persistent settings from config file
    settings = load_config()
    dpg.set_value("baud_rate", settings["baud_rate"])
    dpg.set_value("tcp_host_text", settings["host"])
    dpg.set_value("tcp_port_text", settings["port"])
    dpg.set_value("tcp_pass_text", settings["password"])
    # Match saved device description against available ports
    device = settings["device"]
    if device:
        for p in ports:
            if device in p:
                dpg.set_value("comport", p)
                break
    return device

async def main():
    global TCP,protocol,is_user_admin
    parser = argparse.ArgumentParser(description="Example Python app with command-line arguments.")
    parser.add_argument('-b', '--baudrate', type=str, help='Radio Baudrate')
    parser.add_argument('-c', '--comport', type=str, help='Radio COM Port')
    parser.add_argument('-d', '--debug', action="store_true", help='Enable debug output')
    parser.add_argument('-l', '--list-comports', action="store_true", help='List available COM ports')
    parser.add_argument('-lo', '--log', action="store_true", help='Log radio packets')
    parser.add_argument('-p', '--server-password', type=str, help='Server login password')
    parser.add_argument('-sH', '--server-host-ip', type=str, help='Server hostname/ip')
    parser.add_argument('-sP', '--server-port', type=str, help='Server port')
    parser.add_argument('-s', '--start-server', action="store_true", help='Start server')
    args = parser.parse_args()

    radio = SerialRadio(dpg)
    protocol = SerialProtocol(radio)
    radio.protocol = protocol

    if args.debug:
        radio_protocol.debug = True

    if args.log:
        now = datetime.datetime.now()
        todate = now.strftime("%Y-%m-%d %H:%M:%S")
        radio_protocol.log = True
        logging.basicConfig(filename='TH9800_CAT.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.info(f"\n*****TH9800_CAT app started: {todate}*****")

    if args.list_comports:
        available_ports = serial.tools.list_ports.comports()
        for port in available_ports:
            print(f"{port.device}: {port.description}")
        return

    if args.server_port:
        if int(args.server_port) < 1024 and is_user_admin == False and platform.system() == "Linux":
            print("Ports below 1024 require admin privileges")
            exit()

    if args.start_server:
        if args.comport and args.baudrate:
            if args.server_password is not None:
                password = args.server_password
            else:
                print("*Enter password for CAT server*")
                password = getpass()
                if password == None:
                    password = ""
            radio.dpg_enabled = False
            print("\nStarting command line server...")

            # Single-loop headless: main() runs on the module-level `loop`
            # (see __main__), so the TCP server, shutdown event, and serial
            # callbacks all share one event loop. Earlier versions spun a
            # second loop via asyncio.run() which meant the signal handler
            # set the event on the wrong loop — shutdown hung until SIGKILL.
            tcp_task = asyncio.create_task(
                TCP.start_tcp_server(
                    host=args.server_host_ip, port=args.server_port,
                    password=password, protocol=protocol))

            while TCP.tcpserver_ready == False:
                await asyncio.sleep(0.1)

            # Don't connect serial automatically — let the user connect
            # via the web UI "Connect" button (avoids STARTUP command storm
            # that locks up the radio's serial interface)
            print(f"TCP server ready — waiting for serial connect via web UI or TCP command")
            print(f"  Serial device: {args.comport} @ {args.baudrate}")

            # The shutdown Event lives on this (module) loop. The POSIX signal
            # handler is installed in __main__ on the main thread (add_signal_handler
            # can't be used here — main() runs on the loop's background thread) and
            # wakes us via loop.call_soon_threadsafe(_shutdown_event.set).
            global _headless_shutdown_event
            _headless_shutdown_event = asyncio.Event()

            try:
                await _headless_shutdown_event.wait()
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            finally:
                if protocol.transport and not protocol.transport.is_closing():
                    print("  Closing serial port...")
                    try:
                        protocol.transport.serial.dtr = False
                    except Exception:
                        pass
                    protocol.transport.close()
                if TCP.tcpserver_server is not None:
                    try:
                        TCP.tcpserver_server.close()
                        await TCP.tcpserver_server.wait_closed()
                    except Exception:
                        pass
                TCP.tcpserver_ready = False
                tcp_task.cancel()
                try:
                    await tcp_task
                except (asyncio.CancelledError, Exception):
                    pass
                print("  Headless server shut down cleanly.")
            return  # Skip GUI path below
        else:
            print("A COM Port and Baud Rate are required to start the command line server!")

    if radio.dpg_enabled == True:
        dpg.create_context()
        saved_device = build_gui(protocol)
        dpg.create_viewport(title="TYT TH9800 CAT Control", width=575, height=620, resizable=False)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        # Ensure event loop is running for auto-start features
        if not loop.is_running():
            threading.Thread(target=start_event_loop, daemon=True).start()

        # Auto-start TCP server if configured
        settings = load_config()
        if settings.get("auto_start_server", "").lower() != "false":
            tcp_host = dpg.get_value("tcp_host_text") or "0.0.0.0"
            tcp_port = dpg.get_value("tcp_port_text") or "9800"
            tcp_pass = dpg.get_value("tcp_pass_text") or ""
            TCP.tcpserver_future = asyncio.run_coroutine_threadsafe(
                TCP.start_tcp_server(host=tcp_host, port=tcp_port, password=tcp_pass, protocol=protocol),
                loop
            )
            dpg.configure_item("tcp_startserver_button", label="Stop Server")
            dpg.configure_item("tcp_connect_button", show=False)
            show_rts_dtr_controls(True)

        # Auto-connect to saved serial device if it's present
        comport_value = dpg.get_value("comport")
        if saved_device and comport_value and ":" in comport_value:
            auto_comport = comport_value[0:comport_value.index(":")]
            auto_baudrate = dpg.get_value("baud_rate")
            protocol.reset_ready()
            asyncio.run_coroutine_threadsafe(
                connect_serial_async(protocol, auto_comport, auto_baudrate, auto_dismiss=True),
                loop
            )

    try:
        if radio.dpg_enabled == True:
            await run_dpg()
        else:
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        if protocol.transport != None:
            try:
                protocol.transport.serial.dtr = False
            except:
                pass
            protocol.transport.close()
        if radio.dpg_enabled == True:
            dpg.destroy_context()

_headless_shutdown_event = None  # set by main() once the loop binds it

if __name__ == "__main__":
    # Headless mode runs on the module-level `loop` (started at import by the
    # background thread at line 72). asyncio.run() would create a second loop
    # and leave the TCP server + signal handler straddling two event loops,
    # which is the exact bug that caused the 10 s SIGKILL hang on systemd stop.
    if any(a in sys.argv for a in ("-s", "--start-server")):
        import signal as _signal
        def _shutdown(_signum, _frame):
            print("\nSIGTERM received — shutting down...")
            if _headless_shutdown_event is not None:
                loop.call_soon_threadsafe(_headless_shutdown_event.set)
        _signal.signal(_signal.SIGTERM, _shutdown)
        _signal.signal(_signal.SIGINT, _shutdown)
        fut = asyncio.run_coroutine_threadsafe(main(), loop)
        try:
            fut.result()
        except KeyboardInterrupt:
            pass
    else:
        asyncio.run(main())
