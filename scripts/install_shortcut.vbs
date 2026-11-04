' ------------------------------------------------------------
' Script: scripts/install_shortcut.vbs
' Purpose: Point the Start Menu shortcut at the built app, and
'          retarget an existing taskbar pin or Desktop shortcut
'          whose target is TotalCommanderClone.exe.
'          Does not create a Desktop icon.
' Usage:   cscript //nologo scripts\install_shortcut.vbs <exe>
' ------------------------------------------------------------
Option Explicit

Dim exePath, workDir, shell, fso

If WScript.Arguments.Count < 1 Then
    WScript.Echo "[ERROR] Missing path to TotalCommanderClone.exe."
    WScript.Quit 1
End If

exePath = WScript.Arguments(0)
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If Not fso.FileExists(exePath) Then
    WScript.Echo "[ERROR] Installed app not found: " & exePath
    WScript.Quit 1
End If

workDir = fso.GetParentFolderName(exePath)

Dim startMenu, startLink
startMenu = shell.ExpandEnvironmentStrings("%APPDATA%") & "\Microsoft\Windows\Start Menu\Programs"
If Not fso.FolderExists(startMenu) Then
    WScript.Echo "[ERROR] Start Menu folder not found: " & startMenu
    WScript.Quit 1
End If

startLink = startMenu & "\Total Commander Clone.lnk"
WriteLink startLink, exePath, workDir
WScript.Echo "[INFO] Start Menu shortcut: " & startLink

RetargetFolder shell.ExpandEnvironmentStrings("%APPDATA%") & "\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar", exePath, workDir
RetargetFolder shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\Desktop", exePath, workDir

' ------------------------------------------------------------
' WriteLink: Create or replace a shortcut to the built app.
' ------------------------------------------------------------
Sub WriteLink(linkPath, target, workDir)
    Dim link
    Set link = shell.CreateShortcut(linkPath)
    link.TargetPath = target
    link.WorkingDirectory = workDir
    link.WindowStyle = 1
    link.Description = "Total Commander Clone"
    link.IconLocation = target & ",0"
    link.Save
End Sub

' ------------------------------------------------------------
' RetargetFolder: Update .lnk files in one folder that already
'                 launch TotalCommanderClone.exe. Missing folders
'                 are skipped. New shortcuts are not created.
' ------------------------------------------------------------
Sub RetargetFolder(folderPath, target, workDir)
    Dim folder, file, link, targetName

    If Not fso.FolderExists(folderPath) Then
        Exit Sub
    End If

    Set folder = fso.GetFolder(folderPath)
    For Each file In folder.Files
        If LCase(fso.GetExtensionName(file.Name)) = "lnk" Then
            On Error Resume Next
            Set link = shell.CreateShortcut(file.Path)
            targetName = ""
            If Err.Number = 0 Then
                If Len(link.TargetPath) > 0 Then
                    targetName = LCase(fso.GetFileName(link.TargetPath))
                End If
            End If
            If Err.Number = 0 And targetName = "totalcommanderclone.exe" Then
                If LCase(link.TargetPath) <> LCase(target) _
                    Or LCase(link.WorkingDirectory) <> LCase(workDir) _
                    Or LCase(link.IconLocation) <> LCase(target & ",0") Then
                    link.TargetPath = target
                    link.WorkingDirectory = workDir
                    link.IconLocation = target & ",0"
                    link.Save
                    If Err.Number = 0 Then
                        WScript.Echo "[INFO] Updated shortcut: " & file.Path
                    Else
                        WScript.Echo "[WARN] Could not update shortcut: " & file.Path
                        Err.Clear
                    End If
                End If
            End If
            Err.Clear
            On Error GoTo 0
        End If
    Next
End Sub
