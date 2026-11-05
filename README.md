# SCENE App v0.4

11월 공연 종료를 기념해 준비와 무대 운영을 한 앱에 담았습니다. 12월 공연부터 사용할 음향 제어반, 대본 뷰어, 프로젝터 제어와 설치형 업데이트를 추가했습니다. Windows 10/11 x64용입니다.

[최신 릴리스](https://github.com/hyjys/SCENE-App/releases/latest) · [변경 기록](CHANGELOG.md) · [사용법](docs/SCENE-사용법.txt) · [English](docs/README.en.md)

## 설치와 실행

릴리스의 `sceneapp-0.4-windows-x64-setup.exe`를 실행해 사용자 계정에 설치하거나, `scene-app.zip` 전체를 쓰기 가능한 폴더에 풀고 `sceneapp.exe`를 실행합니다. `ffmpeg.exe`는 실행 파일과 같은 폴더에 둡니다. 배포본에는 Python, Deno, 문서·웹 라이브러리와 나눔고딕이 포함됩니다.

```text
SCENE-App/
  sceneapp.exe
  ffmpeg.exe
  assets/fonts/
  licenses/
  docs/
  사용법.txt
  README.en.md
  LICENSE
  THIRD_PARTY_SOURCES.md
  manifest.json                 # 파일별 크기·SHA-256, 의존성 버전
  Downloads/                    # 저장할 때 생성
```

상단에서 **준비 모드 / 무대 모드**를 선택합니다. 무대 모드는 최대화 창으로 열립니다. 준비 모드로 돌아오면 음원과 프로젝터 영상이 정지합니다. 진행 중인 준비 작업이나 업데이트 다운로드는 먼저 완료하거나 취소하세요.

## 준비 모드

1. 음향 번호와 제목을 입력합니다.
2. 링크 다운로드 또는 파일 변환을 선택하고 주소나 파일을 지정합니다.
3. 기본은 MP3입니다. 영상이 필요하면 **영상으로 다운로드 / 변환**을 켭니다.
4. 실행 버튼을 누르고 실행 파일 옆 `Downloads`에서 결과를 확인합니다.

번호 `7.5`, 제목 `전환`은 `bgm7.5_전환.mp3` 또는 `bgm7.5_전환.mp4`로 저장합니다. 번호는 소수점 제외 최대 12자리이며 `007.50`처럼 입력한 표기를 유지합니다. 같은 이름이 있으면 `(2)` 등을 붙입니다. 외부 파일 변환도 원본을 보존합니다.

MP3는 오디오 전용 형식 중 최고 비트레이트를 선택해 **libmp3lame VBR 2**로 변환합니다. 영상 기본은 **H.264 libx264 / veryslow / CRF 20 + MP3 VBR 2**의 MP4입니다. 앱 설정에서 인코더·속도 프리셋을 바꿀 수 있으며 **Intel Quick Sync(h264_qsv) / NVIDIA NVENC(h264_nvenc)**도 제공합니다. GPU 인코딩에는 지원 장치와 드라이버가 필요합니다.

로그와 취소 버튼을 제공합니다. 네트워크 요청 중에는 취소 반영까지 잠시 걸릴 수 있습니다. 사이트 로그인·접근 제한에 따라 다운로드가 실패할 수 있으며 재생목록에서도 한 항목만 처리합니다. 파일 변환은 오프라인으로 가능합니다.

## 무대 모드: 음향 제어반

왼쪽에서 음원·영상을 모아 둔 폴더를 선택합니다. `bgm1`, `bgm2`, `bgm2.5`, `bgm10` 순으로 번호를 숫자로 정렬하며 영상도 같은 번호 체계를 사용합니다. 목록은 스크롤할 수 있습니다.

각 행과 하단 현재 재생 영역에서 **재생 / 일시정지 / 정지 / 오토 페이드인 / 오토 페이드아웃**을 조작합니다. 하단에는 재생 위치·전체 시간, 탐색 바와 볼륨이 있습니다. 앱의 재생 볼륨을 조절하며 Windows 전체 볼륨을 바꾸지 않습니다.

기본 페이드인은 **3초, 0% → 100%**, 페이드아웃은 **3초, 100% → 0%**입니다. **앱 설정**에서 일반 재생 볼륨과 페이드 시간·시작·종료 볼륨의 전역 기본값을 정합니다. 음원을 우클릭하거나 **음원 설정**을 눌러 해당 파일만 다른 값을 지정합니다. **전역 기본값 사용**으로 개별 설정을 해제합니다.

개별 설정은 음원 폴더의 `.scene-audio.json`에 저장합니다. 설정을 보관하려면 폴더 쓰기 권한이 필요합니다. 공연 자료를 옮길 때 함께 옮기세요.

## 무대 모드: 대본과 오디오 하이라이팅

오른쪽에서 **TXT / DOCX / PDF**를 엽니다. TXT·DOCX는 `CTkTextbox`, DOCX 읽기는 `python-docx`를 사용합니다. DOCX의 문단·표 텍스트와 직접 지정된 굵기·기울임·글자색·하이라이트를 가져오며 Word 페이지 배치는 재현하지 않습니다. PDF는 **CTkPDFViewer 구조를 보완한 내장 뷰어 + PyMuPDF**로 한 쪽씩 표시하고 페이지 비율을 유지합니다.

- **A− / A+**: 텍스트 글자 크기 또는 PDF 확대율을 바꿉니다.
- **형광펜 / 글자색**: 텍스트를 선택하거나 PDF에서 사각형을 드래그해 표시합니다. PDF 색 변경은 선택 영역의 화면 표시 효과입니다.
- **♪ 오디오 큐 추가**: 선택한 대사 또는 PDF 영역에 BGM 번호·파일명과 동작을 연결합니다. PDF는 현재 쪽에도 큐를 추가할 수 있습니다.
- 지원 동작은 **재생, 일시정지, 정지, 페이드인, 페이드아웃, 볼륨(%), 재생 위치(초)**입니다. 대상을 비우면 현재 음원에 적용합니다.
- **위치**로 연결 지점을 확인하고 **GO**로 실행합니다. 문서를 열거나 스크롤하거나 큐를 선택하는 것만으로 소리가 나지는 않습니다.

표시와 큐는 `대본.docx.scene.json`처럼 원본 옆 파일에 자동 저장합니다. TXT·DOCX·PDF 원본은 수정하지 않습니다. 대본 폴더에 쓰기 권한이 필요하며 원본과 표시 파일을 함께 보관하세요. 원본이 바뀌면 잘못된 글자 위치에 적용하지 않도록 이전 표시를 자동 적용하지 않습니다. 이후 새 표시 저장 전에 이전 표시 파일을 백업합니다.

## 프로젝터

Windows에서 **Win+P → 확장**을 선택하고 보조 화면을 연결합니다. 무대 모드 **우하단**에서 암전 ON/OFF, 영상 열기, 일시정지·재개·정지를 조작합니다. 목록의 영상도 프로젝터로 출력하며 개별 볼륨·페이드 설정을 사용합니다. 영상 페이드는 화면 밝기와 음량에 적용합니다. 암전을 켜면 영상을 정지합니다.

주 모니터는 덮지 않고 비주 모니터 중 Windows 내부 장치명 `DISPLAY2`를 우선합니다. 내부 이름은 설정의 식별 번호와 다를 수 있습니다. 보조 화면이 없으면 확장 설정 안내를 표시합니다.

프로젝터·암전 제어는 무대 모드 우하단에 있습니다. 검은 화면으로 마우스를 옮기고 **Alt+F4를 눌렀다 놓으면** 블랙스크린만 해제합니다. 블랙스크린은 Esc·클릭으로 해제하지 않습니다. 연결이 끊기면 검은 창을 숨기고 재연결을 기다립니다. 영상 창은 Esc/Alt+F4로 닫을 수 있고 화면 연결이 끊기면 정지합니다. 앱 종료 시 출력도 정리합니다.

SCENE BlackScreen 1.0의 화면 덮기 동작을 통합했으며 Epson PJ·DDC/CI 제어는 포함하지 않습니다. 검정 화면은 프로젝터 전원을 끄거나 광원을 물리적으로 차단하지 않습니다. 실제 공연 장비에서 영상·음향 동기와 연결 변경을 리허설로 확인하세요. 이 개발 환경에서는 실제 보조 프로젝터 출력을 검증하지 않았습니다.

## 로컬 / 웹·Google을 섞어 사용하기

**앱 설정**에서 음향과 대본 소스를 각각 `local` 또는 `web`으로 지정하고 주소를 저장합니다. 각 패널에서도 로컬/웹 화면을 전환할 수 있어 한쪽만 웹으로 사용할 수 있습니다. 웹 주소를 입력하고 **열기**를 누르면 CustomTkinter 프레임 안의 **TkinterWeb**으로 표시합니다.

`tkinterweb[recommended,javascript]`와 **PythonMonkey 1.4.1 / SpiderMonkey**로 JavaScript를 활성화합니다. 기본 JavaScript·DOM 처리는 확인했지만 전체 브라우저와 같은 웹 기능을 제공하지는 않습니다. Google 로그인, Docs 전체 편집기와 Drive 미디어 기능은 동작하지 않을 수 있습니다. 이 경우 **브라우저에서 열기**를 사용합니다.

로그인 없이 읽을 수 있는 Google Docs 공유 링크는 **Google 대본 가져오기**로 텍스트를 내려받아 로컬 뷰어에서 표시·큐를 설정할 수 있습니다. Docs 서식을 가져오거나 Google 원본에 표시를 쓰지는 않습니다. 로그인 전용 문서는 브라우저에서 내려받아 여세요. Drive 음원을 로컬 제어반·대본 큐로 운영하려면 내려받아 음원 폴더에서 선택하세요. 웹 패널의 재생 버튼은 로컬 큐와 자동 연동하지 않습니다.

전역 설정은 `%APPDATA%\SCENE App\settings.json`, 가져온 Google 대본은 그 아래 `Google 대본`에 저장합니다.

## 자동 업데이트와 수동 릴리스

준비 모드 시작 시 최신 정식 릴리스를 확인하며 앱 설정에서 자동 확인을 끌 수 있습니다. 상단 **업데이트 확인 → 업데이트 다운로드 → 앱 종료 후 설치** 순서로 진행합니다. 무대 모드에서는 업데이트를 설치하지 않습니다. 다운로드를 취소할 수 있으며 실제 설치는 버튼을 눌렀을 때 시작합니다.

업데이터는 `hyjys/SCENE-App`의 최신 정식 GitHub Release에서 다음 이름을 인식합니다. 태그는 `v0.4`와 같은 숫자 버전을 사용합니다.

- `sceneapp-{version}-windows-x64.exe`
- `sceneapp-{version}-windows-x64-setup.exe` — 이 저장소의 Inno 출력

Inno 설치 파일을 직접 빌드하고 Releases에 올리는 방식을 유지할 수 있습니다. 새 버전의 설치 파일이 없으면 안내 후 나중에 다시 확인합니다. 공식 자산 주소·크기와 제공된 SHA-256을 검사합니다.

`installer/sceneapp.iss`는 제공된 v0.3 스크립트를 바탕으로 **AppId `{09594B09-BD34-4B71-90C2-2E8A1349D7B2}`**, **lzma2/ultra64 최대 압축**, solid compression, 별도 LZMA 프로세스·블록 스레드 설정을 유지합니다.

## 소스 실행 및 재빌드

Windows x64, Python 3.15, PyInstaller 6.22.3을 사용합니다. 버전은 `requirements-lock.txt`로 고정합니다.

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt -r requirements-lock.txt
.\.venv\Scripts\python.exe tools\fetch_runtime.py
.\.venv\Scripts\python.exe tools\fetch_ffmpeg.py
.\.venv\Scripts\python.exe scene_app.py

# EXE·배포 ZIP·프로젝트 소스 ZIP
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
# Inno Setup 7 이상으로 설치 EXE도 생성
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -BuildInstaller
# 의존성 원본 소스 ZIP도 생성
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -BuildInstaller -IncludeDependencySources
# 필요하면 -InnoCompiler 'C:\...\ISCC.exe' 지정

.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\verify_releases.py
```

출력은 `sceneapp.exe`, `dist/scene-app.zip`, `dist/SCENE-App-v0.4-source.zip`과 SHA-256 파일입니다. `-BuildInstaller`는 `dist/sceneapp-0.4-windows-x64-setup.exe`와 SHA-256을 추가합니다. `-IncludeDependencySources`는 고정된 PyPI 소스 묶음을 만듭니다. 릴리스에는 바이너리와 해당 프로젝트·의존성 및 네이티브 구성요소의 대응 소스를 함께 제공하세요.

## 라이선스와 소스

Copyright (C) 2026 hyjys. 프로젝트 코드는 **GPL-3.0-or-later**입니다. PyMuPDF/MuPDF는 **AGPL-3.0** 조건으로 사용하며 결합 배포에는 해당 조건도 적용됩니다. 폰트·외부 구성요소는 각자의 라이선스를 유지합니다. 원문과 대응 소스·재빌드 안내는 [LICENSE](LICENSE), `licenses/`, [THIRD_PARTY_SOURCES.md](THIRD_PARTY_SOURCES.md)에 있습니다. 사용 권한이 있는 콘텐츠에 사용하세요.
