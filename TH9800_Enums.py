from enum import Enum, auto

class RADIO_POWER(Enum):
    LOW = "L"
    MEDIUM_LOW = "ML"
    MEDIUM_HIGH = "MH"
    HIGH = "H"

    def __str__(self):
        return str(self.value)

class RADIO_VFO(Enum):
    LEFT = "L"
    RIGHT = "R"
    NONE = "N"

    def __str__(self):
        return str(self.value)

class RADIO_VFO_TYPE(Enum):
    MEMORY = "M"
    VFO = "V"

    def __str__(self):
        return str(self.value)

class RADIO_RX_CMD(Enum): #STILL BUILDING THIS OUT
    DISPLAY_TEXT = 0x01
    CHANNEL_TEXT = 0x02
    DISPLAY_CHANGE = 0x03
    DISPLAY_ICONS = auto()

    def __str__(self):
        return str(self.name)

class RADIO_TX_CMD(Enum):
    #Default Packet (Also sent after button press as a button release/return control to body) **See __init__**
    DEFAULT = (bytearray(),0,0)
    
    #Menu Button
    MENU = (bytearray([0x00,0x20]),3,5)
    
    #Left Buttons
    L_DIAL_PRESS = (bytearray([0x00,0x25]),3,5)
    L_DIAL_HOLD = (bytearray([0x01,0x25]),3,5)
    L_DIAL_LEFT = (bytearray([0x01]),2,3)
    L_DIAL_RIGHT = (bytearray([0x02]),2,3)
    L_VOLUME_PRESS = (bytearray([0x01,0x26]),3,5)
    L_VOLUME = (bytearray([0x01,0xEB,0x00]),5,8)
    L_SQUELCH = (bytearray([0x02,0xEB,0x00]),8,11)
    L_LOW = (bytearray([0x00,0x21]),3,5)
    L_LOW_HOLD = (bytearray([0x01,0x21]),3,5)
    L_VM = (bytearray([0x00,0x22]),3,5)
    L_VM_HOLD = (bytearray([0x01,0x22]),3,5)
    L_HM = (bytearray([0x00,0x23]),3,5)
    L_HM_HOLD = (bytearray([0x01,0x23]),3,5)
    L_SCN = (bytearray([0x00,0x24]),3,5)
    L_SCN_HOLD = (bytearray([0x01,0x24]),3,5)
    
    #Right Buttons
    R_DIAL_HOLD = (bytearray([0x01,0xA5]),3,5)
    R_DIAL_PRESS = (bytearray([0x00,0xA5]),3,5)
    R_DIAL_LEFT = (bytearray([0x81]),2,3)
    R_DIAL_RIGHT = (bytearray([0x82]),2,3)
    R_VOLUME = (bytearray([0x81,0xEB,0x00]),5,8)
    R_SQUELCH = (bytearray([0x82,0xEB,0x00]),8,11)
    R_LOW = (bytearray([0x00,0xA1]),3,5)
    R_LOW_HOLD = (bytearray([0x01,0xA1]),3,5)
    R_VM = (bytearray([0x00,0xA2]),3,5)
    R_VM_HOLD = (bytearray([0x01,0xA2]),3,5)
    R_HM = (bytearray([0x00,0xA3]),3,5)
    R_HM_HOLD = (bytearray([0x01,0xA3]),3,5)
    R_SCN = (bytearray([0x00,0xA4]),3,5)
    R_SCN_HOLD = (bytearray([0x01,0xA4]),3,5)
    
    #MIC/KEYPAD Buttons
    MIC_0 = (bytearray([0x00,0x00]),3,5)
    MIC_1 = (bytearray([0x00,0x01]),3,5)
    MIC_2 = (bytearray([0x00,0x02]),3,5)
    MIC_3 = (bytearray([0x00,0x03]),3,5)
    MIC_4 = (bytearray([0x00,0x04]),3,5)
    MIC_5 = (bytearray([0x00,0x05]),3,5)
    MIC_6 = (bytearray([0x00,0x06]),3,5)
    MIC_7 = (bytearray([0x00,0x07]),3,5)
    MIC_8 = (bytearray([0x00,0x08]),3,5)
    MIC_9 = (bytearray([0x00,0x09]),3,5)
    MIC_A = (bytearray([0x00,0x0A]),3,5)
    MIC_B = (bytearray([0x00,0x0B]),3,5)
    MIC_C = (bytearray([0x00,0x0C]),3,5)
    MIC_D = (bytearray([0x00,0x0D]),3,5)
    MIC_STAR = (bytearray([0x00,0x0E]),3,5)
    MIC_POUND = (bytearray([0x00,0x0F]),3,5)
    MIC_P1 = (bytearray([0x00,0x10]),3,5)
    MIC_P2 = (bytearray([0x00,0x11]),3,5)
    MIC_P3 = (bytearray([0x00,0x12]),3,5)
    MIC_P4 = (bytearray([0x00,0x13]),3,5)
    MIC_UP = (bytearray([0x00,0x14]),3,5)
    MIC_DOWN = (bytearray([0x00,0x15]),3,5)
    MIC_PTT = (bytearray([0x00]),1,2)
    
    #HYPER Buttons
    HYPER_A = (bytearray([0x00,0x27]),3,5)
    HYPER_B = (bytearray([0x00,0x28]),3,5)
    HYPER_C = (bytearray([0x00,0x29]),3,5)
    HYPER_D = (bytearray([0x00,0xAA]),3,5)
    HYPER_E = (bytearray([0x00,0xAB]),3,5)
    HYPER_F = (bytearray([0x00,0xAC]),3,5)

    def __init__(self, data: bytearray, start: int, end: int = None):
        DEFAULT = bytearray([0x84,0xFF,0xFF,0xFF,0xFF,0x81,0xFF,0xFF,0x82,0xFF,0xFF,0x00])
        self.start = start
        self.end = end
        self.data = DEFAULT[0:start] + data + DEFAULT[(end):]

    def as_dict(self):
        return {"data": self.data, "start": self.start, "end": self.end}

    def __str__(self):
        return str(self.name)