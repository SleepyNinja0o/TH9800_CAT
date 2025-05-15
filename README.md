# TYT TH-9800 CAT Control via Remote Head Serial Protocol 
## Research
There was no documentation on the remote radio head protocol so I had to reverse engineer it. Here is what I used:
- Hardware:
  - [USB Logic Analyzer 24MHz 8CH](https://www.amazon.com/dp/B0CHZ13R6D)
  - [USB to TTL UART Adapter](https://www.amazon.com/dp/B07WX2DSVB) (Any USB serial adapter (UART) should work)
  - [RJ12 Breakout Board](https://www.amazon.com/dp/B00CMOW40Q) (Makes wiring easier)
  - [6 Pins 3 Position DPDT Switch](https://www.amazon.com/dp/B07MV52Z9R) (Optional switch to change TX line between USB UART and Radio Head) (RX line doesn't need a switch)
  - [74LS157 - Quad 2-Input Multiplexer IC](https://www.amazon.com/dp/B08CCLF9S4?ref=ppx_yo2ov_dt_b_fed_asin_title) (Optional Multiplexer IC, can be used instead of a TX switch [Controlled by UART RTS Pin]) ****See bottom of Setup section
- Software
  - [Logic](https://www.saleae.com/pages/downloads) software used with the Logic Analyzer to decode packets to/from radio
  - [SerialTool](https://serialtool.com/_en/index.php) software used to capture, modify and replay packets
- Issues
  - You can NOT connect 2 TX pins together (radio head + USB adapter) at the same time since they both will be a normally high state (5v). You will need a TX switch or another type of circuit if you want to control radio from both devices.

## Required
### Software <a href="https://buymeacoffee.com/sleepyninja" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-green.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" align="right"></a>
- [Python](https://www.python.org/downloads/) (written in v3.13)
- Python modules (Install using "pip install -r requirements.txt" for Windows + Linux x64):
  - [asyncio](https://pypi.org/project/asyncio/) module
  - [pySerial-asyncio](https://pypi.org/project/pyserial-asyncio/) module
  - [DearPyGui](https://pypi.org/project/dearpygui/) module
    - If you're running an ARMv7/ARMv8 processor (Common in [SBCs](https://en.wikipedia.org/wiki/Single-board_computer)), you will have to manually build the DearPyGui module.<br>
        (Grab some coffee, the build can take a while on lower end boards)<br><br>
         ```
         apt update
         apt install git cmake python3 python3-dev libglu1-mesa-dev libgl1-mesa-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev
         git clone --recursive https://github.com/hoffstadt/DearPyGui
         cd DearPyGui
         
         #Build for ARMv7 (Ex: Raspberry Pi 2)
         python3 -m setup bdist_wheel --plat-name linux_armv7l --dist-dir ../dist
         pip install ../dist/dearpygui-2.0.0-cp312-cp312-linux_armv7l.whl

         #Build for ARMv8 (Raspberry Pi 3 and above, also works on my Orange Pi Zero 3)
         python3 -m setup bdist_wheel --plat-name linux_aarch64 --dist-dir ../dist
         pip install ../dist/dearpygui-2.0.0-cp312-cp312-linux_aarch64.whl
         ```
## How to Run
 - Right click "TH9800_CAT.py" file and start with Python.
 - Open command line, CD to directory, and run "python.exe TH9800_CAT.py".

## Setup
![Logic Analyzer](https://github.com/user-attachments/assets/d5947f75-5652-4114-9efd-5413d0a7ce16)

![TH9800 Serial USB Setup](https://github.com/user-attachments/assets/8258de67-dcb8-42cf-860e-50841742ae6c)

![RJ12 Pinout at Radio Body](https://github.com/user-attachments/assets/d25ceff1-73d7-40d8-be64-9485357af558)

![TH9800 Serial USB Closeup](https://github.com/user-attachments/assets/f8352717-4ea2-4836-8ca1-856296ceb011)

## 74LS157 - Quad 2-Input Multiplexer IC Setup (Software TX Switch)
![74LS157 TX Switch](https://github.com/user-attachments/assets/2a798c99-ae86-4289-a888-a0873f1f708c)

## Screenshots of Python App
### Serial Connection Window
![Screenshot 2025-04-22 214317](https://github.com/user-attachments/assets/c9029ed8-e146-4580-85d5-26d850d7f922)
![Screenshot 2025-05-02 010311](https://github.com/user-attachments/assets/bd5a6030-328c-4deb-934b-fd69ea7c153a)

### Radio Interface with All Labels Enabled
![Screenshot 2025-05-02 010658](https://github.com/user-attachments/assets/f856fbdf-8e82-4552-850c-33d39964f6e3)

### Regular Radio Interface
![Screenshot 2025-05-02 010505](https://github.com/user-attachments/assets/bcbbf505-cf1f-4cc5-a840-95b8ae650c4c)


## Python App Demo
https://github.com/user-attachments/assets/64dbb72e-c534-4081-8b50-a81ffba903bf

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.

Use at your own risk.
