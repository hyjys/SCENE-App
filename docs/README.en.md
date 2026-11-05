# SCENE App v0.5

The November performance update brings preparation and stage operation into one Windows 10/11 x64 application for the December performance: audio transport, scripts, projector video and installer updates.

Install `sceneapp-0.5-windows-x64-setup.exe`, or extract all of `scene-app.zip` to a writable folder and run `sceneapp.exe`. Keep `ffmpeg.exe` beside it. Python, Deno, fonts and viewer libraries are bundled. Web panels require **Microsoft Edge WebView2 Runtime**. If it is missing, follow the application's guidance to the [official Microsoft download page](https://developer.microsoft.com/microsoft-edge/webview2/#download-section).

## Preparation mode

Enter a cue number and title, then download a URL or convert a local file. MP3 is the default; enable the video toggle for MP4. Audio selects the highest-bitrate audio-only format and uses libmp3lame VBR 2. Video defaults to H.264 libx264, veryslow, CRF 20, with MP3 VBR 2. Global settings offer Intel Quick Sync and NVIDIA NVENC; compatible hardware and drivers are required.

`007.50` / `Opening` produces `bgm007.50_Opening.mp3` or `.mp4` in `Downloads` beside the app. Decimal numbers retain their spelling, with up to 12 digits excluding the decimal point. Duplicate names receive `(2)`, `(3)`, etc. Source files remain intact. Jobs provide progress, logs and cancellation. Network cancellation may wait for a request; site restrictions can prevent downloads. Local conversion works offline. Projector and blackout controls are provided in stage mode.

## Stage mode

Stage mode opens a maximized window. The left half loads audio and video from the selected folder **and its subfolders**. Files directly in the selected folder appear first. Subfolders appear below them in alphabetical/Korean name order; click **▶/▼** beside a folder name to expand or collapse it. Nested folders work the same way. Files within each folder use numeric cue order: bgm1, bgm2, bgm2.5, bgm10. Audio and video share the BGM numbering scheme. Each row and the current-track area provide play, pause, stop and fades. The current-track area includes seeking, elapsed/total time and volume.

Default fades are three seconds, 0→100% in and 100→0% out. Global settings define normal volume and fade duration/start/end levels. Right-click a file or use its settings button for overrides; restore global defaults to remove overrides. `.scene-audio.json` in the writable media folder stores them. Application volume does not change the system mixer.

The right half opens TXT, DOCX and PDF scripts. TXT/DOCX use CTkTextbox and python-docx. DOCX paragraph/table text and direct run emphasis/colors are imported, without reproducing Word pagination. PDF uses an adapted CTkPDFViewer/PyMuPDF widget with proportional single-page rendering, navigation and zoom. Select text or drag a PDF rectangle to add highlighting, display color or an audio cue. PDF ink recoloring is a display effect on the selected region.

Audio cues support play, pause, stop, fade in/out, volume (%) and seeking (seconds). Targets can be cue numbers or filenames; an empty target means the current track. Use **위치** to locate a cue and **GO** to execute it. Opening or scrolling a script and selecting a cue do not start playback.

Notes live beside the script in files such as `Script.docx.scene.json`. The original remains intact. Keep both files in a writable folder. If the original changes, old notes are not applied to potentially wrong offsets; a later note save backs up the previous sidecar. Returning to preparation mode stops audio and projector video while retaining the open script.

## Projector and blackout

Connect a secondary display and choose **Win+P → Extend**. The stage screen's lower-right controls offer blackout, video selection, pause, resume and stop. Video cues in the list also play on the secondary screen and use per-file volume/fades. Video fades affect image brightness and audio. Enabling blackout stops video.

The primary monitor is not covered. Internal Windows device DISPLAY2 is preferred among secondary displays; its name may differ from Settings display numbers. Move the pointer over blackout and press/release Alt+F4 to remove only the cover. Esc/clicks do not remove blackout. A disconnected blackout target is hidden until reconnection; a disconnected video target stops playback. The video window supports Esc/Alt+F4. Closing the app clears outputs.

Blackout integrates SCENE BlackScreen 1.0 behavior. Epson PJ and DDC/CI are excluded. A black image does not physically block projector light. Actual secondary-projector playback, synchronization, scaling and disconnection still need rehearsal on performance equipment; this development environment has not verified a physical projector output.

## Independent local/web sources

Set audio and script sources independently in global settings or switch either panel locally. Web panels embed **tkwebview 0.3.0 / Microsoft Edge WebView2** inside CustomTkinter. tkwebview succeeds tkwebview2 and uses Chromium's JavaScript/DOM engine to display Google Search, Docs, Drive and other websites. If Google restricts sign-in from embedded browsers, use **브라우저에서 열기** (open in browser). Missing WebView2 Runtime produces installation guidance; local features remain available.

For a Google Docs share link readable without login, **Google 대본 가져오기** downloads plain text into the local viewer for annotations/cues. It does not synchronize notes or formatting back to Google. Download private documents through a browser, then open them locally. For local transport and script cues on Drive audio, download media into the selected folder. Web-page playback buttons do not automatically control the local cue engine.

Global configuration is `%APPDATA%\SCENE App\settings.json`; imported Google scripts are in its `Google 대본` subfolder. Newly added stage controls currently use Korean labels.

## Updates and manual releases

Preparation mode can check GitHub's latest stable release on startup; disable this in settings if desired. The header offers check, download and an explicit close-and-install step. Update installation is blocked in stage mode. Downloads can be cancelled and installation never begins merely from a release check.

The updater reads `hyjys/SCENE-App` Releases and accepts `sceneapp-{version}-windows-x64.exe` and `sceneapp-{version}-windows-x64-setup.exe`. Publish numeric tags such as `v0.5` and upload the matching Inno installer manually. The official release location, declared size and available SHA-256 are checked.

`installer/sceneapp.iss` is based on the supplied v0.3 script and preserves AppId `{09594B09-BD34-4B71-90C2-2E8A1349D7B2}`, lzma2/ultra64 maximum compression, solid compression and separate LZMA process/thread settings.

## Build and sources

Use Windows x64, Python 3.15 and pinned `requirements-build.txt`/`requirements-lock.txt`. See the main README for setup. `build.ps1` builds the EXE, portable ZIP and `dist/SCENE-App-v0.5-source.zip`. `build.ps1 -BuildInstaller` also compiles `dist/sceneapp-0.5-windows-x64-setup.exe` using Inno Setup 7 or newer; `-InnoCompiler` supplies an explicit compiler path. `-IncludeDependencySources` adds the pinned PyPI source archive. Artifacts have SHA-256 files.

Run `python -m unittest discover -s tests -v` and `python tools/verify_releases.py` in the build environment. Publish corresponding project, dependency and native-component sources beside the release.

Project code is GPL-3.0-or-later. PyMuPDF/MuPDF are used under AGPL-3.0 and their conditions also apply to the combined distribution. Fonts and dependencies retain their licenses. See LICENSE, licenses/, assets/fonts/OFL.txt and THIRD_PARTY_SOURCES.md.

[Releases](https://github.com/hyjys/SCENE-App/releases/latest) · [Project](https://github.com/hyjys/SCENE-App)
