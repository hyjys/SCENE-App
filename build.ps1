param(
    [switch]$BuildInstaller,
    [switch]$IncludeDependencySources,
    [string]$InnoCompiler = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & py -3.15 -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.15 가상환경을 만들지 못했습니다.' }
    }

    & $venvPython -c 'import sys; assert sys.version_info[:2] == (3, 15), "Python 3.15 가상환경이 필요합니다."'
    if ($LASTEXITCODE -ne 0) { throw '가상환경의 Python 버전을 확인해 주세요.' }

    & $venvPython -m pip install -r (Join-Path $projectRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw '빌드 도구 설치에 실패했습니다.' }

    & $venvPython -m pip install -r (Join-Path $projectRoot 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw '고정된 런타임 의존성 설치에 실패했습니다.' }

    & $venvPython (Join-Path $projectRoot 'tools\fetch_ffmpeg.py')
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg 준비에 실패했습니다.' }

    & $venvPython (Join-Path $projectRoot 'tools\fetch_runtime.py')
    if ($LASTEXITCODE -ne 0) { throw '내장 JavaScript 런타임 준비에 실패했습니다.' }

    & $venvPython -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name sceneapp `
        --collect-all customtkinter `
        --collect-all yt_dlp_ejs `
        --collect-all tkinterweb `
        --collect-all tkinterweb_tkhtml `
        --collect-all tkinterweb_tkhtml_extras `
        --collect-all pythonmonkey `
        --collect-all pminit `
        --collect-all aiohttp `
        --collect-all yarl `
        --collect-all pymupdf `
        --collect-all docx `
        --collect-all PIL `
        --copy-metadata yt-dlp `
        --add-data ((Join-Path $projectRoot 'assets\fonts') + ';assets/fonts') `
        --add-binary ((Join-Path $projectRoot 'vendor\deno.exe') + ';runtime') `
        --add-data ((Join-Path $projectRoot 'vendor\DENO-LICENSE.txt') + ';runtime') `
        --add-data ((Join-Path $projectRoot 'vendor\runtime.json') + ';runtime') `
        --distpath $projectRoot `
        --workpath (Join-Path $projectRoot 'build') `
        --specpath (Join-Path $projectRoot 'build') `
        --version-file (Join-Path $projectRoot 'version_info.txt') `
        (Join-Path $projectRoot 'scene_app.py')
    if ($LASTEXITCODE -ne 0) { throw 'SCENE App 실행 파일 빌드에 실패했습니다.' }
    Write-Output ('빌드 완료: ' + (Join-Path $projectRoot 'sceneapp.exe'))

    & $venvPython (Join-Path $projectRoot 'tools\package_variants.py')
    if ($LASTEXITCODE -ne 0) { throw '배포 ZIP 생성에 실패했습니다.' }

    if ($IncludeDependencySources) {
        & $venvPython (Join-Path $projectRoot 'tools\package_dependency_sources.py')
        if ($LASTEXITCODE -ne 0) { throw '서드파티 소스 배포 ZIP 생성에 실패했습니다.' }
    }

    if ($BuildInstaller) {
        if (-not $InnoCompiler) {
            $taskIsccCommand = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
            if ($taskIsccCommand) { $InnoCompiler = $taskIsccCommand.Source }
        }
        if (-not $InnoCompiler) {
            $taskInnoCandidates = @(
                (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
                (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
                (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe')
            )
            $InnoCompiler = $taskInnoCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        }
        if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler)) {
            throw 'Inno Setup 7 이상을 설치하거나 -InnoCompiler 경로를 지정해 주세요. ZIP 빌드는 완료되었습니다.'
        }
        $taskInstallerStage = Join-Path $projectRoot ('build\installer-input-' + [guid]::NewGuid().ToString('N'))
        Expand-Archive -LiteralPath (Join-Path $projectRoot 'dist\scene-app.zip') -DestinationPath $taskInstallerStage
        $taskVersionSource = Get-Content -LiteralPath (Join-Path $projectRoot 'ui_theme.py') -Raw
        if ($taskVersionSource -notmatch 'VERSION\s*=\s*"([0-9]+(?:\.[0-9]+){1,3})"') {
            throw '앱 버전 정보를 읽을 수 없습니다.'
        }
        $taskReleaseVersion = $Matches[1]
        & $InnoCompiler ('/DAppVersion=' + $taskReleaseVersion) `
            ('/DStageDir=' + (Join-Path $taskInstallerStage 'SCENE-App')) `
            ('/DReleaseDir=' + (Join-Path $projectRoot 'dist')) `
            (Join-Path $projectRoot 'installer\sceneapp.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno 설치 파일 생성에 실패했습니다.' }
        $taskInstallerOutput = Join-Path $projectRoot ('dist\sceneapp-' + $taskReleaseVersion + '-windows-x64-setup.exe')
        $taskInstallerHash = (Get-FileHash -LiteralPath $taskInstallerOutput -Algorithm SHA256).Hash.ToLowerInvariant()
        ($taskInstallerHash + '  ' + (Split-Path -Leaf $taskInstallerOutput)) | Set-Content -LiteralPath ($taskInstallerOutput + '.sha256') -Encoding ascii
        Write-Output ('설치 파일 빌드 완료: ' + $taskInstallerOutput)
    }
}
finally {
    Pop-Location
}
