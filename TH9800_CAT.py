from getpass import getpass
from TH9800_Enums import *
from time import sleep
import dearpygui.dearpygui as dpg
import serial.tools.list_ports,serial_asyncio,asyncio,threading
import argparse,platform,ctypes,re,os

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
debug = False

protocol = None
read_loop_future = None
write_loop_future = None

def printd(msg):
    if debug == True:
        print(msg)

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
        async def process_tcp_cmd(self, cmd, data, writer):
            global protocol
            if cmd != "pass" and cmd != "exit" and self.tcpserver_loggedin == False:
                return "Unauthorized"

            match cmd:
                case "pass":
                    if self.tcpserver_login_count > 3:
                        return "returnLogin"
                    if data == self.tcpserver_passw:
                        self.tcpserver_loggedin = True
                        self.tcpserver_login_count = 0
                        return "Login Successful"
                    else:
                        self.tcpserver_login_count += 1
                        return "Login Failed"
                case "data":
                    protocol.send_packet(data=bytearray.fromhex(data))
                    return "data sent"
                case "rts":
                    if data == None or data == "":
                        protocol.toggle_rts()
                    else:
                        protocol.set_rts(bool(data))
                    return str(protocol.transport.serial.rts)
                case "dtr":
                    if data == None or data == "":
                        protocol.toggle_dtr()
                    else:
                        protocol.set_dtr(bool(data))
                    return str(protocol.transport.serial.dtr)
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
                    continue

                printd(f"Data RCVD: {type(data)} /// {data}")
                data = data[0:-1] #Pull new line character off the end
                
                if type(data) == bytearray or type(data) == bytes: #Data received is a radio packet
                    if data.find(b'\xAA\xFD') != -1:
                        printd(f"Data RCVD(hex): {data.hex().upper()}")
                        if self.tcpserver_loggedin == True:
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
                        print(f"CMD RCVD1:{{{cmd}}}:{{{data}}}")
                        response = f"CMD{{{cmd}[{data}]}} "
                    else:
                        cmd = str(message[1::])
                        data = ""
                        print(f"CMD RCVD2:{{{cmd}}}")
                        response = f"CMD{{{cmd}}} "

                    response2 = await process_tcp_cmd(self=self, cmd=cmd, data=data, writer=writer)
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
                        
                        protocol.set_rts(True)
                        protocol.radio.connect_process = True
                        protocol.radio.exe_cmd(cmd=RADIO_TX_CMD.STARTUP)
                        await asyncio.sleep(0.5)
                        protocol.radio.exe_cmd(cmd=RADIO_TX_CMD.L_VOLUME_SQUELCH)
                        await asyncio.sleep(0.5)
                        protocol.radio.exe_cmd(cmd=RADIO_TX_CMD.R_VOLUME_SQUELCH)
                        await asyncio.sleep(2)
                        
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
            self.tcpserver_loggedin = False
            self.tcpserver_login_count = 0
        finally:
            print(f"Connection closed: {addr}")
            try:
                self.tcpserver_loggedin = False
                self.tcpserver_login_count = 0

                writer.close()
                if sys.platform != "win32": # On Windows, skip wait_closed entirely to avoid WinError 64
                    await writer.wait_closed()
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
                    continue
                
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
                            match data:
                                case "True":
                                    dpg.set_value("rts_text", "USB Controlled")
                                    protocol.radio.set_dpg_theme(tag="rts_text",color="green")
                                case "False":
                                    dpg.set_value("rts_text", "Radio Controlled")
                                    protocol.radio.set_dpg_theme(tag="rts_text",color="red")
                        case "dtr":
                            match data:
                                case "True":
                                    protocol.radio.set_dpg_theme(tag="dtr_button",color="green")
                                case "False":
                                    protocol.radio.set_dpg_theme(tag="dtr_button",color="red")
                    continue
                else:
                    print(f"RCVD:{message}")
                    continue

                #match cmd:
                #    case "data":
                #        protocol.data_received(data=bytearray.fromhex(data))
                #        print(f"cmd data rcvd: {data}")
                #    case "exit":
                #        break
                #    case _:
                #        print("Not Found")
                #        continue
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

class SerialRadio:
    def __init__(self, dpg: dpg = None, protocol = None):
        self.packet = SerialPacket()
        self.protocol = protocol
        
        self.rigctl_server = False
        self.cat = None
        
        self.dpg = dpg
        self.dpg_enabled = True
        
        self.menu_open = False
        self.connect_process = False
        self.startup = False
        
        self.vfo_memory = {
            'vfo_active': RADIO_VFO.LEFT,
            RADIO_VFO.NONE:{
                "icons": {}
            },
            RADIO_VFO.LEFT: {
                "name": "",
                "channel": -1,
                "frequency": 0, # 100.000 MHz
                "mode": "FM",
                "operating_mode": int(RADIO_VFO_TYPE.MEMORY),   # 0 = VFO mode, 1 = Memory mode
                "width": 2500,          # 2.5 kHz
                "ptt": 0,               # PTT off
                "volume": 25,
                "squelch": 25,
                "icons": {}
            },
            RADIO_VFO.RIGHT:{
                "name": "",
                "channel": -1,
                "frequency": 0, # 100.000 MHz
                "mode": "FM",
                "operating_mode": int(RADIO_VFO_TYPE.MEMORY),   # 0 = VFO mode, 1 = Memory mode
                "width": 2500,          # 2.5 kHz
                "ptt": 0,               # PTT off
                "volume": 25,
                "squelch": 25,
                "icons": {}
            }
        }
        
        self.vfo_change = False
        self.vfo_active = RADIO_VFO.LEFT
        self.vfo_active_processing = RADIO_VFO.LEFT
        self.vfo_text = ""
        self.vfo_channel = ""
        self.mic_ptt = False
        self.mic_ptt_disabled = False

        for vfo in (RADIO_VFO.LEFT,RADIO_VFO.RIGHT):
            for icon in RADIO_RX_ICON:
                self.vfo_memory[vfo]['icons'].update({f"{icon.name}": False})
            self.vfo_memory[vfo]['icons']['SIGNAL'] = 0

    def get_vfo(self, vfo: str):
        match vfo.upper():
            case "L":
                return RADIO_VFO.LEFT
            case "R":
                return RADIO_VFO.RIGHT
            case _:
                return RADIO_VFO.LEFT

    def get_cmd_pkt(self, cmd: RADIO_TX_CMD, payload: bytes = None):
        cmd_name = cmd.name
        cmd_data = cmd.data
        if cmd_name.find("SQUELCH") != -1 or cmd_name.find("VOLUME") != -1:
            if payload == None: #VOL/SQ payload default value is 25% (0xEB00)
                return cmd_data
            elif cmd_name.find("SQUELCH") != -1:
                return (cmd_data[0:9] + payload + bytearray([cmd_data[11]]))
            elif cmd_name.find("VOLUME") != -1:
                return (cmd_data[0:6] + payload + cmd_data[8:12])
        else:
            return cmd_data

    def switch_vfo_op_mode(self, vfo: RADIO_VFO):
        return
        match self.vfo_memory[vfo]['operating_mode']:
            case RADIO_VFO_TYPE.MEMORY:
                self.vfo_memory[vfo]['operating_mode'] = int(RADIO_VFO_TYPE.VFO)
            case RADIO_VFO_TYPE.VFO:
                self.vfo_memory[vfo]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
        printd(f"RADIO VFO TYPE0 set to {self.vfo_memory[vfo]['operating_mode']}")

    def set_dpg_theme_background(self, tag, color):
        if self.dpg_enabled == False:
            return
        match color:
            case "red":
                color_value = (255, 0, 0, 255)
            case "green":
                color_value = (0, 255, 0, 255)
            case "black":
                color_value = (37, 37, 38, 255)
            case "white":
                color_value = (255, 255, 255, 255)
            case "darkgray":
                color_value = (64, 64, 64, 255)
            case _:
                raise ValueError("\nColor not implemented in set_dpg_theme function.")
        with dpg.theme() as input_theme:
            with dpg.theme_component(dpg.mvInputText):
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, color_value)
        printd(f"SET_INPUT_BG_THEME {tag} -  {color}")
        try:
            dpg.bind_item_theme(tag, input_theme)
        except Exception as e:
            printd(f"****************Error occurred: {e}****************")

    def set_dpg_theme(self, tag, color):
        if self.dpg_enabled == False:
            return
        match color:
            case "red":
                color_value = (255, 0, 0, 255)
            case "green":
                color_value = (0, 255, 0, 255)
            case "black":
                color_value = (37, 37, 38, 255)
            case "white":
                color_value = (255, 255, 255, 255)
            case _:
                raise ValueError("\nColor not implemented in set_dpg_theme function.")
        with dpg.theme() as text_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, color_value)
        printd(f"SETICONTHEME {tag} -  {color}")
        try:
            dpg.bind_item_theme(tag, text_theme)
        except Exception as e:
            printd(f"****************Error occurred: {e}****************")
            
    def set_active_vfo(self, vfo: RADIO_VFO):
        printd(f"Current VFO: {self.vfo_memory['vfo_active']}")
        vfo_name = str(vfo)
        if self.vfo_memory['vfo_active'] != vfo:
            printd(f"Set MAIN VFO to {vfo_name}")
            self.exe_cmd(cmd=RADIO_TX_CMD[f"{vfo_name}_DIAL_PRESS"])
        
    def set_icon(self, vfo: RADIO_VFO, icon: RADIO_RX_ICON, value):
        vfo_name = str(vfo).lower()
        icon_name = str(icon).lower()
        #self.icons[vfo][icon_name.upper()] = value
        self.vfo_memory[vfo]['icons'][icon_name.upper()] = value
        #printd(f"SETICON {vfo_name.upper()}_{icon_name.upper()} = {value}")
        
        match icon:
            case RADIO_RX_ICON.AM:
                tag = f"icon_l_{icon_name}"
            case RADIO_RX_ICON.BUSY: #NOT USED, refer to RADIO_RX_CMD.ICON_BUSY instead
                return
            case RADIO_RX_ICON.APO | RADIO_RX_ICON.LOCK | RADIO_RX_ICON.SET | RADIO_RX_ICON.KEY2:
                tag = f"icon_{icon_name}"
            case RADIO_RX_ICON.MAIN:
                tag = f"icon_{vfo_name}_{icon_name}"
                if value == True:
                    self.vfo_memory['vfo_active'] = vfo
                    printd(f"*****MAIN VFO SET TO: {self.vfo_memory['vfo_active']}")
            case _:
                tag = f"icon_{vfo_name}_{icon_name}"
        
        if value == True or value > 0x00:
            color = "red"
        elif value == False or value == 0x00:
            if icon == RADIO_RX_ICON.SIGNAL:
                color = "white"
            else:
                color = "black"
        else:
            color = "black"
        
        if self.dpg_enabled == True:
            self.set_dpg_theme(tag=tag,color=color)

    def set_volume(self, vfo: str, vol: int = 25):
        if vol < 0:
            vol = 0
        elif vol > 100:
            vol = 100

        dpg.set_value(f"slider_{vfo.lower()}_volume",vol)
        payload = self.packet.vol_sq_to_packet(value=vol)
        cmd = RADIO_TX_CMD[f"{vfo}_VOLUME"]
        self.vfo_memory[self.get_vfo(vfo=vfo)]['volume'] = vol
        
        printd(f"Set {vfo}_VOLUME: {str(vol)}")
        self.exe_cmd(cmd=cmd, payload=payload)

    def set_squelch(self, vfo: str, sq: int = 25):
        if sq < 0:
            sq = 0
        elif sq > 100:
            sq = 100

        dpg.set_value(f"slider_{vfo.lower()}_squelch",sq)
        payload = self.packet.vol_sq_to_packet(value=sq)
        cmd = RADIO_TX_CMD[f"{vfo}_SQUELCH"]
        self.vfo_memory[self.get_vfo(vfo=vfo)]['squelch'] = sq
        
        printd(f"Set {vfo}_SQUELCH: {str(sq)}")
        self.exe_cmd(cmd=cmd, payload=payload)

    def get_freq(self, vfo: RADIO_VFO):
        vfo_name = str(vfo)
        if self.vfo_memory[vfo]['operating_mode'] == int(RADIO_VFO_TYPE.VFO):
            return self.vfo_memory[vfo]['frequency']
        elif self.vfo_memory[vfo]['operating_mode'] == int(RADIO_VFO_TYPE.MEMORY):
            self.exe_cmd(cmd=RADIO_TX_CMD[f"{vfo_name}_LOW_HOLD"])
            self.exe_cmd(cmd=RADIO_TX_CMD[f"{vfo_name}_LOW_HOLD"])

    def set_freq(self, vfo: RADIO_VFO, freq: str):
        for n in freq:
            cmd_pkt_all = b''
            cmd = RADIO_TX_CMD[f"MIC_{n}"]
            cmd_payload = self.get_cmd_pkt(cmd=cmd)
            cmd_pkt = self.packet.create_tx_packet(payload=cmd_payload)
            cmd_pkt_all += cmd_pkt
            cmd_data2 = self.get_cmd_pkt(cmd=RADIO_TX_CMD.DEFAULT)
            cmd_pkt2 = self.packet.create_tx_packet(payload=cmd_data2)
            cmd_pkt_all += cmd_pkt2
            self.protocol.send_packet(cmd_pkt_all)
            sleep(.15)

    def exe_cmd(self, cmd: RADIO_TX_CMD, payload: bytes = None):
        cmd_name = cmd.name
        cmd_data = self.get_cmd_pkt(cmd=cmd,payload=payload)
        
        if cmd == RADIO_TX_CMD.L_SET_VFO:
            self.set_active_vfo(vfo=RADIO_VFO.LEFT)
            return
        if cmd == RADIO_TX_CMD.R_SET_VFO:
            self.set_active_vfo(vfo=RADIO_VFO.RIGHT)
            return
        
        #If MIC PTT(TX) and UP/DOWN/P btn is pressed, ignore it
        if self.mic_ptt == True and re.match(r"MIC_(UP|DOWN|P\d+)",cmd_name):
            printd("Ignoring keypress...")
            return
        elif self.mic_ptt == True and (cmd_name.find("MIC") != -1 or cmd_name.find("HM") != -1):
            printd("*****mic_ptt=True, setting 0x00 on MIC btn*****")
            cmd_data[1] = 0x00 #5th byte changes to 0x00 if MIC button pressed while MIC PTT (TX) is active

        cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)
        
        #If above was a button/key press, we need to release button/return control to body
        if cmd_name.find("LEFT") == -1 and cmd_name.find("RIGHT") == -1 and cmd_name != "L_VOLUME" and cmd_name != "L_SQUELCH" and cmd_name != "R_VOLUME" and cmd_name != "R_SQUELCH":
            if cmd_name == "MIC_PTT" and self.mic_ptt == True:
                printd("***MIC PTT***")
            elif cmd_name == "MIC_PTT" and self.mic_ptt == False:
                #Only send DEFAULT/release CMD if MIC PTT btn is pressed again after active MIC PTT
                cmd_data = self.get_cmd_pkt(cmd=RADIO_TX_CMD.DEFAULT)
                cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)
                self.mic_ptt_disabled = True
            elif (cmd_name.find("MIC") != -1 or cmd_name.find("HM") != -1) and self.mic_ptt == True:
                self.protocol.send_packet(cmd_pkt)
                sleep(.25)
                
                #MIC PTT cmd is replayed after a MIC button is pressed during active MIC PTT (TX)
                printd(f"MIC pkt: {cmd_pkt.hex().upper()}")
                cmd_data = self.get_cmd_pkt(cmd=RADIO_TX_CMD.MIC_PTT)
                cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)
                printd(f"*****PTT replay: {cmd_pkt.hex().upper()}*****")
            else:
                self.protocol.send_packet(cmd_pkt)
                sleep(.1)
                cmd_data2 = self.get_cmd_pkt(cmd=RADIO_TX_CMD.DEFAULT)
                cmd_pkt2 = self.packet.create_tx_packet(payload=cmd_data2)
                cmd_pkt = cmd_pkt2
        
        self.protocol.send_packet(cmd_pkt)

class SerialProtocol(asyncio.Protocol):
    def __init__(self, radio: SerialRadio):
        self.transport = None
        self.ready = asyncio.Event()
        self.receive_queue = asyncio.Queue()
        self.transmit_queue = asyncio.Queue()
        self.buffer = bytearray()
        self.radio = radio

    def set_rts(self, state: bool):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!rts {state}".encode())
        else:
            printd(f"RTS state: {self.transport.serial.rts} Setting to {state}")
            self.transport.serial.rts = state
        if self.radio.dpg_enabled == False:
            return
        match state:
            case True:
                dpg.set_value("rts_text", "USB Controlled")
                self.radio.set_dpg_theme(tag="rts_text",color="green")
            case False:
                dpg.set_value("rts_text", "Radio Controlled")
                self.radio.set_dpg_theme(tag="rts_text",color="red")

    def toggle_rts(self):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!rts".encode())
            return
        else:
            state = not self.transport.serial.rts  #Toggle state
            self.transport.serial.rts = state
        if self.radio.dpg_enabled == False:
            return
        match state:
            case True:
                dpg.set_value("rts_text", "USB Controlled")
                self.radio.set_dpg_theme(tag="rts_text",color="green")
            case False:
                dpg.set_value("rts_text", "Radio Controlled")
                self.radio.set_dpg_theme(tag="rts_text",color="red")

    def set_dtr(self, state: bool):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!dtr {state}".encode())
        else:
            printd(f"DTR state: {self.transport.serial.dtr} Setting to {state}")
            self.transport.serial.dtr = state
        if self.radio.dpg_enabled == False:
            return
        match state:
            case True:
                self.radio.set_dpg_theme(tag="dtr_button",color="green")
            case False:
                self.radio.set_dpg_theme(tag="dtr_button",color="red")

    def toggle_dtr(self):
        if TCP.tcpclient_ready == True:
            protocol.transmit_queue.put_nowait(f"!dtr".encode())
            return
        else:
            state = not self.transport.serial.dtr  #Toggle state
            printd(f"DTR state: {self.transport.serial.dtr} Setting to {state}")
            self.transport.serial.dtr = state
        if self.radio.dpg_enabled == False:
            return
        match state:
            case True:
                self.radio.set_dpg_theme(tag="dtr_button",color="green")
            case False:
                self.radio.set_dpg_theme(tag="dtr_button",color="red")

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
        print("Connection lost")
        asyncio.get_event_loop().stop()
        self.transport.close()

    def send_packet(self, data: bytes):
        if self.transport and not self.transport.is_closing() or TCP.tcpclient_ready == True:
            printd(f"Sending: {data.hex().upper()}")
            self.transmit_queue.put_nowait(data)
            #self.transport.write(data)
        else:
            print("Transport is not available or already closed.")

class SerialPacket:
    def __init__(self, protocol: SerialProtocol=None):
        self.start_bytes = bytes([0xAA,0xFD])
        self.packet = b''  # Empty payload by default
        self.protocol = protocol
        if protocol != None:
            self.radio = protocol.radio
        
        self.display_packets_icon_map = (
            {},
            {},
            {0x02: "APO",0x08: "LOCK",0x20: "KEY2",0x80: "SET"},
            {0x02: "NEG",0x08: "POS",0x20: "TX",0x80: "MAIN"},
            {0x02: "PREF",0x08: "SKIP",0x20: "ENC",0x80: "DEC"},
            {0x02: "DCS",0x08: "MUTE",0x20: "MT",0x80: "BUSY"},
            {0x00: "H",0x02: "M",0x08: "L",0x80: "AM"}
        )

    def create_tx_packet(self, payload: bytes):
        """
        Create a TX packet with start bytes, payload length, and checksum.
        """
        packet_length = len(payload)
        packet = self.start_bytes + bytes([packet_length]) + payload  # Start bytes + length byte + payload + checksum
        checksum = self.calculate_checksum(packet[2:])
        packet += bytes([checksum])
        self.packet = packet
        return bytearray(packet)

    def format_frequency(self, freq_str):
        freq_str = str(freq_str)  # ensure it's a string
        if len(freq_str) <= 3:
            return freq_str
        return f"{freq_str[:-3]}.{freq_str[-3:]}"

    def process_rx_packet(self, packet: bytes):
        """
        Parse an RX packet: validate checksum and extract payload.
        """
        printd(f"pkt: {packet.hex().upper()}")
        self.packet = packet
        if len(packet) < 4:
            raise ValueError("\nPacket too short to be valid.")

        if packet[:2] != self.start_bytes:
            raise ValueError("\nInvalid start bytes.")

        packet_length = packet[2]
        expected_packet_size = 2 + 1 + packet_length + 1  # Start + Length + Payload + Checksum

        if len(packet) != expected_packet_size:
            raise ValueError("\nIncomplete packet.")

        payload = packet[3:-1]  # Extract payload (skip start bytes and length byte)
        self.payload = payload
        checksum = packet[-1]  # Extract checksum
        self.checksum = checksum
        calculated_checksum = self.calculate_checksum(bytes([packet_length])+payload)  # Only checksum the payload

        if calculated_checksum != checksum:
            raise ValueError(f"\nChecksum mismatch: expected {calculated_checksum:02X}, found {checksum:02X}")
        
        packet_cmd = packet[3]
        packet_data = packet[4:-1]
        match packet_cmd:
            case RADIO_RX_CMD.DISPLAY_TEXT.value:
                self.radio.vfo_text = packet_data[2:8].decode()
                radio_text = self.radio.vfo_text
                radio_channel = self.radio.vfo_channel
                match packet_data[0]:
                    case 0x60:
                        printd(f"{str(self.radio.vfo_active_processing)}<***Set Freq Fast [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                        radio_text = f"*{radio_text}*"
                        self.radio.vfo_text = radio_text
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"ch_{str(self.radio.vfo_active_processing).lower()}_display",radio_channel)
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
                    case (0x40|0xC0):
                        if self.radio.vfo_change == True:
                            return
                        elif self.radio.menu_open == True and self.radio.vfo_active_processing == self.radio.vfo_memory['vfo_active'] and self.radio.connect_process == False:
                            printd(f"{str(self.radio.vfo_active_processing)}<***Set Menu [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                        elif self.radio.connect_process == False:
                            if radio_channel.find("HP") != -1:
                                printd(f"{str(self.radio.vfo_active_processing)}<***Radio Power [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                            else:
                                printd(f"{str(self.radio.vfo_active_processing)}<***Set Channel [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                                if self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] != -1:
                                    self.radio.vfo_memory[self.radio.vfo_active_processing]['name'] = radio_text
                                else:
                                    self.radio.vfo_memory[self.radio.vfo_active_processing]['name'] = ""
                                if radio_channel.strip() == "":
                                    self.radio.vfo_memory[self.radio.vfo_active_processing]['channel'] = -1
                                else:
                                    self.radio.vfo_memory[self.radio.vfo_active_processing]['channel'] = int(radio_channel.strip())
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"ch_{str(self.radio.vfo_active_processing).lower()}_display",radio_channel)
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
            case RADIO_RX_CMD.CHANNEL_TEXT.value:
                if self.radio.vfo_change == True:
                    return
                self.radio.vfo_channel = packet_data[2:5].decode().strip()

                match packet_data[0]:
                    case 0x40 | 0x60:
                        if self.radio.menu_open == False:
                            self.radio.vfo_memory[RADIO_VFO.LEFT]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
                            printd(f"****RADIO VFO TYPE1 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
                        if packet_data[0] == 0x60:
                            if self.radio.dpg_enabled == True:
                                dpg.set_value(f"ch_{str(self.radio.vfo_active_processing).lower()}_display",self.radio.vfo_channel)
                    case 0xC0 | 0xE0:
                        if self.radio.menu_open == False:
                            self.radio.vfo_memory[RADIO_VFO.RIGHT]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
                            printd(f"****RADIO VFO TYPE1 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
            case RADIO_RX_CMD.DISPLAY_CHANGE.value:
                match packet_data[0]:
                    case 0x43:
                        self.radio.vfo_active_processing = RADIO_VFO.LEFT
                        self.radio.vfo_channel = ""
                        self.radio.vfo_text = ""
                    case 0xC3:
                        self.radio.vfo_active_processing = RADIO_VFO.RIGHT
                        self.radio.vfo_channel = ""
                        self.radio.vfo_text = ""
                    case 0x03:
                        self.radio.vfo_change = False
                    case 0x83:
                        if self.radio.startup == True:
                            self.radio.startup = False
                            printd("*******Startup complete*******\n")
                        self.radio.vfo_change = False
                        if self.radio.connect_process == True:
                            self.radio.connect_process = False
            case RADIO_RX_CMD.DISPLAY_ICONS.value:
                self.process_display_packet(packet=packet_data)
            case RADIO_RX_CMD.ICON_SET.value:
                match packet_data[0]:
                    case 0x00:
                        if self.radio.menu_open == True:
                            printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Menu Closed***>{str(self.radio.vfo_memory['vfo_active'])}")
                            self.radio.menu_open = False
                            self.radio.set_icon(vfo=RADIO_VFO.NONE, icon=RADIO_RX_ICON.SET, value=False)
                    case 0x01:
                        printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Menu Opened***>{str(self.radio.vfo_memory['vfo_active'])}")
                        self.radio.menu_open = True
                        self.radio.set_icon(vfo=RADIO_VFO.NONE, icon=RADIO_RX_ICON.SET, value=True)
            case RADIO_RX_CMD.ICON_MAIN.value:
                match packet_data[0]:
                    case 0x01:
                        self.radio.vfo_memory['vfo_active'] = RADIO_VFO.LEFT
                        self.radio.vfo_change = True
                        printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Left  VFO Activated***>{str(self.radio.vfo_memory['vfo_active'])}")
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.MAIN, value=False)
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.MAIN, value=True)
                    case 0x81:
                        self.radio.vfo_memory['vfo_active'] = RADIO_VFO.RIGHT
                        self.radio.vfo_change = True
                        printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Right VFO Activated***>{str(self.radio.vfo_memory['vfo_active'])}")
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.MAIN, value=True)
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.MAIN, value=False)
            case RADIO_RX_CMD.ICON_TX.value:
                match packet_data[0]:
                    case 0x00:
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.TX, value=False)
                        if self.radio.mic_ptt_disabled == True:
                            self.radio.mic_ptt_disabled = False
                            #cmd_pkt = self.create_tx_packet(payload=bytes([0xA0,0x09,0x02]))
                            #self.protocol.send_packet(cmd_pkt)   #Not sure this CMD is needed just yet
                            #printd(f"TX0 pkt: {cmd_pkt.hex().upper()}")
                    case 0x01:
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.TX, value=True)
                        if self.radio.mic_ptt == True:
                            printd("")
                            #cmd_pkt = self.create_tx_packet(payload=bytes([0xA0,0xF9,0x01]))
                            #self.protocol.send_packet(cmd_pkt)   #Not sure this CMD is needed just yet
                            #printd(f"TX1 pkt: {cmd_pkt.hex().upper()}")
                    case 0x80:
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.TX, value=False)
                    case 0x81:
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.TX, value=True)
            case RADIO_RX_CMD.ICON_BUSY.value:
                match packet_data[0]:
                    case 0x00:
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.SIGNAL, value=False)
                    case 0x01:
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.SIGNAL, value=True)
                    case 0x80:
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.SIGNAL, value=False)
                    case 0x81:
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.SIGNAL, value=True)
            case RADIO_RX_CMD.ICON_SIG_BARS.value:
                sig = packet_data[0]
                if sig >= 0x00 and sig <= 0x09:
                    update_signal(radio=self.radio,vfo=RADIO_VFO.LEFT,s_value=sig)
                elif sig >= 0x80 and sig <= 0x89:
                    sig = sig - 0x80
                    update_signal(radio=self.radio,vfo=RADIO_VFO.RIGHT,s_value=sig)
                else:
                    printd("OSIG:",sig)
            case RADIO_RX_CMD.ICON_DOT_1ST.value:
                radio_text_fast = False
                radio_text = self.radio.vfo_text
                if radio_text.find("*") != -1:
                    radio_text_fast = True
                    radio_text = radio_text.replace("*","")
                radio_text_formatted = self.format_frequency(radio_text).strip()
                if radio_text_fast == True:
                    radio_text_formatted = f"*{radio_text_formatted}*"
                match packet_data[0]:
                    case 0x40:
                        self.radio.vfo_active_processing = RADIO_VFO.LEFT
                        if self.radio.menu_open == False:
                            self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
                            printd(f"****RADIO VFO TYPE2 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
                    case 0x41:
                        self.radio.vfo_active_processing = RADIO_VFO.LEFT
                        if self.radio.menu_open == False:
                            self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] = int(RADIO_VFO_TYPE.VFO)
                            printd(f"****RADIO VFO TYPE2 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
                            try:
                                self.radio.vfo_memory[self.radio.vfo_active_processing]['frequency'] = str(int(self.radio.vfo_text)*1000)
                            except:
                                self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] = str(int(-1))
                                self.radio.vfo_memory[self.radio.vfo_active_processing]['frequency'] = str(int(-1))
                            printd(f"Freq set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['frequency']} for {self.radio.vfo_active_processing}")
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text_formatted)
                    case 0xC0:
                        self.radio.vfo_active_processing = RADIO_VFO.RIGHT
                        if self.radio.menu_open == False:
                            self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
                            printd(f"****RADIO VFO TYPE2 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
                    case 0xC1:
                        self.radio.vfo_active_processing = RADIO_VFO.RIGHT
                        if self.radio.menu_open == False:
                            self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] = int(RADIO_VFO_TYPE.VFO)
                            printd(f"****RADIO VFO TYPE2 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
                            try:
                                self.radio.vfo_memory[self.radio.vfo_active_processing]['frequency'] = str(int(self.radio.vfo_text)*1000)
                            except:
                                self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode'] = str(int(-1))
                                self.radio.vfo_memory[self.radio.vfo_active_processing]['frequency'] = str(int(-1))
                            printd(f"Freq set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['frequency']} for {self.radio.vfo_active_processing}")
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text_formatted)
            case RADIO_RX_CMD.STARTUP_1.value:
                match packet_data[0]:
                    case 0x00:
                        if self.radio.startup == False:
                            self.radio.startup = True
                            self.radio.connect_process = False
                            printd("\n*******Startup initiated*******")
                        self.protocol.send_packet(self.create_tx_packet(payload=bytes([0xF0])))
            case RADIO_RX_CMD.STARTUP_2.value:
                match packet_data[0]:
                    case 0x00:
                        #Send Vol/Sql for each VFO
                        self.radio.exe_cmd(cmd=RADIO_TX_CMD.L_VOLUME_SQUELCH)
                        self.radio.exe_cmd(cmd=RADIO_TX_CMD.R_VOLUME_SQUELCH)
            case RADIO_RX_CMD.STARTUP_3.value:
                match packet_data[0]:
                    case 0x20:
                        self.protocol.send_packet(self.create_tx_packet(payload=bytes([0xA0,0x18,0x02])))
            case _:
                printd(F"Unkown pkt: {packet.hex().upper()}")

    def process_display_packet(self, packet: bytes):
        match packet[0]:
            case 0x40:
                vfo = RADIO_VFO.LEFT
                self.radio.vfo_active_processing = vfo
            case 0xC0:
                vfo = RADIO_VFO.RIGHT
                self.radio.vfo_active_processing = vfo
            case _:
                printd(f"Unknown icon display packet: {packet[0]}")
        match packet[1]:
            case 0x00:
                self.radio.vfo_memory[vfo]['icons']['SIGNAL'] = 0x00
                #self.radio.icons[vfo]['SIGNAL'] = 0x00
            case _:
                self.radio.vfo_memory[vfo]['icons']['SIGNAL'] = packet[1]
                #self.radio.icons[vfo]['SIGNAL'] = packet[1]
                printd(F"SIGNAL PACKET! SIG:{packet[1]}")
        for x in range(2,6+1):
            icon_byte = packet[x]
            icon_map = self.display_packets_icon_map[x]
            enabled_icons = [name for bit, name in icon_map.items() if icon_byte & bit]
            disabled_icons = [name for bit, name in icon_map.items() if not icon_byte & bit]
            if "L" in disabled_icons and "M" in disabled_icons:
                enabled_icons += "H"
            for icon in enabled_icons:
                self.radio.set_icon(vfo=vfo,icon=RADIO_RX_ICON[f"{icon}"],value=True)
            for icon in disabled_icons:
                if icon == "H" and "H" in enabled_icons:
                    continue
                self.radio.set_icon(vfo=vfo,icon=RADIO_RX_ICON[f"{icon}"],value=False)
            printd(f"Enabled icons: {enabled_icons}")
            printd(f"Disabled icons: {disabled_icons}")

    def vol_sq_to_packet(self, value: int) -> bytes:
        if not (0 <= value <= 100):
            raise ValueError("Value must be >= 0 and <= 100")

        max_raw = 0x03AC #940

        if value == 0:
            raw_value = 0
        else:
            # Spread values 1–100 evenly over 1–940
            raw_value = round((value / 100) * max_raw)

        return raw_value.to_bytes(2, byteorder='little')

    def calculate_checksum(self, payload: bytes):
        """
        Calculate the XOR checksum over the data portion (payload).
        """
        checksum = 0
        for byte in payload:
            checksum ^= byte
        return checksum

    def __repr__(self):
        return f"SerialPacket(start={self.start_bytes.hex().upper()}, payload={self.payload.hex().upper()}, checksum={self.checksum:02X})"

class RigctlServer:
    def __init__(self, cat_controller, host='127.0.0.1', port=4532):
        self.cat = cat_controller  # Reference to your CAT controller
        self.host = host
        self.port = port
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        print(f"Rigctl server running on {self.host}:{self.port}")

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Connection from {addr}")

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                command = data.decode().strip()
                print(f"Received: {command}")

                # === Use your CAT controller ===
                if command == '\\get_powerstat':
                    writer.write(b"1\n")
                elif command == '\\chk_vfo':
                    writer.write(b"0\n")
                elif command == '\\dump_state':
                    dump = await self.cat.dump_state()
                    writer.write(dump.encode())
                elif command == 'f':
                    freq = await self.cat.get_frequency()
                    writer.write(f"{freq}\n".encode())
                elif command.startswith('F '):
                    try:
                        freq = int(command.split()[1])
                        await self.cat.set_frequency(freq)
                        writer.write(b"0\n")
                    except ValueError:
                        writer.write(b"-1\n")
                elif command == 'g':
                    op_mode = await self.cat.get_operating_mode()  # 0 = VFO, 1 = Memory
                    writer.write(f"{op_mode}\n".encode())
                elif command.startswith('G '):
                    try:
                        mode = int(command.split()[1])
                        await self.cat.set_operating_mode(mode)
                        writer.write(b"0\n")
                    except (IndexError, ValueError):
                        writer.write(b"-1\n")
                elif command == 'm':
                    mode, width = await self.cat.get_mode()
                    writer.write(f"{mode} {width}\n".encode())
                elif command.startswith('M '):
                    try:
                        parts = command.split()
                        mode = parts[1]
                        width = int(parts[2])
                        await self.cat.set_mode(mode, width)
                        writer.write(b"0\n")
                    except (IndexError, ValueError):
                        writer.write(b"-1\n")
                elif command.startswith('n '):
                    try:
                        mem_num = int(command.split()[1])
                        name = await self.cat.get_memory_name(mem_num)
                        writer.write(f"{name}\n".encode())
                    except (IndexError, ValueError):
                        writer.write(b"-1\n")
                elif command == 's':
                    writer.write(b"0\n")
                elif command == 't':
                    ptt = await self.cat.get_ptt()
                    writer.write(f"{ptt}\n".encode())
                elif command.startswith('T '):
                    try:
                        ptt = int(command.split()[1])
                        await self.cat.set_ptt(ptt)
                        writer.write(b"0\n")
                    except ValueError:
                        writer.write(b"-1\n")
                elif command == 'q':
                    print(f"Disconnect from {addr}")
                    break
                elif command == 'v':
                    vfo = await self.cat.get_vfo()
                    writer.write(f"{vfo}\n".encode())
                elif command.startswith('V '):
                    parts = command.split()
                    vfo = str(parts[1])
                    vfo = await self.cat.set_vfo(vfo=vfo)
                    writer.write(f"RPRT 0\n".encode())
                else:
                    print(f"Unknown command: {command}")
                    writer.write(b"-1\n")

                await writer.drain()

        finally:
            writer.close()
            await writer.wait_closed()

class CATController:
    def __init__(self, radio: SerialRadio):
        self.radio = radio
        #self.current_vfo = self.radio.vfo_memory['vfo_active']

    async def dump_state(self) -> str:
        return (
        "0\n"  # rigctl protocol version
        "9800\n"  # rig model (can be any int)
        "2\n"  # ITU region

        # RX frequency range (start, end, modes, power range, vfo, ant) 0x83 for modes?? 0x02 for vfo?
        "0.000000 10000000000.000000 0x2ef 5000 50000 0x1 0x0\n"

        # End of RX ranges
        "0 0 0 0 0 0 0\n"
        # End of TX ranges
        "0 0 0 0 0 0 0\n"

        # Tuning steps: mode mask, step
        "0xef 1\n"
        "0xef 0\n"
        "0 0\n"  # end of tuning steps

        # Filter sizes (mode mask, width)
        "0x82 500\n"
        "0x82 200\n"
        "0x82 2000\n"
        "0x221 10000\n"
        "0x221 5000\n"
        "0x221 20000\n"
        "0x0c 2700\n"
        "0x0c 1400\n"
        "0x0c 3900\n"
        "0x40 160000\n"
        "0x40 120000\n"
        "0x40 200000\n"
        "0 0\n"  # end of filter sizes

        "0\n"  # max_rit
        "0\n"  # max_xit
        "0\n"  # max_ifshift

        "0\n"  # announces (bitfield)

        "0\n"  # preamp list
        "0\n"  # attenuator list

        "0\n"         # get_func
        "0\n"         # set_func
        "0x40000020\n"  # get_level (SQL | STRENGTH)
        "0x20\n"      # set_level (SQL)
        "0\n"         # get_parm
        "0\n"         # set_parm
        )

    async def set_vfo_memory(self, name, value):
        printd(f"rigctl SET {name} = {value}")
        if name == "vfo_active":
            self.radio.set_active_vfo(vfo=value)
            return
        self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']][name] = value
        
    async def get_vfo_memory(self, name):
        printd(f"rigctl GET {name}")
        vfo_active = self.radio.vfo_memory['vfo_active']
        if name == "vfo_active":
            return vfo_active
        printd(f"rigctl GET {name} - VFO: {vfo_active}")
        return self.radio.vfo_memory[vfo_active][name]

    # Operating Mode (VFO/MEMOREY)
    async def get_operating_mode(self) -> int:
        return await self.get_vfo_memory("operating_mode")
        #return self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]['operating_mode']

    async def set_operating_mode(self, mode: int):
        if mode not in (0, 1):
            raise ValueError("Invalid operating mode")
        await self.set_vfo_memory("operating_mode",mode)
        #self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]['operating_mode'] = mode

    # Channel Name
    async def get_memory_name(self, mem_num: int) -> str:
        memory = await self.get_vfo_memory("name")
        #memory = self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]['name']
        if not memory:
            return ""
        return memory

    # Frequency
    async def get_frequency(self) -> int:
        return await self.get_vfo_memory("frequency")
        #return self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]["frequency"]

    async def set_frequency(self, freq: int):
        printd(f"***Set FREQ: {freq}***")
        self.radio.set_freq(vfo=self.radio.vfo_memory['vfo_active'],freq=str(freq))
        await self.set_vfo_memory("frequency",freq)
        #self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]["frequency"] = freq

    # Mode and bandwidth
    async def get_mode(self) -> tuple:
        return await self.get_vfo_memory("mode"),await self.get_vfo_memory("width")
        #return vfo["mode"], vfo["width"]

    async def set_mode(self, mode: str, width: int):
        await self.set_vfo_memory("mode",mode)
        await self.set_vfo_memory("width",width)
        #vfo = self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]
        #vfo["mode"] = "FM"      #RADIO IS SOLO FM
        #vfo["width"] = width

    # PTT
    async def get_ptt(self) -> int:
        return await self.get_vfo_memory("ptt")

    async def set_ptt(self, state: int):
        await self.set_vfo_memory("ptt",state)
        #self.radio.vfo_memory[self.radio.vfo_memory['vfo_active']]["ptt"]

    # VFO switching
    async def get_vfo(self) -> str:
        vfo_active = await self.get_vfo_memory("vfo_active")
        match vfo_active:
            case RADIO_VFO.LEFT:
                return "VFOA"
            case RADIO_VFO.RIGHT:
                return "VFOB"
            case _:
                return "VFOA"

    async def set_vfo(self, vfo: str):
        if vfo not in ("VFOA", "VFOB"):
            raise ValueError("Invalid VFO")
        match vfo:
            case "VFOA":
                await self.set_vfo_memory("vfo_active",RADIO_VFO.LEFT)
            case "VFOB":
                await self.set_vfo_memory("vfo_active",RADIO_VFO.RIGHT)
            case _:
                await self.set_vfo_memory("vfo_active",RADIO_VFO.LEFT)

def tcp_connect_callback(sender, app_data, user_data):
    global TCP,read_loop_future,write_loop_future
    host = dpg.get_value("tcp_host_text")
    port = dpg.get_value("tcp_port_text")
    password = dpg.get_value("tcp_pass_text")
    protocol = user_data['protocol']
    label = user_data['label']
    
    if password == None:
        password = ""
    
    if label == "Start Server":
        tag = "tcp_startserver_button"
        label = dpg.get_item_label(tag)

        if label == "Start Server":
            TCP.tcpserver_future = asyncio.run_coroutine_threadsafe(
                TCP.start_tcp_server(host=host, port=port, password=password, protocol=protocol),
                loop
            )

            dpg.configure_item(tag, label="Stop Server")
            dpg.configure_item("rts_button", show=True)
            dpg.configure_item("dtr_button", show=True)
            
            dpg.configure_item("rts_text", show=True)
            dpg.configure_item("rts_label", show=True)
            
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
            dpg.configure_item("rts_button", show=False)
            dpg.configure_item("dtr_button", show=False)
            
            dpg.configure_item("rts_text", show=False)
            dpg.configure_item("rts_label", show=False)
            
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
            dpg.configure_item("rts_button", show=True)
            dpg.configure_item("dtr_button", show=True)
            
            dpg.configure_item("rts_text", show=True)
            dpg.configure_item("rts_label", show=True)
            
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
            dpg.configure_item("rts_button", show=False)
            dpg.configure_item("dtr_button", show=False)
            
            dpg.configure_item("rts_text", show=False)
            dpg.configure_item("rts_label", show=False)
            
            dpg.configure_item("tcp_connect_button", show=True)
            
            dpg.configure_item("tcp_startserver_button", show=True)

def update_signal(radio: SerialRadio, vfo: RADIO_VFO, s_value: int):
    vfo = vfo.value.lower()
    if s_value == 0:
        percent = 0
    else:
        percent = (s_value - 1) / 8  # Map S1–S9 to 0.0–1.0 range
    if radio.dpg_enabled == True:
        dpg.set_value(f"icon_{vfo}_signal", percent)
        dpg.configure_item(f"icon_{vfo}_signal",overlay=f"S{s_value}")

def refresh_comports_callback(sender, app_data, user_data):
    ports = []
    available_ports = serial.tools.list_ports.comports()
    for port in available_ports:
        ports.append(f"{port.device}: {port.description}")
        printd(f"{port.device} - {port.manufacturer} - {port.description}")
    dpg.configure_item("comport", items=ports)
    dpg.configure_item("comport", default_value=ports[0] if available_ports else "")

def cancel_callback(sender, app_data, user_data):
    dpg.configure_item(user_data, show=False)

def dpg_notification_window(title, message):
    with dpg.window(label=title, modal=True, no_close=True, pos=[22, 100]) as modal_id:
        dpg.add_text(message, wrap=500)
        dpg.add_button(label="Ok", width=75, user_data=(modal_id), callback=cancel_callback)

def button_callback(sender, app_data, user_data):
    global debug
    label = user_data["label"]
    vfo = user_data["vfo"]
    if vfo == RADIO_VFO.LEFT or vfo == RADIO_VFO.RIGHT or vfo == RADIO_VFO.MIC or vfo == RADIO_VFO.NONE:
        vfo_name = user_data["vfo"].value
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
            debug = True
            dpg.configure_item("debug_button", label="Disable Debug")
            return
        elif debug_label == "Disable Debug":
            debug = False
            dpg.configure_item("debug_button", label="Enable Debug")
            return

    match label.upper():
        case "SINGLE VFO":
            radio.exe_cmd(cmd=RADIO_TX_CMD['L_VOLUME_HOLD'])
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
        radio.exe_cmd(cmd=RADIO_TX_CMD[f"{vfo_name}_{label}"])
    else:
        match label:
            case "HA"|"HB"|"HC"|"HD"|"HE"|"HF":
                radio.exe_cmd(cmd=RADIO_TX_CMD[f"HYPER_{label.replace("H","")}"])

    printd(f"Sent {label} button command for {vfo_name} VFO.") #: {packet.hex().upper()}")

def sq_callback(sender, app_data, user_data):
    label = user_data["label"].replace("/","")
    vfo = user_data["vfo"].value
    protocol = user_data["protocol"]
    radio = protocol.radio
    
    radio.set_squelch(vfo=vfo,sq=app_data)

def vol_callback(sender, app_data, user_data):
    label = user_data["label"].replace("/","")
    vfo = user_data["vfo"].value
    protocol = user_data["protocol"]
    radio = protocol.radio
    
    radio.set_volume(vfo=vfo,vol=app_data)

async def connect_serial_async(protocol, comport, baudrate):
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
            await asyncio.sleep(0.5)
            printd(f"Connected to {comport} at {baudrate} baud.")
            protocol.set_rts(True) #Enable USB/CAT TX Control

        if radio.dpg_enabled == True:
            dpg.configure_item("rts_button", show=True)
            dpg.configure_item("dtr_button", show=True)
            dpg.configure_item("rts_text", show=True)
            dpg.configure_item("rts_label", show=True)
            dpg.configure_item("radio_window", show=True)
            dpg.configure_item("connection_window", collapsed=True)
            dpg.configure_item("connect_button", label="Disconnect")
        asyncio.create_task(read_loop(protocol))
        asyncio.create_task(write_loop(protocol))
        if TCP.tcpclient_ready == False:
            radio.connect_process = True

            radio.exe_cmd(cmd=RADIO_TX_CMD.STARTUP)
            await asyncio.sleep(0.5)
            radio.exe_cmd(cmd=RADIO_TX_CMD.L_VOLUME_SQUELCH)
            await asyncio.sleep(0.5)
            radio.exe_cmd(cmd=RADIO_TX_CMD.R_VOLUME_SQUELCH)

        cat_controller = CATController(radio=radio)
        radio.cat = cat_controller
        rigctl_server = RigctlServer(cat_controller)
        
        if radio.rigctl_server == True:
            dpg.configure_item("getstate_button", show=True)
            radio.get_freq(vfo=RADIO_VFO.LEFT)
            radio.get_freq(vfo=RADIO_VFO.RIGHT)
            await rigctl_server.start()
        
        await asyncio.sleep(2)
        if radio.dpg_enabled == True:
            dpg_notification_window(title="Radio Initialized", message="Radio connected and initialized successfully!")
        else:
            print("Radio connected and initialized successfully!")

        return transport
    except Exception as e:
        print(f"Connection failed: {e}")
        if radio.dpg_enabled == True:
            with dpg.window(label="Error", modal=True, no_close=True) as modal_id:
                dpg.add_text(e, wrap=300)
                dpg.add_button(label="Ok", width=75, user_data=(modal_id, True), callback=cancel_callback)
            dpg.set_item_pos(modal_id, [120, 100])
        return None

def port_selected_callback(sender, app_data, user_data):
    label = dpg.get_item_label("connect_button")
    
    protocol = user_data['protocol']
    radio = protocol.radio
    comport = dpg.get_value("comport")
    baudrate = dpg.get_value("baud_rate")
    
    if label == "Disconnect":
        protocol.transport.close()
        print(f"{comport} disconnected.\n")
        dpg.configure_item("connect_button", label="Connect")
        dpg.configure_item("dtr_button", show=False)
        dpg.configure_item("rts_button", show=False)
        dpg.configure_item("rts_text", show=False)
        dpg.configure_item("rts_label", show=False)
        return

    try:
        comport = comport[0:comport.index(":")]
    except:
        with dpg.window(label="Error", modal=True, no_close=True) as modal_id:
            dpg.add_text("Error occured connecting to COM port!")
            dpg.add_button(label="Ok", width=75, user_data=(modal_id, True), callback=cancel_callback)
        dpg.set_item_pos(modal_id, [120, 100])
        return
    
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
    while True:
        packet = await protocol.receive_queue.get()
        
        if TCP.tcpserver_ready == True and TCP.tcpserver != None:
            TCP.tcpserver.write(packet+b'\n')
            await TCP.tcpserver.drain()
            packet_processor = SerialPacket(protocol=protocol).process_rx_packet(packet=packet)
        else:
            packet_processor = SerialPacket(protocol=protocol).process_rx_packet(packet=packet)

async def write_loop(protocol: SerialProtocol):
    global TCP

    while True:
        if TCP.tcpclient_ready == True and TCP.tcpclient != None:
            try:
                data = await asyncio.wait_for(protocol.transmit_queue.get(), timeout=.10)
                printd(f"Send pkt tcp: {data}:{type(data)}")
                TCP.tcpclient.write(data+b'\n')
                await TCP.tcpclient.drain()
                if data.hex().find("aafd0c84ffffffff") == -1: #If match sq/vol cmd skip sleep
                    await asyncio.sleep(0.15)
            except:
                None
        else:
            try:
                data = await asyncio.wait_for(protocol.transmit_queue.get(), timeout=.10) #FIX FOR LINUX FREEZES ON TRANSMIT (Old: #data = await protocol.transmit_queue.get())
                protocol.transport.write(data)
                if data.hex().find("aafd0c84ffffffff") == -1: #If match sq/vol cmd skip sleep
                    await asyncio.sleep(0.15)
            except:
                None

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
            dpg.set_value(f"slider_{str(active_vfo).lower()}_volume",vol)
        case dpg.mvKey_Down:
            vol = radio.vfo_memory[active_vfo]['volume'] - 2
            dpg.set_value(f"slider_{str(active_vfo).lower()}_volume",vol)
        case dpg.mvKey_Left:
            sq = radio.vfo_memory[active_vfo]['squelch'] - 2
            dpg.set_value(f"slider_{str(active_vfo).lower()}_squelch",sq)
        case dpg.mvKey_Right:
            sq = radio.vfo_memory[active_vfo]['squelch'] + 2
            dpg.set_value(f"slider_{str(active_vfo).lower()}_squelch",sq)
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

    with dpg.window(tag="radio_window", show=True, label="Radio Front Panel", width=580, height=530, pos=[0,20], no_move=True, user_data={"protocol": protocol}):
        # === Hyper Mem Buttons A-F ===
        with dpg.group(horizontal=True):
            dpg.add_text("Hyper Memories: ", indent=15)
            for label in ["A", "B", "C", "D", "E", "F"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": f"H{label}", "protocol": protocol, "vfo": RADIO_VFO.NONE})
            dpg.add_spacer(width=10)
            dpg.add_button(label="Single VFO", width=90, callback=button_callback, user_data={"label": "Single VFO", "protocol": protocol, "vfo": RADIO_VFO.NONE})
        dpg.add_spacer(height=5)
        dpg.add_separator()
        dpg.add_spacer(height=3)

        # === PREF/SKIP Channel Icons ===
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=70)
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

        dpg.add_button(label="PTT", pos=(240,423), width=60, height=60, callback=button_callback, user_data={"label": "PTT", "protocol": protocol, "vfo": RADIO_VFO.MIC})

     # === Connection Window ===
    with dpg.window(label="Connection", width=660, height=545, tag="connection_window", no_move=True):
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

            dpg.add_button(label="Connect", tag="connect_button", indent=5, width=100, callback=port_selected_callback, user_data={"comport": comport, "baudrate": baudrate, "protocol": protocol})
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

        if len(available_ports) == 0:
            dpg_notification_window(title="Error", message="No COM ports available for connection!")
        
    with dpg.handler_registry():
        dpg.add_key_press_handler(callback=handle_key_press)

async def main():
    global TCP,debug,protocol,is_user_admin
    parser = argparse.ArgumentParser(description="Example Python app with command-line arguments.")
    parser.add_argument('-b', '--baudrate', type=str, help='Radio Baudrate')
    parser.add_argument('-c', '--comport', type=str, help='Radio COM Port')
    parser.add_argument('-d', '--debug', action="store_true", help='Enable debug output')
    parser.add_argument('-l', '--list-comports', action="store_true", help='List available COM ports')
    parser.add_argument('-p', '--server-password', type=str, help='Server login password')
    parser.add_argument('-sH', '--server-host-ip', type=str, help='Server hostname/ip')
    parser.add_argument('-sP', '--server-port', type=str, help='Server port')
    parser.add_argument('-s', '--start-server', action="store_true", help='Start server')
    args = parser.parse_args()

    radio = SerialRadio(dpg)
    protocol = SerialProtocol(radio)
    radio.protocol = protocol

    if args.debug:
        debug = True

    if args.list_comports:
        available_ports = serial.tools.list_ports.comports()
        for port in available_ports:
            print(f"{port.device}: {port.description}")
        return

    if args.server_port:
        if int(args.server_port) < 1024 and is_user_admin == False and platform.system() == "Linux":
            print("Ports below 1024 require admin privileges")
            exit

    if args.start_server:
        if args.comport and args.baudrate:
            if args.server_password:
                password = args.server_password
            else:
                print("*Enter password for CAT server*")
                password = getpass()
                if password == None:
                    password = ""
            radio.dpg_enabled = False
            print("\nStarting command line server...")

            if not loop.is_running():
                threading.Thread(target=start_event_loop, daemon=True).start()
                protocol.reset_ready()

            TCP.tcpserver_future = asyncio.run_coroutine_threadsafe(
                TCP.start_tcp_server(host=args.server_host_ip, port=args.server_port, password=password, protocol=protocol),
                loop
            )

            while TCP.tcpserver_ready == False:
                await asyncio.sleep(2)

            asyncio.run_coroutine_threadsafe(
                connect_serial_async(protocol, args.comport, args.baudrate),
                loop
            )

            while True:
                await asyncio.sleep(10)
        else:
            print("A COM Port and Baud Rate are required to start the command line server!")

    if radio.dpg_enabled == True:
        dpg.create_context()
        build_gui(protocol)
        dpg.create_viewport(title="TYT TH9800 CAT Control", width=575, height=580, resizable=False)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    try:
        if radio.dpg_enabled == True:
            await run_dpg()
        else:
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        if protocol.transport != None:
            protocol.transport.close()
        if radio.dpg_enabled == True:
            dpg.destroy_context()

if __name__ == "__main__":
    asyncio.run(main())
