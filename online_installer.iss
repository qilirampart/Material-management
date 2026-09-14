[Setup]
#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
AppId={{44ED0744-4C55-4792-95D6-AD1D49B9200E}
AppName=点众素材投放助手下载器
AppVersion={#AppVersion}
AppPublisher=点众
CreateAppDir=no
Uninstallable=no
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
OutputDir=release
OutputBaseFilename=DianzhongMaterialAssistant-Downloader-{#AppVersion}
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

var
  DownloadPage: TOutputProgressWizardPage;

procedure InitializeWizard;
begin
  DownloadPage := CreateOutputProgressPage(
    '正在下载点众素材投放助手',
    '正在获取完整安装包；下载完成后将自动打开正式安装程序。'
  );
end;

function DownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then begin
    DownloadPage.SetProgress(Round(Progress * 100 / ProgressMax), 100);
    DownloadPage.SetText('正在下载完整安装包：' +
      IntToStr(Progress div 1048576) + ' / ' +
      IntToStr(ProgressMax div 1048576) + ' MB', '');
  end else
    DownloadPage.SetText('正在下载完整安装包：' +
      IntToStr(Progress div 1048576) + ' MB', '');
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
  DownloadPage.Show;
  for Attempt := 1 to 3 do begin
    try
      DownloadPage.SetText('正在下载完整安装包（第 ' + IntToStr(Attempt) + ' / 3 次）…', '');
      DownloadPage.SetProgress(0, 100);
      DownloadTemporaryFile(SetupUrl, SetupFileName, '', @DownloadProgress);
      DownloadPage.Hide;
      if not Exec(DownloadedFile, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode) then
        Result := '无法启动完整安装包。请重新下载或直接从 Release 页面下载完整安装包。';
      Exit;
    except
      LastError := GetExceptionMessage;
      if Attempt < 3 then begin
        DownloadPage.SetText('下载连接超时，正在重试…', '');
        Sleep(1500 * Attempt);
      end;
    end;
  end;
  DownloadPage.Hide;
  Result := '下载完整安装包失败（已重试 3 次）：' + LastError + '。请直接从 Release 页面下载完整安装包。';
end;
