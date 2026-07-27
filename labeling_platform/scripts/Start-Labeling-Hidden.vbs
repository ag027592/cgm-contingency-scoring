Option Explicit

Dim shell
Dim command
Dim exitCode

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\SAIL_David\Project\GCM\labeling_interface\data\labeling_platform\scripts"

command = Chr(34) & "C:\windows\System32\WindowsPowerShell\v1.0\powershell.exe" & Chr(34) & _
    " -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & _
    Chr(34) & "C:\SAIL_David\Project\GCM\labeling_interface\data\labeling_platform\scripts\start_labeling_site.ps1" & Chr(34) & _
    " -Loop"

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
