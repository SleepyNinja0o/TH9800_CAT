"""
ESP32-native UART transport, replacing SerialProtocol's asyncio.Protocol/
serial_asyncio (neither exists on MicroPython). Same packet-framing/
checksum state machine as the desktop SerialProtocol.data_received,
driven by polling machine.UART instead of a transport callback.

ESP32-only -- imports `machine`, which doesn't exist on desktop CPython.
"""

import asyncio
from machine import UART

START_BYTES = b'\xAA\xFD'


class AsyncQueue:
    """Minimal asyncio.Queue substitute. MicroPython's asyncio has no
    Queue at all (confirmed on-device) -- only Event."""

    def __init__(self):
        self._items = []
        self._event = asyncio.Event()

    def put_nowait(self, item):
        self._items.append(item)
        self._event.set()

    def get_nowait(self):
        return self._items.pop(0)

    def empty(self):
        return len(self._items) == 0

    async def get(self):
        while not self._items:
            await self._event.wait()
            self._event.clear()
        return self._items.pop(0)


class UartTransport:
    def __init__(self, uart_id=2, tx=17, rx=16, baudrate=19200):
        self.uart = UART(uart_id, baudrate=baudrate, tx=tx, rx=rx)
        self.buffer = bytearray()
        self.receive_queue = AsyncQueue()
        self.transmit_queue = AsyncQueue()
        self._running = False
        self._read_task = None
        self._write_task = None

    def start(self):
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        self._write_task = asyncio.create_task(self._write_loop())

    def stop(self):
        self._running = False
        if self._read_task:
            self._read_task.cancel()
        if self._write_task:
            self._write_task.cancel()

    def xor_checksum(self, data):
        cs = 0
        for b in data:
            cs ^= b
        return cs

    def _feed(self, data):
        self.buffer.extend(data)
        while True:
            start_index = self.buffer.find(START_BYTES)
            if start_index == -1:
                if len(self.buffer) > 2:
                    self.buffer[:-2] = b''
                break

            if len(self.buffer) < start_index + 4:
                break

            length = self.buffer[start_index + 2]
            full_packet_size = 2 + 1 + length + 1

            if len(self.buffer) < start_index + full_packet_size:
                break

            packet = bytes(self.buffer[start_index:start_index + full_packet_size])
            self.buffer[:start_index + full_packet_size] = b''

            expected_cs = packet[-1]
            calculated_cs = self.xor_checksum(packet[2:-1])
            if calculated_cs == expected_cs:
                self.receive_queue.put_nowait(packet)

    async def _read_loop(self):
        while self._running:
            n = self.uart.any()
            if n:
                data = self.uart.read(n)
                if data:
                    self._feed(data)
            else:
                await asyncio.sleep_ms(5)

    async def _write_loop(self):
        while self._running:
            try:
                data = await asyncio.wait_for(self.transmit_queue.get(), 0.1)
                self.uart.write(data)
                await asyncio.sleep_ms(150)
            except asyncio.TimeoutError:
                pass

    def send_packet(self, data):
        self.transmit_queue.put_nowait(bytes(data))
