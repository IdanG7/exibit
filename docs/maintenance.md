# Maintenance

Run these commands from the repository's top-level folder after Setup.cmd has finished.

```powershell
# Automated tests (no connected audio devices required)
.venv\Scripts\python.exe -m unittest discover -v

# Open the controller
.venv\Scripts\python.exe -m app.exhibit

# List available audio devices
.venv\Scripts\python.exe -m app.exhibit --devices
```

The Windows launchers use the app module and always set their working folder to the repository root. Audio, recordings, logs, config.json, and stop.flag remain at the root, independent of the code folder.

Diagnostic tools use real hardware. Stop the exhibit before running them:

```powershell
# Two-second silent test of the CMTECK mic and USB2.0 speaker
.venv\Scripts\python.exe -m tools.hardware_check

# Sixty-second silent test of the saved device configuration
.venv\Scripts\python.exe -m tools.reliability_hardware_check

# Forty-second button check; writes detected key codes to logs
.venv\Scripts\python.exe -m tools.button_probe
```

The diagnostic tools do not save visitor recordings. The reliability check disables button input and mutes every configured speaker, including individual volume overrides.
