# Asks for your Supabase database password (hidden), uploads the bot's memory to the database,
# and leaves the finished connection address on your clipboard for the Render step.
$ref = "zkqvfksoxunwdqymsbtf"
$hostName = "aws-0-ap-northeast-1.pooler.supabase.com"

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "Type your Supabase DATABASE password and press Enter."
Write-Host "(You will not see the letters while typing. That is normal.)"
$sec = Read-Host -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
if ([string]::IsNullOrWhiteSpace($plain)) { Write-Host "Nothing typed. Run it again."; return }

python -c "import psycopg2" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the database driver (one time)..."
    python -m pip install --user --quiet psycopg2-binary
}

$enc = [Uri]::EscapeDataString($plain)
$url = "postgresql://postgres.$ref`:$enc@$hostName`:5432/postgres"

$env:DATABASE_URL = $url
python -m bot.persist push
$code = $LASTEXITCODE
Remove-Item Env:DATABASE_URL

if ($code -eq 0) {
    Set-Clipboard -Value $url
    Write-Host ""
    Write-Host "SUCCESS: the bot's memory is in the database."
    Write-Host "The full address is now on your clipboard, ready to paste into Render. Do not paste it in chat."
} else {
    Write-Host ""
    Write-Host "FAILED. Most likely the password is wrong. Run this again and retype it carefully."
}
