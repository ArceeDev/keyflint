# KeyFlint v1.1.0 — Fast Registry Publishing Helper
param(
    [string]$NpmOtp = "",
    [string]$PypiToken = ""
)

Write-Host "=== KeyFlint Registry Publisher ===" -ForegroundColor Cyan

# 1. npm publishing
if ($NpmOtp -ne "") {
    Write-Host "`n[1/2] Publishing keyflint-verify to npm using OTP..." -ForegroundColor Yellow
    Set-Location "$PSScriptRoot\sdks\js-verify"
    npm publish --access public --otp=$NpmOtp
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ npm publish succeeded!" -ForegroundColor Green
    } else {
        Write-Host "✗ npm publish failed. Check OTP expiration." -ForegroundColor Red
    }
} else {
    Write-Host "`n[1/2] Skipping npm (No -NpmOtp provided). Run with: .\publish_registries.ps1 -NpmOtp 123456" -ForegroundColor Gray
}

# 2. PyPI publishing
if ($PypiToken -ne "") {
    Write-Host "`n[2/2] Publishing keyflint-verify to PyPI..." -ForegroundColor Yellow
    Set-Location "$PSScriptRoot\sdks\python-verify"
    $env:TWINE_USERNAME = "__token__"
    $env:TWINE_PASSWORD = $PypiToken
    python -m twine upload dist/*
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ PyPI upload succeeded!" -ForegroundColor Green
    } else {
        Write-Host "✗ PyPI upload failed. Check PyPI token." -ForegroundColor Red
    }
} else {
    Write-Host "`n[2/2] Skipping PyPI (No -PypiToken provided). Run with: .\publish_registries.ps1 -PypiToken pypi-xxx" -ForegroundColor Gray
}

Set-Location $PSScriptRoot
Write-Host "`nDone." -ForegroundColor Cyan
