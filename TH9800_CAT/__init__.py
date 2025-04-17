import asyncio
import serial_asyncio
import struct

"""
    On initize, grab different configs from radio such as:
        Active VFO
        (Channel # + Name) (Or Freq) + Other Params (Offset, Power, DCs, etc)
        On startup, could click left and right knob to get VFO/Mem mode and determine active VFO (active VFO will flash channel # icon)
"""

class SerialRadio:
    def __init__(self):
        self.vfo_change = False
        self.vfo_active = "L"
        self.vfo_type_l = "M" # M = Memory AND V = VFO (Freq)
        self.vfo_type_r = "M" # M = Memory AND V = VFO (Freq)
        self.menu_open = False

class SerialPacket:
    def __init__(self, data=None, radio=None):
        self.start_bytes = bytes([0xAA,0xFD])
        self.payload = b''  # Empty payload by default
        self.checksum = None
        
        self.radio = radio
        self.data = data

        if data:
            self.parse_rx_packet(data)

    def create_tx_packet(self, payload: bytes):
        """
        Create a TX packet with start bytes, payload length, and checksum.
        """
        self.payload = payload
        packet_length = len(payload)
        packet = self.start_bytes + bytes([packet_length]) + payload  # Start bytes + length byte + payload + checksum
        self.checksum = self.calculate_checksum(packet[2:-1])
        packet += bytes([self.checksum])
        return packet

    def parse_rx_packet(self, data: bytes):
        """
        Parse an RX packet: validate checksum and extract payload.
        """
        if len(data) < 4:
            raise ValueError("\nPacket too short to be valid.")

        if data[:2] != self.start_bytes:
            raise ValueError("\nInvalid start bytes.")

        packet_length = data[2]
        expected_packet_size = 2 + 1 + packet_length + 1  # Start + Length + Payload + Checksum

        if len(data) != expected_packet_size:
            raise ValueError("\nIncomplete packet.")

        payload = data[3:-1]  # Extract payload (skip start bytes and length byte)
        self.payload = payload
        checksum = data[-1]  # Extract checksum
        self.checksum = checksum
        calculated_checksum = self.calculate_checksum(bytes([packet_length])+payload)  # Only checksum the payload

        if calculated_checksum != checksum:
            raise ValueError(f"\nChecksum mismatch: expected {calculated_checksum:02X}, found {checksum:02X}")
        
        packet_cmd = data[3]
        packet_data = data[4:-1]
        
        match packet_cmd:
            case 0x01:
                match packet_data[0]:
                    case 0x40:
                        print(f"{self.radio.vfo_active}<***Get Channel [",packet_data[2:8].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
                    case 0xC0:
                        print(f"{self.radio.vfo_active}<***Get Channel [",packet_data[2:8].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
            case 0x10:
                match packet_data[0]:
                    case 0x01:
                        print(f"{self.radio.vfo_active}<***Menu Opened***>{self.radio.vfo_active}")
                        self.radio.menu_open = True
                        return
                    case 0x00:
                        if self.radio.menu_open == True:
                            print(f"{self.radio.vfo_active}<***Menu Closed***>{self.radio.vfo_active}")
                            self.radio.menu_open = False
                            return
            case 0x02:
                if self.radio.vfo_change == True:
                    return
                match packet_data[0]:
                    case 0x60:
                        print(f"{self.radio.vfo_active}<***Set Channel Rapid [",packet_data[2:5].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
                    case 0x40:
                        if self.radio.menu_open == True:
                            print(f"{self.radio.vfo_active}<***Set Menu [",packet_data[2:5].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
                        else:
                            print(f"{self.radio.vfo_active}<***Set Channel [",packet_data[2:5].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
                    case 0xC0:
                        if self.radio.menu_open == True:
                            print(f"{self.radio.vfo_active}<***Set Menu [",packet_data[2:5].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
                        else:
                            print(f"{self.radio.vfo_active}<***Set Channel [",packet_data[2:5].decode().strip(),f"]***>{self.radio.vfo_active}",sep="")
            case 0x14:
                match packet_data[0]:
                    case 0x01:
                        self.radio.vfo_active = "L"
                        self.radio.vfo_change = True
                        print(f"{self.radio.vfo_active}<***Left  VFO Activated***>{self.radio.vfo_active}")
                    case 0x81:
                        self.radio.vfo_active = "R"
                        self.radio.vfo_change = True
                        print(f"{self.radio.vfo_active}<***Right VFO Activated***>{self.radio.vfo_active}")

    def calculate_checksum(self, data: bytes):
        """
        Calculate the XOR checksum over the data portion (payload).
        """
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum

    def __repr__(self):
        return f"SerialPacket(start={self.start_bytes.hex().upper()}, payload={self.payload.hex().upper()}, checksum={self.checksum:02X})"

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

    def send_packet(self, data: bytes):
        if self.transport and not self.transport.is_closing():
            print(f"Sending: {data}")
            self.transport.write(data)
        else:
            print("Transport is not available or already closed.")

async def read_loop(protocol: SerialProtocol):
    while True:
        packet = await protocol.receive_queue.get()
        p = SerialPacket(data=packet,radio=protocol.radio)
        """
        #print("Processed from queue:", packet.decode('utf-8', errors='ignore'))
        #print("Byte Array:", packet.hex().upper())
        #print("CMD:(",bytes([packet_cmd]).hex().upper(),") Data:(",packet_data.hex().upper(),")")
        """

async def main():
    loop = asyncio.get_running_loop()
    radio = SerialRadio()
    protocol = SerialProtocol(radio)

    # Create serial connection
    transport, _ = await serial_asyncio.create_serial_connection(
        loop, lambda: protocol, 'COM25', baudrate=19200
    )

    await protocol.ready.wait()

    # Start read loop
    asyncio.create_task(read_loop(protocol))

    # Example sending packets
    #protocol.send_packet(b'Hello device!\n')

    try:
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())

"""
            case 0x03:
                match packet_data[0]:
                    case 0x43:
                        #print("L<",end="")
                    case 0xC3:
                        #print("R<",end="")
                    case 0x03:
                        #print(">L")
                    case 0x83:
                        #print(">R")
"""