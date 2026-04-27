from __future__ import annotations

import sys
import threading
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, QMetaObject, Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QIcon
from pathlib import Path
from downloader_app.runtime import set_ui_bridge

class UIBridge(QObject):
    # Signal to trigger folder picker on main thread
    _choose_folder_signal = pyqtSignal()
    _choose_browser_signal = pyqtSignal()

    def __init__(self, parent_window: QMainWindow):
        super().__init__()
        self.parent_window = parent_window
        self._last_folder = ""
        self._last_browser = ""
        self._event = threading.Event()
        self._choose_folder_signal.connect(self._do_choose_folder)
        self._choose_browser_signal.connect(self._do_choose_browser)
        
        self.qsettings = QSettings("Nhat", "VideoDownloader")
        self._recent_folder = self.qsettings.value("recent_folder", "")

    def choose_folder(self) -> str:
        """Called from any thread. Blocks until user chooses a folder."""
        self._last_folder = ""
        self._event.clear()
        # Trigger the signal which will be handled on the main thread
        self._choose_folder_signal.emit()
        # Wait for the main thread to finish
        self._event.wait()
        return self._last_folder

    def choose_browser(self) -> str:
        self._last_browser = ""
        self._event.clear()
        self._choose_browser_signal.emit()
        self._event.wait()
        return self._last_browser

    @pyqtSlot()
    def _do_choose_folder(self):
        """Internal handler that runs on the GUI thread."""
        try:
            folder = QFileDialog.getExistingDirectory(
                self.parent_window,
                "Chọn thư mục lưu trữ",
                self._recent_folder,
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
            )
            if folder:
                self._recent_folder = folder
                self.qsettings.setValue("recent_folder", folder)
            self._last_folder = folder
        finally:
            self._event.set()

    @pyqtSlot()
    def _do_choose_browser(self):
        try:
            if sys.platform == "darwin":
                browser_path, _ = QFileDialog.getOpenFileName(
                    self.parent_window,
                    "Chọn ứng dụng trình duyệt",
                    "/Applications",
                    "Applications (*.app);;All files (*)",
                )
            else:
                browser_path, _ = QFileDialog.getOpenFileName(
                    self.parent_window,
                    "Chọn trình duyệt",
                    "",
                    "Applications (*.exe *.app *.App);;All files (*)",
                )
            self._last_browser = browser_path
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
