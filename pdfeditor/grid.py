"""页面缩略图网格：拖拽排序、跨标签拖拽、从资源管理器拖入文件。"""

from __future__ import annotations

import json
import math

from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from .engine import file_kind
from .model import MODELS, PAGE_MIME, PageListModel
from .render import RenderService, bucket, draw_page_image

PAD = 8
LABEL_H = 22
SPACING = 6


def decode_page_mime(md: QMimeData):
    """解析拖拽数据，返回 (来源模型, 行号列表) 或 None。"""
    if not md.hasFormat(PAGE_MIME):
        return None
    try:
        info = json.loads(bytes(md.data(PAGE_MIME)).decode())
        model = MODELS.get(info["model"])
        rows = [int(r) for r in info["rows"]]
    except Exception:
        return None
    if model is None:
        return None
    return model, [r for r in rows if 0 <= r < len(model)]


def local_files(md: QMimeData) -> list[str]:
    if not md.hasUrls():
        return []
    paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
    return [p for p in paths if file_kind(p)]


class PageDelegate(QStyledItemDelegate):
    def __init__(self, view: "PageGridView", svc: RenderService):
        super().__init__(view)
        self.view = view
        self.svc = svc
        self.thumb = 140

    def box(self) -> QSize:
        return QSize(self.thumb, int(self.thumb * 1.32))

    def sizeHint(self, option, index):
        b = self.box()
        return QSize(b.width() + 2 * PAD, b.height() + 2 * PAD + LABEL_H)

    def paint(self, p: QPainter, option, index):
        model = index.model()
        row = index.row()
        if row >= len(model):
            return
        ref = model.page(row)
        r = option.rect
        pal = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hl = pal.color(QPalette.ColorRole.Highlight)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        cell = QRectF(r).adjusted(2, 2, -2, -2)
        if selected:
            fill = QColor(hl)
            fill.setAlpha(55)
            p.setPen(QPen(hl, 2))
            p.setBrush(fill)
            p.drawRoundedRect(cell, 8, 8)
        elif row == self.view.current_row:
            c = QColor(hl)
            c.setAlpha(110)
            p.setPen(QPen(c, 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cell, 8, 8)

        b = self.box()
        box = QRectF(r.left() + PAD, r.top() + PAD, b.width(), b.height())
        dw, dh = ref.size()
        s = min(box.width() / dw, box.height() / dh)
        tw, th = dw * s, dh * s
        target = QRectF(box.center().x() - tw / 2, box.center().y() - th / 2, tw, th)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawRect(target.translated(1.5, 2.0))
        p.fillRect(target, Qt.GlobalColor.white)
        uw, uh = ref.src.sizes[ref.index]
        px = bucket(max(uw, uh) * s * self.view.devicePixelRatioF())
        img, _exact = self.svc.image(ref.src, ref.index, px)
        if img is not None:
            draw_page_image(p, img, target, ref.rotation)
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(target)

        label = QRectF(r.left(), box.bottom() + 2, r.width(), LABEL_H)
        f = QFont(option.font)
        f.setBold(selected)
        p.setFont(f)
        p.setPen(hl if selected else pal.color(QPalette.ColorRole.Text))
        p.drawText(label, Qt.AlignmentFlag.AlignCenter, str(row + 1))
        p.restore()


class PageGridView(QListView):
    filesDropped = Signal(list, int)   # 文件路径, 插入位置
    pagesDropped = Signal(list)        # 新插入/移动后的行号（用于选中）
    zoomRequested = Signal(int)        # Ctrl+滚轮：+1 放大 / -1 缩小
    resized = Signal()

    def __init__(self, model: PageListModel, svc: RenderService, parent=None):
        super().__init__(parent)
        self.svc = svc
        self.current_row = -1
        self._drop_index = -1
        self._drop_line: QRect | None = None
        self._drag_pos: QPoint | None = None
        self._saved_scroll = 0
        self._delegate = PageDelegate(self, svc)
        self.setItemDelegate(self._delegate)
        self.setModel(model)

        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)  # 自己处理拖放，不用 Qt 的自由摆放
        self.setUniformItemSizes(True)
        self.setSpacing(SPACING)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(30)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setFrameShape(QListView.Shape.NoFrame)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(35)
        self._scroll_timer.timeout.connect(self._auto_scroll)

        model.modelAboutToBeReset.connect(self._before_reset)
        model.modelReset.connect(self._after_reset)
        svc.updated.connect(self._on_rendered)

    # ------------------------------------------------------------ 外观
    @property
    def thumb_size(self) -> int:
        return self._delegate.thumb

    def set_thumb_size(self, t: int) -> None:
        t = int(t)
        if t == self._delegate.thumb:
            return
        self._delegate.thumb = t
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def cell_width(self) -> int:
        return self._delegate.sizeHint(None, None).width()

    def is_idle(self) -> bool:
        return self.state() == QAbstractItemView.State.NoState and self._drag_pos is None

    def set_current_row(self, row: int) -> None:
        if row != self.current_row:
            self.current_row = row
            self.viewport().update()

    def _on_rendered(self, uid: int, _index: int) -> None:
        self.viewport().update()

    def _before_reset(self) -> None:
        self._saved_scroll = self.verticalScrollBar().value()

    def _after_reset(self) -> None:
        self.executeDelayedItemsLayout()
        self.verticalScrollBar().setValue(self._saved_scroll)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y()
            if dy:
                self.zoomRequested.emit(1 if dy > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        if self.model().rowCount() == 0:
            p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.viewport().rect().adjusted(12, 12, -12, -12),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       "这里还没有页面\n把其它标签的页面、PDF 或图片拖到这里")
        if self._drop_line is not None:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
            p.drawRoundedRect(QRectF(self._drop_line), 1.5, 1.5)
        p.end()

    # ------------------------------------------------------------ 选择
    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedIndexes()})

    def select_rows(self, rows) -> None:
        rows = sorted(r for r in set(rows) if 0 <= r < self.model().rowCount())
        sm = self.selectionModel()
        sm.clearSelection()
        if not rows:
            return
        from PySide6.QtCore import QItemSelection
        sel = QItemSelection()
        start = prev = rows[0]
        for r in rows[1:] + [None]:
            if r is not None and r == prev + 1:
                prev = r
                continue
            sel.select(self.model().index(start, 0), self.model().index(prev, 0))
            if r is not None:
                start = prev = r
        sm.select(sel, sm.SelectionFlag.Select)
        sm.setCurrentIndex(self.model().index(rows[0], 0), sm.SelectionFlag.NoUpdate)
        self.scrollTo(self.model().index(rows[0], 0))

    # ------------------------------------------------------------ 拖出
    def startDrag(self, supportedActions):
        rows = self.selected_rows()
        if not rows:
            return
        md = QMimeData()
        md.setData(PAGE_MIME, json.dumps({"model": self.model().uid, "rows": rows}).encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        pm = self._drag_pixmap(rows)
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
        self._clear_drop()

    def _drag_pixmap(self, rows) -> QPixmap:
        ref = self.model().page(rows[0])
        dw, dh = ref.size()
        s = 110 / max(dw, dh)
        w, h = max(1, int(dw * s)), max(1, int(dh * s))
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int((w + 24) * dpr), int((h + 24) * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = QRectF(6, 14, w, h)
        if len(rows) > 1:
            p.fillRect(target.translated(6, -6), QColor(250, 250, 250))
            p.setPen(QColor(0, 0, 0, 80))
            p.drawRect(target.translated(6, -6))
        p.fillRect(target, Qt.GlobalColor.white)
        uw, uh = ref.src.sizes[ref.index]
        img = self.svc.cache.closest(ref.src.uid, ref.index, bucket(max(uw, uh) * s * dpr))
        if img is not None:
            draw_page_image(p, img, target, ref.rotation)
        p.setPen(QColor(0, 0, 0, 90))
        p.drawRect(target)
        if len(rows) > 1:
            badge = QRectF(w - 8, 2, 26, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
            p.drawRoundedRect(badge, 11, 11)
            p.setPen(self.palette().color(QPalette.ColorRole.HighlightedText))
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(len(rows)))
        p.end()
        return pm

    # ------------------------------------------------------------ 拖入
    def _drop_action(self, e):
        md = e.mimeData()
        info = decode_page_mime(md)
        if info is not None:
            same = info[0] is self.model()
            if same and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
                return Qt.DropAction.MoveAction
            return Qt.DropAction.CopyAction
        if local_files(md):
            return Qt.DropAction.CopyAction
        return None

    def compute_drop(self, pos: QPoint) -> tuple[int, QRect | None]:
        """根据鼠标位置算出插入位置，以及插入指示线的位置。"""
        model = self.model()
        n = model.rowCount()
        if n == 0:
            return 0, None
        vr = lambda i: self.visualRect(model.index(i, 0))  # noqa: E731
        r0 = vr(0)
        w, h = r0.width(), r0.height()
        sp = self.spacing()
        cols = 1
        while cols < n and vr(cols).top() == r0.top():
            cols += 1
        step_x = (vr(1).left() - r0.left()) if cols > 1 else w + sp
        step_y = (vr(cols).top() - r0.top()) if n > cols else h + sp
        x, y = pos.x(), pos.y()
        if cols == 1:
            idx = max(0, min(n, math.floor((y - r0.top() - h / 2) / step_y) + 1))
            if idx < n:
                rr = vr(idx)
                ly = rr.top() - sp / 2
            else:
                rr = vr(n - 1)
                ly = rr.bottom() + sp / 2
            return idx, QRect(rr.left() + 4, int(ly) - 1, rr.width() - 8, 3)
        lines = (n + cols - 1) // cols
        line = max(0, math.floor((y - r0.top() + sp / 2) / step_y))
        if line >= lines:
            rr = vr(n - 1)
            return n, QRect(int(rr.right() + sp / 2) - 1, rr.top() + 4, 3, rr.height() - 8)
        first = line * cols
        count = min(cols, n - first)
        col = max(0, min(count, math.floor((x - r0.left() - w / 2) / step_x) + 1))
        idx = first + col
        if col < count:
            rr = vr(idx)
            lx = rr.left() - sp / 2
        else:
            rr = vr(idx - 1)
            lx = rr.right() + sp / 2
        return idx, QRect(int(lx) - 1, rr.top() + 4, 3, rr.height() - 8)

    def dragEnterEvent(self, e):
        action = self._drop_action(e)
        if action is None:
            e.ignore()
            return
        e.setDropAction(action)
        e.accept()

    def dragMoveEvent(self, e):
        action = self._drop_action(e)
        if action is None:
            e.ignore()
            return
        pos = e.position().toPoint()
        self._drag_pos = pos
        self._drop_index, self._drop_line = self.compute_drop(pos)
        self.viewport().update()
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()
        e.setDropAction(action)
        e.accept()

    def dragLeaveEvent(self, e):
        self._clear_drop()
        e.accept()

    def _clear_drop(self) -> None:
        self._scroll_timer.stop()
        self._drag_pos = None
        self._drop_line = None
        self._drop_index = -1
        self.viewport().update()

    def _auto_scroll(self) -> None:
        if self._drag_pos is None:
            self._scroll_timer.stop()
            return
        y = self._drag_pos.y()
        hgt = self.viewport().height()
        margin = 48
        delta = 0
        if y < margin:
            delta = -int((margin - y) / 2) - 2
        elif y > hgt - margin:
            delta = int((y - (hgt - margin)) / 2) + 2
        if delta:
            sb = self.verticalScrollBar()
            old = sb.value()
            sb.setValue(old + delta)
            if sb.value() != old:
                self._drop_index, self._drop_line = self.compute_drop(self._drag_pos)
                self.viewport().update()

    def dropEvent(self, e):
        action = self._drop_action(e)
        pos = e.position().toPoint()
        idx, _ = self.compute_drop(pos)
        self._clear_drop()
        if action is None:
            e.ignore()
            return
        md = e.mimeData()
        info = decode_page_mime(md)
        model: PageListModel = self.model()
        if info is not None:
            src_model, rows = info
            if not rows:
                e.ignore()
                return
            if src_model is model and action == Qt.DropAction.MoveAction:
                new_rows = model.move_rows(rows, idx)
            else:
                refs = [src_model.page(r) for r in rows]
                new_rows = model.insert_pages(idx, refs)
            e.setDropAction(action)
            e.accept()
            self.select_rows(new_rows)
            self.setFocus()
            self.pagesDropped.emit(new_rows)
            return
        files = local_files(md)
        if files:
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            # 放到事件循环之后处理：读文件可能弹出密码框，不能卡在拖放过程中
            QTimer.singleShot(0, lambda: self.filesDropped.emit(files, idx))
            return
        e.ignore()
