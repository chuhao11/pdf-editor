"""阅读视图：所有页面竖向连续排列，可缩放。"""

from __future__ import annotations

from bisect import bisect_right

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSlider, QFrame

from .model import PageListModel
from .render import RenderService, bucket, draw_page_image

MARGIN = 16
GAP = 14
MIN_ZOOM, MAX_ZOOM = 0.1, 8.0
SCREEN_100 = 96 / 72  # 100% = 实际大小（1 点 = 1/72 英寸）


class ReaderView(QAbstractScrollArea):
    currentPageChanged = Signal(int)
    zoomChanged = Signal()

    def __init__(self, model: PageListModel, svc: RenderService, parent=None):
        super().__init__(parent)
        self.model = model
        self.svc = svc
        self._zoom = 1.0
        self._fit = True
        self._rects: list[QRectF] = []
        self._tops: list[float] = []
        self._content = QSize(0, 0)
        self._current = -1
        self._uids: set[int] = set()
        self._tag = f"reader-{id(self)}"
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        model.modelReset.connect(self._on_model_reset)
        svc.updated.connect(self._on_rendered)
        self.verticalScrollBar().valueChanged.connect(self._update_current)
        self._uids = {r.src.uid for r in model.pages}
        self._relayout()

    # ------------------------------------------------------------ 缩放
    @property
    def zoom(self) -> float:
        return self._zoom

    def zoom_percent(self) -> int:
        return round(self._zoom / SCREEN_100 * 100)

    def is_fit_width(self) -> bool:
        return self._fit

    def _fit_zoom(self) -> float:
        pages = self.model.pages
        if not pages:
            return 1.0
        maxw = max(r.size()[0] for r in pages)
        avail = max(50, self.viewport().width() - 2 * MARGIN)
        return max(MIN_ZOOM, min(MAX_ZOOM, avail / maxw))

    def set_zoom(self, z: float, anchor: QPointF | None = None) -> None:
        z = max(MIN_ZOOM, min(MAX_ZOOM, z))
        if not self._fit and abs(z - self._zoom) < 1e-6:
            return
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        a = self._anchor(anchor.y())
        hs = self.horizontalScrollBar()
        old_w = max(1, self._content.width())
        fx = (hs.value() + anchor.x()) / old_w
        self.svc.cancel(self._tag)
        self._fit = False
        self._zoom = z
        self._relayout()
        self._restore_anchor(a)
        hs.setValue(int(fx * self._content.width() - anchor.x()))
        self.zoomChanged.emit()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.25)

    def fit_width(self) -> None:
        a = self._anchor(0)
        self.svc.cancel(self._tag)
        self._fit = True
        self._relayout()
        self._restore_anchor(a)
        self.zoomChanged.emit()

    # ------------------------------------------------------------ 布局
    def _relayout(self) -> None:
        pages = self.model.pages
        if self._fit:
            self._zoom = self._fit_zoom()
        z = self._zoom
        sizes = [(w * z, h * z) for w, h in (r.size() for r in pages)]
        maxw = max((w for w, _ in sizes), default=0)
        vw, vh = self.viewport().width(), self.viewport().height()
        width = max(int(maxw + 2 * MARGIN), vw)
        rects = []
        y = MARGIN
        for w, h in sizes:
            rects.append(QRectF((width - w) / 2, y, w, h))
            y += h + GAP
        self._rects = rects
        self._tops = [r.top() for r in rects]
        total = int(y - GAP + MARGIN) if rects else 0
        self._content = QSize(width, total)
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        hs.setRange(0, max(0, width - vw))
        hs.setPageStep(vw)
        hs.setSingleStep(30)
        vs.setRange(0, max(0, total - vh))
        vs.setPageStep(max(1, vh - 40))
        vs.setSingleStep(40)
        self.viewport().update()
        self._update_current()

    def _page_at_y(self, y: float) -> int:
        if not self._tops:
            return -1
        return max(0, min(len(self._tops) - 1, bisect_right(self._tops, y) - 1))

    def _anchor(self, vy: float):
        if not self._rects:
            return None
        cy = self.verticalScrollBar().value() + vy
        i = self._page_at_y(cy)
        r = self._rects[i]
        frac = (cy - r.top()) / r.height() if r.height() else 0.0
        return i, frac, vy

    def _restore_anchor(self, a) -> None:
        if a is None or not self._rects:
            return
        i, frac, vy = a
        i = min(i, len(self._rects) - 1)
        r = self._rects[i]
        self.verticalScrollBar().setValue(int(r.top() + frac * r.height() - vy))

    def go_to_page(self, row: int) -> None:
        if 0 <= row < len(self._rects):
            self.verticalScrollBar().setValue(int(self._rects[row].top() - MARGIN))

    def current_page(self) -> int:
        return self._current

    def _update_current(self) -> None:
        if not self._rects:
            cur = -1
        else:
            cur = self._page_at_y(self.verticalScrollBar().value() + self.viewport().height() * 0.3)
        if cur != self._current:
            self._current = cur
            self.currentPageChanged.emit(cur)

    def _on_model_reset(self) -> None:
        a = self._anchor(0)
        self._uids = {r.src.uid for r in self.model.pages}
        self._relayout()
        self._restore_anchor(a)

    def _on_rendered(self, uid: int, _index: int) -> None:
        if uid in self._uids and self.isVisible():
            self.viewport().update()

    # ------------------------------------------------------------ 事件
    def resizeEvent(self, e):
        a = self._anchor(0)
        self._relayout()
        self._restore_anchor(a)
        if self._fit:
            self.zoomChanged.emit()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y()
            if dy:
                self.set_zoom(self._zoom * (1.15 ** (dy / 120)), e.position())
            e.accept()
            return
        super().wheelEvent(e)

    def keyPressEvent(self, e):
        vs = self.verticalScrollBar()
        k = e.key()
        A = QAbstractSlider.SliderAction
        if k in (Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            vs.triggerAction(A.SliderPageStepAdd)
        elif k == Qt.Key.Key_PageUp:
            vs.triggerAction(A.SliderPageStepSub)
        elif k == Qt.Key.Key_Down:
            vs.triggerAction(A.SliderSingleStepAdd)
        elif k == Qt.Key.Key_Up:
            vs.triggerAction(A.SliderSingleStepSub)
        elif k == Qt.Key.Key_Home:
            vs.setValue(0)
        elif k == Qt.Key.Key_End:
            vs.setValue(vs.maximum())
        elif k == Qt.Key.Key_Right:
            self.go_to_page(self._current + 1)
        elif k == Qt.Key.Key_Left:
            self.go_to_page(max(0, self._current - 1))
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        vp = self.viewport()
        p = QPainter(vp)
        base = self.palette().color(QPalette.ColorRole.Window)
        bg = base.darker(112) if base.lightness() > 128 else base.lighter(130)
        p.fillRect(vp.rect(), bg)
        pages = self.model.pages
        if not self._rects or len(pages) != len(self._rects):
            p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            p.drawText(vp.rect(), Qt.AlignmentFlag.AlignCenter, "没有页面")
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        dx = self.horizontalScrollBar().value()
        dy = self.verticalScrollBar().value()
        vh = vp.height()
        dpr = self.devicePixelRatioF()
        first = self._page_at_y(dy)
        last = first
        while last + 1 < len(self._rects) and self._rects[last + 1].top() - dy < vh:
            last += 1

        def px_for(i):
            ref = pages[i]
            uw, uh = ref.src.sizes[ref.index]
            return ref, bucket(max(uw, uh) * self._zoom * dpr)

        # 先预约前后各一页（优先级较低），再画可见页面（最后请求的最先渲染）
        for i in (first - 1, last + 1):
            if 0 <= i < len(pages):
                ref, px = px_for(i)
                self.svc.image(ref.src, ref.index, px, tag=self._tag)
        for i in range(first, last + 1):
            r = self._rects[i].translated(-dx, -dy)
            ref, px = px_for(i)
            p.fillRect(r.translated(2, 3), QColor(0, 0, 0, 40))
            p.fillRect(r, Qt.GlobalColor.white)
            img, _exact = self.svc.image(ref.src, ref.index, px, tag=self._tag)
            if img is not None:
                draw_page_image(p, img, r, ref.rotation)
            p.setPen(QPen(QColor(0, 0, 0, 50), 1))
            p.drawRect(r)
        p.end()
