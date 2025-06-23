# 🖥️ My Flask App Desktop Installer

This project wraps a Python Flask web application into a **Windows desktop app** using **PyInstaller** and creates a full **installer executable** using **NSIS**.

Once installed, the app can be launched like any normal desktop software — with a shortcut on your Desktop and Start Menu.

---

## 🚀 Features

- 🧠 Built with Python and Flask
- 📦 Packaged into a `.exe` using PyInstaller
- 📋 Custom Windows Installer using NSIS
- 🔗 Automatically opens in browser at `http://127.0.0.1:5000`
- 💻 Runs silently with a single desktop click
- 🧼 Includes an uninstaller to cleanly remove the app

---

## 📁 Project Structure

```bash
flask_app_installer/
├── flask_app/
│   ├── app.py                # Main Flask app (launches browser)
│   ├── config.py             # App configuration
│   ├── requirements.txt      # Python dependencies
│   ├── static/
│   │   ├── css/style.css     # Stylesheet
│   │   └── js/script.js      # JS Script
│   └── templates/
│       └── index.html        # HTML template
│
├── scripts/
│   └── build_exe.py          # Script to generate FlaskDesktopApp.exe using PyInstaller
│
├── setup/
│   ├── run_app.vbs           # VBScript to launch app silently
│   ├── icon.ico              # App icon for shortcut
│   └── installer_script.nsi  # NSIS script to build installer
│
├── README.md                 # Project instructions (this file)
└── LICENSE                   # Optional license


🔧 Installation for Developers

1. 🧰 Set up the Environment
cd flask_app_installer/flask_app
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

2. ⚙️ Build the Executable
cd ..\scripts
python build_exe.py
Output: dist/FlaskDesktopApp.exe

3. 🛠 Create Installer
Open setup/installer_script.nsi in NSIS
Click Compile
It will generate FlaskAppInstaller.exe

🧪 Using the App (For End Users)
After installing:
✅ A shortcut appears on your Desktop
🖱 Click it → app runs silently in background
🌐 Your browser opens automatically at http://127.0.0.1:5000

To uninstall:
Use Start Menu > My Flask App > Uninstall
Or run uninstall.exe from the install directory

📌 Customization
To auto-start app on Windows boot, add registry key in NSIS.
To change icon: replace setup/icon.ico
To change UI: edit templates/index.html and static/ assets

🪪 License
This project is licensed under the MIT License. See LICENSE for details.