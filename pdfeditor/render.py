"""后台渲染页面图片 + 内存缓存。

只有一个渲染线程，按“最近请求优先”的顺序处理，所以快速滚动时总是先画眼前的页面。
"""

from __future__ import annotations

import threading
from collections import OrderedDict, defaultdict

import pymupdf
from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter

from .engine import PDF_LOCK, SourceDoc

MAX_PX = 6144  # 单张渲染图最长边的上限


def bucket(px: float) -> int:
    """把需要的像素尺寸取整到几个固定档位，减少重复渲染。"""
    px = max(64, int(px + 0.5))
    step = 128 if px <= 1024 else 256 if px <= 4096 else 512
    return min(MAX_PX, -(-px // step) * step)


def render_page_image(src: SourceDoc, index: int, px: int) -> QImage | None:
    """把页面渲染成最长边为 px 像素的图片（已包含页面自带的旋转）。"""
    with PDF_LOCK:
        if src.closed:
            return None
        try:
            page = src.doc.load_page(index)
            r = page.rect
            s = px / max(r.width, r.height, 1.0)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(s, s), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            del pix, page
            return img
        except Exception:
            img = QImage(64, 90, QImage.Format.Format_RGB888)
            img.fill(QColor(235, 235, 235))
            return img


def draw_page_image(p: QPainter, img: QImage, target: QRectF, rotation: int) -> None:
    """把未旋转的页面图按 rotation（顺时针）画进 target。"""
    rotation %= 360
    if rotation == 0:
        p.drawImage(target, img)
        return
    p.save()
    p.translate(target.center())
    p.rotate(rotation)
    w, h = (target.height(), target.width()) if rotation % 180 else (target.width(), target.height())
    p.drawImage(QRectF(-w / 2, -h / 2, w, h), img)
    p.restore()


class ImageCache:
    def __init__(self, budget_bytes: int):
        self.budget = budget_bytes
        self._d: OrderedDict[tuple[int, int, int], QImage] = OrderedDict()
        self._bytes = 0
        self._sizes: dict[tuple[int, int], set[int]] = defaultdict(set)

    def get(self, key):
        img = self._d.get(key)
        if img is not None:
            self._d.move_to_end(key)
        return img

    def put(self, key, img: QImage) -> None:
        old = self._d.pop(key, None)
        if old is not None:
            self._bytes -= old.sizeInBytes()
        self._d[key] = img
        self._bytes += img.sizeInBytes()
        self._sizes[key[:2]].add(key[2])
        while self._bytes > self.budget and len(self._d) > 1:
            k, v = self._d.popitem(last=False)
            self._bytes -= v.sizeInBytes()
            self._sizes[k[:2]].discard(k[2])

    def closest(self, uid: int, index: int, px: int):
        """缓存里同一页的其它尺寸（用来在高清图出来之前先顶上）。"""
        sizes = self._sizes.get((uid, index))
        if not sizes:
            return None
        bigger = [s for s in sizes if s >= px]
        best = min(bigger) if bigger else max(sizes)
        return self._d.get((uid, index, best))

    def drop_source(self, uid: int) -> None:
        for k in [k for k in self._d if k[0] == uid]:
            self._bytes -= self._d.pop(k).sizeInBytes()
        for k in [k for k in self._sizes if k[0] == uid]:
            del self._sizes[k]

    def __len__(self) -> int:
        return len(self._d)


class RenderService(QObject):
    updated = Signal(int, int)        # 来源 uid, 页码：有新图片可用了
    _done = Signal(object, object)    # (key, QImage)，由渲染线程发出

    def __init__(self, budget_mb: int = 640):
        super().__init__()
        self.cache = ImageCache(budget_mb * 1024 * 1024)
        self._cv = threading.Condition()
        self._pending: OrderedDict = OrderedDict()
        self._current = None
        self._stop = False
        self._done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)
        self._thread = threading.Thread(target=self._run, name="pdf-render", daemon=True)
        self._thread.start()

    def image(self, src: SourceDoc, index: int, px: int, tag: str | None = None):
        """返回 (图片或 None, 是否正好是要求的尺寸)。缺图时自动安排渲染。"""
        key = (src.uid, index, px)
        img = self.cache.get(key)
        if img is not None:
            return img, True
        self._enqueue(key, src, tag)
        return self.cache.closest(src.uid, index, px), False

    def _enqueue(self, key, src, tag) -> None:
        with self._cv:
            if key == self._current:
                return
            if key in self._pending:
                self._pending.move_to_end(key)
            else:
                self._pending[key] = (src, tag)
                while len(self._pending) > 600:
                    self._pending.popitem(last=False)
            self._cv.notify()

    def cancel(self, tag: str) -> None:
        with self._cv:
            for k in [k for k, v in self._pending.items() if v[1] == tag]:
                del self._pending[k]

    def drop_source(self, uid: int) -> None:
        with self._cv:
            for k in [k for k in self._pending if k[0] == uid]:
                del self._pending[k]
        self.cache.drop_source(uid)

    def idle(self) -> bool:
        with self._cv:
            return not self._pending and self._current is None

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                key, (src, _tag) = self._pending.popitem(last=True)
                self._current = key
            img = render_page_image(src, key[1], key[2])
            with self._cv:
                self._current = None
            if img is not None:
                self._done.emit(key, img)

    def _on_done(self, key, img) -> None:
        self.cache.put(key, img)
        self.updated.emit(key[0], key[1])

    def shutdown(self) -> None:
        with self._cv:
            self._stop = True
            self._pending.clear()
            self._cv.notify_all()
        self._thread.join(timeout=3)
