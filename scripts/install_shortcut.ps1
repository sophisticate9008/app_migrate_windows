param(
    [string]$ShortcutDirectory = [Environment]::GetFolderPath("Desktop"),
    [string]$ShortcutName = "App Migrate"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $projectRoot "启动应用迁移工具.vbs"
$targetPath = Join-Path $env:SYSTEMROOT "System32\wscript.exe"
$iconPath = Join-Path $projectRoot "src\app_migrate\resources\icons\app-migrate.ico"
$shortcutPath = Join-Path $ShortcutDirectory "$ShortcutName.lnk"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Portable application launcher not found: $launcherPath"
}

if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Application icon not found: $iconPath"
}

if (-not (Test-Path -LiteralPath $ShortcutDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = "`"$launcherPath`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = "Move Windows application folders to another drive using NTFS junctions."
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Output $shortcutPath
