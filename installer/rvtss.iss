; Per-user installer for RVTSS: the Revit side (C# add-in and/or pyRevit extension) plus the MCP server with its own Python.
; Built by installer\build.ps1, which prepares the payload.
;
; Installs to   {localappdata}\Programs\Coordify\RVTSS           (no admin rights)
;               {app}\RVTSS.extension   the pyRevit extension
;               {app}\python            Python 3.13 + locked dependencies
;               {app}\host\R<year>      the RVTSS Host add-in for Revit 2024-2027 (no pyRevit needed)
;               {app}\host\tests        test model of the "Run Self-Test" ribbon button
; MCP command   {app}\python\python.exe {app}\RVTSS.extension\main.py   (also in {app}\mcp-connection.json)
; Add-in side   task "hostaddin" (default): writes RvtssHost.addin into %APPDATA%\Autodesk\Revit\Addins\<year>
;               for every Revit 2024-2027 found for this user. The add-in listens on 127.0.0.1:48885, so the
;               MCP command gets REVIT_PORT=48885 (see mcp-connection.json).
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
Name: "hostaddin"; Description: "Install the RVTSS add-in into Revit 2024-2027 (recommended, no pyRevit needed; Revit must be closed)"
Name: "pyrevit"; Description: "Also attach the pyRevit extension and enable pyRevit Routes (needs pyRevit; Revit must be closed)"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\RVTSS.extension"
Type: filesandordirs; Name: "{app}\host"
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

function AddinDir(Year: Integer): String;
begin
  Result := ExpandConstant('{userappdata}\Autodesk\Revit\Addins\') + IntToStr(Year);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if (WizardIsTaskSelected('pyrevit') or WizardIsTaskSelected('hostaddin')) and IsProcessRunning('Revit.exe') then
    Result := 'Revit is running. Close Revit and click Back, then Next: Revit locks the add-in files and pyRevit rewrites its settings when Revit closes.'
  else if WizardIsTaskSelected('pyrevit') and not PyRevitInstalled() then
    Result := 'pyRevit was not found for this user. Install pyRevit first (https://github.com/pyrevitlabs/pyRevit/releases), or click Back and untick the pyRevit task: the RVTSS add-in works without pyRevit.';
end;

{ RvtssHost.addin for every Revit year whose add-ins folder exists; the list of written files is kept for uninstall. }
procedure RegisterHostAddin();
var
  Year: Integer;
  Lines: TArrayOfString;
  Manifest, Written: String;
begin
  Written := '';
  for Year := 2024 to 2027 do
  begin
    if not DirExists(AddinDir(Year)) then continue;
    if not FileExists(ExpandConstant('{app}\host\R') + IntToStr(Year) + '\RvtssHost.dll') then continue;
    Manifest := AddinDir(Year) + '\RvtssHost.addin';
    SetArrayLength(Lines, 11);
    Lines[0] := '<?xml version="1.0" encoding="utf-8"?>';
    Lines[1] := '<RevitAddIns>';
    Lines[2] := '  <AddIn Type="Application">';
    Lines[3] := '    <Name>RVTSS Host</Name>';
    Lines[4] := '    <Assembly>' + ExpandConstant('{app}\host\R') + IntToStr(Year) + '\RvtssHost.dll</Assembly>';
    Lines[5] := '    <FullClassName>RvtssHost.App</FullClassName>';
    Lines[6] := '    <ClientId>6f0c2a51-9d3e-4b7a-8c15-2e4d7a9b3f10</ClientId>';
    Lines[7] := '    <VendorId>RVTSS</VendorId>';
    Lines[8] := '    <VendorDescription>RVTSS, Suhaib Al Smadi</VendorDescription>';
    Lines[9] := '  </AddIn>';
    Lines[10] := '</RevitAddIns>';
    if SaveStringsToUTF8FileWithoutBOM(Manifest, Lines, False) then
      Written := Written + Manifest + #13#10;
  end;
  SaveStringToFile(ExpandConstant('{app}\setup\host-addins.txt'), Written, False);
  if Written = '' then
    SuppressibleMsgBox('No Revit 2024-2027 add-ins folder was found for this user, so the RVTSS add-in was not registered.' + #13#10#13#10 +
      'Start Revit once, then run this setup again.', mbInformation, MB_OK, IDOK);
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
  if WizardIsTaskSelected('hostaddin') then
    Lines[4] := '  "env": {"REVIT_PORT": "48885"},'
  else
    Lines[4] := '  "env": {},';
  Lines[5] := '  "version": "{#AppVersion}"';
  Lines[6] := '}';
  SaveStringsToUTF8FileWithoutBOM(ExpandConstant('{app}\mcp-connection.json'), Lines, False);

  if WizardIsTaskSelected('hostaddin') then
    RegisterHostAddin();

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
  Rc, I: Integer;
  Manifests: TArrayOfString;
begin
  if (CurUninstallStep = usUninstall) and
     LoadStringsFromFile(ExpandConstant('{app}\setup\host-addins.txt'), Manifests) then
    for I := 0 to GetArrayLength(Manifests) - 1 do
      if (Trim(Manifests[I]) <> '') and (ExtractFileName(Trim(Manifests[I])) = 'RvtssHost.addin') then
        DeleteFile(Trim(Manifests[I]));
  if (CurUninstallStep = usUninstall) and
     LoadStringFromFile(ExpandConstant('{app}\setup\registered.ini'), Ini) then
  begin
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup\pyrevit-register.ps1') +
              '" -Unregister -ExtRoot "' + ExpandConstant('{app}') + '" -Ini "' + Trim(String(Ini)) + '"';
    Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Rc);
  end;
end;
