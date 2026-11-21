"""主窗口：顶部标签栏 + 工具栏 + 文档区域。"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider, QStackedWidget, QTabBar,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from . import APP_NAME
from .document import MODE_ORGANIZE, MODE_READ, DocumentTab
from .engine import (
    IMAGE_EXTS, IMAGE_PAGE_A4, IMAGE_PAGE_FIT, PasswordRequired, PdfError, SourceDoc,
    all_pages, file_kind, images_to_source, natural_key, read_pdf, save_pdf,
)
from .grid import decode_page_mime, local_files
from .icons import app_icon, icon
from .model import PAGE_MIME
from .render import RenderService

_IMG_PATTERN = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
OPEN_FILTER = (f"PDF 和图片 (*.pdf {_IMG_PATTERN});;PDF 文件 (*.pdf);;"
               f"图片 ({_IMG_PATTERN});;所有文件 (*)")
IMAGE_FILTER = f"图片 ({_IMG_PATTERN});;所有文件 (*)"


@contextmanager
def busy():
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


class DocTabBar(QTabBar):
    """像浏览器一样的标签栏。拖着页面停在某个标签上会自动切换过去。"""

    pagesDropped = Signal(int, object, bool)  # 标签下标, (来源模型, 行号), 是否复制
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.setUsesScrollButtons(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._hover = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._switch_to_hover)

    def tabSizeHint(self, index):
        s = super().tabSizeHint(index)
        return QSize(min(max(s.width(), 120), 240), s.height())

    def _switch_to_hover(self):
        if 0 <= self._hover < self.count():
            self.setCurrentIndex(self._hover)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(PAGE_MIME) or local_files(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        md = e.mimeData()
        i = self.tabAt(e.position().toPoint())
        if md.hasFormat(PAGE_MIME):
            if i != self._hover:
                self._hover = i
                self._timer.stop()
                if i >= 0 and i != self.currentIndex():
                    self._timer.start()
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        elif local_files(md):
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._timer.stop()
        self._hover = -1

    def dropEvent(self, e):
        self._timer.stop()
        self._hover = -1
        md = e.mimeData()
        i = self.tabAt(e.position().toPoint())
        info = decode_page_mime(md)
        if info is not None and i >= 0:
            copy = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            QTimer.singleShot(0, lambda: self.pagesDropped.emit(i, info, copy))
            return
        files = local_files(md)
        if files:
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            QTimer.singleShot(0, lambda: self.filesDropped.emit(files))
            return
        e.ignore()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(e.position().toPoint())
            if i >= 0:
                self.tabCloseRequested.emit(i)
                return
        super().mouseReleaseEvent(e)


class WelcomePage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(3)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(72, 72))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(APP_NAME)
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.8)
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("把 PDF 或图片拖到窗口里就能打开，也可以：")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setEnabled(False)
        lay.addWidget(logo)
        lay.addWidget(title)
        lay.addSpacing(6)
        lay.addWidget(hint)
        lay.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch()
        for text, ic, slot in (("打开文件", "open", win.open_dialog),
                               ("图片转 PDF", "image", win.images_to_pdf_dialog),
                               ("新建空白文档", "new", win.new_blank)):
            b = QPushButton(icon(ic), "  " + text)
            win.themed.append((b, ic))
            b.setIconSize(QSize(20, 20))
            b.setMinimumHeight(38)
            b.setMinimumWidth(140)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch(4)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.svc = RenderService()
        self.sources: list[SourceDoc] = []
        self.clipboard: list = []
        self._untitled = itertools.count(1)
        self.themed: list = []  # (动作或按钮, 图标名)：切换浅色/深色时重新上色
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_ui()
        self.resize(1200, 820)
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._refresh()

    # ================================================================ 界面
    def _act(self, text, slot, shortcut=None, ic=None, tip=None, checkable=False):
        a = QAction(text, self)
        if ic:
            a.setIcon(icon(ic))
            self.themed.append((a, ic))
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        if tip or shortcut:
            keys = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            a.setToolTip(f"{tip or text}" + (f"（{keys}）" if keys else ""))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self):
        A = self._act
        self.act_open = A("打开", self.open_dialog, QKeySequence.StandardKey.Open, "open", "打开 PDF 或图片")
        self.act_new = A("新建空白文档", self.new_blank, "Ctrl+N", "new")
        self.act_save = A("保存", self.save_current, QKeySequence.StandardKey.Save, "save", "保存（覆盖原文件）")
        self.act_save_as = A("另存为…", self.save_current_as, "Ctrl+Shift+S", "save")
        self.act_export = A("导出选中页面…", self.export_selected, None, "export", "把选中的页面另存为新的 PDF")
        self.act_add = A("添加", self.add_files_dialog, "Ctrl+I", "add", "添加 PDF 或图片到当前文档末尾")
        self.act_images = A("图片转 PDF", self.images_to_pdf_dialog, None, "image", "选择图片，生成新的 PDF")
        self.act_undo = A("撤销", lambda: self._tab_call("undo"), QKeySequence.StandardKey.Undo, "undo")
        self.act_redo = A("重做", lambda: self._tab_call("redo"), ["Ctrl+Y", "Ctrl+Shift+Z"], "redo")
        self.act_rot_l = A("左转", lambda: self.rotate(-90), "Ctrl+L", "rotate_left", "向左旋转 90°")
        self.act_rot_r = A("右转", lambda: self.rotate(90), "Ctrl+R", "rotate_right", "向右旋转 90°")
        self.act_delete = A("删除", self.delete_pages, [QKeySequence.StandardKey.Delete, "Backspace"],
                            "delete", "删除选中的页面")
        self.act_copy = A("复制页面", self.copy_pages, QKeySequence.StandardKey.Copy, "copy")
        self.act_cut = A("剪切页面", self.cut_pages, QKeySequence.StandardKey.Cut, "cut")
        self.act_paste = A("粘贴页面", self.paste_pages, QKeySequence.StandardKey.Paste, "paste",
                           "粘贴到选中页面后面（没有选中则粘贴到末尾）")
        self.act_extract = A("提取到新文档", self.extract_to_new, None, "extract", "把选中的页面复制到一个新标签")
        self.act_select_all = A("全选", self.select_all, QKeySequence.StandardKey.SelectAll)
        self.act_insert_here = A("在选中页后插入文件…", self.insert_files_after_selection, None, "add")
        self.act_read = A("阅读", lambda: self.set_mode(MODE_READ), "Ctrl+1", "read", "阅读模式：左侧缩略图 + 右侧大图", True)
        self.act_organize = A("整理", lambda: self.set_mode(MODE_ORGANIZE), "Ctrl+2", "grid",
                              "整理模式：大缩略图网格，方便拖拽排序", True)
        grp = QActionGroup(self)
        grp.addAction(self.act_read)
        grp.addAction(self.act_organize)
        self.act_zoom_in = A("放大", lambda: self._reader_call("zoom_in"), ["Ctrl+=", "Ctrl++"], "zoom_in")
        self.act_zoom_out = A("缩小", lambda: self._reader_call("zoom_out"), "Ctrl+-", "zoom_out")
        self.act_fit = A("适应宽度", lambda: self._reader_call("fit_width"), "Ctrl+0", "fit_width", None, True)
        self.act_close_tab = A("关闭标签", lambda: self.close_tab(self.tabbar.currentIndex()), QKeySequence.StandardKey.Close)

        mode = self.settings.value("image_page_mode", IMAGE_PAGE_A4)
        self.img_mode_group = QActionGroup(self)
        self.act_img_a4 = QAction("图片页面：A4 纸大小（自动横竖）", self, checkable=True)
        self.act_img_fit = QAction("图片页面：跟随图片比例（无白边）", self, checkable=True)
        for a, m in ((self.act_img_a4, IMAGE_PAGE_A4), (self.act_img_fit, IMAGE_PAGE_FIT)):
            a.setData(m)
            a.setChecked(m == mode)
            self.img_mode_group.addAction(a)
        self.img_mode_group.triggered.connect(lambda a: self.settings.setValue("image_page_mode", a.data()))

        QShortcut(QKeySequence("Ctrl+Tab"), self, lambda: self._cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, lambda: self._cycle_tab(-1))

    def _build_ui(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 第一行：标签栏 + “+” 按钮
        top = QWidget()
        h = QHBoxLayout(top)
        h.setContentsMargins(6, 4, 6, 0)
        h.setSpacing(4)
        self.tabbar = DocTabBar()
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        self.tabbar.pagesDropped.connect(self._on_pages_dropped_on_tab)
        self.tabbar.filesDropped.connect(self.open_paths)
        self.tabbar.customContextMenuRequested.connect(self._tab_menu)
        self.plus_btn = QToolButton()
        self.plus_btn.setIcon(icon("plus"))
        self.themed.append((self.plus_btn, "plus"))
        self.plus_btn.setAutoRaise(True)
        self.plus_btn.setToolTip("打开 PDF 或图片")
        self.plus_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        plus_menu = QMenu(self)
        plus_menu.addAction(self.act_open)
        plus_menu.addAction(self.act_new)
        plus_menu.addAction(self.act_images)
        self.plus_btn.setMenu(plus_menu)
        self.plus_btn.clicked.connect(self.open_dialog)
        h.addWidget(self.tabbar, 0)
        h.addWidget(self.plus_btn, 0)
        h.addStretch(1)
        v.addWidget(top)

        # 第二行：工具栏
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar = tb
        tb.addAction(self.act_open)
        save_btn = QToolButton()
        save_btn.setDefaultAction(self.act_save)
        save_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        save_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        save_menu = QMenu(self)
        save_menu.addAction(self.act_save)
        save_menu.addAction(self.act_save_as)
        save_menu.addSeparator()
        save_menu.addAction(self.act_export)
        save_btn.setMenu(save_menu)
        tb.addWidget(save_btn)
        tb.addSeparator()
        tb.addAction(self.act_add)
        img_btn = QToolButton()
        img_btn.setDefaultAction(self.act_images)
        img_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        img_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        img_menu = QMenu(self)
        img_menu.addAction(self.act_images)
        img_menu.addSeparator()
        img_menu.addAction(self.act_img_a4)
        img_menu.addAction(self.act_img_fit)
        img_btn.setMenu(img_menu)
        tb.addWidget(img_btn)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()
        tb.addAction(self.act_rot_l)
        tb.addAction(self.act_rot_r)
        tb.addAction(self.act_delete)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.act_read)
        tb.addAction(self.act_organize)
        tb.addSeparator()
        # 阅读模式：缩放控件；整理模式：缩略图大小滑块
        tb.addAction(self.act_zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(46)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_label_action = tb.addWidget(self.zoom_label)
        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_fit)
        self._zoom_actions = [self.act_zoom_out, zoom_label_action, self.act_zoom_in, self.act_fit]
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_fit):
            w = tb.widgetForAction(a)
            if isinstance(w, QToolButton):
                w.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.thumb_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumb_slider.setRange(80, 400)
        self.thumb_slider.setFixedWidth(140)
        self.thumb_slider.setToolTip("缩略图大小（也可以按住 Ctrl 滚动鼠标滚轮）")
        self.thumb_slider.setValue(int(self.settings.value("organize_thumb", 170)))
        self.thumb_slider.valueChanged.connect(self._on_thumb_slider)
        self._thumb_actions = [tb.addWidget(QLabel("缩略图 ")), tb.addWidget(self.thumb_slider)]
        v.addWidget(tb)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        v.addWidget(line)

        self.stack = QStackedWidget()
        self.welcome = WelcomePage(self)
        self.stack.addWidget(self.welcome)
        v.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.page_label = QLabel()
        self.statusBar().addPermanentWidget(self.page_label)

    # ================================================================ 标签管理
    def tabs(self) -> list[DocumentTab]:
        return [self.tabbar.tabData(i) for i in range(self.tabbar.count())]

    def current_tab(self) -> DocumentTab | None:
        i = self.tabbar.currentIndex()
        return self.tabbar.tabData(i) if i >= 0 else None

    def _index_of(self, tab) -> int:
        for i in range(self.tabbar.count()):
            if self.tabbar.tabData(i) is tab:
                return i
        return -1

    def add_tab(self, pages, path=None, title=None, mode=MODE_READ) -> DocumentTab:
        tab = DocumentTab(self.svc, pages, path, title, mode, self.thumb_slider.value())
        tab.changed.connect(lambda t=tab: self._on_tab_changed_content(t))
        tab.filesDropped.connect(self._on_files_dropped_in_grid)
        tab.contextMenuRequested.connect(self._grid_menu)
        self.stack.addWidget(tab)
        i = self.tabbar.addTab(tab.display_name())
        self.tabbar.setTabData(i, tab)
        self.tabbar.setTabToolTip(i, path or tab.display_name())
        self.tabbar.setCurrentIndex(i)
        self._on_tab_changed(i)
        tab.grid.setFocus()
        return tab

    def _on_tab_changed(self, i):
        tab = self.current_tab()
        self.stack.setCurrentWidget(tab if tab is not None else self.welcome)
        self._refresh()

    def _on_tab_changed_content(self, tab):
        i = self._index_of(tab)
        if i >= 0:
            name = tab.display_name()
            self.tabbar.setTabText(i, name + (" *" if tab.model.is_modified() else ""))
            self.tabbar.setTabToolTip(i, tab.path or name)
        if tab is self.current_tab():
            self._refresh()

    def _cycle_tab(self, step):
        n = self.tabbar.count()
        if n:
            self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + step) % n)

    def close_tab(self, i) -> bool:
        if not 0 <= i < self.tabbar.count():
            return False
        tab = self.tabbar.tabData(i)
        if not self._confirm_discard(tab):
            return False
        self.tabbar.removeTab(self._index_of(tab))
        self.stack.removeWidget(tab)
        tab.deleteLater()
        self._collect_sources()
        self._refresh()
        return True

    def _confirm_discard(self, tab) -> bool:
        """有未保存修改时询问。返回 True 表示可以关闭。"""
        if not tab.model.is_modified() or (not tab.path and len(tab.model) == 0):
            return True
        self.tabbar.setCurrentIndex(self._index_of(tab))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(f"“{tab.display_name()}”有未保存的修改，要保存吗？")
        b_save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        b_discard = box.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_save:
            return self.save_tab(tab)
        return clicked is b_discard

    def _collect_sources(self):
        """释放已经没有任何标签（包括撤销历史和剪贴板）在用的来源文件。"""
        alive = set()
        for t in self.tabs():
            alive |= t.model.source_uids()
        alive |= {r.src.uid for r in self.clipboard}
        keep = []
        for s in self.sources:
            if s.uid in alive:
                keep.append(s)
            else:
                self.svc.drop_source(s.uid)
                s.close()
        self.sources = keep

    def _tab_menu(self, pos):
        i = self.tabbar.tabAt(pos)
        if i < 0:
            return
        tab = self.tabbar.tabData(i)
        m = QMenu(self)
        m.addAction("关闭", lambda: self.close_tab(self._index_of(tab)))
        m.addAction("关闭其它标签", lambda: self._close_others(tab)).setEnabled(self.tabbar.count() > 1)
        m.addSeparator()
        m.addAction(icon("extract"), "合并所有标签到新文档", self.merge_all_tabs).setEnabled(self.tabbar.count() > 1)
        if tab.path:
            m.addSeparator()
            m.addAction("在文件夹中显示", lambda: self._reveal(tab.path))
        m.exec(self.tabbar.mapToGlobal(pos))

    def _close_others(self, keep):
        for t in self.tabs():
            if t is not keep and not self.close_tab(self._index_of(t)):
                return

    def _reveal(self, path):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])

    # ================================================================ 打开文件
    def _last_dir(self) -> str:
        return str(self.settings.value("last_dir", str(Path.home())))

    def _remember_dir(self, path):
        self.settings.setValue("last_dir", str(Path(path).parent))

    def _error(self, title, text):
        QMessageBox.warning(self, APP_NAME, f"{title}\n\n{text}" if text else title)

    def load_pdf(self, path) -> SourceDoc | None:
        name = Path(path).name
        password = None
        for _ in range(5):
            try:
                with busy():
                    src = read_pdf(path, password)
            except PasswordRequired as e:
                text = f"“{name}”有密码保护，请输入密码：" if password is None else "密码不正确，请重新输入："
                password, ok = QInputDialog.getText(self, "需要密码", text, QLineEdit.EchoMode.Password)
                if not ok:
                    return None
                continue
            except PdfError as e:
                self._error(f"无法打开“{name}”", str(e))
                return None
            self.sources.append(src)
            return src
        return None

    def load_images(self, paths) -> SourceDoc | None:
        mode = self.img_mode_group.checkedAction().data()
        try:
            with busy():
                src, failed = images_to_source(paths, mode)
        except PdfError as e:
            self._error("无法转换图片", str(e))
            return None
        if failed:
            self._error("有些图片无法读取，已跳过：", "\n".join(Path(p).name for p in failed))
        self.sources.append(src)
        return src

    def pages_from_files(self, paths):
        """把文件变成页面列表：PDF 逐个读取，相邻的图片合成一组。"""
        paths = sorted(paths, key=natural_key)
        refs, images, bad = [], [], []

        def flush():
            if images:
                src = self.load_images(list(images))
                if src:
                    refs.extend(all_pages(src))
                images.clear()

        for p in paths:
            kind = file_kind(p)
            if kind == "image":
                images.append(p)
            elif kind == "pdf":
                flush()
                src = self.load_pdf(p)
                if src:
                    refs.extend(all_pages(src))
            else:
                bad.append(p)
        flush()
        if bad:
            self._error("不支持这些文件：", "\n".join(Path(p).name for p in bad))
        if paths:
            self._remember_dir(paths[0])
        return refs

    def open_paths(self, paths):
        """每个 PDF 打开成一个标签；选中的图片合成一个新文档。"""
        paths = [str(Path(p).resolve()) for p in paths]
        pdfs = sorted((p for p in paths if file_kind(p) == "pdf"), key=natural_key)
        images = sorted((p for p in paths if file_kind(p) == "image"), key=natural_key)
        bad = [p for p in paths if file_kind(p) is None]
        for p in pdfs:
            existing = next((t for t in self.tabs() if t.path and os.path.normcase(t.path) == os.path.normcase(p)), None)
            if existing is not None:
                self.tabbar.setCurrentIndex(self._index_of(existing))
                continue
            src = self.load_pdf(p)
            if src:
                self.add_tab(all_pages(src), path=p)
        if images:
            src = self.load_images(images)
            if src:
                self.add_tab(all_pages(src), title=src.name, mode=MODE_ORGANIZE)
        if bad:
            self._error("不支持这些文件：", "\n".join(Path(p).name for p in bad))
        if paths:
            self._remember_dir(paths[0])

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "打开 PDF 或图片", self._last_dir(), OPEN_FILTER)
        if paths:
            self.open_paths(paths)

    def images_to_pdf_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要转换成 PDF 的图片", self._last_dir(), IMAGE_FILTER)
        if paths:
            self._remember_dir(paths[0])
            paths = sorted(paths, key=natural_key)
            src = self.load_images(paths)
            if src:
                self.add_tab(all_pages(src), title=src.name, mode=MODE_ORGANIZE)

    def new_blank(self):
        self.add_tab([], title=f"未命名 {next(self._untitled)}", mode=MODE_ORGANIZE)

    def add_files_dialog(self, pos=None):
        tab = self.current_tab()
        if tab is None:
            return self.open_dialog()
        paths, _ = QFileDialog.getOpenFileNames(self, "添加 PDF 或图片到当前文档", self._last_dir(), OPEN_FILTER)
        if not paths:
            return
        refs = self.pages_from_files(paths)
        if refs:
            at = len(tab.model) if pos is None else pos
            tab.insert_pages(at, refs)
            self.statusBar().showMessage(f"已添加 {len(refs)} 页", 4000)

    def insert_files_after_selection(self):
        tab = self.current_tab()
        if tab is None:
            return
        rows = tab.selected_rows()
        self.add_files_dialog(rows[-1] + 1 if rows else None)

    def _on_files_dropped_in_grid(self, tab, files, pos):
        refs = self.pages_from_files(files)
        if refs:
            tab.insert_pages(pos, refs)
            self.statusBar().showMessage(f"已插入 {len(refs)} 页", 4000)

    def _on_pages_dropped_on_tab(self, i, info, copy):
        target = self.tabbar.tabData(i)
        src_model, rows = info
        if not rows or target is None:
            return
        if src_model is target.model and not copy:
            new_rows = target.model.move_rows(rows, len(target.model))
            target.grid.select_rows(new_rows)
        else:
            target.insert_pages(len(target.model), [src_model.page(r) for r in rows])
        self.tabbar.setCurrentIndex(i)
        self.statusBar().showMessage(f"已把 {len(rows)} 页放到“{target.display_name()}”末尾", 4000)

    def merge_all_tabs(self):
        refs = [r for t in self.tabs() for r in t.model.pages]
        if refs:
            self.add_tab(refs, title=f"合并文档 {next(self._untitled)}", mode=MODE_ORGANIZE)

    # 整个窗口都接受文件拖入（拖到缩略图区域之外 = 打开成新标签）
    def dragEnterEvent(self, e):
        if local_files(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if local_files(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        files = local_files(e.mimeData())
        if files:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.open_paths(files))

    def receive_from_other_instance(self, paths):
        if paths:
            self.open_paths(paths)
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ================================================================ 保存
    def _ask_save_path(self, suggested) -> str | None:
        start = str(Path(self._last_dir()) / suggested)
        path, _ = QFileDialog.getSaveFileName(self, "保存为 PDF", start, "PDF 文件 (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._remember_dir(path)
        return path

    def write_pdf(self, pages, path) -> bool:
        try:
            with busy():
                save_pdf(pages, path)
            return True
        except PermissionError:
            self._error(f"无法写入“{Path(path).name}”",
                        "文件可能正被其它程序（如 Acrobat、浏览器）打开，或者没有写入权限。\n"
                        "请关闭占用它的程序后再试，或者用“另存为”保存到别的位置。")
        except PdfError as e:
            self._error("保存失败", str(e))
        except Exception as e:  # pragma: no cover
            self._error("保存失败", str(e))
        return False

    def save_tab(self, tab, save_as=False) -> bool:
        pages = tab.model.pages
        if not pages:
            self._error("文档里没有页面，无法保存。", "")
            return False
        path = tab.path
        if save_as or not path:
            path = self._ask_save_path(tab.suggested_filename())
            if not path:
                return False
        if not self.write_pdf(pages, path):
            return False
        tab.path = path
        tab.model.mark_saved()
        self._on_tab_changed_content(tab)
        self.statusBar().showMessage(f"已保存：{path}", 5000)
        return True

    def save_current(self):
        tab = self.current_tab()
        if tab:
            self.save_tab(tab)

    def save_current_as(self):
        tab = self.current_tab()
        if tab:
            self.save_tab(tab, save_as=True)

    def export_selected(self):
        tab = self.current_tab()
        if not tab:
            return
        pages = tab.selected_pages()
        if not pages:
            self.statusBar().showMessage("请先选中要导出的页面", 4000)
            return
        stem = Path(tab.suggested_filename()).stem
        path = self._ask_save_path(f"{stem}-选中页面.pdf")
        if path and self.write_pdf(pages, path):
            self.statusBar().showMessage(f"已导出 {len(pages)} 页：{path}", 5000)

    # ================================================================ 页面操作
    def _tab_call(self, name):
        tab = self.current_tab()
        if tab:
            getattr(tab, name)()

    def _reader_call(self, name):
        tab = self.current_tab()
        if tab and tab.mode == MODE_READ:
            getattr(tab.reader, name)()

    def _need_selection(self, tab) -> bool:
        if tab is None:
            return False
        if not tab.selected_rows():
            self.statusBar().showMessage("请先点选页面（按住 Ctrl 或 Shift 可以多选）", 4000)
            return False
        return True

    def rotate(self, delta):
        tab = self.current_tab()
        if self._need_selection(tab):
            tab.rotate_selected(delta)

    def delete_pages(self):
        tab = self.current_tab()
        if self._need_selection(tab):
            n = tab.delete_selected()
            self.statusBar().showMessage(f"已删除 {n} 页（可以按 Ctrl+Z 撤销）", 4000)

    def copy_pages(self):
        tab = self.current_tab()
        if self._need_selection(tab):
            self.clipboard = tab.selected_pages()
            self.statusBar().showMessage(f"已复制 {len(self.clipboard)} 页", 3000)
            self._refresh()

    def cut_pages(self):
        tab = self.current_tab()
        if self._need_selection(tab):
            self.clipboard = tab.selected_pages()
            tab.delete_selected()
            self.statusBar().showMessage(f"已剪切 {len(self.clipboard)} 页", 3000)

    def paste_pages(self):
        tab = self.current_tab()
        if tab is None or not self.clipboard:
            return
        rows = tab.selected_rows()
        pos = rows[-1] + 1 if rows else len(tab.model)
        tab.insert_pages(pos, list(self.clipboard))
        self.statusBar().showMessage(f"已粘贴 {len(self.clipboard)} 页", 3000)

    def extract_to_new(self):
        tab = self.current_tab()
        if self._need_selection(tab):
            stem = Path(tab.suggested_filename()).stem
            self.add_tab(tab.selected_pages(), title=f"{stem}（提取）", mode=MODE_ORGANIZE)

    def send_to(self, target):
        tab = self.current_tab()
        if self._need_selection(tab) and target is not None:
            pages = tab.selected_pages()
            target.model.insert_pages(len(target.model), pages)
            self.statusBar().showMessage(f"已把 {len(pages)} 页复制到“{target.display_name()}”末尾", 4000)

    def select_all(self):
        tab = self.current_tab()
        if tab:
            tab.grid.selectAll()

    def set_mode(self, mode):
        tab = self.current_tab()
        if tab:
            tab.set_mode(mode)
        self._refresh()

    def _on_thumb_slider(self, value):
        self.settings.setValue("organize_thumb", value)
        for t in self.tabs():
            t.set_organize_thumb(value)

    def _grid_menu(self, tab, global_pos):
        has = bool(tab.selected_rows())
        m = QMenu(self)
        for a in (self.act_rot_l, self.act_rot_r, self.act_delete):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_copy)
        m.addAction(self.act_cut)
        m.addAction(self.act_paste)
        m.addSeparator()
        m.addAction(self.act_extract)
        send = m.addMenu("复制到其它标签")
        others = [t for t in self.tabs() if t is not tab]
        for t in others:
            send.addAction(t.display_name(), lambda t=t: self.send_to(t))
        send.setEnabled(has and bool(others))
        m.addAction(self.act_export)
        m.addSeparator()
        m.addAction(self.act_insert_here)
        m.addAction(self.act_select_all)
        m.exec(global_pos)

    # ================================================================ 状态刷新
    def _refresh(self):
        tab = self.current_tab()
        has_tab = tab is not None
        rows = tab.selected_rows() if has_tab else []
        sel = bool(rows)
        self.tabbar.setVisible(has_tab)
        for a in (self.act_save, self.act_save_as, self.act_add, self.act_read, self.act_organize,
                  self.act_select_all, self.act_insert_here, self.act_close_tab):
            a.setEnabled(has_tab)
        for a in (self.act_rot_l, self.act_rot_r, self.act_delete, self.act_copy, self.act_cut,
                  self.act_extract, self.act_export):
            a.setEnabled(sel)
        self.act_paste.setEnabled(has_tab and bool(self.clipboard))
        self.act_undo.setEnabled(has_tab and tab.model.can_undo())
        self.act_redo.setEnabled(has_tab and tab.model.can_redo())
        reading = has_tab and tab.mode == MODE_READ
        self.act_read.setChecked(reading)
        self.act_organize.setChecked(has_tab and tab.mode == MODE_ORGANIZE)
        for a in self._zoom_actions:
            a.setVisible(reading)
        for a in self._thumb_actions:
            a.setVisible(has_tab and not reading)
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_fit):
            a.setEnabled(reading)
        if has_tab:
            self.act_fit.setChecked(tab.reader.is_fit_width())
            self.zoom_label.setText(f"{tab.reader.zoom_percent()}%")
            n = len(tab.model)
            parts = [f"共 {n} 页"]
            if sel:
                parts.append(f"已选 {len(rows)} 页")
            if reading and n:
                parts.append(f"当前第 {tab.reader.current_page() + 1} 页")
            self.page_label.setText("  ·  ".join(parts) + "  ")
            mod = " *" if tab.model.is_modified() else ""
            self.setWindowTitle(f"{tab.display_name()}{mod} - {APP_NAME}")
        else:
            self.page_label.setText("")
            self.setWindowTitle(APP_NAME)

    def changeEvent(self, e):
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange, QEvent.Type.ThemeChange):
            QTimer.singleShot(0, self._refresh_icons)
        super().changeEvent(e)

    def _refresh_icons(self):
        for w, name in self.themed:
            w.setIcon(icon(name))

    # ================================================================ 退出
    def closeEvent(self, e):
        for tab in self.tabs():
            if not self._confirm_discard(tab):
                e.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        self.svc.shutdown()
        e.accept()
