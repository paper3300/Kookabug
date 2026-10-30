; Kookabug 설치 파일 (구현 계획 M1 2.12). 직접 iscc로 빌드하지 않는다 — tools/installer/build.py가
; 스테이징 폴더를 만들고 정의를 넘긴다:
;   iscc /DAppVersion=0.1.0.dev0 /DFileVersion=0.1.0.0 /DStageDir=<스테이징> /DOutputDir=<출력 폴더>
;        /DOutputBase=<설치 파일 이름> /DMaxRelPath=<설치 폴더 기준 가장 긴 상대 경로 길이>
;        /DAppGuid=<AppId GUID> /DAppName=<이름> /DDirName=<기본 설치 폴더 이름> kookabug.iss
; 이 파일은 UTF-8 BOM으로 저장한다 (iscc가 [Code]의 한국어 문자열을 UTF-8로 읽게)
;
; - 판은 둘이다(build.py VARIANTS): 제품(Kookabug)과 테스트 전용(Kookabug Test). 테스트 판은 AppId·
;   이름·기본 폴더·제거 등록 이름이 모두 달라 자동 검사가 실제 설치를 건드리지 않는다
; - 사용자별 설치(관리자 권한 없음): %LOCALAPPDATA%\Programs\<DirName>, 사용자 PATH에 bin, 제거 등록
; - 스테이징 폴더가 곧 설치 폴더 구조다. 실행기(bin\kookabug.exe)는 Python 경로를 상대 경로로 담고
;   있어 설치 뒤에 고치는 단계가 없다
; - 제거는 설치한 폴더만 지운다 (예제 실행 기록 runs\·.kookabug\ 포함)

#ifndef AppVersion
  #error AppVersion이 없다. tools/installer/build.py로 빌드한다
#endif
#ifndef MaxRelPath
  #error MaxRelPath가 없다. tools/installer/build.py로 빌드한다
#endif
#ifndef AppGuid
  #error AppGuid가 없다. tools/installer/build.py로 빌드한다
#endif
; Windows 경로 한도 (MAX_PATH 260, 끝 NUL 제외)
#define PathLimit 259

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kookabug contributors
VersionInfoVersion={#FileVersion}
; 스모크는 설치 파일의 ProductName으로 판을 가린다 (smoke.setup_product_name)
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#DirName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows Graphics Capture 창 캡처는 Windows 10 1903부터
MinVersion=10.0.18362
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ChangesEnvironment=yes
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
SetupLogging=yes
ShowLanguageDialog=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; 설치 뒤 생기는 파일(실행 기록, Python이 다시 쓰는 __pycache__, 예제 local.json)까지 지운다
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\examples"
Type: filesandordirs; Name: "{app}\licenses"
Type: filesandordirs; Name: "{app}\ocr-models"
Type: filesandordirs; Name: "{app}\python"

[Code]
const
  EnvKey = 'Environment';

function BinDir(): String;
begin
  Result := ExpandConstant('{app}\bin');
end;

function SamePath(A, B: String): Boolean;
begin
  Result := (CompareText(RemoveBackslashUnlessRoot(A), RemoveBackslashUnlessRoot(B)) = 0);
end;

function PathHas(Paths, Dir: String): Boolean;
var
  Rest, Item: String;
  P: Integer;
begin
  Result := False;
  Rest := Paths;
  while Rest <> '' do
  begin
    P := Pos(';', Rest);
    if P = 0 then
    begin
      Item := Rest;
      Rest := '';
    end
    else
    begin
      Item := Copy(Rest, 1, P - 1);
      Rest := Copy(Rest, P + 1, Length(Rest));
    end;
    if (Item <> '') and SamePath(Item, Dir) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

{ 사용자 PATH 끝에 bin을 더한다 (이미 있으면 그대로) }
procedure AddToPath(Dir: String);
var
  Paths: String;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
    Paths := '';
  if PathHas(Paths, Dir) then
    Exit;
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then
    Paths := Paths + ';';
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths + Dir);
end;

{ 사용자 PATH에서 bin 항목만 뺀다. 다른 항목은 순서·모양 그대로 둔다 }
procedure RemoveFromPath(Dir: String);
var
  Paths, Rest, Item, Kept: String;
  P: Integer;
  Found: Boolean;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
    Exit;
  Rest := Paths;
  Kept := '';
  Found := False;
  while Rest <> '' do
  begin
    P := Pos(';', Rest);
    if P = 0 then
    begin
      Item := Rest;
      Rest := '';
    end
    else
    begin
      Item := Copy(Rest, 1, P - 1);
      Rest := Copy(Rest, P + 1, Length(Rest));
    end;
    if (Item <> '') and SamePath(Item, Dir) then
      Found := True
    else if Item <> '' then
    begin
      if Kept <> '' then
        Kept := Kept + ';';
      Kept := Kept + Item;
    end;
  end;
  if not Found then
    Exit;
  if Kept = '' then
    RegDeleteValue(HKCU, EnvKey, 'Path')
  else
    RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Kept);
end;

function JsonPath(Path: String): String;
begin
  Result := Path;
  StringChangeEx(Result, '\', '/', True);
end;

{ 예제 워크스페이스의 사람마다 다른 설정: 예제 게임을 띄울 Python = 동봉 Python }
procedure WriteExampleLocal();
var
  Lines: TArrayOfString;
  Folder: String;
begin
  Folder := ExpandConstant('{app}\examples\sample-game\workspace\.kookabug');
  if not ForceDirectories(Folder) then
    Exit;
  SetArrayLength(Lines, 7);
  Lines[0] := '{';
  Lines[1] := '  "format": "kookabug.local/0",';
  Lines[2] := '  "settings": {';
  Lines[3] := '    "game.cwd": "' + JsonPath(ExpandConstant('{app}\examples\sample-game')) + '",';
  Lines[4] := '    "game.executable": "' + JsonPath(ExpandConstant('{app}\python\python.exe')) + '"';
  Lines[5] := '  }';
  Lines[6] := '}';
  SaveStringsToUTF8FileWithoutBOM(Folder + '\local.json', Lines, False);
end;

{ 설치 폴더 + 가장 긴 상대 경로가 MAX_PATH를 넘으면 파일을 복사하다 중간에 실패하고 되돌린다.
  복사를 시작하기 전에 사유를 알리고 멈춘다 (무인 설치에서도 이 문구로 끝난다) }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Room: Integer;
begin
  Result := '';
  Room := {#PathLimit} - {#MaxRelPath} - 1;
  if Length(ExpandConstant('{app}')) > Room then
    Result := '설치 폴더 경로가 너무 길다 (' + IntToStr(Length(ExpandConstant('{app}'))) +
      '자, 최대 ' + IntToStr(Room) + '자). 더 짧은 폴더를 고른다.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    AddToPath(BinDir());
    WriteExampleLocal();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveFromPath(BinDir());
end;
