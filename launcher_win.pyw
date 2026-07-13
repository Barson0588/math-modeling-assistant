#!/usr/bin/env python3
"""Math Modeling Assistant — Windows App Launcher (.pyw — no console window)

Starts the Flask server and opens the default browser.
Works both in development and as a PyInstaller .exe bundle.
"""
import os
import sys
import time
import threading
import webbrowser
from pathlib import Path


IS_FROZEN = getattr(sys, 'frozen', False)


def get_data_dir():
    """User-writable data directory. %APPDATA%/MathModelingAssistant/"""
    base = os.environ.get("APPDATA", str(Path.home()))
    path = Path(base) / "MathModelingAssistant"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_bundle_dir():
    """Root directory — project root in dev, sys._MEIPASS in PyInstaller."""
    if IS_FROZEN:
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def ensure_api_key():
    """Check for API key in env or user config file. Create template if missing."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return True

    env_file = get_data_dir() / ".env"
    if env_file.exists():
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val and val != "your-api-key-here":
                            os.environ["DEEPSEEK_API_KEY"] = val
                            return True
        except Exception:
            pass

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "# Math Modeling Assistant — API Configuration\n"
        "# Get your API key from https://platform.deepseek.com/api_keys\n"
        "DEEPSEEK_API_KEY=your-api-key-here\n"
    )
    return False


def main():
    # Load env from user config before importing app modules
    env_file = get_data_dir() / ".env"
    if env_file.exists():
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY=") and not line.startswith("#"):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val and val != "your-api-key-here":
                            os.environ["DEEPSEEK_API_KEY"] = val
        except Exception:
            pass

    has_key = bool(os.environ.get("DEEPSEEK_API_KEY"))

    if not has_key:
        ensure_api_key()
        config_path = str(get_data_dir() / ".env")
        print(f"[MMA] API key not configured. Please edit: {config_path}")
        print("[MMA] Add your DeepSeek API key, then relaunch.")
        # Try to open Notepad for the user
        try:
            os.startfile(config_path)  # noqa — Windows-only
        except Exception:
            pass

    # Import app AFTER setting up environment
    import app as app_module

    # Override Flask's template/static folder paths for PyInstaller bundles
    if IS_FROZEN:
        bundle = get_bundle_dir()
        app_module.app.template_folder = str(bundle / "templates")
        app_module.app.static_folder = str(bundle / "static")
        app_module.app.jinja_loader = app_module.app.create_global_jinja_loader()

    # Find an available port
    port = 8080
    url = f"http://127.0.0.1:{port}"

    def run_flask():
        try:
            app_module.app.run(
                host="127.0.0.1",
                port=port,
                debug=False,
                use_reloader=False,
            )
        except OSError as e:
            print(f"[MMA] Server error: {e}", file=sys.stderr)

    server_thread = threading.Thread(target=run_flask, daemon=True)
    server_thread.start()

    # Poll until Flask is ready
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(url, timeout=0.5)
            break
        except Exception:
            time.sleep(0.25)

    print(f"[MMA] Opening {url}")
    webbrowser.open(url)

    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[MMA] Shutting down.")


if __name__ == "__main__":
    main()
