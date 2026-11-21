# PDF 编辑器

一个简洁的 Windows PDF 小工具，只做页面级的事情：**合并、拖拽排序、旋转、删除、图片转 PDF**。
不做文字识别、文字编辑或画笔批注。

![图标](pdfeditor/resources/app.png)

## 下载

到 [Releases](https://github.com/chuhao11/pdf-editor/releases/latest) 下载：

- [**PDFEditor-Setup.exe**](https://github.com/chuhao11/pdf-editor/releases/latest/download/PDFEditor-Setup.exe)（推荐）：双击安装，不需要管理员权限
- [**PDFEditor-Portable.zip**](https://github.com/chuhao11/pdf-editor/releases/latest/download/PDFEditor-Portable.zip)：免安装，解压后双击 `PDFEditor.exe`

> 第一次运行如果出现“Windows 已保护你的电脑”，点 **更多信息 → 仍要运行**。
> 这是因为软件没有购买代码签名证书，只会提醒一次。

支持 Windows 10 / 11（64 位）。

## 功能

| 功能 | 怎么用 |
|---|---|
| 同时打开多个 PDF | 顶部是标签栏，像浏览器一样切换；也可以直接把文件拖进窗口 |
| 拖拽排序 | 拖动缩略图到新位置；按住 Ctrl 或 Shift 可以多选一起拖 |
| 在文件之间拖页面 | 拖着页面停在另一个标签上，它会自动切过去，再放到想要的位置（复制，不会改动原文档） |
| 合并 PDF | 点“添加”把别的 PDF 或图片接到当前文档末尾；或者把文件直接拖进缩略图区域的任意位置 |
| 图片转 PDF | 点“图片转 PDF”选图片；旁边的下拉菜单可选页面是 A4 还是跟随图片比例。支持 JPG、PNG、HEIC、WebP、BMP、TIFF，手机照片会自动摆正 |
| 旋转 / 删除 | 选中页面后点工具栏按钮，或者右键 |
| 复制 / 剪切 / 粘贴页面 | Ctrl+C / Ctrl+X / Ctrl+V，可以跨标签粘贴 |
| 提取页面 | 右键“提取到新文档”，或者保存按钮下拉菜单里的“导出选中页面” |
| 保存 | Ctrl+S **直接覆盖原文件**；保存按钮的下拉菜单里有“另存为” |
| 两种视图 | “阅读”：左边缩略图，右边大图；“整理”：大缩略图网格，适合排序 |

原文件里的书签会跟着页面一起移动，被删掉的页面对应的书签会自动去掉。

### 快捷键

| 快捷键 | 作用 |
|---|---|
| Ctrl+O | 打开 |
| Ctrl+S / Ctrl+Shift+S | 保存（覆盖）/ 另存为 |
| Ctrl+I | 添加 PDF 或图片到末尾 |
| Ctrl+N | 新建空白文档 |
| Ctrl+Z / Ctrl+Y | 撤销 / 重做 |
| Delete | 删除选中页面 |
| Ctrl+L / Ctrl+R | 向左 / 向右旋转 |
| Ctrl+A | 全选页面 |
| Ctrl+1 / Ctrl+2 | 阅读 / 整理视图 |
| Ctrl+滚轮、Ctrl+= / Ctrl+- / Ctrl+0 | 缩放 / 适应宽度 |
| Ctrl+Tab、Ctrl+W | 切换标签、关闭标签（中键点击标签也能关闭） |

## 从源码运行

需要 Python 3.12：

```bash
pip install -r requirements.txt
python -m pdfeditor
```

运行测试：

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## 打包和发布

推送到 `main` 时，GitHub Actions 会在 Windows 上跑测试、用 PyInstaller 打包、自检，再用 Inno Setup 生成安装包，结果可以在 Actions 页面下载。

推送 `v` 开头的标签就会自动发布 Release：

```bash
git tag v1.0.1
git push origin v1.0.1
```

版本号写在 `pdfeditor/__init__.py` 里。

## 技术说明

- 界面：PySide6 (Qt 6)
- PDF 渲染和生成：PyMuPDF (MuPDF)
- 图片：Pillow + pillow-heif

编辑时只记录“哪个文件的第几页、转了多少度”，保存时才生成新 PDF；原文件会整份读进内存，所以可以安全地覆盖保存。

## 许可证

因为用到了 PyMuPDF（AGPL-3.0），本项目同样使用 [AGPL-3.0](LICENSE) 许可证。
