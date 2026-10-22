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
# Usage (project folder me) - ApiToken na do to secure prompt aayega:
#   .\setup_greenapi.ps1 -Phone 919876543210 -IdInstance 1101xxxxxx
#   (token ki jagah: PowerShell "ApiTokenInstance paste karo" pe paste karo - screen pe nahi dikhega,
#    aur command history me bhi save nahi hoga)

param(
    [Parameter(Mandatory = $true)][string]$Phone,
    [Parameter(Mandatory = $true)][string]$IdInstance,
    # -ApiToken optional: na do to script secure prompt se poochhega,
    # taaki token command line / PowerShell history me na jaye.
    [string]$ApiToken
)

$ErrorActionPreference = "Stop"

if (-not $ApiToken) {
    $secureToken = Read-Host "ApiTokenInstance paste karo (screen pe nahi dikhega)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $ApiToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
$ApiToken = "$ApiToken".Trim()
if (-not $ApiToken) { throw "ApiToken khali hai - instance page se ApiTokenInstance copy karo." }

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
# Naye instances ka apna host hota hai (e.g. 7103.api.greenapi.com) - dono try karo
$hosts = @("https://api.green-api.com")
$prefix = $IdInstance.Substring(0, [Math]::Min(4, $IdInstance.Length))
if ($prefix -match '^\d{4}$') { $hosts += "https://$prefix.api.greenapi.com" }

$base = $null
$state = ""
foreach ($h in $hosts) {
    try {
        $r = Invoke-RestMethod -Uri "$h/waInstance$IdInstance/getStateInstance/$ApiToken" -TimeoutSec 25
        $base = $h
        if ($null -eq $r) { $state = "creating (null)" } else { $state = "$($r.stateInstance)" }
        break
    } catch {
        Write-Host "     $h -> fail ($($_.Exception.Message))" -ForegroundColor DarkGray
    }
}
if (-not $base) {
    throw "Green API credentials galat lag rahe hain (ID Instance / ApiToken check karo)."
}
Write-Host "     host  = $base" -ForegroundColor Green
Write-Host "     state = $state" -ForegroundColor Green
if ($state -eq "notAuthorized") {
    Write-Host ""
    Write-Host "     QR scan baaki hai. Ye link kholo (browser me QR dikhega):" -ForegroundColor Yellow
    Write-Host "     $base/waInstance$IdInstance/qr/$ApiToken" -ForegroundColor Yellow
    Write-Host "     Phir WhatsApp -> Linked devices -> Link a device" -ForegroundColor Yellow
    Write-Host "     Scan ke baad ye script dobara chalao." -ForegroundColor Yellow
}
if ($state -eq "yellowCard" -or $state -eq "suspended") {
    Write-Host "     ATTENTION: number flag ho gaya hai. Console me verify/support se baat karo." -ForegroundColor Red
}
if ($state -ne "authorized") {
    Write-Host ""
    Write-Host "Pehle QR scan complete karo (ya 2-5 min wait karo agar instance ban raha hai)," -ForegroundColor Yellow
    Write-Host "phir ye script dobara chalao. Abhi kuch set nahi kiya." -ForegroundColor Yellow
    exit 1
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
Set-EnvValue $envFile "WHATSAPP_GREEN_URL" $base
Write-Host "     done (local .env)" -ForegroundColor Green

Write-Host ""
Write-Host "3/4  GitHub secrets set kar raha hoon..." -ForegroundColor Cyan
# Value stdin se jaati hai (--body se nahi) taaki token process arguments me na dikhe
function Set-GhSecret {
    param([string]$Name, [string]$Value)
    $Value | gh secret set $Name
    if ($LASTEXITCODE -ne 0) { throw "gh secret set $Name fail hua (gh auth status check karo)." }
}
Set-GhSecret "WHATSAPP_ENABLED" "true"
Set-GhSecret "WHATSAPP_PROVIDER" "greenapi"
Set-GhSecret "WHATSAPP_PHONE" $Phone
Set-GhSecret "WHATSAPP_GREEN_ID" $IdInstance
Set-GhSecret "WHATSAPP_GREEN_TOKEN" $ApiToken
Write-Host "     done (Actions secrets)" -ForegroundColor Green

Write-Host ""
Write-Host "4/4  Test alert bhej raha hoon..." -ForegroundColor Cyan
py -3.14 main.py --test-alert

Write-Host ""
Write-Host "WhatsApp line me OK aaya to setup ho gaya." -ForegroundColor Green
Write-Host "Aage se har alert Telegram + WhatsApp dono pe aayega (PC off ho tab bhi)." -ForegroundColor Green
