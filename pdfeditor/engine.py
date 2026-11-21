"""PDF 处理核心：读取、按页组合、保存、图片转 PDF。

文档在内存里只是一串 PageRef（来源文件 + 页码 + 额外旋转角度），
所有排序、删除、旋转、跨文档复制都只改这串引用，保存时才真正生成新 PDF。
来源文件整份读进内存，所以不会占用磁盘上的原文件，可以直接覆盖保存。
"""

from __future__ import annotations

import io
import itertools
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

try:  # 让 Pillow 能读 iPhone 的 HEIC/HEIF 照片
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - 缺少该插件时仍可使用其它格式
    pass

Image.MAX_IMAGE_PIXELS = 400_000_000

try:
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
except Exception:  # pragma: no cover
    pass

# MuPDF 不是线程安全的：所有对 pymupdf 的调用（包括后台渲染）都必须持有这把锁。
PDF_LOCK = threading.RLock()

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".bmp", ".gif", ".tif", ".tiff",
    ".webp", ".heic", ".heif",
}
A4 = (595.2756, 841.8898)

IMAGE_PAGE_A4 = "a4"      # 图片放进 A4 页面（自动横竖，居中，可能留白）
IMAGE_PAGE_FIT = "fit"    # 页面大小跟随图片比例（无白边）


class PdfError(Exception):
    """给用户看的错误（消息是中文）。"""


class PasswordRequired(PdfError):
    pass


_source_ids = itertools.count(1)


class SourceDoc:
    """一份只读的、完全在内存中的 PDF，页面都从这里取。"""

    def __init__(self, doc: pymupdf.Document, name: str, path: str | None = None):
        self.uid = next(_source_ids)
        self.doc = doc
        self.name = name
        self.path = path
        self.closed = False
        with PDF_LOCK:
            self.sizes = [_page_size(doc, i) for i in range(doc.page_count)]
            try:
                self.toc = [list(e[:3]) for e in doc.get_toc(simple=True)]
            except Exception:
                self.toc = []
            try:
                self.metadata = dict(doc.metadata or {})
            except Exception:
                self.metadata = {}

    @property
    def page_count(self) -> int:
        return len(self.sizes)

    def close(self) -> None:
        with PDF_LOCK:
            if not self.closed:
                self.closed = True
                try:
                    self.doc.close()
                except Exception:
                    pass

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SourceDoc {self.uid} {self.name!r} {self.page_count}p>"


def _page_size(doc: pymupdf.Document, i: int) -> tuple[float, float]:
    try:
        r = doc.load_page(i).rect  # 已包含页面自带的旋转
        if r.width > 0 and r.height > 0:
            return (r.width, r.height)
    except Exception:
        pass
    return A4


@dataclass(frozen=True, slots=True)
class PageRef:
    src: SourceDoc
    index: int
    rotation: int = 0  # 用户额外加的顺时针旋转（0/90/180/270）

    def size(self) -> tuple[float, float]:
        """显示尺寸（点），已考虑旋转。"""
        w, h = self.src.sizes[self.index]
        return (h, w) if self.rotation % 180 else (w, h)

    def rotated(self, delta: int) -> "PageRef":
        return PageRef(self.src, self.index, (self.rotation + delta) % 360)


def all_pages(src: SourceDoc) -> list[PageRef]:
    return [PageRef(src, i) for i in range(src.page_count)]


def natural_key(path: str):
    """按“人类习惯”排序：IMG_2 在 IMG_10 前面。"""
    name = Path(path).name.lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def file_kind(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return None


# ---------------------------------------------------------------- 读取 PDF

def read_pdf(path: str, password: str | None = None) -> SourceDoc:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise PdfError(f"无法读取文件：{e.strerror or e}") from e
    with PDF_LOCK:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as e:
            raise PdfError("无法打开，文件可能已损坏，或者不是 PDF。") from e
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                raise PasswordRequired("需要密码" if not password else "密码不正确")
        if doc.page_count == 0:
            doc.close()
            raise PdfError("这个 PDF 里没有任何页面。")
        return SourceDoc(doc, Path(path).name, str(path))


# ---------------------------------------------------------------- 图片转 PDF

def image_page_geometry(w: float, h: float, mode: str):
    """返回 ((页面宽, 页面高), 图片放置矩形)。"""
    landscape = w > h
    page_w, page_h = (A4[1], A4[0]) if landscape else A4
    s = min(page_w / w, page_h / h)
    iw, ih = w * s, h * s
    if mode == IMAGE_PAGE_FIT:
        return (iw, ih), pymupdf.Rect(0, 0, iw, ih)
    x, y = (page_w - iw) / 2, (page_h - ih) / 2
    return (page_w, page_h), pymupdf.Rect(x, y, x + iw, y + ih)


def _image_payloads(path: str, force_reencode: bool = False):
    """把一张图片（多页 TIFF 则为多张）变成可以直接嵌入 PDF 的数据。

    JPEG/PNG 尽量原样嵌入（无损、不增大体积）；需要按 EXIF 方向旋转的、
    或 MuPDF 不认识的格式（HEIC、WebP 等）才用 Pillow 重新编码。
    """
    raw = Path(path).read_bytes()
    out = []
    with Image.open(io.BytesIO(raw)) as im:
        fmt = (im.format or "").upper()
        frames = getattr(im, "n_frames", 1) if fmt == "TIFF" else 1
        for k in range(frames):
            if frames > 1:
                im.seek(k)
            try:
                orient = int(im.getexif().get(0x0112, 1) or 1)
            except Exception:
                orient = 1
            if (not force_reencode and frames == 1 and orient == 1
                    and fmt in ("JPEG", "MPO", "PNG")):
                out.append((raw, im.width, im.height))
                continue
            frame = ImageOps.exif_transpose(im) if orient != 1 else im.copy()
            has_alpha = frame.mode in ("RGBA", "LA", "PA") or (
                frame.mode == "P" and "transparency" in frame.info)
            buf = io.BytesIO()
            if has_alpha:
                frame.convert("RGBA").save(buf, "PNG")
            elif fmt in ("PNG", "BMP", "GIF", "TIFF", "ICO", "PPM", "PCX", "TGA"):
                if frame.mode not in ("RGB", "L", "1"):
                    frame = frame.convert("RGB")
                frame.save(buf, "PNG")
            else:
                frame.convert("RGB").save(buf, "JPEG", quality=92)
            out.append((buf.getvalue(), frame.width, frame.height))
    return out


def images_to_source(paths: list[str], mode: str = IMAGE_PAGE_A4) -> tuple[SourceDoc, list[str]]:
    """把多张图片做成一份内存中的 PDF。返回 (来源文档, 失败的文件列表)。"""
    failed: list[str] = []
    with PDF_LOCK:
        doc = pymupdf.open()
    for p in paths:
        try:
            items = _image_payloads(p)
        except Exception:
            failed.append(p)
            continue
        ok = True
        for k, (data, w, h) in enumerate(items):
            with PDF_LOCK:
                (pw, ph), rect = image_page_geometry(w, h, mode)
                page = doc.new_page(width=pw, height=ph)
                try:
                    page.insert_image(rect, stream=data)
                    continue
                except Exception:
                    pass
            # MuPDF 不能直接用原始数据时，改用 Pillow 重新编码再试一次
            try:
                data2 = _image_payloads(p, force_reencode=True)[k][0]
                with PDF_LOCK:
                    page.insert_image(rect, stream=data2)
            except Exception:
                with PDF_LOCK:
                    doc.delete_page(page.number)
                ok = False
        if not ok:
            failed.append(p)
    with PDF_LOCK:
        if doc.page_count == 0:
            doc.close()
            raise PdfError("无法读取所选图片。")
        name = Path(paths[0]).stem if len(paths) == 1 else f"{Path(paths[0]).stem} 等 {len(paths)} 张图片"
        return SourceDoc(doc, name), failed


# ---------------------------------------------------------------- 生成与保存

def build_document(pages: list[PageRef]) -> pymupdf.Document:
    """按 PageRef 列表拼出一份新 PDF（调用方需持有 PDF_LOCK）。"""
    out = pymupdf.open()
    runs: list[list] = []  # 连续的页一起复制，可以保留它们之间的内部链接
    for ref in pages:
        if runs and runs[-1][0] is ref.src and runs[-1][2] == ref.index - 1:
            runs[-1][2] = ref.index
        else:
            runs.append([ref.src, ref.index, ref.index])
    for src, a, b in runs:
        out.insert_pdf(src.doc, from_page=a, to_page=b)
    for i, ref in enumerate(pages):
        if ref.rotation:
            page = out.load_page(i)
            page.set_rotation((page.rotation + ref.rotation) % 360)
    _apply_toc(out, pages)
    _apply_metadata(out, pages)
    return out


def _apply_toc(out: pymupdf.Document, pages: list[PageRef]) -> None:
    """保留原文件的书签：书签指向的页还在就跟着移动，页被删了就去掉该书签。"""
    first_pos: dict[tuple[int, int], int] = {}
    sources: list[SourceDoc] = []
    for i, ref in enumerate(pages):
        first_pos.setdefault((ref.src.uid, ref.index), i + 1)
        if ref.src not in sources:
            sources.append(ref.src)
    toc = []
    for src in sources:
        for level, title, pno in src.toc:
            new = first_pos.get((src.uid, pno - 1))
            if new is not None:
                toc.append([level, title, new])
    prev = 0
    for entry in toc:  # 删掉某些书签后，修正层级让它仍然合法
        entry[0] = max(1, min(entry[0], prev + 1))
        prev = entry[0]
    if toc:
        try:
            out.set_toc(toc)
        except Exception:
            pass


def _apply_metadata(out: pymupdf.Document, pages: list[PageRef]) -> None:
    for ref in pages:
        if ref.src.path:
            md = {k: ref.src.metadata.get(k) or "" for k in ("title", "author", "subject", "keywords", "creator")}
            try:
                out.set_metadata(md)
            except Exception:
                pass
            return


def pdf_bytes(pages: list[PageRef]) -> bytes:
    if not pages:
        raise PdfError("文档里没有页面，无法保存。")
    with PDF_LOCK:
        out = build_document(pages)
        try:
            return out.tobytes(garbage=3, deflate=True)
        finally:
            out.close()


def save_pdf(pages: list[PageRef], path: str) -> None:
    """生成 PDF 并写到 path。先写临时文件再替换，避免写一半时损坏原文件。"""
    data = pdf_bytes(pages)
    path = os.fspath(path)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows 上杀毒软件或索引服务可能短暂占用文件，稍等重试
                if attempt == 5:
                    raise
                time.sleep(0.3)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
