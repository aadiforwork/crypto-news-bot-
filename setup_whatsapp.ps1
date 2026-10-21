# One-shot WhatsApp (CallMeBot) setup: updates .env + GitHub secrets, then tests.
#
# Usage (PowerShell, project folder me):
#   .\setup_whatsapp.ps1 -Phone 919876543210 -ApiKey 123456
#
# Phone: country code ke saath, bina + ke (e.g. 919876543210)
# ApiKey: CallMeBot ne WhatsApp pe reply me bheji thi

param(
    [Parameter(Mandatory = $true)][string]$Phone,
    [Parameter(Mandatory = $true)][string]$ApiKey
)

$ErrorActionPreference = "Stop"

$Phone = ($Phone -replace '[^\d]', '')
if ($Phone.Length -lt 10) {
    throw "Phone number chhota lag raha hai. Country code ke saath do, e.g. 919876543210"
}

function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = @(Get-Content $Path)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) { $out = @($out) + "$Key=$Value" }
    Set-Content -Path $Path -Value $out -Encoding utf8
}

Write-Host ""
Write-Host "1/3  .env update kar raha hoon..." -ForegroundColor Cyan
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile
    Write-Host "     .env nahi tha, .env.example se banaya" -ForegroundColor Yellow
}
Set-EnvValue $envFile "WHATSAPP_ENABLED" "true"
Set-EnvValue $envFile "WHATSAPP_PROVIDER" "callmebot"
Set-EnvValue $envFile "WHATSAPP_PHONE" $Phone
Set-EnvValue $envFile "WHATSAPP_APIKEY" $ApiKey
Write-Host "     done (local .env)" -ForegroundColor Green

Write-Host ""
Write-Host "2/3  GitHub secrets set kar raha hoon..." -ForegroundColor Cyan
gh secret set WHATSAPP_ENABLED --body "true"
gh secret set WHATSAPP_PROVIDER --body "callmebot"
gh secret set WHATSAPP_PHONE --body $Phone
gh secret set WHATSAPP_APIKEY --body $ApiKey
Write-Host "     done (Actions secrets)" -ForegroundColor Green

Write-Host ""
Write-Host "3/3  Test alert bhej raha hoon..." -ForegroundColor Cyan
py -3.14 main.py --test-alert

Write-Host ""
Write-Host "Agar WhatsApp line me OK aaya, to setup ho gaya." -ForegroundColor Green
Write-Host "Aage se har alert Telegram + WhatsApp dono pe aayega." -ForegroundColor Green
