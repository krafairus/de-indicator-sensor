# DE Indicator Sensor
Program for monitoring temperatures and other system data for Deepin Linux.

https://github.com/user-attachments/assets/f4e9750d-18b3-4a28-a585-7d79c4b4fd50

### Available languages:
 -   Portuguese
 -   Spanish
 -   English

### Compile binary:
- pyinstaller --onefile --noconfirm --clean --strip -w --name "SensorMonitor" --icon=resources/appicon.png --add-data "resources:resources" --exclude-module tkinter --exclude-module unittest --exclude-module doctest --exclude-module pydoc --hidden-import PyQt6.QtCore --hidden-import PyQt6.QtGui --hidden-import PyQt6.QtWidgets main.py

### Compile Deb package:
1. Create release file.

- dch --create -D stable --package "de-indicator-sensor" --newversion=1.x.x "New release."

2. Compilation Dependencies:

- sudo apt build-dep .

3. Compile Package:

- dpkg-buildpackage -Zxz -rfakeroot -b


### Warning: The quality of this product is not guaranteed. If you encounter any problems, please report them.

### Using the GPL v3 license.
