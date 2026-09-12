#Requires -Version 5.1
<#
.SYNOPSIS
  Build standalone with Nuitka, then Inno Setup installer.
.PARAMETER Stage
  all (default), nuitka, or inno.
.PARAMETER Clean
  Delete installer/dist and stage markers first.
.PARAMETER Force
  Rebuild the requested stage(s) even if markers and artifacts exist.
#>
param(
    [ValidateSet("all", "nuitka", "inno")]
    [string]$Stage = "all",
    [switch]$Clean,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $PackDir "..")).Path
$DistDir = Join-Path $PackDir "dist"
$StateDir = Join-Path $PackDir ".build-state"
$IconPath = Join-Path $PackDir "comtee.ico"
$IssPath = Join-Path $PackDir "comtee.iss"
$script:ProjectVersion = $null

function Get-ProjectVersion {
    # 读 pyproject.toml 的版本；同一次运行只问一次。
    if ($null -ne $script:ProjectVersion -and $script:ProjectVersion -ne "") {
        return $script:ProjectVersion
    }
    $pyproject = Join-Path $Root "pyproject.toml"
    $code = "import tomllib, pathlib; print(tomllib.loads(pathlib.Path(r'$pyproject').read_text(encoding='utf-8'))['project']['version'])"
    $version = & uv run python -c $code
    if (-not $version) {
        throw "Cannot read version from pyproject.toml."
    }
    $script:ProjectVersion = $version.Trim()
    return $script:ProjectVersion
}

function Get-WindowsFileVersion {
    # Nuitka 的 Windows 文件版本必须是四段数字。
    param([Parameter(Mandatory = $true)][string]$Version)
    $parts = [System.Collections.Generic.List[string]]::new()
    foreach ($part in $Version.Split(".")) {
        $parts.Add($part)
    }
    while ($parts.Count -lt 4) {
        $parts.Add("0")
    }
    return (($parts[0], $parts[1], $parts[2], $parts[3]) -join ".")
}

function Find-Iscc {
    # 找 Inno Setup 6 或 7 的 ISCC.exe。
    $roots = @(
        ${env:ProgramFiles(x86)},
        $env:ProgramFiles,
        (Join-Path $env:LOCALAPPDATA "Programs")
    )
    $names = @("Inno Setup 7\ISCC.exe", "Inno Setup 6\ISCC.exe")
    foreach ($root in $roots) {
        if (-not $root) { continue }
        foreach ($name in $names) {
            $path = Join-Path $root $name
            if (Test-Path $path) {
                return $path
            }
        }
    }
    $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Stop-PackagingLocks {
    # 停掉正在跑的 comtee.exe，避免产物被锁。
    Get-CimInstance Win32_Process -Filter "Name = 'comtee.exe'" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Resolve-StandaloneDir {
    # Nuitka 可能写出 comtee.dist 或 main.dist。
    $names = @("comtee.dist", "main.dist")
    foreach ($name in $names) {
        $dir = Join-Path $DistDir $name
        $exe = Join-Path $dir "comtee.exe"
        if (Test-Path $exe) {
            return $dir
        }
    }
    throw "comtee.exe not found. Run -Stage nuitka first."
}

function Get-StatePath {
    # 某个阶段的 .ok 标记路径。
    param([Parameter(Mandatory = $true)][string]$Name)
    return Join-Path $StateDir ("{0}.ok" -f $Name)
}

function Read-StageVersion {
    # 读阶段标记里记下的版本；没有则返回空。
    param([Parameter(Mandatory = $true)][string]$Name)
    $path = Get-StatePath -Name $Name
    if (-not (Test-Path $path)) {
        return $null
    }
    foreach ($line in Get-Content -Path $path) {
        if ($line -match "^version=(.+)$") {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Write-StageOk {
    # 阶段成功后写下标记，下次默认可跳过。
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Artifact,
        [Parameter(Mandatory = $true)][string]$Version
    )
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $relative = $Artifact
    $prefix = $PackDir.TrimEnd("\") + "\"
    if ($Artifact.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = $Artifact.Substring($prefix.Length)
    }
    $lines = @(
        "version=$Version",
        "artifact=$relative",
        "utc=$((Get-Date).ToUniversalTime().ToString('o'))"
    )
    Set-Content -Path (Get-StatePath -Name $Name) -Value $lines -Encoding ascii
}

function Clear-StageOk {
    # 丢掉阶段标记，让下次重打这一阶段。
    param([Parameter(Mandatory = $true)][string]$Name)
    $path = Get-StatePath -Name $Name
    if (Test-Path $path) {
        Remove-Item -Force $path
    }
}

function Get-SetupPath {
    # 当前版本对应的安装包路径。
    $version = Get-ProjectVersion
    return Join-Path $DistDir ("Comtee-Setup-{0}.exe" -f $version)
}

function Test-NuitkaFresh {
    # 未强制且 standalone exe 仍在、版本未变，则视为可跳过。
    if ($Force) {
        return $false
    }
    try {
        $standalone = Resolve-StandaloneDir
    }
    catch {
        return $false
    }
    $exe = Join-Path $standalone "comtee.exe"
    if (-not (Test-Path $exe)) {
        return $false
    }
    $version = Get-ProjectVersion
    $okVersion = Read-StageVersion -Name "nuitka"
    if ($null -ne $okVersion -and $okVersion -ne "" -and $okVersion -ne $version) {
        Write-Host "nuitka.ok version $okVersion != project $version; will rebuild."
        return $false
    }
    if (-not (Test-Path (Get-StatePath -Name "nuitka"))) {
        Write-StageOk -Name "nuitka" -Artifact $exe -Version $version
        Write-Host "Healed nuitka.ok from existing artifact"
    }
    return $true
}

function Test-InnoFresh {
    # 未强制且当前版本安装包仍在，则视为可跳过。
    if ($Force) {
        return $false
    }
    $setup = Get-SetupPath
    if (-not (Test-Path $setup)) {
        return $false
    }
    $version = Get-ProjectVersion
    $okVersion = Read-StageVersion -Name "inno"
    if ($null -ne $okVersion -and $okVersion -ne "" -and $okVersion -ne $version) {
        Write-Host "inno.ok version $okVersion != project $version; will rebuild."
        return $false
    }
    if (-not (Test-Path (Get-StatePath -Name "inno"))) {
        Write-StageOk -Name "inno" -Artifact $setup -Version $version
        Write-Host "Healed inno.ok from existing artifact"
    }
    return $true
}

function Build-Icon {
    # 写出 exe 和安装包共用的 ICO。
    Push-Location $Root
    try {
        uv run python (Join-Path $PackDir "generate_icon.py")
    }
    finally {
        Pop-Location
    }
    if (-not (Test-Path $IconPath)) {
        throw "Failed to write $IconPath"
    }
}

function Build-Nuitka {
    # 编译 standalone 目录。中断后续打时不要带 -RemoveOutput。
    param([switch]$RemoveOutput)
    Stop-PackagingLocks
    $version = Get-ProjectVersion
    $fileVersion = Get-WindowsFileVersion -Version $version
    Build-Icon
    New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
    $nuitkaArgs = @(
        "--mode=standalone",
        "--assume-yes-for-downloads",
        "--include-package=comtee",
        "--include-package=nicegui",
        "--include-package-data=nicegui",
        "--include-package=pystray",
        "--include-package=PIL",
        "--include-package=serial",
        "--windows-console-mode=disable",
        "--force-stderr-spec={PROGRAM_BASE}.log",
        "--windows-icon-from-ico=$IconPath",
        "--output-dir=$DistDir",
        "--output-filename=comtee.exe",
        "--product-name=Comtee",
        "--product-version=$fileVersion",
        "--file-version=$fileVersion",
        "--file-description=Comtee",
        "--company-name=comtee",
        "--show-progress"
    )
    if ($RemoveOutput) {
        $nuitkaArgs += "--remove-output"
    }
    $nuitkaArgs += "main.py"
    Push-Location $Root
    try {
        uv run --group packaging python -m nuitka @nuitkaArgs
    }
    finally {
        Pop-Location
    }
    $standalone = Resolve-StandaloneDir
    Write-Host "Nuitka output: $standalone"
}

function Build-Inno {
    # 把 standalone 目录打成每用户安装包。
    Stop-PackagingLocks
    $iscc = Find-Iscc
    if (-not $iscc) {
        throw "ISCC.exe not found. Install Inno Setup from https://jrsoftware.org/isinfo.php"
    }
    $version = Get-ProjectVersion
    $standalone = Resolve-StandaloneDir
    $relativeDist = $standalone.Substring($PackDir.Length).TrimStart("\")
    Push-Location $PackDir
    try {
        & $iscc `
            "/DMyAppVersion=$version" `
            "/DMyAppDistDir=$relativeDist" `
            $IssPath
    }
    finally {
        Pop-Location
    }
    $setup = Get-SetupPath
    if (-not (Test-Path $setup)) {
        throw "Inno did not write $setup"
    }
    Write-Host "Installer: $setup"
}

function Invoke-NuitkaStage {
    # 跳过、续打或强制重打 Nuitka。重打会作废安装包标记。
    if (-not $Force -and (Test-NuitkaFresh)) {
        Write-Host ("Skip nuitka (stage ok): {0}" -f (Resolve-StandaloneDir))
        return
    }
    Clear-StageOk -Name "nuitka"
    Clear-StageOk -Name "inno"
    $removeOutput = [bool]($Force -or $Clean)
    Build-Nuitka -RemoveOutput:$removeOutput
    $standalone = Resolve-StandaloneDir
    Write-StageOk -Name "nuitka" -Artifact (Join-Path $standalone "comtee.exe") -Version (Get-ProjectVersion)
}

function Invoke-InnoStage {
    # 跳过或重打 Inno 安装包。
    if (-not $Force -and (Test-InnoFresh)) {
        Write-Host ("Skip inno (stage ok): {0}" -f (Get-SetupPath))
        return
    }
    Clear-StageOk -Name "inno"
    Build-Inno
    Write-StageOk -Name "inno" -Artifact (Get-SetupPath) -Version (Get-ProjectVersion)
}

if ($Clean) {
    Stop-PackagingLocks
    if (Test-Path $DistDir) {
        Remove-Item -Recurse -Force $DistDir
    }
    if (Test-Path $StateDir) {
        Remove-Item -Recurse -Force $StateDir
    }
}

switch ($Stage) {
    "nuitka" { Invoke-NuitkaStage }
    "inno" { Invoke-InnoStage }
    default {
        Invoke-NuitkaStage
        Invoke-InnoStage
    }
}
