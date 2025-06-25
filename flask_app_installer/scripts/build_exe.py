import PyInstaller.__main__

PyInstaller.__main__.run([
    'flask_app/app.py',
    '--name=FlaskDesktopApp',
    '--onefile',
    '--console',  # TEMP: Show console to debug; change to '--noconsole' later
    '--add-data=flask_app/templates;templates',
    '--add-data=flask_app/static;static',
])
