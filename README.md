# TYT TH-9800 CAT Control via Remote Head Serial Protocol 
## Required
### Software <a href="https://buymeacoffee.com/sleepyninja" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-green.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" align="right"></a>
- Install [Python](https://www.python.org/downloads/) (written in v3.13)
- Install Python modules:
  - [pySerial-asyncio](https://pypi.org/project/pyserial-asyncio/) module (pip install pyserial-asyncio)
  - [DearPyGui](https://pypi.org/project/dearpygui/) module (pip install dearpygui)
### Hardware
- [RJ12 Breakout Board](https://www.amazon.com/dp/B00CMOW40Q) (Makes wiring easier)
- [USB to TTL UART Adapter](https://www.amazon.com/dp/B07WX2DSVB) (Any USB serial (UART) adapter should work)
- Optional switch to change TX line between USB UART and Radio Head (RX line doesn't need a switch)
  - I believe there are ways to connect two TX lines to one RX but it requires a more complex circuit (2 Diodes and pullup resistor??)

## How to Run
 - Right click "TH9800_CAT.py" file and start with Python.
 - Open command line, CD to directory, and run "python.exe TH9800_CAT.py".

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
