#define MyAppName "TetrapakReport"
#define MyAppVersion "1.0.23"
#define MyAppPublisher "MEK AI Automation"
#define MyAppExeName "TetrapakReport.exe"

[Setup]
AppId={{YOUR-GUID-HERE}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\TetrapakReport
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=TetrapakReport_Setup_{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=force
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"

[Files]
Source: "..\dist\TetrapakReport.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  AppPath: String;
  I: Integer;
begin
  // Kill process
  Exec('taskkill.exe', '/F /IM TetrapakReport.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // Use localappdata path directly — {app} not available here
  AppPath := ExpandConstant('{localappdata}') + '\TetrapakReport\TetrapakReport.exe';

  // Wait up to 10 seconds for file lock to release
  I := 0;
  while (I < 10) and FileExists(AppPath) and not DeleteFile(AppPath) do
  begin
    Sleep(1000);
    I := I + 1;
  end;

  Result := True;
end;
