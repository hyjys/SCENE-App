# 변경 기록

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
