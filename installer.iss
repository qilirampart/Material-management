[Setup]
#ifndef AppVersion
#define AppVersion "0.5.3"
#endif
#ifndef AppSourceDir
#define AppSourceDir "release\素材投放助手"
#endif
#ifndef PackageOutputDir
#define PackageOutputDir "release"
#endif
#ifndef SetupBaseName
#define SetupBaseName "素材投放助手-安装包-" + AppVersion
#endif
#ifdef ValidationBuild
AppId={{48173F10-D063-4F39-A062-584FB879D2BD}
AppName=点众素材投放助手（验收）
#else
AppId={{22F74318-4740-49D9-A5F8-107A83EA6B24}
AppName=点众素材投放助手
#endif
AppVersion={#AppVersion}
AppPublisher=点众
DefaultDirName={localappdata}\Programs\DianzhongMaterialAssistant
DefaultGroupName=点众素材投放助手
PrivilegesRequired=lowest
OutputDir={#PackageOutputDir}
OutputBaseFilename={#SetupBaseName}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\素材投放助手.exe
CloseApplications=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "assets\installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\点众素材投放助手"; Filename: "{app}\素材投放助手.exe"
Name: "{autodesktop}\点众素材投放助手"; Filename: "{app}\素材投放助手.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\素材投放助手.exe"; Description: "启动素材投放助手"; Flags: nowait postinstall skipifsilent
