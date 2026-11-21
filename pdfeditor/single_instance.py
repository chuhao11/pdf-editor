"""只运行一个窗口：再次双击 PDF 时，把文件交给已经打开的窗口（作为新标签）。"""

from __future__ import annotations

import getpass
import hashlib
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _key(app_id: str) -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"{app_id}-" + hashlib.sha1(user.encode()).hexdigest()[:12]


class SingleInstance(QObject):
    messageReceived = Signal(list)

    def __init__(self, app_id: str):
        super().__init__()
        self.name = _key(app_id)
        self.lock = QLockFile(str(Path(QDir.tempPath()) / f"{self.name}.lock"))
        self.lock.setStaleLockTime(0)
        self.is_primary = self.lock.tryLock(100)
        self.server = None
        if self.is_primary:
            QLocalServer.removeServer(self.name)
            self.server = QLocalServer(self)
            self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            self.server.newConnection.connect(self._on_connection)
            self.server.listen(self.name)

    def send(self, paths: list[str], timeout_ms: int = 4000) -> bool:
        """（次要实例）把文件路径发给主窗口。成功返回 True。"""
        if sys.platform == "win32":
            try:  # 允许主窗口把自己切到前台
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
        payload = json.dumps(paths).encode() + b"\n"
        waited = 0
        while waited < timeout_ms:
            sock = QLocalSocket()
            sock.connectToServer(self.name)
            if sock.waitForConnected(500):
                sock.write(payload)
                sock.flush()
                sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
                return True
            waited += 500
            time.sleep(0.25)  # 主实例可能还在启动，稍等再试
            waited += 250
        return False

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()

            def read(sock=sock, buf=buf):
                buf.extend(bytes(sock.readAll()))
                if buf.endswith(b"\n"):
                    try:
                        paths = json.loads(buf.decode())
                    except Exception:
                        paths = []
                    self.messageReceived.emit([p for p in paths if isinstance(p, str)])
                    sock.disconnectFromServer()

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)
