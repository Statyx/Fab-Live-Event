' CCE Validation Portal - Silent launcher
' Starts service.ps1 in a hidden window. Drop a shortcut to this file in shell:startup.
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
objShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File service.ps1", 0, False
Set objShell = Nothing
