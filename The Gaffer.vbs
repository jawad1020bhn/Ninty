' Starts The Gaffer without a console window (the app opens in its own window).
' pc186: if The Gaffer is already running, only its window is opened (nothing is killed).
' After an update (new version on disk) the old app is asked to close, then the new one starts.
' If Python is missing it opens The Gaffer.bat instead, which offers to install it.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir

Function Http(method, path)
    Http = ""
    On Error Resume Next
    Set x = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    x.setTimeouts 800, 800, 1500, 1500
    x.open method, "http://127.0.0.1:8766" & path, False
    x.setRequestHeader "X-Gaffer", "1"
    x.setRequestHeader "Content-Type", "application/json"
    x.send "{}"
    If Err.Number = 0 Then
        If x.status = 200 Then Http = x.responseText
    End If
    On Error GoTo 0
End Function

Function DiskVersion()
    DiskVersion = ""
    On Error Resume Next
    Set f = fso.OpenTextFile(dir & "\server.py", 1)
    For i = 1 To 60
        If f.AtEndOfStream Then Exit For
        ln = f.ReadLine
        p = InStr(ln, "APP_VERSION = '")
        If p > 0 Then
            DiskVersion = Mid(ln, p + 15, InStr(p + 15, ln, "'") - p - 15)
            Exit For
        End If
    Next
    f.Close
    On Error GoTo 0
End Function

' First start: create "The Gaffer" shortcuts with the logo (in this folder and on the Desktop)
On Error Resume Next
ico = dir & "\TheGaffer.ico"
If Not fso.FileExists(ico) Then ico = dir & "\Karijera.ico"
If fso.FileExists(ico) Then
    For Each lnkDir In Array(dir, sh.SpecialFolders("Desktop"))
        lnk = lnkDir & "\The Gaffer.lnk"
        If lnkDir <> "" And Not fso.FileExists(lnk) Then
            Set sc = sh.CreateShortcut(lnk)
            sc.TargetPath = sh.ExpandEnvironmentStrings("%WINDIR%") & "\System32\wscript.exe"
            sc.Arguments = """" & WScript.ScriptFullName & """"
            sc.WorkingDirectory = dir
            sc.IconLocation = ico & ",0"
            sc.Description = "The Gaffer"
            sc.Save
        End If
    Next
End If
On Error GoTo 0

running = Http("GET", "/api/version")
If running <> "" Then
    If InStr(running, """thegaffer""") > 0 And InStr(running, """code""") > 0 Then
        ' pc316+: server.py itself compares the code on disk with the running app:
        ' same code = only its window opens, changed code (update or edited files) = the old app closes first
    ElseIf InStr(running, """thegaffer""") > 0 Then
        dv = DiskVersion()
        If dv = "" Or InStr(running, """" & dv & """") > 0 Then
            Http "GET", "/api/show"
            WScript.Quit
        End If
        ' older version of The Gaffer is running: ask it to close
        Http "POST", "/api/quit"
        For i = 1 To 20
            WScript.Sleep 300
            If Http("GET", "/api/version") = "" Then Exit For
        Next
    ElseIf InStr(running, """version""") > 0 And InStr(running, """built""") > 0 Then
        ' The Gaffer before pc186 (no quit command): stop only that app
        sh.Run "powershell -NoProfile -WindowStyle Hidden -Command ""Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 4 } | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }""", 0, True
    Else
        MsgBox "Port 8766 is used by another program, so The Gaffer cannot start. Close that program and try again.", 48, "The Gaffer"
        WScript.Quit
    End If
End If

py = ""
If fso.FileExists(dir & "\python\python.exe") Then
    py = """" & dir & "\python\python.exe"""
ElseIf sh.Run("cmd /c python -c ""import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)""", 0, True) = 0 Then
    py = "python"
ElseIf sh.Run("cmd /c py -3 -c ""import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)""", 0, True) = 0 Then
    py = "py -3"
End If
If py = "" Then
    bat = dir & "\The Gaffer.bat"
    If Not fso.FileExists(bat) Then bat = dir & "\The Gaffer.bat"
    sh.Run """" & bat & """", 1, False
    WScript.Quit
End If
' cmd /c strips the first and last quote, so the whole command gets one extra pair of quotes (fix by Michele)
' pc323: an app that is still running keeps career.log open, and then cmd could not redirect the new app's output
' (it silently did not start). Use a free log file and unbuffered output (-u) so errors are visible.
logf = ""
For Each nm In Array("career.log", "career2.log", "career3.log")
    On Error Resume Next
    Err.Clear
    Set tf = fso.OpenTextFile(dir & "\" & nm, 2, True)
    If Err.Number = 0 Then
        tf.Close
        logf = dir & "\" & nm
    End If
    On Error GoTo 0
    If logf <> "" Then Exit For
Next
If logf = "" Then logf = sh.ExpandEnvironmentStrings("%TEMP%") & "\thegaffer.log"
sh.Run "cmd /c """ & py & " -u """ & dir & "\server.py"" --port 8766 > """ & logf & """ 2>&1""", 0, False
