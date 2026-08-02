"""
WiFi station connection for the ESP32. Reads credentials from
wifi_config.py (gitignored, not committed -- see wifi_config.example.py).
"""

import network
import time


def connect(ssid, password, timeout_s=15):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi:", ssid)
        wlan.connect(ssid, password)
        start = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
                raise RuntimeError("WiFi connection timed out")
            time.sleep_ms(200)
    ip = wlan.ifconfig()[0]
    print("WiFi connected, IP:", ip)
    return wlan


def connect_from_config(timeout_s=15):
    import wifi_config
    return connect(wifi_config.SSID, wifi_config.PASSWORD, timeout_s=timeout_s)
