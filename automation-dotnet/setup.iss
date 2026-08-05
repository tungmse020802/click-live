[Setup]
AppName=Click Live Desktop Tool
AppVersion=1.0.0
DefaultDirName={userlocalappdata}\ClickLiveDesktopTool
DefaultGroupName=Click Live Desktop Tool
OutputDir=.\installer
OutputBaseFilename=ClickLiveDesktopTool-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: ".\dist-standalone\AutomationDotNet.exe"; DestDir: "{app}"; DestName: "ClickLiveDesktopTool.exe"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Click Live Desktop Tool"; Filename: "{app}\ClickLiveDesktopTool.exe"
Name: "{autodesktop}\Click Live Desktop Tool"; Filename: "{app}\ClickLiveDesktopTool.exe"

[Run]
Filename: "{app}\ClickLiveDesktopTool.exe"; Description: "Launch Click Live Desktop Tool"; Flags: postinstall nowait skipifsilent
