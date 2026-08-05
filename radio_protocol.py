from time import sleep
import re
import asyncio

from TH9800_Enums import *

debug = False

def printd(msg):
    if debug == True:
        print(msg)

class SerialRadio:
    def __init__(self, protocol = None, on_update = None):
        self.packet = SerialPacket()
        self.protocol = protocol

        self.rigctl_server = False
        self.cat = None

        self.on_update = on_update

        self.menu_open = False
        self.connect_process = False
        self.startup = False

        vfo_defaults = {
            "name": "",
            "channel": -1,
            "frequency": 0,
            "mode": "FM",
            "operating_mode": int(RADIO_VFO_TYPE.MEMORY),
            "width": 2500,
            "ptt": 0,
            "volume": 25,
            "squelch": 25,
        }
        self.vfo_memory = {
            'vfo_active': RADIO_VFO.LEFT,
            RADIO_VFO.NONE: {"icons": {}},
            RADIO_VFO.LEFT: dict(vfo_defaults, icons={}),
            RADIO_VFO.RIGHT: dict(vfo_defaults, icons={}),
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

    _VFO_FROM_LETTER = {"L": RADIO_VFO.LEFT, "R": RADIO_VFO.RIGHT}

    def get_vfo(self, vfo: str):
        return self._VFO_FROM_LETTER.get(vfo.upper(), RADIO_VFO.LEFT)

    _LETTER_FROM_VFO = {RADIO_VFO.LEFT: "L", RADIO_VFO.RIGHT: "R"}

    def get_vfo_str(self, vfo: RADIO_VFO):
        return self._LETTER_FROM_VFO.get(vfo, "L")

    def _notify(self, event, **kwargs):
        if self.on_update:
            self.on_update(event, **kwargs)

    def get_cmd_pkt(self, cmd: RADIO_TX_CMD, payload: bytes = None):
        cmd_name = cmd.name
        cmd_data = cmd.data
        if cmd_name.find("SQUELCH") != -1 or cmd_name.find("VOLUME") != -1:
            if payload == None:
                return cmd_data
            elif cmd_name.find("SQUELCH") != -1:
                return (cmd_data[0:9] + payload + bytearray([cmd_data[11]]))
            elif cmd_name.find("VOLUME") != -1:
                return (cmd_data[0:6] + payload + cmd_data[8:12])
        else:
            return cmd_data

    _TOGGLE_VFO_TYPE = {RADIO_VFO_TYPE.MEMORY: RADIO_VFO_TYPE.VFO, RADIO_VFO_TYPE.VFO: RADIO_VFO_TYPE.MEMORY}

    def switch_vfo_op_mode(self, vfo: RADIO_VFO):
        return
        current = self.vfo_memory[vfo]['operating_mode']
        if current in self._TOGGLE_VFO_TYPE:
            self.vfo_memory[vfo]['operating_mode'] = self._TOGGLE_VFO_TYPE[current]
        printd(f"RADIO VFO TYPE0 set to {self.vfo_memory[vfo]['operating_mode']}")

    def show_rts_state(self, state: bool):
        label = "USB Controlled" if state else "Radio Controlled"
        color = "green" if state else "red"
        self._notify("rts_state", label=label, color=color)

    def show_dtr_state(self, state: bool):
        color = "green" if state else "red"
        self._notify("dtr_state", color=color)

    def set_active_vfo(self, vfo: RADIO_VFO):
        printd(f"Current VFO: {self.vfo_memory['vfo_active']}")
        vfo_name = str(vfo)
        if self.vfo_memory['vfo_active'] != vfo:
            printd(f"Set MAIN VFO to {vfo_name}")
            self.exe_cmd(cmd=RADIO_TX_CMD.get(f"{vfo_name}_DIAL_PRESS"))

    def _icon_tag_am(self, vfo, vfo_name, icon_name, value):
        return f"icon_l_{icon_name}"

    def _icon_tag_busy(self, vfo, vfo_name, icon_name, value):
        return None

    def _icon_tag_menu_group(self, vfo, vfo_name, icon_name, value):
        return f"icon_{icon_name}"

    def _icon_tag_main(self, vfo, vfo_name, icon_name, value):
        tag = f"icon_{vfo_name}_{icon_name}"
        if value == True:
            self.vfo_memory['vfo_active'] = vfo
            printd(f"*****MAIN VFO SET TO: {self.vfo_memory['vfo_active']}")
        return tag

    def _icon_tag_default(self, vfo, vfo_name, icon_name, value):
        return f"icon_{vfo_name}_{icon_name}"

    _ICON_TAG_HANDLERS = {
        RADIO_RX_ICON.AM: _icon_tag_am,
        RADIO_RX_ICON.BUSY: _icon_tag_busy,
        RADIO_RX_ICON.APO: _icon_tag_menu_group,
        RADIO_RX_ICON.LOCK: _icon_tag_menu_group,
        RADIO_RX_ICON.SET: _icon_tag_menu_group,
        RADIO_RX_ICON.KEY2: _icon_tag_menu_group,
        RADIO_RX_ICON.MAIN: _icon_tag_main,
    }

    def set_icon(self, vfo: RADIO_VFO, icon: RADIO_RX_ICON, value):
        vfo_name = str(vfo).lower()
        icon_name = str(icon).lower()
        self.vfo_memory[vfo]['icons'][icon_name.upper()] = value

        handler = self._ICON_TAG_HANDLERS.get(icon, SerialRadio._icon_tag_default)
        tag = handler(self, vfo, vfo_name, icon_name, value)
        if tag is None:
            return

        if value == True or value > 0x00:
            color = "red"
        elif value == False or value == 0x00:
            if icon == RADIO_RX_ICON.SIGNAL:
                color = "white"
            else:
                color = "black"
        else:
            color = "black"

        self._notify("icon_color", tag=tag, color=color)

    def set_volume(self, vfo: RADIO_VFO, vol: int = 25):
        if vol < 0:
            vol = 0
        elif vol > 100:
            vol = 100

        vfo = str(vfo)
        self._notify("slider", kind="volume", vfo=vfo, value=vol)
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
        self._notify("slider", kind="squelch", vfo=vfo, value=sq)
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
            sleep(.20)

    def exe_cmd(self, cmd: RADIO_TX_CMD, payload: bytes = None):
        cmd_name = cmd.name
        cmd_data = self.get_cmd_pkt(cmd=cmd,payload=payload)

        if cmd == RADIO_TX_CMD.L_SET_VFO:
            self.set_active_vfo(vfo=RADIO_VFO.LEFT)
            return
        if cmd == RADIO_TX_CMD.R_SET_VFO:
            self.set_active_vfo(vfo=RADIO_VFO.RIGHT)
            return

        if self.mic_ptt == True and re.match(r"MIC_(UP|DOWN|P\d+)",cmd_name):
            printd("Ignoring keypress...")
            return
        elif self.mic_ptt == True and (cmd_name.find("MIC") != -1 or cmd_name.find("HM") != -1):
            printd("*****mic_ptt=True, setting 0x00 on MIC btn*****")
            cmd_data[1] = 0x00

        cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)

        if cmd_name.find("LEFT") == -1 and cmd_name.find("RIGHT") == -1 and cmd_name != "L_VOLUME" and cmd_name != "L_SQUELCH" and cmd_name != "R_VOLUME" and cmd_name != "R_SQUELCH":
            if cmd_name == "MIC_PTT" and self.mic_ptt == True:
                printd("***MIC PTT***")
            elif cmd_name == "MIC_PTT" and self.mic_ptt == False:
                cmd_data = self.get_cmd_pkt(cmd=RADIO_TX_CMD.DEFAULT)
                cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)
                self.mic_ptt_disabled = True
            elif (cmd_name.find("MIC") != -1 or cmd_name.find("HM") != -1) and self.mic_ptt == True:
                self.protocol.send_packet(cmd_pkt)
                sleep(.25)

                printd(f"MIC pkt: {cmd_pkt.hex().upper()}")
                cmd_data = self.get_cmd_pkt(cmd=RADIO_TX_CMD.MIC_PTT)
                cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)
                printd(f"*****PTT replay: {cmd_pkt.hex().upper()}*****")
            else:
                self.protocol.send_packet(cmd_pkt)
                sleep(.1)
                cmd_data2 = self.get_cmd_pkt(cmd=RADIO_TX_CMD.DEFAULT)
                cmd_pkt = self.packet.create_tx_packet(payload=cmd_data2)

        self.protocol.send_packet(cmd_pkt)

def update_signal(radio: SerialRadio, vfo: RADIO_VFO, s_value: int):
    vfo2 = vfo.lower()
    if debug == True:
        printd(f'{str(vfo)} sig: {str(s_value)}')
    if s_value == 0:
        percent = 0
    else:
        percent = (s_value - 1) / 8
    radio._notify("signal", vfo=vfo2, percent=percent, s_value=s_value)

class SerialPacket:
    def __init__(self, protocol: "SerialProtocol" = None):
        self.start_bytes = bytes([0xAA,0xFD])
        self.packet = b''
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
        packet = self.start_bytes + bytes([packet_length]) + payload
        checksum = self.calculate_checksum(packet[2:])
        packet += bytes([checksum])
        self.packet = packet
        return bytearray(packet)

    def format_frequency(self, freq_str):
        freq_str = str(freq_str)
        if len(freq_str) <= 3:
            return freq_str
        return f"{freq_str[:-3]}.{freq_str[-3:]}"

    def _rx_display_text(self, packet_data):
        self.radio.vfo_text = packet_data[2:8].decode()
        radio_text = self.radio.vfo_text
        radio_channel = self.radio.vfo_channel
        if packet_data[0] == 0x00:
            self.radio.vfo_active_processing = RADIO_VFO.LEFT
        elif packet_data[0] == 0x80:
            self.radio.vfo_active_processing = RADIO_VFO.RIGHT
        if packet_data[0] in (0x60, 0x00, 0x80):
            printd(f"{str(self.radio.vfo_active_processing)}<***Set Freq Fast [{radio_channel}][{radio_text}]***>{str(self.radio.vfo_active_processing)}")
            radio_text = f"*{radio_text}*"
            self.radio.vfo_text = radio_text
            self.radio._notify("channel_display", vfo=self.radio.vfo_active_processing, channel=radio_channel)
            self.radio._notify("vfo_display", vfo=self.radio.vfo_active_processing, text=radio_text)
        elif packet_data[0] in (0x40, 0xC0):
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
            self.radio._notify("channel_display", vfo=self.radio.vfo_active_processing, channel=radio_channel)
            self.radio._notify("vfo_display", vfo=self.radio.vfo_active_processing, text=radio_text)

    def _rx_channel_text(self, packet_data):
        if self.radio.vfo_change == True:
            return
        self.radio.vfo_channel = packet_data[2:5].decode().strip()

        if packet_data[0] in (0x40, 0x60):
            if self.radio.menu_open == False:
                self.radio.vfo_memory[RADIO_VFO.LEFT]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
                printd(f"****RADIO VFO TYPE1 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")
            if packet_data[0] == 0x60:
                self.radio._notify("channel_display", vfo=self.radio.vfo_active_processing, channel=self.radio.vfo_channel)
        elif packet_data[0] in (0xC0, 0xE0):
            if self.radio.menu_open == False:
                self.radio.vfo_memory[RADIO_VFO.RIGHT]['operating_mode'] = int(RADIO_VFO_TYPE.MEMORY)
                printd(f"****RADIO VFO TYPE1 set to {self.radio.vfo_memory[self.radio.vfo_active_processing]['operating_mode']}")

    def _restore_vfo_text_cache(self, vfo):
        cached = self.radio.vfo_memory[vfo]
        self.radio.vfo_channel = str(cached['channel']) if cached['channel'] != -1 else ""
        self.radio.vfo_text = cached['name']

    def _rx_display_change(self, packet_data):
        if packet_data[0] == 0x43:
            self.radio.vfo_active_processing = RADIO_VFO.LEFT
            self._restore_vfo_text_cache(RADIO_VFO.LEFT)
        elif packet_data[0] == 0xC3:
            self.radio.vfo_active_processing = RADIO_VFO.RIGHT
            self._restore_vfo_text_cache(RADIO_VFO.RIGHT)
        elif packet_data[0] == 0x03:
            self.radio.vfo_change = False
        elif packet_data[0] == 0x83:
            if self.radio.startup == True:
                self.radio.startup = False
                printd("*******Startup complete*******\n")
            self.radio.vfo_change = False
            if self.radio.connect_process == True:
                self.radio.connect_process = False

    def _rx_display_icons(self, packet_data):
        self.process_display_packet(packet=packet_data)

    def _rx_icon_set(self, packet_data):
        if packet_data[0] == 0x00:
            if self.radio.menu_open == True:
                printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Menu Closed***>{str(self.radio.vfo_memory['vfo_active'])}")
                self.radio.menu_open = False
                self.radio.set_icon(vfo=RADIO_VFO.NONE, icon=RADIO_RX_ICON.SET, value=False)
        elif packet_data[0] == 0x01:
            printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Menu Opened***>{str(self.radio.vfo_memory['vfo_active'])}")
            self.radio.menu_open = True
            self.radio.set_icon(vfo=RADIO_VFO.NONE, icon=RADIO_RX_ICON.SET, value=True)

    def _rx_icon_main(self, packet_data):
        if packet_data[0] == 0x01:
            self.radio.vfo_memory['vfo_active'] = RADIO_VFO.LEFT
            self.radio.vfo_change = True
            printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Left  VFO Activated***>{str(self.radio.vfo_memory['vfo_active'])}")
            self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.MAIN, value=False)
            self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.MAIN, value=True)
        elif packet_data[0] == 0x81:
            self.radio.vfo_memory['vfo_active'] = RADIO_VFO.RIGHT
            self.radio.vfo_change = True
            printd(f"{str(self.radio.vfo_memory['vfo_active'])}<***Right VFO Activated***>{str(self.radio.vfo_memory['vfo_active'])}")
            self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.MAIN, value=True)
            self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.MAIN, value=False)

    def _rx_icon_tx(self, packet_data):
        if packet_data[0] == 0x00:
            self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.TX, value=False)
            if self.radio.mic_ptt_disabled == True:
                self.radio.mic_ptt_disabled = False
        elif packet_data[0] == 0x01:
            self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.TX, value=True)
            if self.radio.mic_ptt == True:
                printd("")
        elif packet_data[0] == 0x80:
            self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.TX, value=False)
        elif packet_data[0] == 0x81:
            self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.TX, value=True)

    def _rx_icon_busy(self, packet_data):
        if packet_data[0] == 0x00:
            self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.SIGNAL, value=False)
        elif packet_data[0] == 0x01:
            self.radio.set_icon(vfo=RADIO_VFO.LEFT, icon=RADIO_RX_ICON.SIGNAL, value=True)
        elif packet_data[0] == 0x80:
            self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.SIGNAL, value=False)
        elif packet_data[0] == 0x81:
            self.radio.set_icon(vfo=RADIO_VFO.RIGHT, icon=RADIO_RX_ICON.SIGNAL, value=True)

    def _rx_icon_sig_bars(self, packet_data):
        sig = packet_data[0]
        if sig >= 0x00 and sig <= 0x09:
            update_signal(radio=self.radio,vfo=RADIO_VFO.LEFT,s_value=sig)
        elif sig >= 0x80 and sig <= 0x89:
            sig = sig - 0x80
            update_signal(radio=self.radio,vfo=RADIO_VFO.RIGHT,s_value=sig)
        else:
            printd(f"OSIG: {sig}")

    _DOT1ST_STATE = {
        0x40: (RADIO_VFO.LEFT, False),
        0x41: (RADIO_VFO.LEFT, True),
        0xC0: (RADIO_VFO.RIGHT, False),
        0xC1: (RADIO_VFO.RIGHT, True),
    }

    def _rx_icon_dot_1st(self, packet_data):
        state = self._DOT1ST_STATE.get(packet_data[0])
        if state is None:
            return
        new_vfo, is_vfo_mode = state
        if new_vfo != self.radio.vfo_active_processing:
            self._restore_vfo_text_cache(new_vfo)

        radio_text_fast = False
        radio_text = self.radio.vfo_text
        if radio_text.find("*") != -1:
            radio_text_fast = True
            radio_text = radio_text.replace("*","")
        radio_text_formatted = self.format_frequency(radio_text).strip()
        if radio_text_fast == True:
            radio_text_formatted = f"*{radio_text_formatted}*"

        self.radio.vfo_active_processing = new_vfo
        if self.radio.menu_open == False:
            mode = RADIO_VFO_TYPE.VFO if is_vfo_mode else RADIO_VFO_TYPE.MEMORY
            self.radio.vfo_memory[new_vfo]['operating_mode'] = int(mode)
            printd(f"****RADIO VFO TYPE2 set to {self.radio.vfo_memory[new_vfo]['operating_mode']}")
            if is_vfo_mode:
                try:
                    self.radio.vfo_memory[new_vfo]['frequency'] = str(int(radio_text)*1000)
                except:
                    self.radio.vfo_memory[new_vfo]['operating_mode'] = str(int(-1))
                    self.radio.vfo_memory[new_vfo]['frequency'] = str(int(-1))
                printd(f"Freq set to {self.radio.vfo_memory[new_vfo]['frequency']} for {new_vfo}")
        self.radio._notify("vfo_display", vfo=new_vfo, text=radio_text_formatted if is_vfo_mode else radio_text)

    def _rx_startup_1(self, packet_data):
        if packet_data[0] == 0x00:
            if self.radio.startup == False:
                self.radio.startup = True
                self.radio.connect_process = False
                printd("\n*******Startup initiated*******")
            self.protocol.send_packet(self.create_tx_packet(payload=bytes([0xF0])))

    def _rx_startup_2(self, packet_data):
        if packet_data[0] == 0x00:
            self.radio.exe_cmd(cmd=RADIO_TX_CMD.L_VOLUME_SQUELCH)
            self.radio.exe_cmd(cmd=RADIO_TX_CMD.R_VOLUME_SQUELCH)

    def _rx_startup_3(self, packet_data):
        if packet_data[0] == 0x20:
            self.protocol.send_packet(self.create_tx_packet(payload=bytes([0xA0,0x18,0x02])))

    _RX_DISPATCH = {
        RADIO_RX_CMD.DISPLAY_TEXT: _rx_display_text,
        RADIO_RX_CMD.CHANNEL_TEXT: _rx_channel_text,
        RADIO_RX_CMD.DISPLAY_CHANGE: _rx_display_change,
        RADIO_RX_CMD.DISPLAY_ICONS: _rx_display_icons,
        RADIO_RX_CMD.ICON_SET: _rx_icon_set,
        RADIO_RX_CMD.ICON_MAIN: _rx_icon_main,
        RADIO_RX_CMD.ICON_TX: _rx_icon_tx,
        RADIO_RX_CMD.ICON_BUSY: _rx_icon_busy,
        RADIO_RX_CMD.ICON_SIG_BARS: _rx_icon_sig_bars,
        RADIO_RX_CMD.ICON_DOT_1ST: _rx_icon_dot_1st,
        RADIO_RX_CMD.STARTUP_1: _rx_startup_1,
        RADIO_RX_CMD.STARTUP_2: _rx_startup_2,
        RADIO_RX_CMD.STARTUP_3: _rx_startup_3,
    }

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
        expected_packet_size = 2 + 1 + packet_length + 1

        if len(packet) != expected_packet_size:
            raise ValueError("\nIncomplete packet.")

        payload = packet[3:-1]
        self.payload = payload
        checksum = packet[-1]
        self.checksum = checksum
        calculated_checksum = self.calculate_checksum(bytes([packet_length])+payload)

        if calculated_checksum != checksum:
            raise ValueError(f"\nChecksum mismatch: expected {calculated_checksum:02X}, found {checksum:02X}")

        packet_cmd = packet[3]
        packet_data = packet[4:-1]
        handler = self._RX_DISPATCH.get(packet_cmd)
        if handler:
            handler(self, packet_data)
        else:
            printd(f"Unkown pkt: {packet.hex().upper()}")

    def process_display_packet(self, packet: bytes):
        if packet[0] == 0x40:
            vfo = RADIO_VFO.LEFT
            self.radio.vfo_active_processing = vfo
        elif packet[0] == 0xC0:
            vfo = RADIO_VFO.RIGHT
            self.radio.vfo_active_processing = vfo
        else:
            printd(f"Unknown icon display packet: {packet[0]}")
        if packet[1] == 0x00:
            self.radio.vfo_memory[vfo]['icons']['SIGNAL'] = 0x00
        else:
            self.radio.vfo_memory[vfo]['icons']['SIGNAL'] = packet[1]
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

        max_raw = 0x03AC

        if value == 0:
            raw_value = 0
        else:
            raw_value = round((value / 100) * max_raw)

        return raw_value.to_bytes(2, 'little')

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
        self.cat = cat_controller
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
                    op_mode = await self.cat.get_operating_mode()
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

    async def dump_state(self) -> str:
        return (
        "0\n"
        "9800\n"
        "2\n"

        "0.000000 10000000000.000000 0x2ef 5000 50000 0x1 0x0\n"

        "0 0 0 0 0 0 0\n"
        "0 0 0 0 0 0 0\n"

        "0xef 1\n"
        "0xef 0\n"
        "0 0\n"

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
        "0 0\n"

        "0\n"
        "0\n"
        "0\n"

        "0\n"

        "0\n"
        "0\n"

        "0\n"
        "0\n"
        "0x40000020\n"
        "0x20\n"
        "0\n"
        "0\n"
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

    async def get_operating_mode(self) -> int:
        return await self.get_vfo_memory("operating_mode")

    async def set_operating_mode(self, mode: int):
        if mode not in (0, 1):
            raise ValueError("Invalid operating mode")
        await self.set_vfo_memory("operating_mode",mode)

    async def get_memory_name(self, mem_num: int) -> str:
        memory = await self.get_vfo_memory("name")
        if not memory:
            return ""
        return memory

    async def get_frequency(self) -> int:
        return await self.get_vfo_memory("frequency")

    async def set_frequency(self, freq: int):
        printd(f"***Set FREQ: {freq}***")
        self.radio.set_freq(vfo=self.radio.vfo_memory['vfo_active'],freq=str(freq))
        await self.set_vfo_memory("frequency",freq)

    async def get_mode(self) -> tuple:
        return await self.get_vfo_memory("mode"),await self.get_vfo_memory("width")

    async def set_mode(self, mode: str, width: int):
        await self.set_vfo_memory("mode",mode)
        await self.set_vfo_memory("width",width)

    async def get_ptt(self) -> int:
        return await self.get_vfo_memory("ptt")

    async def set_ptt(self, state: int):
        await self.set_vfo_memory("ptt",state)

    _VFO_TO_RIGCTL = {RADIO_VFO.LEFT: "VFOA", RADIO_VFO.RIGHT: "VFOB"}

    async def get_vfo(self) -> str:
        vfo_active = await self.get_vfo_memory("vfo_active")
        return self._VFO_TO_RIGCTL.get(vfo_active, "VFOA")

    _RIGCTL_TO_VFO = {"VFOA": RADIO_VFO.LEFT, "VFOB": RADIO_VFO.RIGHT}

    async def set_vfo(self, vfo: str):
        if vfo not in ("VFOA", "VFOB"):
            raise ValueError("Invalid VFO")
        await self.set_vfo_memory("vfo_active", self._RIGCTL_TO_VFO.get(vfo, RADIO_VFO.LEFT))
