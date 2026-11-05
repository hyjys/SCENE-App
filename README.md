# SCENE App v0.3

Windows x64용 공연 준비 도구입니다. 음원 다운로드·MP3 변환과 보조 화면 블랙스크린을 한 창에서 사용합니다. v0.3부터 기존 GUI YT-DLP Original 배포를 종료하고 SCENE App으로 통합합니다.

[릴리스 다운로드](https://github.com/hyjys/SCENE-App/releases/latest) · [v0.3 소스](https://github.com/hyjys/SCENE-App/tree/v0.3)

## 다운로드 및 실행

`scene-app.zip` 전체를 쓰기 가능한 폴더에 압축 해제한 뒤 `sceneapp.exe`를 실행하세요. Windows 10/11 x64에서 사용하며 Python·pip·Deno를 따로 설치할 필요가 없습니다. FFmpeg는 실행 파일과 같은 폴더에 둡니다.

```text
SCENE-App/
  sceneapp.exe
  ffmpeg.exe
  assets/fonts/                 # 나눔고딕 Regular/Bold, OFL.txt
  licenses/                     # 동봉 구성요소 라이선스
  사용법.txt
  README.en.md
  LICENSE
  THIRD_PARTY_SOURCES.md
  manifest.json                 # 파일별 크기·SHA-256, 의존성 버전
  Downloads/                    # 저장할 때 자동 생성
```

Windows 표시 언어가 한국어이면 한국어, 그 외에는 영어 UI로 실행됩니다. 동봉된 나눔고딕은 앱 실행 중 등록하므로 별도로 설치할 필요가 없습니다.

## 음원 다운로드·변환

1. 음향 번호와 제목을 입력합니다.
2. 링크 다운로드 또는 파일 변환을 선택합니다.
3. 링크를 붙여넣거나 파일을 고른 뒤 실행 버튼을 누릅니다.
4. 실행 파일 옆 `Downloads` 폴더에서 MP3를 확인합니다.

링크는 오디오 전용 형식 중 비트레이트가 가장 높은 형식을 자동 선택합니다. 외부 음원·영상 파일은 첫 번째 오디오 트랙을 MP3로 변환하며 원본을 보존합니다. 두 방식 모두 `libmp3lame -q:a 2` (VBR 2)를 사용합니다.

번호 `7`, 제목 `오프닝` → `bgm7_오프닝.mp3`로 저장합니다. `7.5` 같은 소수점 번호와 `007.50`처럼 입력한 표기를 지원합니다. 같은 이름이 있으면 `(2)` 등을 붙여 기존 파일을 보존합니다.

작업 로그에서 진행 상황과 오류를 확인하고 **취소**로 중단할 수 있습니다. 네트워크 응답 중에는 취소 반영까지 잠시 걸릴 수 있습니다. 사이트 로그인·접근 제한으로 다운로드가 실패할 수 있으며, 재생목록 링크에서도 영상 한 개만 처리합니다. 파일 변환은 오프라인으로 사용할 수 있습니다.

## 블랙스크린 ON/OFF

프로젝터나 보조 모니터를 연결한 뒤 Windows의 **Win+P → 확장**을 선택합니다. SCENE App의 **블랙스크린 ON** 버튼으로 보조 화면 한 대를 검정(RGB 0,0,0) 전체화면으로 덮고 **블랙스크린 OFF** 버튼으로 해제합니다. 다운로드·변환 중에도 조작할 수 있습니다.

- 주 모니터는 덮지 않습니다. 보조 화면이 없으면 확장 설정 안내를 표시합니다.
- 비주 모니터 중 Windows 내부 장치명 `DISPLAY2`를 우선 사용합니다. 내부 이름은 설정 화면의 식별 번호와 다를 수 있습니다.
- 검은 창은 테두리·글자·버튼 없이 표시하며 기존 음향 프로그램의 포커스를 빼앗지 않습니다. 검은 화면 안에서는 커서를 숨깁니다.
- 마우스를 검은 화면 쪽으로 옮기고 **Alt+F4**를 눌렀다 놓아도 블랙스크린만 해제할 수 있습니다. Esc·클릭·더블클릭은 해제하지 않습니다.
- 연결이 끊기면 검은 창을 숨기고 재연결을 기다립니다. 앱을 종료하면 블랙스크린도 정리합니다.
- 활성화 중에는 Windows에 화면·시스템 절전 방지를 요청합니다.

SCENE BlackScreen 1.0의 화면 덮기 동작을 통합했습니다. Epson PJ 제어·DDC/CI 밝기 조절은 포함하지 않으며, 디스플레이 전원·오디오 출력·볼륨을 바꾸지 않습니다. 검정 화면 표시만으로 프로젝터의 빛이 완전히 차단되는 것은 아닙니다.

## 소스 실행 및 재빌드

Windows x64, Python 3.15, PyInstaller 6.22.3을 사용합니다. 설치·빌드에는 인터넷 연결이 필요하며 런타임 버전은 `requirements-lock.txt`로 고정합니다.

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt -r requirements-lock.txt
.\.venv\Scripts\python.exe tools\fetch_runtime.py
.\.venv\Scripts\python.exe tools\fetch_ffmpeg.py
.\.venv\Scripts\python.exe scene_app.py

# SCENE App EXE·배포 ZIP·소스 ZIP
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1

# 단위·GUI·FFmpeg·로컬 HTTP 다운로드 검사
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# Python/Deno 없는 PATH 환경에서 ZIP 안의 EXE 검사
.\.venv\Scripts\python.exe tools\verify_releases.py
# 고정된 Python 의존성 원본 소스 묶음
.\.venv\Scripts\python.exe tools\package_dependency_sources.py
```

`build.ps1`은 `dist/scene-app.zip`과 재빌드 가능한 `dist/SCENE-App-v0.3-source.zip` 및 각각의 SHA-256 파일을 만듭니다. 소스 ZIP은 `.git`·가상환경·실행 파일·다운로드 결과를 제외하고 코드·테스트·문서·폰트·빌드 스크립트와 FFmpeg 소스 자료를 담습니다.

CustomTkinter 테마·폰트, `yt_dlp.YoutubeDL` API, EJS 스크립트와 Deno를 실행 파일에 포함합니다. `yt-dlp.exe`·`ffprobe.exe`는 필요하지 않습니다. 의존성을 업데이트하려면 버전을 변경하고 EXE를 다시 빌드하세요.

## 라이선스와 소스

Copyright (C) 2026 hyjys. 프로젝트 코드는 **GPL-3.0-or-later**로 배포합니다. 자세한 내용과 보증 부인은 [LICENSE](LICENSE)를 참고하세요. 폰트·외부 구성요소는 각자의 라이선스를 유지합니다. 버전·소스·재빌드 안내는 [THIRD_PARTY_SOURCES.md](THIRD_PARTY_SOURCES.md)에 있습니다.

사용 권한이 있는 콘텐츠에 사용하세요. 자세한 조작법은 [사용법](docs/SCENE-사용법.txt)을 참고하세요.
