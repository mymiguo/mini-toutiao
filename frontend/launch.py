"""Launch backend + Electron frontend together."""
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent / "backend"
FRONTEND_DIR = Path(__file__).parent


def main():
    print("Starting A-share trading backend...")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(BACKEND_DIR)
    )
    time.sleep(3)
    print("Backend started at http://127.0.0.1:8765")
    print("API docs at http://127.0.0.1:8765/docs")

    # Try to start Electron; if not available, open browser instead
    try:
        electron = subprocess.Popen(
            ["npx", "electron", "."],
            cwd=str(FRONTEND_DIR)
        )
    except Exception:
        print("Electron not found, opening browser...")
        webbrowser.open("http://127.0.0.1:8765/docs")

    try:
        backend.wait()
    except KeyboardInterrupt:
        print("Shutting down...")
        backend.terminate()
        try:
            electron.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
