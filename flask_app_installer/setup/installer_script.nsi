Outfile "FlaskAppInstaller.exe"
InstallDir "$PROGRAMFILES\MyFlaskApp"
RequestExecutionLevel admin

; Metadata (optional but good)
Name "My Flask App"
InstallDirRegKey HKCU "Software\MyFlaskApp" "Install_Dir"

; ------------------------
Section "Install"
  SetOutPath $INSTDIR
  File /r "..\dist\FlaskDesktopApp.exe"
  File "..\setup\run_app.vbs"
  File "..\setup\icon.ico"

  ; Create shortcuts
  CreateShortCut "$DESKTOP\My Flask App.lnk" "$INSTDIR\run_app.vbs" "" "$INSTDIR\icon.ico"
  CreateDirectory "$SMPROGRAMS\My Flask App"
  CreateShortCut "$SMPROGRAMS\My Flask App\My Flask App.lnk" "$INSTDIR\run_app.vbs" "" "$INSTDIR\icon.ico"
  CreateShortCut "$SMPROGRAMS\My Flask App\Uninstall.lnk" "$INSTDIR\uninstall.exe" "" "$INSTDIR\icon.ico"

  ; Write uninstaller to app directory
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Optional: save install path to registry
  WriteRegStr HKCU "Software\MyFlaskApp" "Install_Dir" "$INSTDIR"

SectionEnd

; ------------------------
Section "Uninstall"
  Delete "$INSTDIR\FlaskDesktopApp.exe"
  Delete "$INSTDIR\run_app.vbs"
  Delete "$INSTDIR\icon.ico"
  Delete "$INSTDIR\uninstall.exe"

  ; Remove shortcuts
  Delete "$DESKTOP\My Flask App.lnk"
  Delete "$SMPROGRAMS\My Flask App\My Flask App.lnk"
  Delete "$SMPROGRAMS\My Flask App\Uninstall.lnk"
  RMDir "$SMPROGRAMS\My Flask App"

  ; Remove directory
  RMDir "$INSTDIR"

  ; Clean registry
  DeleteRegKey HKCU "Software\MyFlaskApp"

SectionEnd
