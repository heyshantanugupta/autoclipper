; Windows installer, built by the "Build desktop apps" workflow with: iscc /DAppVersion=0.1.6 installer\autoclipper.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2B1A-5D4E-4C7B-9A21-6E0B7D3F1C55}
AppName=AutoClipper
AppVersion={#AppVersion}
AppVerName=AutoClipper {#AppVersion}
AppPublisher=Shantanu Gupta
AppPublisherURL=https://github.com/heyshantanugupta/autoclipper
AppSupportURL=https://github.com/heyshantanugupta/autoclipper/issues
DefaultDirName={localappdata}\Programs\AutoClipper
DefaultGroupName=AutoClipper
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\out
OutputBaseFilename=AutoClipper-Setup-{#AppVersion}-windows-x64
SetupIconFile=..\autoclipper\assets\icon.ico
UninstallDisplayIcon={app}\AutoClipper.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\AutoClipper.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AutoClipper"; Filename: "{app}\AutoClipper.exe"
Name: "{autodesktop}\AutoClipper"; Filename: "{app}\AutoClipper.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoClipper.exe"; Description: "Open AutoClipper"; Flags: nowait postinstall
