from __future__ import annotations

import sys
import threading
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, QMetaObject, Qt, pyqtSignal, QSettings, QStandardPaths
from PyQt6.QtGui import QIcon
from pathlib import Path
from downloader_app.runtime import set_ui_bridge

class UIBridge(QObject):
    # Signal to trigger folder picker on main thread
    _choose_folder_signal = pyqtSignal()
    _choose_browser_signal = pyqtSignal()
    _choose_file_signal = pyqtSignal()
    _save_file_signal = pyqtSignal()

    def __init__(self, parent_window: QMainWindow):
        super().__init__()
        self.parent_window = parent_window
        self._last_folder = ""
        self._last_browser = ""
        self._last_file = ""
        self._event = threading.Event()
        self._choose_folder_signal.connect(self._do_choose_folder)
        self._choose_browser_signal.connect(self._do_choose_browser)
        self._choose_file_signal.connect(self._do_choose_file)
        self._save_file_signal.connect(self._do_save_file)
        
        self.qsettings = QSettings()
        self._recent_folder = self.qsettings.value("recent_folder", "", type=str)
        self._pending_file_title = "Chọn tệp"
        self._pending_file_directory = ""
        self._pending_file_filter = "All files (*)"
        self._pending_save_title = "Lưu tệp"
        self._pending_save_path = ""
        self._pending_save_filter = "All files (*)"

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

    def choose_file(
        self,
        title: str = "Chọn tệp",
        directory: str = "",
        file_filter: str = "All files (*)",
    ) -> str:
        self._last_file = ""
        self._pending_file_title = title
        self._pending_file_directory = directory
        self._pending_file_filter = file_filter
        self._event.clear()
        self._choose_file_signal.emit()
        self._event.wait()
        return self._last_file

    def save_file(
        self,
        title: str = "Lưu tệp",
        default_path: str = "",
        file_filter: str = "All files (*)",
    ) -> str:
        self._last_file = ""
        self._pending_save_title = title
        self._pending_save_path = default_path
        self._pending_save_filter = file_filter
        self._event.clear()
        self._save_file_signal.emit()
        self._event.wait()
        return self._last_file

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

    @pyqtSlot()
    def _do_choose_file(self):
        try:
            start_dir = self._pending_file_directory or self._recent_folder
            file_path, _ = QFileDialog.getOpenFileName(
                self.parent_window,
                self._pending_file_title,
                start_dir,
                self._pending_file_filter,
            )
            if file_path:
                self._recent_folder = str(Path(file_path).expanduser().parent)
                self.qsettings.setValue("recent_folder", self._recent_folder)
            self._last_file = file_path
        finally:
            self._event.set()

    @pyqtSlot()
    def _do_save_file(self):
        try:
            start_path = self._pending_save_path or self._recent_folder
            file_path, _ = QFileDialog.getSaveFileName(
                self.parent_window,
                self._pending_save_title,
                start_path,
                self._pending_save_filter,
            )
            if file_path:
                self._recent_folder = str(Path(file_path).expanduser().parent)
                self.qsettings.setValue("recent_folder", self._recent_folder)
            self._last_file = file_path
        finally:
            self._event.set()

class DesktopWindow(QMainWindow):
    def __init__(self, url: str):
        super().__init__()
        self.setWindowTitle("Video Downloader")
        
        self.qsettings = QSettings()
        geometry = self.qsettings.value("geometry")
        state = self.qsettings.value("windowState")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1280, 800)
            
        if state is not None:
            self.restoreState(state)
        
        # Set window icon
        icon_path = Path(__file__).resolve().parent.parent / "static" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Initialize bridge
        self.bridge = UIBridge(self)
        set_ui_bridge(self.bridge)

        storage_root = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
        )
        profile_storage_path = storage_root / "webengine"
        profile_cache_path = storage_root / "webengine-cache"
        profile_storage_path.mkdir(parents=True, exist_ok=True)
        profile_cache_path.mkdir(parents=True, exist_ok=True)

        self.browser = QWebEngineView()
        self.profile = QWebEngineProfile("VideoDownloader", self.browser)
        self.profile.setPersistentStoragePath(str(profile_storage_path))
        self.profile.setCachePath(str(profile_cache_path))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        self.browser.setPage(QWebEnginePage(self.profile, self.browser))

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

    def closeEvent(self, event):
        self.qsettings.setValue("geometry", self.saveGeometry())
        self.qsettings.setValue("windowState", self.saveState())
        super().closeEvent(event)


def run_desktop(url: str) -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("Nhat")
    app.setApplicationName("VideoDownloader")
    window = DesktopWindow(url)
    window.show()
    return app.exec()
