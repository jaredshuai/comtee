#Requires -Version 7.0
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
try {
    $gates = @(
        @{ Name = "format"; Args = @("run", "ruff", "format", "--check", ".") },
        @{ Name = "lint";   Args = @("run", "ruff", "check", ".") },
        @{ Name = "type";   Args = @("run", "ty", "check") },
        @{ Name = "test";   Args = @("run", "pytest") }
    )
    foreach ($gate in $gates) {
        Write-Host "[check] Running $($gate.Name): uv $($gate.Args -join ' ')"
        & uv @($gate.Args)
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Gate '$($gate.Name)' failed with exit code $LASTEXITCODE."
            exit $LASTEXITCODE
        }
    }
}
finally {
    Pop-Location
}
