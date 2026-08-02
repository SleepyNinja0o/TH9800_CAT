"""
Raw packet relay + control-command server for the ESP32, matching the
subset of TH9800_CAT.py's TCP.handle_tcpserver_stream protocol still
needed once the ESP32 is directly wired to the radio: password auth,
raw packet relay (!data), volume (!vol), PTT (!ptt), and RTS/DTR
(!rts/!dtr).

RTS/DTR on the desktop toggled a real PySerial control line (used to
switch a hardware mux between a USB adapter and the radio's own head).
machine.UART has no equivalent pins, so here they're generic GPIO
toggles instead -- reserved for whatever gets wired to them later
(e.g. DTR driving a relay/transistor onto the radio's power button).
Passing no pin number leaves the command accepted but a no-op.
"""

import asyncio
from machine import Pin
from TH9800_Enums import RADIO_VFO, RADIO_TX_CMD


class GpioSignal:
    """A named, optionally-wired GPIO output with software-tracked state."""

    def __init__(self, pin_num=None):
        self.pin = Pin(pin_num, Pin.OUT) if pin_num is not None else None
        self.state = False
        if self.pin:
            self.pin.value(0)

    def set(self, state: bool):
        self.state = state
        if self.pin:
            self.pin.value(1 if state else 0)

    def toggle(self):
        self.set(not self.state)


class RelayServer:
    def __init__(self, transport, radio, password="", host="0.0.0.0", port=24, rts_pin=None, dtr_pin=None):
        self.transport = transport
        self.radio = radio
        self.password = password
        self.host = host
        self.port = port
        self.client_writer = None
        self._logged_in = False
        self.server = None
        self.rts = GpioSignal(rts_pin)
        self.dtr = GpioSignal(dtr_pin)

    async def start(self):
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        print("Relay server running on", self.host, self.port)

    def forward_packet(self, packet: bytes):
        """Call from the RX pump so a connected, logged-in client sees
        every raw radio packet -- this drives the desktop app's live
        display mirror."""
        if self.client_writer and self._logged_in:
            try:
                self.client_writer.write(packet + b'\n')
            except Exception as e:
                print("Relay forward error:", e)

    async def _process_cmd(self, cmd, data):
        if cmd != "pass" and cmd != "exit" and not self._logged_in:
            return "Unauthorized"

        if cmd == "pass":
            if data == self.password:
                self._logged_in = True
                return "Login Successful"
            return "Login Failed"
        elif cmd == "data":
            self.transport.send_packet(bytes.fromhex(data))
            return "data sent"
        elif cmd == "vol":
            parts = data.split() if data else []
            if len(parts) == 2:
                vfo_str = parts[0].upper()
                vol = int(parts[1])
                if vfo_str in ("LEFT", "L"):
                    self.radio.set_volume(vfo=RADIO_VFO.LEFT, vol=vol)
                elif vfo_str in ("RIGHT", "R"):
                    self.radio.set_volume(vfo=RADIO_VFO.RIGHT, vol=vol)
                return "vol " + vfo_str + " " + str(vol)
            return "usage: !vol LEFT|RIGHT 0-100"
        elif cmd == "ptt":
            action = (data or "").strip().lower()
            if action == "on":
                desired = True
            elif action == "off":
                desired = False
            else:
                desired = not self.radio.mic_ptt
            if desired != self.radio.mic_ptt:
                self.radio.mic_ptt = desired
                self.radio.vfo_memory[self.radio.vfo_memory["vfo_active"]]["ptt"] = 1 if desired else 0
                self.radio.exe_cmd(cmd=RADIO_TX_CMD.MIC_PTT)
            return str(self.radio.mic_ptt)
        elif cmd == "rts":
            if data == "" or data is None:
                self.rts.toggle()
            else:
                self.rts.set(data.strip().lower() in ("true", "1", "on"))
            return str(self.rts.state)
        elif cmd == "dtr":
            if data == "" or data is None:
                self.dtr.toggle()
            else:
                self.dtr.set(data.strip().lower() in ("true", "1", "on"))
            return str(self.dtr.state)
        elif cmd == "exit":
            return "return"
        else:
            return "Not Found"

    async def _handle_client(self, reader, writer):
        addr = writer.get_extra_info("peername")
        print("Relay connection from", addr)
        self.client_writer = writer
        self._logged_in = False

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                message = line[:-1].decode().strip()
                if not message:
                    continue
                if message[0] != "!":
                    continue

                sp = message.find(" ")
                if sp != -1:
                    cmd = message[1:sp]
                    data = message[sp + 1:]
                else:
                    cmd = message[1:]
                    data = ""

                result = await self._process_cmd(cmd, data)
                if result == "return":
                    writer.write(b"Ok\n")
                    await writer.drain()
                    break
                writer.write((result + "\n").encode())
                await writer.drain()
        except Exception as e:
            print("Relay client error:", e)
        finally:
            print("Relay connection closed:", addr)
            if self.client_writer is writer:
                self.client_writer = None
                self._logged_in = False
            try:
                writer.close()
            except Exception:
                pass
