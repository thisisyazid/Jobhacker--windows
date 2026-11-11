"""Job Hacker for Windows: starts the app on this computer and opens it in the browser.

- Runs the web app on http://127.0.0.1 only, so nothing outside this PC can reach it.
- Keeps data in %LOCALAPPDATA%\\JobHacker (jobhacker.db, jobhacker.log).
- Tray icon: Open Job Hacker, Start when Windows starts, Open data folder, Quit.
- Starting it again while it's running just opens the browser.

Options:
  --background  start without opening the browser (used by "Start when Windows starts")
  --check       start, make sure the app answers, then exit 0 (used by the build)
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "JobHacker"
PREFERRED_PORT = 47815  # fixed, so the browser keeps its saved filters between runs
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
FROZEN = getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Where static/ lives: inside the exe when frozen, else the repo root."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:  # running the launcher on macOS/Linux for development
        base = Path.home() / ".local" / "share"
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def local_timezone() -> str:
    try:
        from tzlocal import get_localzone_name
        return get_localzone_name() or "UTC"
    except Exception:
        return "UTC"


def health(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return json.load(r).get("app") == "jobhacker"
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":  # a just-closed port lingers in TIME_WAIT; the server reuses it the same way
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def any_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- Start when Windows starts ----------

def _autostart_command() -> str:
    exe = sys.executable if FROZEN else f'{sys.executable}" "{Path(__file__).resolve()}'
    return f'"{exe}" --background'


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


# ---------- server ----------

def start_server(port: int):
    """Start the app in a background thread; returns the uvicorn Server once it answers."""
    import uvicorn
    from app.main import app  # imported after the environment is set: settings are read at import

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None,
                                           access_log=False, lifespan="on"))
    threading.Thread(target=server.run, name="jobhacker-server", daemon=True).start()
    for _ in range(300):  # up to 30 s
        if server.started and health(port):
            return server
        time.sleep(0.1)
    raise RuntimeError("Job Hacker didn't start within 30 seconds. See jobhacker.log.")


def check(port: int) -> int:
    """Smoke test for the build: page, script, API and the Claude key setting all answer."""
    base = f"http://127.0.0.1:{port}"
    for path, must in (("/", b"Job Hacker"), ("/assets/app.js", b"renderList"),
                       ("/api/session", b"ai_enabled"), ("/api/settings/ai", b"has_key")):
        with urllib.request.urlopen(base + path, timeout=10) as r:
            body = r.read()
            if r.status != 200 or must not in body:
                logging.error("check failed: %s", path)
                return 1
    try:  # the PDF export needs the bundled fonts
        from app.pdf_export import to_pdf
        if to_pdf("# Check\nx@y.z\nHeadline\n\n## Experience\n- Did things", "resume")[:5] != b"%PDF-":
            raise ValueError("not a PDF")
    except Exception:
        logging.exception("check failed: PDF export")
        return 1
    try:  # Excel export of the job list
        import io
        from openpyxl import Workbook
        buf = io.BytesIO()
        Workbook().save(buf)
        if buf.getvalue()[:2] != b"PK":
            raise ValueError("not an xlsx")
    except Exception:
        logging.exception("check failed: Excel export")
        return 1
    logging.info("check passed")
    return 0


# ---------- tray ----------

def run_tray(server, url: str, folder: Path) -> None:
    import pystray
    from PIL import Image

    image = Image.open(resource_dir() / "static" / "icons" / "icon-192.png")

    def open_app(icon=None, item=None):
        webbrowser.open(url)

    def toggle_autostart(icon, item):
        set_autostart(not autostart_enabled())

    def open_folder(icon, item):
        if os.name == "nt":
            os.startfile(folder)  # noqa: S606 - opens Explorer on our own data folder
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def quit_app(icon, item):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Job Hacker", open_app, default=True),
        pystray.MenuItem("Start when Windows starts", toggle_autostart,
                         checked=lambda item: autostart_enabled(), visible=os.name == "nt"),
        pystray.MenuItem("Open data folder", open_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Job Hacker", quit_app),
    )
    pystray.Icon(APP_NAME, image, "Job Hacker", menu).run()


def message(text: str) -> None:
    """Show an error the user can see even though the exe has no console window."""
    logging.error(text)
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Job Hacker", 0x10)
    else:
        print(text, file=sys.stderr)


def main(argv: list[str]) -> int:
    background, checking = "--background" in argv, "--check" in argv
    folder = data_dir()

    # A windowed exe has no console: send output to a log file instead.
    log = open(folder / ("check.log" if checking else "jobhacker.log"), "a", encoding="utf-8", buffering=1)
    if FROZEN or sys.stdout is None:
        sys.stdout = sys.stderr = log
    logging.basicConfig(stream=log, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Already running? Just open it.
    if not checking and health(PREFERRED_PORT):
        if not background:
            webbrowser.open(f"http://127.0.0.1:{PREFERRED_PORT}/")
        return 0

    port = any_free_port() if checking else None
    for _ in range(10):  # right after Quit the port can take a moment to free up
        if port or port_free(PREFERRED_PORT):
            port = port or PREFERRED_PORT
            break
        time.sleep(0.5)
    port = port or any_free_port()
    os.environ.setdefault("DATA_DIR", str(folder))
    os.environ.setdefault("STATIC_DIR", str(resource_dir() / "static"))
    os.environ.setdefault("TZ_NAME", local_timezone())
    os.environ.setdefault("COOKIE_SECURE", "false")
    if checking:
        os.environ["DATA_DIR"] = str(folder / "check")
        os.environ["NIGHTLY_SCHEDULER"] = "0"
        Path(os.environ["DATA_DIR"]).mkdir(exist_ok=True)
    sys.path.insert(0, str(resource_dir()))
    logging.info("starting on port %s, data in %s, time zone %s", port, os.environ["DATA_DIR"], os.environ["TZ_NAME"])

    try:
        server = start_server(port)
    except Exception as e:
        logging.exception("startup failed")
        if checking:
            return 1
        message(f"Job Hacker couldn't start.\n\n{e}\n\nDetails are in {folder / 'jobhacker.log'}")
        return 1

    if checking:
        try:
            return check(port)
        finally:
            server.should_exit = True

    url = f"http://127.0.0.1:{port}/"
    if not background:
        webbrowser.open(url)
    try:
        run_tray(server, url, folder)
    except ImportError:  # no tray library (development on another OS): run until Ctrl+C
        logging.info("no tray available; press Ctrl+C to stop")
        try:
            while not server.should_exit:
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.should_exit = True
    time.sleep(0.5)  # let the server finish what it's doing
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
