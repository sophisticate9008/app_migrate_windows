Option Explicit

Dim fileSystem
Dim shell
Dim projectRoot
Dim applicationPath
Dim syncExitCode

Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
applicationPath = fileSystem.BuildPath(projectRoot, ".venv\Scripts\app-migrate.exe")
shell.CurrentDirectory = projectRoot

If Not fileSystem.FileExists(applicationPath) Then
    shell.Popup "Preparing the application environment. This may take a few minutes.", 4, "App Migrate", 64
    syncExitCode = shell.Run("cmd.exe /d /c uv sync", 0, True)

    If syncExitCode <> 0 Or Not fileSystem.FileExists(applicationPath) Then
        shell.Popup "Setup failed. Install uv and double-click this launcher again.", 0, "App Migrate", 16
        WScript.Quit 1
    End If
End If

shell.Run Chr(34) & applicationPath & Chr(34), 1, False
