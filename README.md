# TYT TH-9800 CAT Control via Remote Head Serial Protocol
## Required
- Python (written in v3.13) + Modules:
  - serial_asyncio module (pip install pyserial-asyncio)
  - dearpygui module (pip install dearpygui)
- [RJ12 Breakout Board](https://www.amazon.com/dp/B00CMOW40Q) (Makes wiring easier)
- [USB to TTL UART Adapter](https://www.amazon.com/dp/B07WX2DSVB) (Any USB serial (UART) adapter should work)
- Optional switch to change TX line between USB UART and Radio Head (RX line doesn't need a switch)
  - I believe there are ways to connect two TX lines to one RX but it requires a more complex circuit (2 Diodes and pullup resistor??)

## Setup
![TH9800 Serial USB Setup](https://github.com/user-attachments/assets/12cae08c-5a36-4b19-ae55-cad5e6db2fa0)

![RJ12 Pinout at Radio Body](https://github.com/user-attachments/assets/d25ceff1-73d7-40d8-be64-9485357af558)

![TH9800 Serial USB Closeup](https://github.com/user-attachments/assets/f8352717-4ea2-4836-8ca1-856296ceb011)

## Screenshots of Python App
### Serial Connection Window
![Screenshot 2025-04-22 214317](https://github.com/user-attachments/assets/c9029ed8-e146-4580-85d5-26d850d7f922)
### Radio Interface with All Labels Enabled
![Screenshot 2025-04-22 021954](https://github.com/user-attachments/assets/e916092d-2c22-405b-92a5-9a8e0ce38115)
### Regular Radio Interface
![Screenshot 2025-04-22 214628](https://github.com/user-attachments/assets/a0899888-b840-46c8-9e71-e6cdf84f9e93)
