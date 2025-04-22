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
    MIC = "MIC"
    NONE = "N"

    def __str__(self):
        return str(self.value)

class RADIO_VFO_TYPE(Enum):
    MEMORY = "M"
    VFO = "V"

    def __str__(self):
        return str(self.value)

class RADIO_RX_ICON(Enum):
    #Data index 1
    SIGNAL = (0x00,1) # to 0x09

    #Data index 2
    APO = (0x02,2)
    LOCK = (0x08,2)
    KEY2 = (0x20,2)
    SET = (0x80,2)
    
    #Data index 3
    NEG = (0x02,3)
    POS = (0x08,3)
    TX = (0x20,3) #Not sent by radio
    MAIN = (0x80,3)
    
    #Data index 4
    PREF = (0x02,4)
    SKIP = (0x08,4)
    ENC = (0x20,4)
    #DEC_ONLY = (0x80,4) #Not sent by radio
    DEC = (0xA0,4)
    
    #Data index 5
    DCS = (0x02,5)
    MUTE = (0x08,5)
    MT = (0x20,5)
    BUSY = (0x80,5)
    
    #Data index 6
    H = (0x00,6)
    M = (0x02,6)
    L = (0x08,6)
    #D9600 = (0x20,6) #Not sent by radio
    AM = (0x80,6)

    def __init__(self, data: int, pos: int):
        self.data = data
        self.pos = pos

    def as_dict(self):
        return {"data": self.data, "pos": self.pos}

    def __str__(self):
        return str(self.name)

class RADIO_RX_CMD(Enum):
    #Startup CMDs
    STARTUP_1 = 0x70
    STARTUP_2 = 0x72
    STARTUP_3 = 0x52
    STARTUP_4 = 0x41
    
    #Display/Channel CMDs
    DISPLAY_TEXT = 0x01
    CHANNEL_TEXT = 0x02
    DISPLAY_CHANGE = 0x03
    DISPLAY_ICONS = 0x04
    
    #ICON CMDs
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

    def __int__(self):
        return int(self.value)

    def __str__(self):
        return str(self.name)

class RADIO_TX_CMD(Enum):
    #Default Packet (Also sent after button press as a button release/return control to body) **See __init__**
    DEFAULT = (bytearray(),0,0)
    STARTUP = (bytearray([0x80]),0,12)
    
    #Menu Button
    MENU = (bytearray([0x00,0x20]),3,5)
    
    #Left/Right VOL SQ CMDs used during radio startup
    L_VOLUME_SQUELCH = (bytearray([0x01,0xEB,0x00,0x02,0xEB,0x00]),5,11)
    R_VOLUME_SQUELCH = (bytearray([0x81,0xEB,0x00,0x82,0xEB,0x00]),5,11)
    
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