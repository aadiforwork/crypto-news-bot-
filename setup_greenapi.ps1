# One-shot WhatsApp (Green API - FREE Developer plan) setup: .env + GitHub secrets + test.
#
# Green API kyun: free Developer plan (1 instance, 3 chats, sendMessage unlimited) aur
# WhatsApp session unke SERVER pe rehta hai -> PC/phone 24x7 ON rakhne ki zarurat nahi.
#
# Pehle ye karo (ek hi baar, console me):
#   1. green-api.com -> Console -> Google se login
#   2. Create instance -> plan: Developer (free)
#   3. Scan QR -> phone se WhatsApp -> Linked devices -> Link a device
#   4. Instance page se ID Instance + ApiTokenInstance copy karo
#
# Usage (project folder me):
#   .\setup_greenapi.ps1 -Phone 919876543210 -IdInstance 1101xxxxxx -ApiToken xxxxxxxx

param(
    [Parameter(Mandatory = $true)][string]$Phone,
    [Parameter(Mandatory = $true)][string]$IdInstance,
    [Parameter(Mandatory = $true)][string]$ApiToken
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
Write-Host "1/4  Instance state check kar raha hoon (QR scan hua ya nahi)..." -ForegroundColor Cyan
try {
    $state = (Invoke-RestMethod -Uri "https://api.green-api.com/waInstance$IdInstance/getStateInstance/$ApiToken" -TimeoutSec 25).stateInstance
    Write-Host "     state = $state" -ForegroundColor Green
    if ($state -ne "authorized") {
        Write-Host "     ATTENTION: state '$state' hai. Console me QR scan karo, phir dobara chalao." -ForegroundColor Yellow
    }
} catch {
    throw "Green API credentials galat lag rahe hain (ID/ApiToken check karo): $($_.Exception.Message)"
}

Write-Host ""
Write-Host "2/4  .env update kar raha hoon..." -ForegroundColor Cyan
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile
    Write-Host "     .env nahi tha, .env.example se banaya" -ForegroundColor Yellow
}
Set-EnvValue $envFile "WHATSAPP_ENABLED" "true"
Set-EnvValue $envFile "WHATSAPP_PROVIDER" "greenapi"
Set-EnvValue $envFile "WHATSAPP_PHONE" $Phone
Set-EnvValue $envFile "WHATSAPP_GREEN_ID" $IdInstance
Set-EnvValue $envFile "WHATSAPP_GREEN_TOKEN" $ApiToken
Write-Host "     done (local .env)" -ForegroundColor Green

Write-Host ""
Write-Host "3/4  GitHub secrets set kar raha hoon..." -ForegroundColor Cyan
gh secret set WHATSAPP_ENABLED --body "true"
gh secret set WHATSAPP_PROVIDER --body "greenapi"
gh secret set WHATSAPP_PHONE --body $Phone
gh secret set WHATSAPP_GREEN_ID --body $IdInstance
gh secret set WHATSAPP_GREEN_TOKEN --body $ApiToken
Write-Host "     done (Actions secrets)" -ForegroundColor Green

Write-Host ""
Write-Host "4/4  Test alert bhej raha hoon..." -ForegroundColor Cyan
py -3.14 main.py --test-alert

Write-Host ""
Write-Host "WhatsApp line me OK aaya to setup ho gaya." -ForegroundColor Green
Write-Host "Aage se har alert Telegram + WhatsApp dono pe aayega (PC off ho tab bhi)." -ForegroundColor Green
