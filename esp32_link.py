"""
Wires esp32_uart.py's UART transport to radio_protocol.py's portable
SerialRadio/SerialPacket -- the ESP32-side equivalent of TH9800_CAT.py's
main() + read_loop().
"""

import asyncio
import radio_protocol as rp
from esp32_uart import UartTransport
from esp32_relay import RelayServer


def _relay_password():
    try:
        import wifi_config
        return getattr(wifi_config, "RELAY_PASSWORD", "")
    except ImportError:
        return ""


async def rx_pump(transport, packet_parser, relay=None):
    """Feed every framed, checksum-valid packet into the protocol/state
    layer, and (if a relay client is connected) forward the raw packet
    to it too -- the ESP32 equivalent of the desktop read_loop() calling
    SerialPacket.process_rx_packet() and forwarding to TCP.tcpserver."""
    while True:
        packet = await transport.receive_queue.get()
        if relay:
            relay.forward_packet(packet)
        try:
            packet_parser.process_rx_packet(packet=packet)
        except Exception as e:
            print("RX packet error:", e)


def setup(uart_id=2, tx=17, rx=16, baudrate=19200, rigctl_host="0.0.0.0", rigctl_port=4532,
          relay_host="0.0.0.0", relay_port=24, rts_pin=None, dtr_pin=None):
    """Wire up the transport + radio + packet parser, start the
    background UART tasks, and start the rigctl + relay TCP servers.
    Returns (transport, radio, packet_parser, rigctl, relay)."""
    transport = UartTransport(uart_id=uart_id, tx=tx, rx=rx, baudrate=baudrate)

    radio = rp.SerialRadio(dpg=None, protocol=transport)
    radio.dpg_enabled = False

    transport.radio = radio  # SerialPacket.__init__ expects protocol.radio
    packet_parser = rp.SerialPacket(protocol=transport)

    cat = rp.CATController(radio=radio)
    radio.cat = cat
    rigctl = rp.RigctlServer(cat, host=rigctl_host, port=rigctl_port)

    relay = RelayServer(transport, radio, password=_relay_password(),
                         host=relay_host, port=relay_port, rts_pin=rts_pin, dtr_pin=dtr_pin)

    transport.start()
    asyncio.create_task(rx_pump(transport, packet_parser, relay=relay))
    asyncio.create_task(rigctl.start())
    asyncio.create_task(relay.start())

    return transport, radio, packet_parser, rigctl, relay
