param(
    [string]$ShortcutDirectory = [Environment]::GetFolderPath("Desktop"),
    [string]$ShortcutName = "App Migrate"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$targetPath = Join-Path $projectRoot ".venv\Scripts\app-migrate.exe"
$iconPath = Join-Path $projectRoot "src\app_migrate\resources\icons\app-migrate.ico"
$shortcutPath = Join-Path $ShortcutDirectory "$ShortcutName.lnk"

if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
    throw "Application launcher not found. Run 'uv sync' in the project first."
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
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = "Move Windows application folders to another drive using NTFS junctions."
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Output $shortcutPath
