#!/usr/bin/env python3
"""Math Modeling Assistant — macOS App Launcher

Starts the Flask server and opens the default browser.
Works both in development (python launcher.py) and as a PyInstaller .app bundle.
"""
import os
import sys
import time
import threading
import webbrowser
from pathlib import Path


IS_FROZEN = getattr(sys, 'frozen', False)


def get_data_dir():
    """User-writable data directory. ~/.math-modeling-assistant/"""
    path = Path.home() / ".math-modeling-assistant"
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

    # Try loading from user config dir
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

    # Create template
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
        # Open the config file so user can fill in the key
        config_path = str(get_data_dir() / ".env")
        os.system(f"open -a TextEdit '{config_path}' 2>/dev/null || open -t '{config_path}'")
        print("[MMA] API key not configured. Template opened in TextEdit.")
        print(f"[MMA] Edit {config_path} to add your DeepSeek API key, then relaunch.")

    # Import app AFTER setting up environment
    import app as app_module

    # Override Flask's template/static folder paths for PyInstaller bundles
    if IS_FROZEN:
        bundle = get_bundle_dir()
        app_module.app.template_folder = str(bundle / "templates")
        app_module.app.static_folder = str(bundle / "static")
        # Reload the Jinja environment so the new template_folder takes effect
        app_module.app.jinja_loader = app_module.app.create_global_jinja_loader()

    # Start Flask in a daemon thread
    port = 8080

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
    url = f"http://127.0.0.1:{port}"
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(url, timeout=0.5)
            break
        except Exception:
            time.sleep(0.25)
    else:
        print("[MMA] Warning: server may not be ready", file=sys.stderr)

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
