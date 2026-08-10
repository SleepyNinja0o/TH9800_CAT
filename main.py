import uasyncio as asyncio
import esp32_wifi
import esp32_link
import esp32_config

esp32_wifi.connect_from_config()

transport, radio, packet_parser, rigctl, relay = esp32_link.setup(rts_pin=esp32_config.CONFIG_DEFAULTS["rts_pin"])
print('TH9800_CAT server started...')

async def keepalive():
    while True:
        await asyncio.sleep(3600)

asyncio.run(keepalive())