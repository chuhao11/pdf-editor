; Inno Setup 安装包脚本。GitHub Actions 里用：ISCC /DAppVersion=1.0.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "PDF 编辑器"
#define AppExe "PDFEditor.exe"
#define ChsIsl AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl"

[Setup]
AppId={{6E0F3A52-9B1C-4C7E-A7D2-5F2B8C1E4A90}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=chuhao11
AppPublisherURL=https://github.com/chuhao11/pdf-editor
AppSupportURL=https://github.com/chuhao11/pdf-editor/issues
AppUpdatesURL=https://github.com/chuhao11/pdf-editor/releases
; 只装给当前用户，不需要管理员权限
PrivilegesRequired=lowest
DefaultDirName={autopf}\PDFEditor
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist
OutputBaseFilename=PDFEditor-Setup
SetupIconFile=..\pdfeditor\resources\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(ChsIsl)
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#else
; Inno Setup 6 没有自带简体中文，用仓库里附带的翻译（来自 Inno Setup 官方仓库）
Name: "chs"; MessagesFile: "ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\PDFEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 升级时清掉旧版本留下的文件，避免新旧库混在一起
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; 出现在 PDF 文件右键菜单的“打开方式”里（不会抢走默认打开程序）
Root: HKA; Subkey: "Software\Classes\PDFEditor.pdf"; ValueType: string; ValueName: ""; ValueData: "PDF 文档"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PDFEditor.pdf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\PDFEditor.pdf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFEditor.pdf"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
