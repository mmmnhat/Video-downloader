from __future__ import annotations

import sys
import threading
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, QMetaObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from pathlib import Path
from downloader_app.runtime import set_ui_bridge
import threading

class UIBridge(QObject):
    # Signal to trigger folder picker on main thread
    _choose_folder_signal = pyqtSignal()

    def __init__(self, parent_window: QMainWindow):
        super().__init__()
        self.parent_window = parent_window
        self._last_folder = ""
        self._event = threading.Event()
        self._choose_folder_signal.connect(self._do_choose_folder)

    def choose_folder(self) -> str:
        """Called from any thread. Blocks until user chooses a folder."""
        self._last_folder = ""
        self._event.clear()
        # Trigger the signal which will be handled on the main thread
        self._choose_folder_signal.emit()
        # Wait for the main thread to finish
        self._event.wait()
        return self._last_folder

    @pyqtSlot()
    def _do_choose_folder(self):
        """Internal handler that runs on the GUI thread."""
        try:
            folder = QFileDialog.getExistingDirectory(
                self.parent_window,
                "Chọn thư mục lưu trữ",
                "",
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
            )
            self._last_folder = folder
        finally:
            self._event.set()

class DesktopWindow(QMainWindow):
    def __init__(self, url: str):
        super().__init__()
        self.setWindowTitle("Video Downloader")
        self.resize(1280, 800)
        
        # Set window icon
        icon_path = Path(__file__).resolve().parent.parent / "static" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Initialize bridge
        self.bridge = UIBridge(self)
        set_ui_bridge(self.bridge)

        self.browser = QWebEngineView()
        
        # Enable clipboard access and other modern features
        settings = self.browser.settings()
        settings.setAttribute(settings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(settings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(settings.WebAttribute.AllowRunningInsecureContent, True)

        # Handle permissions (like clipboard access)
        self.browser.page().permissionRequested.connect(self._handle_permission_request)
        
        self.browser.setUrl(QUrl(url))
        self.setCentralWidget(self.browser)

    def _handle_permission_request(self, request):
        # Auto-grant clipboard and other basic permissions for our app
        request.grant()


def run_desktop(url: str) -> int:
    app = QApplication(sys.argv)
    window = DesktopWindow(url)
    window.show()
    return app.exec()
