from TH9800_Enums import *
from time import sleep
import dearpygui.dearpygui as dpg
import serial.tools.list_ports
import serial_asyncio
import asyncio
import threading
import re

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
debug = False

def start_event_loop():
    loop.run_forever()

threading.Thread(target=start_event_loop, daemon=True).start()

def printd(msg):
    if debug == True:
        print(msg)

class SerialRadio:
    def __init__(self, dpg: dpg = None, protocol = None):
        self.packet = SerialPacket()
        self.protocol = protocol
        
        self.dpg = dpg
        self.dpg_enabled = True
        
        self.menu_open = False
        self.connect_process = False
        self.startup = False
        
        self.vfo_change = False
        self.vfo_active = RADIO_VFO.LEFT
        self.vfo_active_processing = RADIO_VFO.LEFT
        self.vfo_type = {}
        self.vfo_type[RADIO_VFO.LEFT] = RADIO_VFO_TYPE.VFO
        self.vfo_type[RADIO_VFO.RIGHT] = RADIO_VFO_TYPE.VFO
        self.vfo_text = ""
        self.vfo_channel = ""
        self.mic_ptt = False
        self.mic_ptt_disabled = False

        self.icons = {}
        self.icons[RADIO_VFO.NONE] = {}
        self.icons[RADIO_VFO.LEFT] = {}
        self.icons[RADIO_VFO.RIGHT] = {}
        for icon in RADIO_RX_ICON:
            self.icons[RADIO_VFO.NONE].update({f"{icon.name}": False})
            self.icons[RADIO_VFO.LEFT].update({f"{icon.name}": False})
            self.icons[RADIO_VFO.RIGHT].update({f"{icon.name}": False})
        self.icons[RADIO_VFO.LEFT]['SIGNAL'] = 0
        self.icons[RADIO_VFO.RIGHT]['SIGNAL'] = 0

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

    def switch_vfo_type(self, vfo: RADIO_VFO):
        match self.vfo_type[vfo]:
            case RADIO_VFO_TYPE.MEMORY:
                self.vfo_type[vfo] = RADIO_VFO_TYPE.VFO
            case RADIO_VFO_TYPE.VFO:
                self.vfo_type[vfo] = RADIO_VFO_TYPE.MEMORY
        printd(f"RADIO VFO TYPE set to {self.vfo_type[vfo]}")

    def set_dpg_theme(self, tag, color):
        if self.dpg_enabled == False:
            return
        match color:
            case "red":
                color_value = (255, 0, 0, 255)
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
        printd(f"Current VFO: {self.vfo_active}")
        vfo_name = str(vfo)
        if self.vfo_active != vfo:
            printd(f"Set MAIN VFO to {vfo_name}")
            self.exe_cmd(cmd=RADIO_TX_CMD[f"{vfo_name}_DIAL_PRESS"])
        
    def set_icon(self, vfo: RADIO_VFO, icon: RADIO_RX_ICON, value):
        vfo_name = str(vfo).lower()
        icon_name = str(icon).lower()
        self.icons[vfo][icon_name.upper()] = value
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
                    self.vfo_active = vfo
                    printd(f"*****MAIN VFO SET TO: {self.vfo_active}")
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

    def set_volume(self, vfo: RADIO_VFO, vol: int = 25):
        vfo = str(vfo)
        payload = self.packet.vol_sq_to_packet(value=vol)
        cmd = RADIO_TX_CMD[f"{vfo}_VOLUME"]
        
        self.exe_cmd(cmd=cmd, payload=payload)

    def set_squelch(self, vfo: RADIO_VFO, sq: int = 25):
        vfo = str(vfo)
        payload = self.packet.vol_sq_to_packet(value=sq)
        cmd = RADIO_TX_CMD[f"{vfo}_SQUELCH"]
        
        self.exe_cmd(cmd=cmd, payload=payload)

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
                cmd_data2 = self.get_cmd_pkt(cmd=RADIO_TX_CMD.DEFAULT)
                cmd_pkt2 = self.packet.create_tx_packet(payload=cmd_data2)
                cmd_pkt += cmd_pkt2
        
        self.protocol.send_packet(cmd_pkt)

class SerialProtocol(asyncio.Protocol):
    def __init__(self, radio: SerialRadio):
        self.transport = None
        self.ready = asyncio.Event()
        self.receive_queue = asyncio.Queue()
        self.buffer = bytearray()
        self.radio = radio

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
        if self.transport and not self.transport.is_closing():
            printd(f"Sending: {data.hex().upper()}")
            self.transport.write(data)
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
                        elif self.radio.menu_open == True and self.radio.vfo_active_processing == self.radio.vfo_active and self.radio.connect_process == False:
                            printd(f"{str(self.radio.vfo_active_processing)}<***Set Menu [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                        elif self.radio.connect_process == False:
                            if radio_channel.find("HP") != -1:
                                printd(f"{str(self.radio.vfo_active_processing)}<***Radio Power [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                            else:
                                printd(f"{str(self.radio.vfo_active_processing)}<***Set Channel [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"ch_{str(self.radio.vfo_active_processing).lower()}_display",radio_channel)
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
            case RADIO_RX_CMD.CHANNEL_TEXT.value:
                if self.radio.vfo_change == True:
                    return
                self.radio.vfo_channel = packet_data[2:5].decode().strip()

                match packet_data[0]:
                    case 0x40 | 0x60:
                        self.radio.vfo_type[RADIO_VFO.LEFT] = RADIO_VFO_TYPE.MEMORY
                        if packet_data[0] == 0x60:
                            if self.radio.dpg_enabled == True:
                                dpg.set_value(f"ch_{str(self.radio.vfo_active_processing).lower()}_display",self.radio.vfo_channel)
                    case 0xC0 | 0xE0:
                        self.radio.vfo_type[RADIO_VFO.RIGHT] = RADIO_VFO_TYPE.MEMORY
            case RADIO_RX_CMD.DISPLAY_CHANGE.value:
                match packet_data[0]:
                    case 0x43:
                        self.radio.vfo_active_processing = RADIO_VFO.LEFT
                        self.radio.vfo_channel = ""
                    case 0xC3:
                        self.radio.vfo_active_processing = RADIO_VFO.RIGHT
                        self.radio.vfo_channel = ""
                    case 0x03:
                        self.radio.vfo_change = False
                        printd("vfo_change: False")
                    case 0x83:
                        if self.radio.startup == True:
                            self.radio.startup = False
                            printd("*******Startup complete*******\n")
                        self.radio.vfo_change = False
                        printd("vfo_change: False")
                        if self.radio.connect_process == True:
                            self.radio.connect_process = False
            case RADIO_RX_CMD.DISPLAY_ICONS.value:
                self.process_display_packet(packet=packet_data)
            case RADIO_RX_CMD.ICON_SET.value:
                match packet_data[0]:
                    case 0x00:
                        if self.radio.menu_open == True:
                            printd(f"{str(self.radio.vfo_active)}<***Menu Closed***>{str(self.radio.vfo_active)}")
                            self.radio.menu_open = False
                            self.radio.set_icon(vfo=RADIO_VFO.NONE, icon=RADIO_RX_ICON.SET, value=False)
                    case 0x01:
                        printd(f"{str(self.radio.vfo_active)}<***Menu Opened***>{str(self.radio.vfo_active)}")
                        self.radio.menu_open = True
                        self.radio.set_icon(vfo=RADIO_VFO.NONE, icon=RADIO_RX_ICON.SET, value=True)
                        
            case RADIO_RX_CMD.ICON_MAIN.value:
                match packet_data[0]:
                    case 0x01:
                        self.radio.vfo_active = RADIO_VFO.LEFT
                        self.radio.vfo_change = True
                        printd(f"{str(self.radio.vfo_active)}<***Left  VFO Activated***>{str(self.radio.vfo_active)}")
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.MAIN, value=False)
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.MAIN, value=True)
                    case 0x81:
                        self.radio.vfo_active = RADIO_VFO.RIGHT
                        self.radio.vfo_change = True
                        printd(f"{str(self.radio.vfo_active)}<***Right VFO Activated***>{str(self.radio.vfo_active)}")
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
                    update_signal(vfo=RADIO_VFO.LEFT,s_value=sig)
                elif sig >= 0x80 and sig <= 0x89:
                    sig = sig - 0x80
                    update_signal(vfo=RADIO_VFO.RIGHT,s_value=sig)
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
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
                    case 0x41:
                        self.radio.vfo_active_processing = RADIO_VFO.LEFT
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text_formatted)
                    case 0xC0:
                        self.radio.vfo_active_processing = RADIO_VFO.RIGHT
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"vfo_{str(self.radio.vfo_active_processing).lower()}_display",radio_text)
                    case 0xC1:
                        self.radio.vfo_active_processing = RADIO_VFO.RIGHT
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
                self.radio.icons[vfo]['SIGNAL'] = 0x00
            case _:
                self.radio.icons[vfo]['SIGNAL'] = packet[1]
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

def update_signal(vfo: RADIO_VFO, s_value: int):
    vfo = vfo.value.lower()
    if s_value == 0:
        percent = 0
    else:
        percent = (s_value - 1) / 8  # Map S1–S9 to 0.0–1.0 range
    if self.radio.dpg_enabled == True:
        dpg.set_value(f"icon_{vfo}_signal", percent)
        dpg.configure_item(f"icon_{vfo}_signal",overlay=f"S{s_value}")

def refresh_comports_callback(sender, app_data, user_data):
    ports = []
    available_ports = serial.tools.list_ports.comports()
    for port in available_ports:
        ports.append(f"{port.device}: {port.description}")
        printd(f"{port.device} - {port.manufacturer} - {port.description}")
    dpg.configure_item("com_port", items=ports)
    dpg.configure_item("com_port", default_value=ports[0] if available_ports else "")

def cancel_callback(sender, app_data, user_data):
    modal_id = user_data[0]
    dpg.configure_item(modal_id, show=False)

def button_callback(sender, app_data, user_data):
    label = user_data["label"]
    if user_data["vfo"] == RADIO_VFO.LEFT or user_data["vfo"] == RADIO_VFO.RIGHT or user_data["vfo"] == RADIO_VFO.MIC or user_data["vfo"] == RADIO_VFO.NONE:
        vfo = user_data["vfo"].value
    else:
        vfo = user_data["vfo"]
    protocol = user_data["protocol"]
    radio = protocol.radio

    match label.upper():
        case "SINGLE VFO":
            radio.exe_cmd(cmd=RADIO_TX_CMD['L_VOLUME_HOLD'])
            return
        case "SET FREQ":
            if radio.vfo_type[radio.vfo_active] == RADIO_VFO_TYPE.MEMORY:
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
            radio.set_freq(vfo=radio.vfo_active,freq=freq)
            return
        case "VM":
            radio.switch_vfo_type(vfo=user_data["vfo"])
        case "PTT":
            if radio.mic_ptt == False:
                radio.mic_ptt = True
            else:
                radio.mic_ptt = False
        case "*":
            label = "STAR"
        case "#":
            label = "POUND"
            

    if vfo == RADIO_VFO.LEFT.value or vfo == RADIO_VFO.RIGHT.value or vfo == RADIO_VFO.MIC.value or vfo == RADIO_VFO.NONE.value:
        radio.exe_cmd(cmd=RADIO_TX_CMD[f"{vfo}_{label}"])
    else:
        match label:
            case "HA"|"HB"|"HC"|"HD"|"HE"|"HF":
                radio.exe_cmd(cmd=RADIO_TX_CMD[f"HYPER_{label.replace("H","")}"])

    printd(f"Sent {label} button command for {vfo} VFO.") #: {packet.hex().upper()}")

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

async def connect_serial_async(protocol, com_port, baudrate):
    radio = protocol.radio
    packet = SerialPacket()

    try:
        transport, _ = await serial_asyncio.create_serial_connection(
            asyncio.get_event_loop(), lambda: protocol, com_port, baudrate=baudrate
        )
        await protocol.ready.wait()
        printd(f"Connected to {com_port} at {baudrate} baud.")
        if radio.dpg_enabled == True:
            dpg.configure_item("radio_window", show=True)
            dpg.configure_item("connection_window", collapsed=True)
            dpg.configure_item("connect_button", label="Disconnect")
        asyncio.create_task(read_loop(protocol))
        radio.connect_process = True

        radio.exe_cmd(cmd=RADIO_TX_CMD.STARTUP)
        await asyncio.sleep(0.5)
        radio.exe_cmd(cmd=RADIO_TX_CMD.L_VOLUME_SQUELCH)
        await asyncio.sleep(0.5)
        radio.exe_cmd(cmd=RADIO_TX_CMD.R_VOLUME_SQUELCH)
        
        return transport
    except Exception as e:
        printd(f"Connection failed: {e}")
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
    com_port = dpg.get_value("com_port")
    baudrate = dpg.get_value("baud_rate")
    
    if label == "Disconnect":
        protocol.transport.close()
        print(f"{com_port} disconnected.\n")
        dpg.configure_item("connect_button", label="Connect")
        return

    try:
        com_port = com_port[0:com_port.index(":")]
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
        connect_serial_async(protocol, com_port, baudrate),
        loop
    )

async def run_dpg():
    while dpg.is_dearpygui_running():
        dpg.render_dearpygui_frame()
        await asyncio.sleep(1/60)

async def read_loop(protocol: SerialProtocol):
    while True:
        packet = await protocol.receive_queue.get()
        packet_processor = SerialPacket(protocol=protocol).process_rx_packet(packet=packet)
        """
        #printd("Processed from queue:", packet.decode('utf-8', errors='ignore'))
        #printd("Byte Array:", packet.hex().upper())
        #printd("CMD:(",bytes([packet_cmd]).hex().upper(),") Data:(",packet_data.hex().upper(),")")
        """

def build_gui(protocol):
    ports = []
    available_ports = serial.tools.list_ports.comports()
    for port in available_ports:
        ports.append(f"{port.device}: {port.description}")
        printd(f"{port.device} - {port.manufacturer} - {port.description}")

    with dpg.theme() as black_text_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (37, 37, 38, 255)) #(255, 0, 0, 255) (37, 37, 38, 255)

    with dpg.window(tag="radio_window", show=False, label="Radio Front Panel", width=580, height=530, pos=[0,20], no_move=True, user_data={"protocol": protocol}):
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

        # === VFO Volume Slider ===
        with dpg.group(horizontal=True):
            dpg.add_text("SQ:",indent=32)
            dpg.add_slider_int(width=100, default_value=25, max_value=100, callback=sq_callback, user_data={"label": "SQ", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=61)
            dpg.add_text("APO", tag="icon_apo")#, show=False)
            dpg.bind_item_theme("icon_apo", black_text_theme)
            #dpg.add_text("LOCK", tag="icon_lock")#, show=False)
            #dpg.bind_item_theme("icon_lock", black_text_theme)
            dpg.add_spacer(width=32)
            dpg.add_text("SQ:")
            dpg.add_slider_int(width=100, default_value=25, max_value=100, callback=sq_callback, user_data={"label": "SQ", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
        
        # === VFO Squelch Slider ===
        with dpg.group(horizontal=True):
            dpg.add_text("VOL:",indent=25)
            dpg.add_slider_int(width=100, default_value=25, max_value=100, callback=vol_callback, user_data={"label": "VOL", "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=58)
            dpg.add_text("LOCK", tag="icon_lock")#, show=False)
            dpg.bind_item_theme("icon_lock", black_text_theme)
            dpg.add_spacer(width=21)
            dpg.add_text("VOL:")
            dpg.add_slider_int(width=100, default_value=25, max_value=100, callback=vol_callback, user_data={"label": "VOL", "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
        
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
            dpg.add_button(label=".", width=40, height=20, callback=button_callback, user_data={"label": "MENU", "protocol": protocol, "vfo": RADIO_VFO.NONE})

            dpg.add_spacer(width=10)

            # VFO Right Buttons
            for label in ["LOW", "V/M", "HM", "SCN"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label.replace("/",""), "protocol": protocol, "vfo": RADIO_VFO.RIGHT})

            dpg.add_text("<KEY2", tag="icon_key2")#, show=False)
            dpg.bind_item_theme("icon_key2", black_text_theme)
        dpg.add_spacer(height=5)
        
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=10)
            dpg.add_progress_bar(default_value=0.0, tag="icon_l_signal", overlay="S0", width=185)
            dpg.add_spacer(width=18)
            dpg.add_text("SET", tag="icon_set")#, show=False)
            dpg.bind_item_theme("icon_set", black_text_theme)
            dpg.add_spacer(width=21)
            dpg.add_progress_bar(default_value=0.0, tag="icon_r_signal", overlay="S0", width=185)

        dpg.add_spacer(height=50)
        dpg.add_separator()
        dpg.add_spacer(height=10)

        # === MICROPHONE Keypad ===
        mic_spacer_width = 20
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["1", "2", "3", "A"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol,"vfo": RADIO_VFO.MIC})
            dpg.add_spacer(width=130)
            dpg.add_button(label="Set Freq", width=80, callback=button_callback, user_data={"label": "Set Freq", "protocol": protocol,"vfo": RADIO_VFO.MIC})
            dpg.add_input_text(tag="setfreq_text", decimal=True, no_spaces=True, width=80, default_value="")
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=mic_spacer_width)
            for label in ["4", "5", "6", "B"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.MIC})
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
                    tag="com_port",
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
            com_port = ""
            baudrate = ""
            com_port = dpg.get_value("com_port")
            baudrate = dpg.get_value("baud_rate")

            dpg.add_button(label="Connect", tag="connect_button", indent=5, width=100, callback=port_selected_callback, user_data={"com_port": com_port, "baudrate": baudrate, "protocol": protocol})

        if len(available_ports) == 0:
            with dpg.window(label="Error", modal=True, no_close=True) as modal_id:
                dpg.add_text("No COM ports available for connection!")
                dpg.add_button(label="Ok", width=75, user_data=(modal_id, True), callback=cancel_callback)
            dpg.set_item_pos(modal_id, [120, 100])

async def main():
    radio = SerialRadio(dpg)
    protocol = SerialProtocol(radio)
    radio.protocol = protocol

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
