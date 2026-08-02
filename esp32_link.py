"""
Wires esp32_uart.py's UART transport to radio_protocol.py's portable
SerialRadio/SerialPacket -- the ESP32-side equivalent of TH9800_CAT.py's
main() + read_loop().
"""

import asyncio
import radio_protocol as rp
from esp32_uart import UartTransport


async def rx_pump(transport, packet_parser):
    """Feed every framed, checksum-valid packet into the protocol/state
    layer -- the ESP32 equivalent of the desktop read_loop() calling
    SerialPacket.process_rx_packet()."""
    while True:
        packet = await transport.receive_queue.get()
        try:
            packet_parser.process_rx_packet(packet=packet)
        except Exception as e:
            print("RX packet error:", e)


def setup(uart_id=2, tx=17, rx=16, baudrate=19200, rigctl_host="0.0.0.0", rigctl_port=4532):
    """Wire up the transport + radio + packet parser, start the
    background UART tasks, and start the rigctl TCP server. Returns
    (transport, radio, packet_parser, rigctl)."""
    transport = UartTransport(uart_id=uart_id, tx=tx, rx=rx, baudrate=baudrate)

    radio = rp.SerialRadio(dpg=None, protocol=transport)
    radio.dpg_enabled = False

    transport.radio = radio  # SerialPacket.__init__ expects protocol.radio
    packet_parser = rp.SerialPacket(protocol=transport)

    transport.start()
    asyncio.create_task(rx_pump(transport, packet_parser))

    cat = rp.CATController(radio=radio)
    radio.cat = cat
    rigctl = rp.RigctlServer(cat, host=rigctl_host, port=rigctl_port)
    asyncio.create_task(rigctl.start())

    return transport, radio, packet_parser, rigctl
