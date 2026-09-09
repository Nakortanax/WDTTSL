#define MyAppName "VPNSL"
#define MyAppVersion "1.0.8"
#define MyAppPublisher "Sazhaev-IA"
#define MyAppExeName "VPNSL.Windows.exe"

[Setup]
AppId={{C68C34D8-8B68-4F09-B4D1-AE8A2D4D1080}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VPNSL
DefaultGroupName=VPNSL
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VPNSL-1.0.8-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
Source: "..\dist\VPNSL-1.0.8-Windows-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VPNSL"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\VPNSL"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить VPNSL"; Flags: nowait postinstall skipifsilent shellexec
