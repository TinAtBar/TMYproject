; Barlage PM Admin – Admin-Konsole, nur für den Administrator-PC (pro Benutzer, keine Administratorrechte)
; Optional: /DATA="\\NAS\Firma\PM-OPL" gibt den Datenordner vor (sonst fragt der Einrichtungsassistent).
; R4-I: Ist die Konsole schon installiert, fragt das Setup (nicht still): Aktualisieren (Standard) / Deinstallieren.

#define AppName "Barlage PM Admin"
#define AppVersion "2.8.0"
#define AppExe "BarlagePM-Admin.exe"
#define Dist "..\dist\BarlagePM-Admin"
; R4-I: eigene AppId (ohne doppelte Klammer) für den Registry-Schlüssel
#define MyAppId "{3D671A20-BE41-4AC9-B2DA-0E55A4CB8210}"

[Setup]
AppId={{3D671A20-BE41-4AC9-B2DA-0E55A4CB8210}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Barlage
DefaultDirName={localappdata}\Programs\BarlagePM-Admin
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=BarlagePM-Admin-Setup
SetupIconFile=..\build\icons\barlagepm-admin.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung anlegen"; GroupDescription: "Verknüpfungen:"

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; BarlagePM-Setup.exe mitliefern, damit die Konsole ihn in <Datenordner>\installation kopieren kann
Source: "Output\BarlagePM-Setup.exe"; DestDir: "{app}\installer"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Admin-Konsole jetzt starten"; Flags: nowait postinstall skipifsilent

[Code]
var
  { R4-I: Wartungsseite }
  WartungSeite: TWizardPage;
  RbAktualisieren, RbDeinstallieren: TNewRadioButton;
  InstallierterUninstaller: String;
  SetupBeenden: Boolean;

function ParamWert(Name: String): String;
var I: Integer; P: String;
begin
  Result := '';
  for I := 1 to ParamCount do begin
    P := ParamStr(I);
    if CompareText(Copy(P, 1, Length(Name) + 1), Name + '=') = 0 then
      Result := RemoveQuotes(Copy(P, Length(Name) + 2, MaxInt));
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var D, Z: String;
begin
  if CurStep = ssPostInstall then begin
    D := ParamWert('/DATA');
    if D <> '' then begin
      Z := ExpandConstant('{localappdata}\BarlagePM');
      ForceDirectories(Z);
      StringChangeEx(D, '\', '\\', True);
      SaveStringToFile(Z + '\cache.json', '{"admin_data": "' + D + '"}', False);
    end;
  end;
end;

{ ------------------------------------------------------------------ R4-I: Wartung }
function UninstallerFinden: String;
var Schluessel, Cmd: String;
begin
  Result := '';
  Schluessel := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';
  if not RegQueryStringValue(HKCU, Schluessel, 'UninstallString', Cmd) then Exit;
  Cmd := RemoveQuotes(Cmd);
  if FileExists(Cmd) then Result := Cmd;
end;

function InitializeSetup: Boolean;
begin
  InstallierterUninstaller := UninstallerFinden;
  SetupBeenden := False;
  Result := True;
end;

procedure InitializeWizard;
begin
  WartungSeite := CreateCustomPage(wpWelcome, 'Barlage PM Admin ist bereits installiert',
    'Was soll das Setup tun?');
  RbAktualisieren := TNewRadioButton.Create(WartungSeite);
  RbAktualisieren.Parent := WartungSeite.Surface;
  RbAktualisieren.Top := 0;
  RbAktualisieren.Width := WartungSeite.SurfaceWidth;
  RbAktualisieren.Height := ScaleY(20);
  RbAktualisieren.Caption := 'Aktualisieren (empfohlen)';
  RbAktualisieren.Checked := True;
  RbDeinstallieren := TNewRadioButton.Create(WartungSeite);
  RbDeinstallieren.Parent := WartungSeite.Surface;
  RbDeinstallieren.Top := ScaleY(28);
  RbDeinstallieren.Width := WartungSeite.SurfaceWidth;
  RbDeinstallieren.Height := ScaleY(20);
  RbDeinstallieren.Caption := 'Deinstallieren (der Datenordner auf dem Server/NAS bleibt unverändert)';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = WartungSeite.ID then
    Result := WizardSilent or (InstallierterUninstaller = '');
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if SetupBeenden then begin
    Cancel := True;
    Confirm := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var RC: Integer;
begin
  Result := True;
  if (CurPageID = WartungSeite.ID) and RbDeinstallieren.Checked then begin
    Result := False;
    if Exec(InstallierterUninstaller, '', '', SW_SHOW, ewWaitUntilTerminated, RC) then begin
      SetupBeenden := True;
      WizardForm.Close;
    end else
      MsgBox('Die Deinstallation konnte nicht gestartet werden:' + #13#10 + InstallierterUninstaller,
        mbError, MB_OK);
  end;
end;
