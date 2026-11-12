; Per-user installer for RVTSS: the pyRevit extension (Revit side) plus the MCP server with its own Python.
; Built by installer\build.ps1, which prepares the payload.
;
; Installs to   {localappdata}\Programs\Coordify\RVTSS           (no admin rights)
;               {app}\RVTSS.extension   the pyRevit extension
;               {app}\python            Python 3.13 + locked dependencies
; MCP command   {app}\python\python.exe {app}\RVTSS.extension\main.py   (also in {app}\mcp-connection.json)
; pyRevit side  optional task: adds {app} to pyRevit's custom extension folders and turns on the
;               pyRevit Routes server (127.0.0.1:48884) in %APPDATA%\pyRevit\pyRevit_config.ini (backed up first).
;               pyRevit itself must be installed; setup checks and warns.
;
; Test-only switch: /PYREVITINI=<file> edits that ini instead of %APPDATA%\pyRevit\pyRevit_config.ini.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "build\payload"
#endif
#define AppName "RVTSS Revit MCP (Coordify)"

[Setup]
AppId={{31B93230-92EB-4E44-9D3A-6C6F530AC203}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Coordify
DefaultDirName={localappdata}\Programs\Coordify\RVTSS
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=RVTSS-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupLogging=yes

[Tasks]
Name: "pyrevit"; Description: "Attach the extension to pyRevit and enable pyRevit Routes (Revit must be closed)"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\RVTSS.extension"
Type: filesandordirs; Name: "{app}\setup"
Type: files; Name: "{app}\mcp-connection.json"

[Code]
function PyRevitIni(): String;
begin
  Result := ExpandConstant('{param:PYREVITINI|}');
  if Result = '' then
    Result := ExpandConstant('{userappdata}\pyRevit\pyRevit_config.ini');
end;

function PyRevitInstalled(): Boolean;
begin
  Result := DirExists(ExpandConstant('{userappdata}\pyRevit-Master')) or
            DirExists(ExpandConstant('{commonappdata}\pyRevit-Master')) or
            DirExists(ExpandConstant('{commonpf64}\pyRevit-Master')) or
            DirExists(ExpandConstant('{commonpf64}\pyRevit CLI')) or
            FileExists(ExpandConstant('{userappdata}\pyRevit\pyRevit_config.ini'));
end;

function IsProcessRunning(ExeName: String): Boolean;
var
  Locator, Service, Found: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Found := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''' + ExeName + '''');
    Result := Found.Count > 0;
  except
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not PyRevitInstalled() then
    Result := SuppressibleMsgBox('pyRevit was not found for this user.' + #13#10#13#10 +
      'RVTSS runs inside Revit through pyRevit. Install pyRevit first ' +
      '(https://github.com/pyrevitlabs/pyRevit/releases), then run this setup again so the extension can be attached.' + #13#10#13#10 +
      'Continue anyway (the MCP server is installed, the Revit side waits for pyRevit)?',
      mbConfirmation, MB_YESNO, IDYES) = IDYES;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if WizardIsTaskSelected('pyrevit') and IsProcessRunning('Revit.exe') then
    Result := 'Revit is running. Close Revit and click Back, then Next: pyRevit rewrites its settings when Revit closes.';
end;

function JsonStr(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := '"' + S + '"';
end;

function RunRegister(Mode: String): Integer;
var
  Params: String;
begin
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup\pyrevit-register.ps1') + '" ' + Mode +
            ' -ExtRoot "' + ExpandConstant('{app}') + '" -Ini "' + PyRevitIni() + '"' +
            ' -Log "' + ExpandConstant('{app}\setup\pyrevit' + Mode + '.log') + '"';
  if not Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := 1;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
  Rc: Integer;
  LogText: AnsiString;
begin
  if CurStep <> ssPostInstall then exit;

  SetArrayLength(Lines, 7);
  Lines[0] := '{';
  Lines[1] := '  "name": "revit",';
  Lines[2] := '  "command": ' + JsonStr(ExpandConstant('{app}\python\python.exe')) + ',';
  Lines[3] := '  "args": [' + JsonStr(ExpandConstant('{app}\RVTSS.extension\main.py')) + '],';
  Lines[4] := '  "env": {},';
  Lines[5] := '  "version": "{#AppVersion}"';
  Lines[6] := '}';
  SaveStringsToUTF8FileWithoutBOM(ExpandConstant('{app}\mcp-connection.json'), Lines, False);

  if WizardIsTaskSelected('pyrevit') then
  begin
    Rc := RunRegister('-Register');
    LoadStringFromFile(ExpandConstant('{app}\setup\pyrevit-Register.log'), LogText);
    if Rc = 0 then
      SaveStringToFile(ExpandConstant('{app}\setup\registered.ini'), PyRevitIni(), False)
    else if Rc = 2 then
    begin
      SaveStringToFile(ExpandConstant('{app}\setup\registered.ini'), PyRevitIni(), False);
      SuppressibleMsgBox('RVTSS is attached to pyRevit, but:' + #13#10#13#10 + String(LogText), mbInformation, MB_OK, IDOK);
    end
    else
      SuppressibleMsgBox('Attaching RVTSS to pyRevit failed:' + #13#10#13#10 + String(LogText) + #13#10#13#10 +
        'Add this folder in pyRevit Settings > Custom Extension Directories:' + #13#10 + ExpandConstant('{app}'),
        mbError, MB_OK, IDOK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Ini: AnsiString;
  Params: String;
  Rc: Integer;
begin
  if (CurUninstallStep = usUninstall) and
     LoadStringFromFile(ExpandConstant('{app}\setup\registered.ini'), Ini) then
  begin
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup\pyrevit-register.ps1') +
              '" -Unregister -ExtRoot "' + ExpandConstant('{app}') + '" -Ini "' + Trim(String(Ini)) + '"';
    Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Rc);
  end;
end;
