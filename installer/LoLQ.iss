#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{72739DF1-7C35-4FA0-B793-B205742B3F54}
AppName=LoLQ
AppVersion={#AppVersion}
AppPublisher=imoutosuki
AppPublisherURL=https://imoutosuki.com/lolq/
AppSupportURL=https://imoutosuki.com/lolq/
DefaultDirName={localappdata}\Programs\LoLQ
DefaultGroupName=LoLQ
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=yes
WizardStyle=modern
SetupIconFile=LoLQ.ico
UninstallDisplayIcon={app}\LoLQ.exe
OutputDir=..\dist\installer
OutputBaseFilename=LoLQ-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=LoLQ.exe
RestartApplications=no
UsePreviousTasks=yes

[Tasks]
Name: "startup"; Description: "Start LoLQ when I sign in to Windows"; Flags: checkedonce

[Files]
Source: "..\dist\LoLQ\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LoLQ"; Filename: "{app}\LoLQ.exe"
Name: "{group}\Uninstall LoLQ"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LoLQ"; ValueData: """{app}\LoLQ.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\lolq"; ValueType: string; ValueName: ""; ValueData: "URL:LoLQ"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\lolq"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\lolq\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LoLQ.exe,0"
Root: HKCU; Subkey: "Software\Classes\lolq\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LoLQ.exe"" --uri ""%1"""

[Run]
Filename: "{app}\LoLQ.exe"; Description: "Open LoLQ and finish setup"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\LoLQ.exe"; Parameters: "--shutdown"; Flags: runhidden waituntilterminated; RunOnceId: "StopLoLQ"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var ResultCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\LoLQ.exe')) then
    Exec(ExpandConstant('{app}\LoLQ.exe'), '--shutdown', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('startup') then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'LoLQ');
end;
