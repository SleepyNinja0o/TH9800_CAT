"""
Radio protocol constants.

No `enum` module dependency on purpose — MicroPython (the ESP32 target) doesn't
ship CPython's `enum`, and this file needs to run unmodified on both. Members
are plain class attributes (so `X.NAME` and `case X.NAME:` keep working) plus a
`.get(name)` classmethod where dynamic name-based lookup is actually needed.
"""

__all__ = ["RADIO_VFO", "RADIO_VFO_TYPE", "RADIO_RX_ICON", "RADIO_RX_CMD", "RADIO_TX_CMD"]


class RADIO_VFO:
    LEFT = "L"
    RIGHT = "R"
    MIC = "MIC"
    NONE = "N"


class RADIO_VFO_TYPE:
    MEMORY = 1
    VFO = 0


class RADIO_RX_CMD:
    # Startup CMDs
    STARTUP_1 = 0x70
    STARTUP_2 = 0x72
    STARTUP_3 = 0x52
    STARTUP_4 = 0x41

    # Display/Channel CMDs
    DISPLAY_TEXT = 0x01
    CHANNEL_TEXT = 0x02
    DISPLAY_CHANGE = 0x03
    DISPLAY_ICONS = 0x04

    # ICON CMDs
    ICON_SET = 0x10
    ICON_KEY2 = 0x11
    ICON_LOCK = 0x12
    ICON_APO = 0x13
    ICON_MAIN = 0x14
    ICON_TX = 0x15
    ICON_RPT_OFFSET_POS = 0x16
    ICON_RPT_OFFSET_NEG = 0x17
    ICON_CTCSS_ENCDEC = 0x18
    ICON_CTCSS_ENC = 0x19
    ICON_CHAN_SKIP = 0x1A
    ICON_CHAN_PREF = 0x1B
    ICON_BUSY = 0x1C
    ICON_SIG_BARS = 0x1D
    ICON_MEM_TUNE = 0x1E
    ICON_MUTE = 0x1F
    ICON_DCS = 0x20
    ICON_AM = 0x21
    ICON_9600 = 0x22
    ICON_PWR_LOW = 0x23
    ICON_PWR_MED = 0x24
    ICON_DOT_1ST = 0x25
    ICON_DOT_2ND = 0x26
    ICON_5 = 0x27


class _Icon:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


class RADIO_RX_ICON:
    @classmethod
    def get(cls, name):
        return getattr(cls, name)

    @classmethod
    def all(cls):
        return _RX_ICON_ALL


_RX_ICON_NAMES = (
    "SIGNAL",
    "APO", "LOCK", "KEY2", "SET",
    "NEG", "POS", "TX", "MAIN",
    "PREF", "SKIP", "ENC", "DEC",
    "DCS", "MUTE", "MT", "BUSY",
    "H", "M", "L", "AM",
)
for _name in _RX_ICON_NAMES:
    setattr(RADIO_RX_ICON, _name, _Icon(_name))
_RX_ICON_ALL = tuple(getattr(RADIO_RX_ICON, _n) for _n in _RX_ICON_NAMES)


class _TxCmd:
    def __init__(self, name, data):
        self.name = name
        self.data = data


# Every TX command is a 12-byte frame. DEFAULT is the base/idle frame; each
# command below overlays `payload` onto DEFAULT at [start:end] to build its
# frame — this is exactly what RADIO_TX_CMD.__init__ used to do per-member.
_TX_FRAME_DEFAULT = bytearray([0x84, 0xFF, 0xFF, 0xFF, 0xFF, 0x81, 0xFF, 0xFF, 0x82, 0xFF, 0xFF, 0x00])


def _tx_data(payload, start, end):
    return _TX_FRAME_DEFAULT[0:start] + bytearray(payload) + _TX_FRAME_DEFAULT[end:]


class RADIO_TX_CMD:
    @classmethod
    def get(cls, name):
        return getattr(cls, name)


# (name, payload, start, end) — see _tx_data / the original per-member __init__ this replaces.
_TX_TABLE = (
    ("DEFAULT", [], 0, 0),
    ("STARTUP", [0x80], 0, 12),

    # Custom Commands
    ("L_SET_VFO", [0x23, 0x24], 3, 5),  # Set main VFO to Left side
    ("R_SET_VFO", [0x24, 0x23], 3, 5),  # Set main VFO to Right side

    # Menu (aka SET) Button
    ("N_SET", [0x00, 0x20], 3, 5),
    ("N_SET_HOLD", [0x01, 0x20], 3, 5),

    # Left/Right VOL SQ CMDs used during radio startup
    ("L_VOLUME_SQUELCH", [0x01, 0xEB, 0x00, 0x02, 0xEB, 0x00], 5, 11),
    ("R_VOLUME_SQUELCH", [0x81, 0xEB, 0x00, 0x82, 0xEB, 0x00], 5, 11),

    # Left Buttons
    ("L_DIAL_PRESS", [0x00, 0x25], 3, 5),
    ("L_DIAL_HOLD", [0x01, 0x25], 3, 5),
    ("L_DIAL_LEFT", [0x01], 2, 3),
    ("L_DIAL_RIGHT", [0x02], 2, 3),
    ("L_VOLUME_PRESS", [0x01, 0x26], 3, 5),
    ("L_VOLUME_HOLD", [0x00, 0x26], 3, 5),
    ("L_VOLUME", [0x01, 0xEB, 0x00], 5, 8),
    ("L_SQUELCH", [0x02, 0xEB, 0x00], 8, 11),
    ("L_LOW", [0x00, 0x21], 3, 5),
    ("L_LOW_HOLD", [0x01, 0x21], 3, 5),
    ("L_VM", [0x00, 0x22], 3, 5),
    ("L_VM_HOLD", [0x01, 0x22], 3, 5),
    ("L_HM", [0x00, 0x23], 3, 5),
    ("L_HM_HOLD", [0x01, 0x23], 3, 5),
    ("L_SCN", [0x00, 0x24], 3, 5),
    ("L_SCN_HOLD", [0x01, 0x24], 3, 5),

    # Right Buttons
    ("R_DIAL_HOLD", [0x01, 0xA5], 3, 5),
    ("R_DIAL_PRESS", [0x00, 0xA5], 3, 5),
    ("R_DIAL_LEFT", [0x81], 2, 3),
    ("R_DIAL_RIGHT", [0x82], 2, 3),
    ("R_VOLUME", [0x81, 0xEB, 0x00], 5, 8),
    ("R_SQUELCH", [0x82, 0xEB, 0x00], 8, 11),
    ("R_LOW", [0x00, 0xA1], 3, 5),
    ("R_LOW_HOLD", [0x01, 0xA1], 3, 5),
    ("R_VM", [0x00, 0xA2], 3, 5),
    ("R_VM_HOLD", [0x01, 0xA2], 3, 5),
    ("R_HM", [0x00, 0xA3], 3, 5),
    ("R_HM_HOLD", [0x01, 0xA3], 3, 5),
    ("R_SCN", [0x00, 0xA4], 3, 5),
    ("R_SCN_HOLD", [0x01, 0xA4], 3, 5),

    # MIC/KEYPAD Buttons
    ("MIC_0", [0x00, 0x00], 3, 5),
    ("MIC_1", [0x00, 0x01], 3, 5),
    ("MIC_2", [0x00, 0x02], 3, 5),
    ("MIC_3", [0x00, 0x03], 3, 5),
    ("MIC_4", [0x00, 0x04], 3, 5),
    ("MIC_5", [0x00, 0x05], 3, 5),
    ("MIC_6", [0x00, 0x06], 3, 5),
    ("MIC_7", [0x00, 0x07], 3, 5),
    ("MIC_8", [0x00, 0x08], 3, 5),
    ("MIC_9", [0x00, 0x09], 3, 5),
    ("MIC_A", [0x00, 0x0A], 3, 5),
    ("MIC_B", [0x00, 0x0B], 3, 5),
    ("MIC_C", [0x00, 0x0C], 3, 5),
    ("MIC_D", [0x00, 0x0D], 3, 5),
    ("MIC_STAR", [0x00, 0x0E], 3, 5),
    ("MIC_POUND", [0x00, 0x0F], 3, 5),
    ("MIC_P1", [0x00, 0x10], 3, 5),
    ("MIC_P2", [0x00, 0x11], 3, 5),
    ("MIC_P3", [0x00, 0x12], 3, 5),
    ("MIC_P4", [0x00, 0x13], 3, 5),
    ("MIC_UP", [0x00, 0x14], 3, 5),
    ("MIC_DOWN", [0x00, 0x15], 3, 5),
    ("MIC_PTT", [0x00], 1, 2),

    # HYPER Buttons
    ("HYPER_A", [0x00, 0x27], 3, 5),
    ("HYPER_B", [0x00, 0x28], 3, 5),
    ("HYPER_C", [0x00, 0x29], 3, 5),
    ("HYPER_D", [0x00, 0xAA], 3, 5),
    ("HYPER_E", [0x00, 0xAB], 3, 5),
    ("HYPER_F", [0x00, 0xAC], 3, 5),
)
for _name, _payload, _start, _end in _TX_TABLE:
    setattr(RADIO_TX_CMD, _name, _TxCmd(_name, _tx_data(_payload, _start, _end)))
