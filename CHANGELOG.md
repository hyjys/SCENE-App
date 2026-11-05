# 변경 기록

## v0.4 — 2026-11-05

11월 공연 종료 기념 업데이트. 12월 공연부터 사용할 준비·무대 운영 기능 추가.

- 준비 모드와 최대화 창 기반 무대 모드로 구성하고 프로젝터·암전을 무대 우하단에 배치.
- BGM 번호 숫자 순 음원·영상 목록, 재생·일시정지·정지·탐색·볼륨과 오토 페이드인/아웃 추가.
- 전역 및 파일별 일반 볼륨·페이드 시간·시작/종료 비율과 설정 저장 추가.
- TXT/DOCX/PDF 대본 뷰어, 글자 크기·색·하이라이트와 원본을 보존하는 표시 파일 추가.
- 대본 범위별 오디오 큐와 명시적 GO 실행, 볼륨·재생 위치 이동 큐 지원.
- 프로젝터 영상 제어와 BGM 번호를 공유하는 MP4 준비 기능 추가.
- 영상 기본 libx264 veryslow + MP3 VBR 2, Intel Quick Sync/NVIDIA NVENC 선택 지원.
- 좌우 독립 로컬/웹 전환, TkinterWeb + PythonMonkey JavaScript와 공유 Google Docs 텍스트 가져오기 추가. Google 전체 웹 앱·로그인은 외부 브라우저로 보완.
- GitHub 최신 정식 릴리스 확인·설치 파일 다운로드·앱 종료 후 Inno 설치 추가. 기존 및 -setup 설치 파일명 모두 인식.
- 제공된 Inno 스크립트의 AppId와 lzma2/ultra64 최대 압축 설정을 유지하고 선택적 설치 파일 빌드 추가.

## v0.3 — 2026-11-05

- GUI YT-DLP Original을 제거하고 단일 SCENE App으로 개편.
- 음원 다운로드·외부 파일 MP3 변환과 블랙스크린 ON/OFF를 같은 GUI에 통합.
- 다운로드·변환 중에도 블랙스크린 조작 가능.
- SCENE BlackScreen 1.0 방식의 보조 화면 검정 덮기, 포커스 유지, 커서 숨김, Alt+F4 해제와 연결 변경 대응 적용.
- Epson PJ·DDC/CI 밝기 제어 제외.
- 실행 파일을 sceneapp.exe, 배포 ZIP을 scene-app.zip으로 변경하고 빌드·검증·문서 갱신.

## v0.2 — 2026-11-01

- GUI YT-DLP와 SCENE Audio Downloader를 CustomTkinter로 전환.
- 별도 yt-dlp.exe 대신 pip의 yt_dlp.YoutubeDL API로 조회·다운로드.
- 나눔고딕 Regular/Bold와 OFL 라이선스를 동봉하고 앱 내에서 적용.
- Windows 표시 언어에 따라 한국어·영어 자동 선택.
- SCENE 음향 번호에 소수점 허용, 앞자리·소수부 0을 포함한 입력 표기 유지.
- 형식 표의 왼쪽 선택 열 잘림과 작은 창에서의 배치 수정.
- GPLv3 소스 공개, Windows x64 실행 파일 및 검증 가능한 배포 ZIP 제공.
- 정확한 형식 선택, MP3/MP4 변환, SCENE 큐 이름, 취소·진행 표시 유지.
