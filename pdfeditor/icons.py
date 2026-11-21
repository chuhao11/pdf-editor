"""线条风格的工具栏图标（内置 SVG，颜色跟随系统浅色/深色主题）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

RESOURCES = Path(__file__).resolve().parent / "resources"

_PATHS = {
    "open": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    "save": '<path d="M5 3.5h10.5L20 8v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19V5a1.5 1.5 0 0 1 1-1.5z"/>'
            '<path d="M8 3.5v5h7v-5"/><rect x="7.5" y="13" width="9" height="7.5" rx="1"/>',
    "add": '<path d="M14 3H6.5A2.5 2.5 0 0 0 4 5.5v13A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V9z"/>'
           '<path d="M14 3v6h6"/><path d="M12 12v6M9 15h6"/>',
    "new": '<path d="M14 3H6.5A2.5 2.5 0 0 0 4 5.5v13A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V9z"/>'
           '<path d="M14 3v6h6"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="2"/>'
             '<path d="M20.5 16.5l-5-5L6 20"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "rotate_left": '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/>',
    "rotate_right": '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    "delete": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/>'
              '<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4.5h6V7"/>',
    "read": '<path d="M2.5 5h6A3.5 3.5 0 0 1 12 8.5V20a2.5 2.5 0 0 0-2.5-2.5h-7z"/>'
            '<path d="M21.5 5h-6A3.5 3.5 0 0 0 12 8.5V20a2.5 2.5 0 0 1 2.5-2.5h7z"/>',
    "grid": '<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/>'
            '<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.5-4.5M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.5-4.5M8 11h6"/>',
    "fit_width": '<path d="M3 4v16M21 4v16"/><path d="M7 12h10"/><path d="M9.5 9L7 12l2.5 3M14.5 9l2.5 3-2.5 3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "paste": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 10h6M9 14h6"/>',
    "cut": '<circle cx="6" cy="17" r="3"/><circle cx="18" cy="17" r="3"/><path d="M8.2 15L18 4M15.8 15L6 4"/>',
    "extract": '<path d="M14 3H6.5A2.5 2.5 0 0 0 4 5.5v13A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V9z"/>'
               '<path d="M14 3v6h6"/><path d="M9 15h6M12.5 12.5L15 15l-2.5 2.5"/>',
    "export": '<path d="M12 3v12"/><path d="M7.5 7.5L12 3l4.5 4.5"/><path d="M5 14v4.5A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V14"/>',
}

_cache: dict[tuple[str, str], QIcon] = {}


def _render(svg: str, size: int) -> QPixmap:
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def icon(name: str) -> QIcon:
    color = QGuiApplication.palette().color(QPalette.ColorRole.WindowText).name()
    key = (name, color)
    if key not in _cache:
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
               f'{_PATHS[name]}</svg>')
        ic = QIcon()
        for s in (16, 20, 24, 32, 40, 48, 64):
            ic.addPixmap(_render(svg, s))
        _cache[key] = ic
    return _cache[key]


def app_icon() -> QIcon:
    ic = QIcon()
    for name in ("app.ico", "app.png"):
        f = RESOURCES / name
        if f.exists():
            ic.addFile(str(f))
    return ic
