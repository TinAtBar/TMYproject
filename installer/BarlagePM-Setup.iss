; Barlage PM – Installer für alle PCs (pro Benutzer, keine Administratorrechte)
; Datenordner-Konfiguration (Priorität):
;   1. Parameter  /DATA="\\NAS\Firma\PM-OPL"  [/PORT=8080]
;   2. config.json neben BarlagePM-Setup.exe (die Admin-Konsole legt sie in <Datenordner>\installation ab)
;   3. bereits vorhandene %LOCALAPPDATA%\BarlagePM\config.json (Update)
;   4. sonst: Assistentenseite „Datenordner“ (Pfad/UNC + Durchsuchen, prüft <Pfad>\opl.db)
; Firmen-Zertifikat <Datenordner>\tls\ca.crt wird für den Benutzer als vertrauenswürdig importiert
;   (certutil -user -addstore Root – Windows fragt einmal nach; im stillen Update übernimmt das die App).
; Stilles Update (von Barlage PM selbst gestartet):  BarlagePM-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /RESTARTAPP
; R4-I Wartung: Ist Barlage PM schon installiert, fragt das Setup (nicht im stillen Modus):
;   Aktualisieren (Standard) / Neu installieren (persönliche Einstellungen zurücksetzen) / Deinstallieren.
; R4-I Deinstallation: fragt „Auch persönliche Einstellungen entfernen?“ (Standard Nein; still = Nein) und – nur wenn
;   Barlage PM das Firmen-Zertifikat selbst importiert hat (config.json "ca_importiert") – ob es entfernt werden soll.
;   Der Datenordner auf dem NAS wird nie angefasst.

#define AppName "Barlage PM"
#define AppVersion "2.9.0"
#define AppExe "BarlagePM.exe"
#define Dist "..\dist\BarlagePM"
; R4-I: eigene AppId (ohne doppelte Klammer) für den Registry-Schlüssel ...\Uninstall\<AppId>_is1
#define MyAppId "{FE00D9C0-211F-45C3-B21C-42442C0D6801}"

[Setup]
AppId={{FE00D9C0-211F-45C3-B21C-42442C0D6801}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Barlage
DefaultDirName={localappdata}\Programs\BarlagePM
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=Output
OutputBaseFilename=BarlagePM-Setup
SetupIconFile=..\build\icons\barlagepm.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung anlegen"; GroupDescription: "Verknüpfungen:"

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; R29-A (131a): Link-Protokoll barlagepm://ordner?pfad=… öffnet den Ordner im Windows-Explorer dieses PCs
Root: HKCU; Subkey: "Software\Classes\barlagepm"; ValueType: string; ValueName: ""; ValueData: "URL:Barlage PM Ordner"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\barlagepm"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\barlagepm\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\barlagepm\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "Barlage PM jetzt starten"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Parameters: "--kein-update"; Flags: nowait; Check: NeustartGewuenscht

[Code]
var
  DatenSeite: TInputDirWizardPage;
  { R4-I: Wartungsseite }
  WartungSeite: TWizardPage;
  RbAktualisieren, RbNeu, RbDeinstallieren: TNewRadioButton;
  CbKonfigReset: TNewCheckBox;
  InstallierterUninstaller: String;
  SetupBeenden: Boolean;
  { R4-A: bei „Neu installieren“ gemerkter Datenordner/Port (Datenordner wird neu erkannt statt erfragt) }
  NeuDaten, NeuPort: String;

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

function HatParam(Name: String): Boolean;
var I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then Result := True;
end;

function NeustartGewuenscht: Boolean;
begin
  Result := WizardSilent and HatParam('/RESTARTAPP');
end;

function JsonText(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := S;
end;

{ Liest den Wert von "data" aus einer config.json (einfacher Parser, reicht für unsere Datei). }
function JsonDaten(Datei: String): String;
var Inhalt: AnsiString; S: String; P, I: Integer;
begin
  Result := '';
  if not LoadStringFromFile(Datei, Inhalt) then Exit;
  S := String(Inhalt);
  P := Pos('"data"', S);
  if P = 0 then Exit;
  S := Copy(S, P + 6, MaxInt);
  P := Pos('"', S);
  if P = 0 then Exit;
  S := Copy(S, P + 1, MaxInt);
  I := 1;
  while I <= Length(S) do begin
    if S[I] = '\' then begin
      Result := Result + S[I + 1];
      I := I + 2;
    end else if S[I] = '"' then
      Break
    else begin
      Result := Result + S[I];
      I := I + 1;
    end;
  end;
end;

{ R4-A: Zahlenwert "port": 8080 aus config.json, sonst '' }
function JsonPort(Datei: String): String;
var Inhalt: AnsiString; S: String; P, I: Integer;
begin
  Result := '';
  if not LoadStringFromFile(Datei, Inhalt) then Exit;
  S := String(Inhalt);
  P := Pos('"port"', S);
  if P = 0 then Exit;
  S := Copy(S, P + 6, MaxInt);
  P := Pos(':', S);
  if P = 0 then Exit;
  S := TrimLeft(Copy(S, P + 1, MaxInt));
  I := 1;
  while (I <= Length(S)) and (S[I] >= '0') and (S[I] <= '9') do I := I + 1;
  Result := Copy(S, 1, I - 1);
end;

function ZielOrdner: String;
begin
  Result := ExpandConstant('{localappdata}\BarlagePM');
end;

{ R4-I: Neu installieren mit „auch Datenordner-Verbindung zurücksetzen“ }
function KonfigZuruecksetzen: Boolean;
begin
  Result := False;
  if WizardSilent then Exit;
  if RbNeu = nil then Exit;
  Result := RbNeu.Checked and CbKonfigReset.Checked;
end;

function DatenordnerBekannt: Boolean;
begin
  Result := (ParamWert('/DATA') <> '')
    or FileExists(ExpandConstant('{src}\config.json'))
    or ((not KonfigZuruecksetzen) and FileExists(ZielOrdner + '\config.json'));
end;

{ R4-I: Pfad des Uninstallers einer vorhandenen Barlage-PM-Installation (gleiche AppId), sonst '' }
function UninstallerFinden: String;
var Schluessel, Cmd: String;
begin
  Result := '';
  Schluessel := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';
  if not RegQueryStringValue(HKCU, Schluessel, 'UninstallString', Cmd) then
    if not RegQueryStringValue(HKLM, Schluessel, 'UninstallString', Cmd) then Exit;
  Cmd := RemoveQuotes(Cmd);
  if FileExists(Cmd) then Result := Cmd;
end;

function InitializeSetup: Boolean;
begin
  InstallierterUninstaller := UninstallerFinden;
  SetupBeenden := False;
  NeuDaten := '';
  NeuPort := '';
  Result := True;
end;

procedure WartungSeiteAnlegen;
var Y: Integer;
begin
  WartungSeite := CreateCustomPage(wpWelcome, 'Barlage PM ist bereits installiert',
    'Was soll das Setup tun?');
  Y := 0;
  RbAktualisieren := TNewRadioButton.Create(WartungSeite);
  RbAktualisieren.Parent := WartungSeite.Surface;
  RbAktualisieren.Top := Y;
  RbAktualisieren.Width := WartungSeite.SurfaceWidth;
  RbAktualisieren.Height := ScaleY(20);
  RbAktualisieren.Caption := 'Aktualisieren (empfohlen) – Einstellungen und Anmeldung bleiben erhalten';
  RbAktualisieren.Checked := True;
  Y := Y + ScaleY(28);
  RbNeu := TNewRadioButton.Create(WartungSeite);
  RbNeu.Parent := WartungSeite.Surface;
  RbNeu.Top := Y;
  RbNeu.Width := WartungSeite.SurfaceWidth;
  RbNeu.Height := ScaleY(20);
  RbNeu.Caption := 'Neu installieren (Konfiguration, Zwischenspeicher und Browserprofil zurücksetzen)';
  Y := Y + ScaleY(22);
  CbKonfigReset := TNewCheckBox.Create(WartungSeite);
  CbKonfigReset.Parent := WartungSeite.Surface;
  CbKonfigReset.Top := Y;
  CbKonfigReset.Left := ScaleX(20);
  CbKonfigReset.Width := WartungSeite.SurfaceWidth - ScaleX(20);
  CbKonfigReset.Height := ScaleY(20);
  CbKonfigReset.Caption := 'auch Datenordner-Verbindung zurücksetzen (Setup fragt neu nach dem Datenordner)';
  CbKonfigReset.Checked := False;
  Y := Y + ScaleY(28);
  RbDeinstallieren := TNewRadioButton.Create(WartungSeite);
  RbDeinstallieren.Parent := WartungSeite.Surface;
  RbDeinstallieren.Top := Y;
  RbDeinstallieren.Width := WartungSeite.SurfaceWidth;
  RbDeinstallieren.Height := ScaleY(20);
  RbDeinstallieren.Caption := 'Deinstallieren';
  Y := Y + ScaleY(36);
  with TNewStaticText.Create(WartungSeite) do begin
    Parent := WartungSeite.Surface;
    Top := Y;
    Width := WartungSeite.SurfaceWidth;
    WordWrap := True;
    AutoSize := False;
    Height := ScaleY(60);
    Caption := '„Neu installieren“ löscht auf diesem PC den Zwischenspeicher, das App-Browserprofil und die ' +
      'Offline-Daten (%LOCALAPPDATA%\BarlagePM). Die Daten im Datenordner auf dem Server/NAS bleiben unverändert.';
  end;
end;

{ R4-I: persönliche Daten unter %LOCALAPPDATA%\BarlagePM entfernen (nie den NAS-Datenordner).
  MitKonfig: auch config.json (Datenordner-Verbindung, Zertifikat-Merker). }
procedure PersoenlichesLoeschen(MitKonfig: Boolean);
var Z: String;
begin
  Z := ExpandConstant('{localappdata}\BarlagePM');
  if not DirExists(Z) then Exit;
  Log('Persönliche Einstellungen entfernen: ' + Z);
  DeleteFile(Z + '\cache.json');
  DeleteFile(Z + '\ca_import_installer.flag');
  DelTree(Z + '\browser', True, True, True);
  if MitKonfig then begin
    DeleteFile(Z + '\config.json');
    DelTree(Z + '\logs', True, True, True);
    RemoveDir(Z);
  end;
end;

procedure InitializeWizard;
begin
  { R4-I: DatenSeite zuerst anlegen; die Wartungsseite (ebenfalls nach wpWelcome) steht dann davor }
  DatenSeite := CreateInputDirPage(wpWelcome,
    'Datenordner', 'Wo liegen die Barlage-PM-Daten?',
    'Bitte den Datenordner auf dem Server/NAS angeben (er enthält die Datei opl.db), ' +
    'z. B. \\file01\Freigabe\PM-OPL. Ein UNC-Pfad ist besser als ein Laufwerksbuchstabe.',
    False, '');
  DatenSeite.Add('Datenordner:');
  DatenSeite.Values[0] := '';
  WartungSeiteAnlegen;  { R4-I }
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = DatenSeite.ID) and DatenordnerBekannt;
  { R4-I: Wartungsseite nur bei vorhandener Installation und nie im stillen Modus (Update = Aktualisieren) }
  if PageID = WartungSeite.ID then
    Result := WizardSilent or (InstallierterUninstaller = '');
end;

{ R4-I: Setup ohne Rückfrage beenden (nach „Deinstallieren“) }
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if SetupBeenden then begin
    Cancel := True;
    Confirm := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var D: String; RC: Integer;
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
    Exit;
  end;
  if CurPageID = DatenSeite.ID then begin
    D := Trim(DatenSeite.Values[0]);
    if (Length(D) > 3) and (D[Length(D)] = '\') then D := Copy(D, 1, Length(D) - 1);
    DatenSeite.Values[0] := D;
    if D = '' then begin
      MsgBox('Bitte den Datenordner angeben.', mbError, MB_OK);
      Result := False;
    end else if not FileExists(D + '\opl.db') then begin
      MsgBox('In diesem Ordner wurde keine Datenbank (opl.db) gefunden:' + #13#10 + D + #13#10#13#10 +
        'Bitte den Datenordner wählen, den der Administrator eingerichtet hat, und prüfen, ob die Freigabe erreichbar ist.',
        mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure KonfigSchreiben;
var Ziel, Daten, Port, Quelle: String;
begin
  Ziel := ZielOrdner;
  ForceDirectories(Ziel);
  Daten := ParamWert('/DATA');
  Port := ParamWert('/PORT');
  if Port = '' then Port := '8080';
  Quelle := ExpandConstant('{src}\config.json');
  if Daten <> '' then
    SaveStringToFile(Ziel + '\config.json',
      '{"data": "' + JsonText(Daten) + '", "port": ' + Port + '}', False)
  else if FileExists(Quelle) then
    FileCopy(Quelle, Ziel + '\config.json', False)
  else if NeuDaten <> '' then begin
    { R4-A: Neu installieren – frische config.json mit dem bisherigen Datenordner }
    if NeuPort <> '' then Port := NeuPort;
    SaveStringToFile(Ziel + '\config.json',
      '{"data": "' + JsonText(NeuDaten) + '", "port": ' + Port + '}', False);
  end
  else if FileExists(Ziel + '\config.json') then begin
    Log('Update: vorhandene Konfiguration bleibt');
  end else if Trim(DatenSeite.Values[0]) <> '' then
    SaveStringToFile(Ziel + '\config.json',
      '{"data": "' + JsonText(Trim(DatenSeite.Values[0])) + '", "port": ' + Port + '}', False)
  else if not WizardSilent then
    MsgBox('Kein Datenordner bekannt. Barlage PM fragt beim ersten Start danach.', mbInformation, MB_OK);
end;

{ Firmen-CA für den aktuellen Benutzer vertrauen (keine Adminrechte; Windows zeigt eine Sicherheitsabfrage). }
procedure ZertifikatVertrauen;
var Daten, Ca: String; RC: Integer;
begin
  if WizardSilent then Exit;  { stilles Update: macht die App beim Start }
  Daten := JsonDaten(ZielOrdner + '\config.json');
  if Daten = '' then Exit;
  Ca := Daten + '\tls\ca.crt';
  if not FileExists(Ca) then Exit;
  if Exec(ExpandConstant('{sys}\certutil.exe'), '-user -addstore Root "' + Ca + '"', '', SW_HIDE,
          ewWaitUntilTerminated, RC) then begin
    Log('certutil -addstore Root: Code ' + IntToStr(RC));
    { R4-I: Merker – die App trägt beim Start den Fingerabdruck als ca_importiert in config.json ein }
    if RC = 0 then
      SaveStringToFile(ZielOrdner + '\ca_import_installer.flag', 'certutil', False);
  end else
    Log('certutil konnte nicht gestartet werden');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then begin
    { R4-I: Neu installieren }
    if (not WizardSilent) and (InstallierterUninstaller <> '') and RbNeu.Checked then begin
      { R4-A: Konfiguration immer zurücksetzen; Datenordner bleibt bekannt, außer die Verbindung soll neu gewählt werden }
      NeuDaten := '';
      NeuPort := '';
      if not CbKonfigReset.Checked then begin
        NeuDaten := JsonDaten(ZielOrdner + '\config.json');
        NeuPort := JsonPort(ZielOrdner + '\config.json');
      end;
      PersoenlichesLoeschen(True);
    end;
  end;
  if CurStep = ssPostInstall then begin
    KonfigSchreiben;
    ZertifikatVertrauen;
  end;
end;

{ ------------------------------------------------------------------ R4-I: Deinstallation }
{ Liest einen Textwert "Schluessel": "..." aus einer JSON-Datei (einfach, für config.json). }
function JsonWert(Datei, Schluessel: String): String;
var Inhalt: AnsiString; S: String; P: Integer;
begin
  Result := '';
  if not LoadStringFromFile(Datei, Inhalt) then Exit;
  S := String(Inhalt);
  P := Pos('"' + Schluessel + '"', S);
  if P = 0 then Exit;
  S := Copy(S, P + Length(Schluessel) + 2, MaxInt);
  P := Pos(':', S);
  if P = 0 then Exit;
  S := TrimLeft(Copy(S, P + 1, MaxInt));
  if (Length(S) = 0) or (S[1] <> '"') then Exit;
  S := Copy(S, 2, MaxInt);
  P := Pos('"', S);
  if P = 0 then Exit;
  Result := Copy(S, 1, P - 1);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Z, Fp: String; RC: Integer; MitZertifikat: Boolean;
begin
  if CurUninstallStep <> usUninstall then Exit;
  if UninstallSilent then Exit;  { still: nichts Persönliches entfernen }
  Z := ExpandConstant('{localappdata}\BarlagePM');
  Fp := JsonWert(Z + '\config.json', 'ca_importiert');
  if MsgBox('Auch persönliche Einstellungen entfernen?' + #13#10#13#10 +
      'Konfiguration (Datenordner-Verbindung), Zwischenspeicher, Offline-Daten und das App-Browserprofil ' +
      'unter ' + Z + '.' + #13#10#13#10 +
      'Die Daten im Datenordner auf dem Server/NAS werden NICHT gelöscht.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    PersoenlichesLoeschen(True);
  MitZertifikat := False;
  if Fp <> '' then
    MitZertifikat := MsgBox('Auch das Firmen-Zertifikat (Barlage PM) aus den vertrauenswürdigen Zertifikaten ' +
      'dieses Benutzers entfernen?' + #13#10#13#10 + 'Fingerabdruck: ' + Fp,
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  if MitZertifikat then begin
    if Exec(ExpandConstant('{sys}\certutil.exe'), '-user -delstore Root ' + Fp, '', SW_HIDE,
            ewWaitUntilTerminated, RC) then
      Log('certutil -delstore Root: Code ' + IntToStr(RC));
  end;
end;
