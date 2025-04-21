from TH9800_Enums import *
from time import sleep
import dearpygui.dearpygui as dpg
import serial.tools.list_ports
import serial_asyncio
import asyncio
import threading

"""
    On initize, grab different configs from radio such as:
        Active VFO
        (Channel # + Name) (Or Freq) + Other Params (Offset, Power, DCs, etc)
        On startup, could click left and right knob to get VFO/Mem mode and determine active VFO (active VFO will flash channel # icon)

import importlib
import TH9800_CAT

def clear():
    for num in range(1,100):
        print("\n")

def reload():
    importlib.reload(TH9800_CAT)
    TH9800_CAT.asyncio.run(TH9800_CAT.main())
"""

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def start_event_loop():
    loop.run_forever()

threading.Thread(target=start_event_loop, daemon=True).start()

class SerialRadio:
    def __init__(self, dpg: dpg = None, protocol: SerialProtocol = None):
        self.dpg = dpg
        self.dpg_enabled = True
        self.packet = SerialPacket()
        self.protocol = protocol
        self.menu_open = False
        self.connect_process = False
        self.startup = False
        self.vfo_change = False
        self.vfo_active = str(RADIO_VFO.LEFT)
        self.vfo_active_processing = str(RADIO_VFO.LEFT)
        self.vfo_type_l = str(RADIO_VFO_TYPE.MEMORY)
        self.vfo_type_r = str(RADIO_VFO_TYPE.MEMORY)
        self.vfo_text = ""
        self.vfo_channel = ""

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
    
    def exe_cmd(self, cmd: RADIO_TX_CMD, payload: bytes = None):
        cmd_name = cmd.name
        cmd_data = self.get_cmd_pkt(cmd=cmd,payload=payload)
        cmd_pkt = self.packet.create_tx_packet(payload=cmd_data)
        
        #If above was a button/key press, we need to release button/return control to body
        if cmd_name.find("LEFT") == -1 and cmd_name.find("RIGHT") == -1 and cmd_name != "L_VOLUME" and cmd_name != "L_SQUELCH" and cmd_name != "R_VOLUME" and cmd_name != "R_SQUELCH":
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

    def connection_made(self, transport):
        self.transport = transport
        print("Connection opened")
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
                print(f"Checksum mismatch: expected {expected_cs:02X}, calculated {calculated_cs:02X}")
                # Optionally: log, raise alert, or resync buffer here

    def connection_lost(self, exc):
        print("Connection lost")
        asyncio.get_event_loop().stop()
        self.transport.close()

    def send_packet(self, data: bytes):
        if self.transport and not self.transport.is_closing():
            print(f"Sending: {data.hex().upper()}")
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

    def create_tx_packet(self, payload: bytes):
        """
        Create a TX packet with start bytes, payload length, and checksum.
        """
        packet_length = len(payload)
        packet = self.start_bytes + bytes([packet_length]) + payload  # Start bytes + length byte + payload + checksum
        checksum = self.calculate_checksum(packet[2:])
        packet += bytes([checksum])
        self.packet = packet
        return packet

    def process_rx_packet(self, packet: bytes):
        """
        Parse an RX packet: validate checksum and extract payload.
        """
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
                self.radio.vfo_text = packet_data[2:8].decode().strip()
                radio_text = self.radio.vfo_text
                radio_channel = self.radio.vfo_channel
                match packet_data[0]:
                    case 0x60:
                        print(f"{self.radio.vfo_active_processing}<***Set Freq Fast [{radio_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                    case (0x40|0xC0):
                        if self.radio.vfo_change == True:
                            return
                        elif self.radio.menu_open == True and self.radio.vfo_active_processing == self.radio.vfo_active and self.radio.connect_process == False:
                            print(f"{self.radio.vfo_active_processing}<***Set Menu [{radio_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                        elif self.radio.connect_process == False:
                            if radio_channel.find("HP") != -1:
                                print(f"{self.radio.vfo_active_processing}<***Radio Power [{radio_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                            else:
                                print(f"{self.radio.vfo_active_processing}<***Set Channel [{radio_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                        if self.radio.dpg_enabled == True:
                            dpg.set_value(f"ch_{self.radio.vfo_active_processing.lower()}_display",radio_channel)
                            dpg.set_value(f"vfo_{self.radio.vfo_active_processing.lower()}_display",radio_text)
            case RADIO_RX_CMD.CHANNEL_TEXT.value:
                if self.radio.vfo_change == True:
                    return
                self.radio.vfo_channel = packet_data[2:5].decode().strip()
                return
                match packet_data[0]:
                    case 0x60:
                        print(f"{self.radio.vfo_active_processing}<***Set Channel Fast [{self.radio.vfo_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                    case 0x40:
                        if self.radio.menu_open == True:
                            print(f"{self.radio.vfo_active_processing}<***Set Menu [{self.radio.vfo_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                        #else:
                            #print(f"{self.radio.vfo_active_processing}<***Set Channel [{self.radio.vfo_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                    case 0xC0:
                        if self.radio.menu_open == True:
                            print(f"{self.radio.vfo_active_processing}<***Set Menu [{self.radio.vfo_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
                        #else:
                        #    print(f"{self.radio.vfo_active_processing}<***Set Channel [{self.radio.vfo_channel}][{radio_text}]***>{self.radio.vfo_active_processing}",sep="")
            case RADIO_RX_CMD.DISPLAY_CHANGE.value:
                match packet_data[0]:
                    case 0x43:
                        #print("L<",end="")
                        self.radio.vfo_active_processing = str(RADIO_VFO.LEFT)
                    case 0xC3:
                        #print("R<",end="")
                        self.radio.vfo_active_processing = str(RADIO_VFO.RIGHT)
                    case 0x03:
                        self.radio.vfo_change = False
                    case 0x83:
                        self.radio.vfo_change = False
                        if self.radio.connect_process == True:
                            self.radio.connect_process = False
            case RADIO_RX_CMD.DISPLAY_ICONS.value:
                match packet_data[0]:
                    case 0x40:
                         match packet_data[3]:
                             case 0x80:
                                self.radio.vfo_active = str(RADIO_VFO.LEFT)
                    case 0xC0:
                         match packet_data[3]:
                             case 0x80:
                                self.radio.vfo_active = str(RADIO_VFO.RIGHT)
            case RADIO_RX_CMD.ICON_SET.value:
                match packet_data[0]:
                    case 0x00:
                        if self.radio.menu_open == True:
                            print(f"{self.radio.vfo_active}<***Menu Closed***>{self.radio.vfo_active}")
                            self.radio.menu_open = False
                    case 0x01:
                        print(f"{self.radio.vfo_active}<***Menu Opened***>{self.radio.vfo_active}")
                        self.radio.menu_open = True
            case RADIO_RX_CMD.ICON_MAIN.value:
                match packet_data[0]:
                    case 0x01:
                        self.radio.vfo_active = str(RADIO_VFO.LEFT)
                        self.radio.vfo_active_processing = str(RADIO_VFO.LEFT)
                        self.radio.vfo_change = True
                        print(f"{self.radio.vfo_active}<***Left  VFO Activated***>{self.radio.vfo_active}")
                    case 0x81:
                        self.radio.vfo_active = str(RADIO_VFO.RIGHT)
                        self.radio.vfo_active_processing = str(RADIO_VFO.RIGHT)
                        self.radio.vfo_change = True
                        print(f"{self.radio.vfo_active}<***Right VFO Activated***>{self.radio.vfo_active}")
            case RADIO_RX_CMD.ICON_DOT_1ST.value:
                match packet_data[0]:
                    case 0x40:
                        print("")
            case RADIO_RX_CMD.STARTUP_1.value:
                match packet_data[0]:
                    case 0x00:
                        if self.radio.startup == False:
                            self.radio.startup = True
                            self.radio.connect_process = False
                            print("\n*******Startup initiated*******")
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
            case RADIO_RX_CMD.STARTUP_4.value:
                match packet_data[0]:
                    case 0xFF:
                        self.radio.startup = False
                        print("*******Startup complete*******\n")

    def vol_sq_to_packet(self, volume: int) -> bytes:
        if not (0 <= volume <= 100):
            raise ValueError("Volume must be >= 0 and <= 100")

        max_raw = 0x03AC #940

        if volume == 0:
            raw_value = 0
        else:
            # Spread values 1–100 evenly over 1–940
            raw_value = round((volume / 100) * max_raw)

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

async def run_dpg():
    while dpg.is_dearpygui_running():
        dpg.render_dearpygui_frame()
        await asyncio.sleep(1/60)

def build_gui(protocol):
    ports = []
    available_ports = serial.tools.list_ports.comports()
    for port in available_ports:
        ports.append(f"{port.device}: {port.description}")
        print(f"{port.device} - {port.manufacturer} - {port.description}")

    with dpg.window(label="Radio Front Panel", width=660, height=300, pos=[0,22], no_move=True, on_close=dpg_window_closed, user_data={"protocol": protocol}):
        # === VFO Channel Displays ===
        with dpg.group(horizontal=True):
            dpg.add_text("CH:", indent=21)
            dpg.add_input_text(tag="ch_l_display", readonly=True, width=100, default_value="")
            dpg.add_spacer(width=231)
            dpg.add_text("CH:")
            dpg.add_input_text(tag="ch_r_display", readonly=True, width=100, default_value="")
            
        # === VFO Frequency Displays ===
        with dpg.group(horizontal=True):
            dpg.add_text("VFO L:")
            dpg.add_input_text(tag="vfo_l_display", readonly=True, width=100, default_value="")
            dpg.add_spacer(width=210)
            dpg.add_text("VFO R:")
            dpg.add_input_text(tag="vfo_r_display", readonly=True, width=100, default_value="")

        dpg.add_spacer(height=15)

        # === VFO Control Buttons + Center Menu Button ===
        with dpg.group(horizontal=True):
            # VFO Left Buttons
            for label in ["LOW", "V/M", "HM", "SCN"]:
                dpg.add_button(label=label, width=60, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.LEFT})

            dpg.add_spacer(width=20)

            # Center Menu Button
            label = "."
            dpg.add_button(label=".", width=40, height=20, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.NONE})

            dpg.add_spacer(width=20)

            # VFO Right Buttons
            for label in ["LOW", "V/M", "HM", "SCN"]:
                dpg.add_button(label=label, width=60, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.RIGHT})

        dpg.add_separator()

        # === Buttons A-F ===
        with dpg.group(horizontal=True):
            for label in ["A", "B", "C", "D", "E", "F"]:
                dpg.add_button(label=label, width=40, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.NONE})

        dpg.add_separator()

        # === Knob Simulation Buttons ===
        with dpg.group(horizontal=True):
            dpg.add_button(label="VOL/SQ (L)", width=100, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.LEFT})
            dpg.add_spacer(width=300)
            dpg.add_button(label="SQL/ENC (R)", width=100, callback=button_callback, user_data={"label": label, "protocol": protocol, "vfo": RADIO_VFO.RIGHT})
    with dpg.window(label="Connection", width=660, height=300, tag="connection_window"):
        with dpg.group(horizontal=True):
            dpg.add_combo(
                    tag="com_port",
                    items=ports,
                    label="Select Port",
                    default_value=ports[0] if available_ports else ""
                )
        dpg.add_spacer(height=5)
        
        # === Baud Rate Selector ===
        with dpg.group(horizontal=True):
            dpg.add_text("Baud Rate:")
            dpg.add_combo(
                tag="baud_rate",
                items=["4800", "9600", "19200", "38400", "57600", "115200"],
                default_value="19200",
                width=100
            )
        dpg.add_spacer(height=15)
        
        with dpg.group(horizontal=True):
            # dpg.set_value(f"vfo_{self.radio.vfo_active_processing.lower()}_display",radio_text)
            com_port = dpg.get_value("com_port")
            baudrate = dpg.get_value("baud_rate")
            com_port = com_port[0:com_port.index(":")]
            dpg.add_button(label="Connect", width=100, callback=port_selected_callback, user_data={"com_port": com_port, "baudrate": baudrate,"protocol": protocol})

def update_vfo_display(radio):
    dpg.set_value("vfo_l_display", radio.vfo_text if radio.vfo_active == RADIO_VFO.LEFT else "")
    dpg.set_value("vfo_r_display", radio.vfo_text if radio.vfo_active == RADIO_VFO.RIGHT else "")

def dpg_window_closed(sender, app_data, user_data):
    user_data['protocol'].transport.close()

async def connect_serial_async(protocol, com_port, baudrate):
    radio = protocol.radio
    packet = SerialPacket()
    try:
        transport, _ = await serial_asyncio.create_serial_connection(
            asyncio.get_event_loop(), lambda: protocol, com_port, baudrate=baudrate
        )
        await protocol.ready.wait()
        print(f"Connected to {com_port} at {baudrate} baud.")
        dpg.configure_item("connection_window", collapsed=True)
        asyncio.create_task(read_loop(protocol))
        
        radio.connect_process = True
        radio.exe_cmd(cmd=RADIO_TX_CMD.L_DIAL_RIGHT)
        await asyncio.sleep(0.1)
        radio.exe_cmd(cmd=RADIO_TX_CMD.L_DIAL_LEFT)
        await asyncio.sleep(0.1)
        radio.exe_cmd(cmd=RADIO_TX_CMD.R_DIAL_RIGHT)
        await asyncio.sleep(0.1)
        radio.exe_cmd(cmd=RADIO_TX_CMD.R_DIAL_LEFT)
        
        return transport
    except Exception as e:
        print(f"Connection failed: {e}")
        return None

def port_selected_callback(sender, app_data, user_data):
    protocol = user_data['protocol']
    radio = protocol.radio
    baudrate = user_data['baudrate']
    com_port = user_data['com_port']
    #print(f"[{com_port}][{baudrate}]")
    
    asyncio.run_coroutine_threadsafe(
        connect_serial_async(protocol, com_port, baudrate),
        loop
    )

def button_callback(sender, app_data, user_data):
    label = user_data["label"]
    vfo = user_data["vfo"]
    protocol = user_data["protocol"]
    radio = protocol.radio

    match vfo:
        case RADIO_VFO.LEFT:
            match label:
                case "LOW":
                    radio.exe_cmd(cmd=RADIO_TX_CMD.L_DIAL_LEFT)
                    radio.exe_cmd(cmd=RADIO_TX_CMD.L_DIAL_RIGHT)
        case RADIO_VFO.RIGHT:
            match label:
                case "LOW":
                    radio.exe_cmd(cmd=RADIO_TX_CMD.R_DIAL_LEFT)
                    radio.exe_cmd(cmd=RADIO_TX_CMD.R_DIAL_RIGHT)

    print(f"Sent {label} button command for {vfo} VFO.") #: {packet.hex().upper()}")

async def read_loop(protocol: SerialProtocol):
    while True:
        packet = await protocol.receive_queue.get()
        packet_processor = SerialPacket(protocol=protocol).process_rx_packet(packet=packet)
        """
        #print("Processed from queue:", packet.decode('utf-8', errors='ignore'))
        #print("Byte Array:", packet.hex().upper())
        #print("CMD:(",bytes([packet_cmd]).hex().upper(),") Data:(",packet_data.hex().upper(),")")
        """

async def main_old():
    # Start Serial Read Loop
    loop = asyncio.get_running_loop()
    radio = SerialRadio(dpg)
    protocol = SerialProtocol(radio)
    if radio.dpg_enabled == True:
        dpg.create_context()
        build_gui(protocol)
        dpg.create_viewport(title="Radio GUI", width=675, height=300)
        dpg.setup_dearpygui()
        dpg.show_viewport()
    transport, _ = await serial_asyncio.create_serial_connection(
        loop, lambda: protocol, 'COM25', baudrate=19200
    )

    await protocol.ready.wait()
    asyncio.create_task(read_loop(protocol))

    try:
        if radio.dpg_enabled == True:
            await run_dpg()
        else:
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        transport.close()
        if radio.dpg_enabled == True:
            dpg.destroy_context()

async def main():
    # Start Serial Read Loop
    radio = SerialRadio(dpg)
    protocol = SerialProtocol(radio)
    radio.protocol = protocol
    if radio.dpg_enabled == True:
        dpg.create_context()
        build_gui(protocol)
        dpg.create_viewport(title="Radio GUI", width=675, height=300)
        dpg.setup_dearpygui()
        dpg.show_viewport()
    #transport, _ = await serial_asyncio.create_serial_connection(
    #    loop, lambda: protocol, 'COM25', baudrate=19200
    #)

    #await protocol.ready.wait()
    #asyncio.create_task(read_loop(protocol))

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