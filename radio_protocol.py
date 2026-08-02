"""
Portable radio-protocol core: packet framing/checksum, the TX command
state machine, and the rigctl/CAT server. No hard dependency on
anything outside the standard library (DearPyGui and logging are
imported optionally, purely for the desktop app's live display/log
file) - this is what the future ESP32/MicroPython firmware will
import directly instead of being hand-ported.
"""

from time import sleep
import re

try:
    import logging
except ImportError:
    logging = None  # Not available on MicroPython

try:
    import dearpygui.dearpygui as dpg
except ImportError:
    dpg = None  # Headless mode - no GUI

from TH9800_Enums import *

debug = False
log = False

def printd(msg):
    if debug == True:
        print(msg)

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
            for icon in RADIO_RX_ICON.all():
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

    def get_vfo_str(self, vfo: RADIO_VFO):
        match vfo:
            case RADIO_VFO.LEFT:
                return "L"
            case RADIO_VFO.RIGHT:
                return "R"
            case _:
                return "L"

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

    def show_rts_state(self, state: bool):
        if self.dpg_enabled == False:
            return
        label = "USB Controlled" if state else "Radio Controlled"
        color = "green" if state else "red"
        for tag in ("rts_text", "fp_rts_text"):
            dpg.set_value(tag, label)
            self.set_dpg_theme(tag=tag, color=color)

    def show_dtr_state(self, state: bool):
        if self.dpg_enabled == False:
            return
        self.set_dpg_theme(tag="dtr_button", color="green" if state else "red")

    def set_active_vfo(self, vfo: RADIO_VFO):
        printd(f"Current VFO: {self.vfo_memory['vfo_active']}")
        vfo_name = str(vfo)
        if self.vfo_memory['vfo_active'] != vfo:
            printd(f"Set MAIN VFO to {vfo_name}")
            self.exe_cmd(cmd=RADIO_TX_CMD.get(f"{vfo_name}_DIAL_PRESS"))
        
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

    def set_volume(self, vfo: RADIO_VFO, vol: int = 25):
        if vol < 0:
            vol = 0
        elif vol > 100:
            vol = 100

        vfo = str(vfo)
        if self.dpg_enabled and dpg:
            dpg.set_value(f"slider_{vfo.lower()}_volume",vol)
        payload = self.packet.vol_sq_to_packet(value=vol)
        cmd = RADIO_TX_CMD.get(f"{vfo}_VOLUME")
        self.vfo_memory[self.get_vfo(vfo=vfo)]['volume'] = vol
        
        printd(f"Set {vfo}_VOLUME: {str(vol)}")
        self.exe_cmd(cmd=cmd, payload=payload)

    def set_squelch(self, vfo: RADIO_VFO, sq: int = 25):
        if sq < 0:
            sq = 0
        elif sq > 100:
            sq = 100

        vfo = str(vfo)
        if self.dpg_enabled and dpg:
            dpg.set_value(f"slider_{vfo.lower()}_squelch",sq)
        payload = self.packet.vol_sq_to_packet(value=sq)
        cmd = RADIO_TX_CMD.get(f"{vfo}_SQUELCH")
        self.vfo_memory[self.get_vfo(vfo=vfo)]['squelch'] = sq
        
        printd(f"Set {vfo}_SQUELCH: {str(sq)}")
        self.exe_cmd(cmd=cmd, payload=payload)

    def get_freq(self, vfo: RADIO_VFO):
        vfo_name = str(vfo)
        if self.vfo_memory[vfo]['operating_mode'] == int(RADIO_VFO_TYPE.VFO):
            return self.vfo_memory[vfo]['frequency']
        elif self.vfo_memory[vfo]['operating_mode'] == int(RADIO_VFO_TYPE.MEMORY):
            self.exe_cmd(cmd=RADIO_TX_CMD.get(f"{vfo_name}_LOW_HOLD"))
            self.exe_cmd(cmd=RADIO_TX_CMD.get(f"{vfo_name}_LOW_HOLD"))

    def set_freq(self, vfo: RADIO_VFO, freq: str):
        for n in freq:
            cmd_pkt_all = b''
            cmd = RADIO_TX_CMD.get(f"MIC_{n}")
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

def update_signal(radio: SerialRadio, vfo: RADIO_VFO, s_value: int):
    vfo2 = vfo.lower()
    if log == True:
        logging.info(f'{str(vfo)} sig: {str(s_value)}')
    if s_value == 0:
        percent = 0
    else:
        percent = (s_value - 1) / 8  # Map S1–S9 to 0.0–1.0 range
    if radio.dpg_enabled == True:
        dpg.set_value(f"icon_{vfo2}_signal", percent)
        dpg.configure_item(f"icon_{vfo2}_signal",overlay=f"S{s_value}")

class SerialPacket:
    def __init__(self, protocol: "SerialProtocol" = None):
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
            case RADIO_RX_CMD.DISPLAY_TEXT:
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
                    case 0x40 | 0xC0:
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
            case RADIO_RX_CMD.CHANNEL_TEXT:
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
            case RADIO_RX_CMD.DISPLAY_CHANGE:
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
            case RADIO_RX_CMD.DISPLAY_ICONS:
                self.process_display_packet(packet=packet_data)
            case RADIO_RX_CMD.ICON_SET:
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
            case RADIO_RX_CMD.ICON_MAIN:
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
            case RADIO_RX_CMD.ICON_TX:
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
            case RADIO_RX_CMD.ICON_BUSY:
                match packet_data[0]:
                    case 0x00:
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.SIGNAL, value=False)
                    case 0x01:
                        self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.SIGNAL, value=True)
                    case 0x80:
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.SIGNAL, value=False)
                    case 0x81:
                        self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.SIGNAL, value=True)
            case RADIO_RX_CMD.ICON_SIG_BARS:
                sig = packet_data[0]
                if sig >= 0x00 and sig <= 0x09:
                    update_signal(radio=self.radio,vfo=RADIO_VFO.LEFT,s_value=sig)
                elif sig >= 0x80 and sig <= 0x89:
                    sig = sig - 0x80
                    update_signal(radio=self.radio,vfo=RADIO_VFO.RIGHT,s_value=sig)
                else:
                    printd(f"OSIG: {sig}")
            case RADIO_RX_CMD.ICON_DOT_1ST:
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
            case RADIO_RX_CMD.STARTUP_1:
                match packet_data[0]:
                    case 0x00:
                        if self.radio.startup == False:
                            self.radio.startup = True
                            self.radio.connect_process = False
                            printd("\n*******Startup initiated*******")
                        self.protocol.send_packet(self.create_tx_packet(payload=bytes([0xF0])))
            case RADIO_RX_CMD.STARTUP_2:
                match packet_data[0]:
                    case 0x00:
                        #Send Vol/Sql for each VFO
                        self.radio.exe_cmd(cmd=RADIO_TX_CMD.L_VOLUME_SQUELCH)
                        self.radio.exe_cmd(cmd=RADIO_TX_CMD.R_VOLUME_SQUELCH)
            case RADIO_RX_CMD.STARTUP_3:
                match packet_data[0]:
                    case 0x20:
                        self.protocol.send_packet(self.create_tx_packet(payload=bytes([0xA0,0x18,0x02])))
            case _:
                printd(f"Unkown pkt: {packet.hex().upper()}")

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
                printd(f"SIGNAL PACKET! SIG:{packet[1]}")
        for x in range(2,6+1):
            icon_byte = packet[x]
            icon_map = self.display_packets_icon_map[x]
            enabled_icons = [name for bit, name in icon_map.items() if icon_byte & bit]
            disabled_icons = [name for bit, name in icon_map.items() if not icon_byte & bit]
            if "L" in disabled_icons and "M" in disabled_icons:
                enabled_icons += ["H"]
            for icon in enabled_icons:
                self.radio.set_icon(vfo=vfo,icon=RADIO_RX_ICON.get(icon),value=True)
            for icon in disabled_icons:
                if icon == "H" and "H" in enabled_icons:
                    continue
                self.radio.set_icon(vfo=vfo,icon=RADIO_RX_ICON.get(icon),value=False)
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
