# SCENE App v0.3

A portable Windows 10/11 x64 tool for stage audio preparation and secondary-screen blackout. SCENE App replaces the separate GUI YT-DLP Original application in v0.3.

Extract all of `scene-app.zip` to a writable folder and run `sceneapp.exe`. Keep `ffmpeg.exe` beside the app. Python, pip, yt-dlp.exe and a separate JavaScript runtime are not needed. The interface uses Korean on Korean Windows and English otherwise. Nanum Gothic Regular/Bold fonts are bundled and loaded privately.

## Audio

Enter a cue number, title and URL. The app selects the audio-only format with the highest reported bitrate and converts it to MP3. The file conversion tab converts the first audio track from existing media without modifying the original. Both use libmp3lame VBR 2.

Cue `007` and title `Opening` produce `bgm007_Opening.mp3`. Decimal cues such as `7.5` and the original spelling `007.50` are supported. Use up to 12 digits and optionally one decimal point with digits on both sides. Files are saved in `Downloads` beside the app; `(2)`, `(3)`, etc. preserve existing outputs.

Cancel stops a job; network cancellation may wait for the current request. The activity log reports errors and retained partial files. Site login or access restrictions can prevent downloading. File conversion works offline.

## Black screen ON/OFF

Connect a secondary monitor/projector and choose **Win+P → Extend**. Use **Black screen ON** to cover one secondary display with a borderless pure-black window and **Black screen OFF** to remove it. These controls remain available during audio downloads and conversions.

The primary monitor is never covered. Windows internal device `DISPLAY2` is preferred among nonprimary monitors; internal names can differ from Settings display numbers. No secondary display means an Extend-mode guidance message.

The cover does not take keyboard focus from the sound player and hides the cursor over its surface. Move the pointer over the black screen, then press and release **Alt+F4** to turn off only the cover. Esc, clicks and double-clicks do not dismiss it. Disconnecting the target hides the cover until a secondary display returns. Closing SCENE App also stops it. While enabled, the app requests that Windows prevent display/system sleep.

This integrates SCENE BlackScreen 1.0 screen-cover behavior. Epson PJ control and DDC/CI brightness changes are excluded. Display power, audio output and volume are unchanged. A black image does not guarantee that a projector emits no light.

## Build and source

Use Windows x64, Python 3.15 and the pinned dependencies in `requirements-build.txt` and `requirements-lock.txt`. Run `build.ps1` to produce `sceneapp.exe` and `dist/scene-app.zip`, plus the rebuildable `dist/SCENE-App-v0.3-source.zip` and SHA-256 files. The source archive includes code, tests, tools, docs, fonts and FFmpeg source material; it excludes local environments and executables. Run `python -m unittest discover -s tests -v` and `python tools/verify_releases.py` in the build virtual environment. Detailed setup is in README.md.

Application source: GPL-3.0-or-later; see LICENSE. Fonts and dependencies retain their licenses; see assets/fonts/OFL.txt, licenses/ and THIRD_PARTY_SOURCES.md. Use content you have permission to download.

[Source](https://github.com/hyjys/SCENE-App/tree/v0.3) · [Releases](https://github.com/hyjys/SCENE-App/releases/latest)
