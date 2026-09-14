[Setup]
#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
AppId={{44ED0744-4C55-4792-95D6-AD1D49B9200E}
AppName=点众素材投放助手在线安装器
AppVersion={#AppVersion}
AppPublisher=点众
CreateAppDir=no
Uninstallable=no
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
OutputDir=release
OutputBaseFilename=DianzhongMaterialAssistant-OnlineInstaller-{#AppVersion}
SetupIconFile=assets\icons\app-icon.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimp"; MessagesFile: "assets\installer\ChineseSimplified.isl"

[Code]
const
  SetupFileName = 'DianzhongMaterialAssistant-Setup-{#AppVersion}.exe';
  SetupUrl = 'https://github.com/qilirampart/Material-management/releases/download/v{#AppVersion}/DianzhongMaterialAssistant-Setup-{#AppVersion}.exe';

function DownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then begin
    WizardForm.ProgressGauge.Max := 100;
    WizardForm.ProgressGauge.Position := Round(Progress * 100 / ProgressMax);
    WizardForm.StatusLabel.Caption := '正在下载完整安装包：' +
      IntToStr(Progress div 1048576) + ' / ' +
      IntToStr(ProgressMax div 1048576) + ' MB';
  end else
    WizardForm.StatusLabel.Caption := '正在下载完整安装包：' +
      IntToStr(Progress div 1048576) + ' MB';
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  DownloadedFile: String;
  Attempt: Integer;
  LastError: String;
begin
  Result := '';
  DownloadedFile := ExpandConstant('{tmp}\') + SetupFileName;
  for Attempt := 1 to 3 do begin
    try
      WizardForm.StatusLabel.Caption := '正在下载完整安装包（第 ' + IntToStr(Attempt) + ' / 3 次）…';
      WizardForm.ProgressGauge.Position := 0;
      DownloadTemporaryFile(SetupUrl, SetupFileName, '', @DownloadProgress);
      if not Exec(DownloadedFile, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode) then
        Result := '无法启动完整安装包。请重新下载或直接从 Release 页面下载完整安装包。';
      Exit;
    except
      LastError := GetExceptionMessage;
      if Attempt < 3 then begin
        WizardForm.StatusLabel.Caption := '下载连接超时，正在重试…';
        Sleep(1500 * Attempt);
      end;
    end;
  end;
  Result := '下载完整安装包失败（已重试 3 次）：' + LastError + '。请直接从 Release 页面下载完整安装包。';
end;
