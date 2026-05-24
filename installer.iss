; ============================================================
; Ciclométricas v2.0 — Inno Setup Script
; Genera: Ciclometricas_Setup_v2.0.exe
;
; Requisito: ejecutar build_exe.bat ANTES para generar
;            la carpeta dist\Ciclometricas\
;
; Abrir este archivo con Inno Setup y pulsar Compile.
; ============================================================

#define MyAppName "Ciclométricas"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Juan Carlos López San Joaquín"
#define MyAppURL "https://github.com/juancar1lo/ciclometricas"
#define MyAppExeName "Ciclometricas.exe"
#define MyAppIcon "assets\icon.ico"

[Setup]
AppId={{8F2E4A3B-1C5D-4E6F-A7B8-9D0E1F2A3B4C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\Ciclometricas
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=installer_output
OutputBaseFilename=Ciclometricas_Setup_v2.0
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el &Escritorio"; GroupDescription: "Iconos adicionales:"

[Files]
; Copiar toda la carpeta dist\Ciclometricas\ al directorio de instalación
Source: "dist\Ciclometricas\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Copiar icono explícitamente para accesos directos
Source: "assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
