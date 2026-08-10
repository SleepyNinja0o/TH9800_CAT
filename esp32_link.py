import asyncio
import radio_protocol as rp
import esp32_config
from esp32_uart import UartTransport
from esp32_relay import RelayServer


async def rx_pump(transport, packet_parser, relay=None):
    while True:
        packet = await transport.receive_queue.get()
        if relay:
            relay.forward_packet(packet)
        try:
            packet_parser.process_rx_packet(packet=packet)
        except Exception as e:
            print("RX packet error:", e)


def setup(uart_id=2, tx=26, rx=27, baudrate=19200, rigctl_host="0.0.0.0", rigctl_port=4532,
          relay_host="0.0.0.0", relay_port=9800, rts_pin=5, dtr_pin=None):
    transport = UartTransport(uart_id=uart_id, tx=tx, rx=rx, baudrate=baudrate)
    radio = rp.SerialRadio(protocol=transport)

    transport.radio = radio
    packet_parser = rp.SerialPacket(protocol=transport)

    cat = rp.CATController(radio=radio)
    radio.cat = cat
    rigctl = rp.RigctlServer(cat, host=rigctl_host, port=rigctl_port)

    relay = RelayServer(transport, radio, password=esp32_config.CONFIG_DEFAULTS["relay_password"],
                         host=relay_host, port=relay_port, rts_pin=rts_pin, dtr_pin=dtr_pin)

    transport.start()
    asyncio.create_task(rx_pump(transport, packet_parser, relay=relay))
    asyncio.create_task(rigctl.start())
    asyncio.create_task(relay.start())

    return transport, radio, packet_parser, rigctl, relay
