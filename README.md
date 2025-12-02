# DE Indicator Sensor
Program for monitoring temperatures and other system data for Deepin Linux.
<img width="2000" height="1600" alt="l" src="https://github.com/user-attachments/assets/53515bba-e023-4111-979a-80945b5aeadf" />

### Video Test
https://github.com/user-attachments/assets/8429b4e3-3621-435c-80e7-a0d1ea398ce0

### Available languages:
 -   Portuguese
 -   Spanish
 -   English

### Compile binary:
- pyinstaller --onefile --noconfirm --clean --strip -w --name "de-indicator-sensor" --icon=resources/appicon.png --add-data "resources:resources" --exclude-module tkinter --exclude-module unittest --exclude-module doctest --exclude-module pydoc --hidden-import PyQt6.QtCore --hidden-import PyQt6.QtGui --hidden-import PyQt6.QtWidgets main.py

### Compile Deb package:
1. Create release file.

- dch --create -D stable --package "de-indicator-sensor" --newversion=1.x.x "New release."

2. Compilation Dependencies:

- sudo apt build-dep .

3. Compile Package:

- dpkg-buildpackage -Zxz -rfakeroot -b


### Warning: The quality of this product is not guaranteed. If you encounter any problems, please report them.

### Using the GPL v3 license.
