# Installiert die Stadtkarten-Werkstatt für den aktuellen Benutzer (keine Administratorrechte nötig).
$ErrorActionPreference = 'Stop'
$name    = 'Stadtkarten-Werkstatt'
$version = '__VERSION__'
$target  = Join-Path $env:LOCALAPPDATA "Programs\$name"
$exe     = Join-Path $target "$name.exe"

Write-Host "Installiere $name $version nach $target ..."
Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path $target) { Remove-Item $target -Recurse -Force }   # ältere Version ersetzen
New-Item -ItemType Directory -Force -Path $target | Out-Null
Expand-Archive -Path (Join-Path $PSScriptRoot 'app.zip') -DestinationPath $target -Force
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') $target -Force

# Verknüpfungen: Desktop und Startmenü
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) $name
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
foreach ($lnkPath in @((Join-Path ([Environment]::GetFolderPath('Desktop')) "$name.lnk"), (Join-Path $startMenu "$name.lnk"))) {
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $target
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = 'Stadtkarten für Die Alte Ordnung erzeugen'
    $lnk.Save()
}
$uninstallCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$target\uninstall.ps1`""
$lnk = $shell.CreateShortcut((Join-Path $startMenu "$name deinstallieren.lnk"))
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$target\uninstall.ps1`""
$lnk.Save()

# Eintrag unter "Apps & Features"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$name"
New-Item -Path $key -Force | Out-Null
Set-ItemProperty $key DisplayName $name
Set-ItemProperty $key DisplayVersion $version
Set-ItemProperty $key Publisher 'Die Alte Ordnung - Stadtkarten'
Set-ItemProperty $key DisplayIcon "$exe,0"
Set-ItemProperty $key InstallLocation $target
Set-ItemProperty $key UninstallString $uninstallCmd
Set-ItemProperty $key NoModify 1 -Type DWord
Set-ItemProperty $key NoRepair 1 -Type DWord

Add-Type -AssemblyName System.Windows.Forms
$answer = [System.Windows.Forms.MessageBox]::Show(
    "$name wurde installiert.`n`nVerknüpfungen liegen auf dem Desktop und im Startmenü.`nGespeicherte Karten landen in Dokumente\Stadtkarten.`n`nJetzt starten?",
    $name, 'YesNo', 'Information')
if ($answer -eq 'Yes') { Start-Process $exe -WorkingDirectory $target }
