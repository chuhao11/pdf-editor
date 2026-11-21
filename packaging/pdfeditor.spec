# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置。用法（在仓库根目录）：
#   pyinstaller packaging/pdfeditor.spec --noconfirm --distpath dist --workpath build
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from pdfeditor import __version__  # noqa: E402

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "pdfeditor", "resources"), "pdfeditor/resources")],
    hiddenimports=["pillow_heif"],
    excludes=["tkinter", "unittest", "pydoc", "doctest", "numpy", "pytest"],
    noarchive=False,
)


def _keep(entry):
    """去掉用不到的大文件：其它语言的 Qt 翻译、软件 OpenGL。"""
    dest = entry[0].replace("\\", "/").lower()
    if "/translations/" in dest:
        return "zh_cn" in dest
    if dest.endswith("opengl32sw.dll"):
        return False
    return True


a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]

version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
    nums = tuple(int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4])
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("080404B0", [
                StringStruct("CompanyName", "chuhao11"),
                StringStruct("FileDescription", "PDF 编辑器"),
                StringStruct("FileVersion", __version__),
                StringStruct("InternalName", "PDFEditor"),
                StringStruct("OriginalFilename", "PDFEditor.exe"),
                StringStruct("ProductName", "PDF 编辑器"),
                StringStruct("ProductVersion", __version__),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0804, 1200])]),
        ],
    )

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFEditor",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "pdfeditor", "resources", "app.ico"),
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PDFEditor",
)
