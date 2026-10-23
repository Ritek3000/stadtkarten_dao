# Entfernt die Stadtkarten-Werkstatt. Gespeicherte Karten in Dokumente\Stadtkarten bleiben erhalten.
$name   = 'Stadtkarten-Werkstatt'
$target = Join-Path $env:LOCALAPPDATA "Programs\$name"

# Aus dem Programmordner heraus kann der Ordner nicht gelöscht werden: Kopie im Temp-Ordner starten
if ($PSScriptRoot -eq $target) {
    $tmp = Join-Path $env:TEMP "$name-uninstall.ps1"
    Copy-Item $PSCommandPath $tmp -Force
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$tmp`"" -WorkingDirectory $env:TEMP
    exit
}

Add-Type -AssemblyName System.Windows.Forms
$answer = [System.Windows.Forms.MessageBox]::Show("$name wirklich entfernen?`n(Deine Karten in Dokumente\Stadtkarten bleiben erhalten.)",
    $name, 'YesNo', 'Question')
if ($answer -ne 'Yes') { exit }

Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500
Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) "$name.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) $name) -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$name" -Recurse -Force -ErrorAction SilentlyContinue
[System.Windows.Forms.MessageBox]::Show("$name wurde entfernt.", $name, 'OK', 'Information') | Out-Null
