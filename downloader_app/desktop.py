from __future__ import annotations

import sys
import threading
import time
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QIcon
from pathlib import Path

class DesktopWindow(QMainWindow):
    def __init__(self, url: str):
        super().__init__()
        self.setWindowTitle("Video Downloader")
        self.resize(1280, 800)
        
        # Set window icon
        icon_path = Path(__file__).resolve().parent.parent / "static" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

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
