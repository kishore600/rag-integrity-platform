<#
.SYNOPSIS
  Sets the two secrets the hosted app needs on your Vercel project. YOU run this; nothing else does it for you.

.DESCRIPTION
  RAGI_DATABASE_URL  Postgres / Supabase connection string (accounts, sessions, encrypted connection secrets, ledger).
                     Read from RAGI_DATABASE_URL in .env. A Supabase *session* pooler URL (port 5432) is switched to the
                     *transaction* pooler (port 6543), which is what serverless functions should use.
  RAGI_SECRET_KEY    Encrypts the connection secrets users store (their S3 keys, database URLs, Qdrant keys).
                     Generated here if .env does not have one, and saved to .env (git-ignored).

  Values are piped to the Vercel CLI over stdin and stored as *sensitive* (write-only) variables. They are never printed.

  KEEP A COPY OF RAGI_SECRET_KEY. If it is lost, stored connection secrets can no longer be decrypted and users must
  re-enter them. To rotate: set RAGI_SECRET_KEY to "<new key>,<old key>" (the first encrypts, all decrypt).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\vercel-env.ps1
  powershell -ExecutionPolicy Bypass -File scripts\vercel-env.ps1 -DryRun
#>
[CmdletBinding()]
param(
  [string]$Scope = "kishore600s-projects",
  [string]$EnvFile = ".env",
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Read-DotEnv([string]$Path) {
  $h = @{}
  if (Test-Path $Path) {
    foreach ($line in Get-Content $Path) {
      if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $h[$Matches[1]] = $Matches[2].Trim('"').Trim("'") }
    }
  }
  return $h
}

if (-not (Test-Path ".vercel\project.json")) { throw "This folder is not linked to a Vercel project. Run: npx vercel link" }
$cfg = Read-DotEnv $EnvFile

# ---- database
$dbUrl = $cfg["RAGI_DATABASE_URL"]
if (-not $dbUrl -or $dbUrl -like "sqlite*") { throw "RAGI_DATABASE_URL in $EnvFile must be your Supabase / Postgres connection string." }
if ($dbUrl -match 'pooler\.supabase\.com:5432/') {
  $dbUrl = $dbUrl -replace 'pooler\.supabase\.com:5432/', 'pooler.supabase.com:6543/'
  Write-Host "Using Supabase's transaction pooler (port 6543), which suits serverless functions."
}

# ---- secret key
$secret = $cfg["RAGI_SECRET_KEY"]
if (-not $secret) {
  $bytes = New-Object byte[] 48
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
  if ($DryRun) { Write-Host "(dry run) would generate RAGI_SECRET_KEY and save it to $EnvFile" }
  else {
    $existing = if (Test-Path $EnvFile) { Get-Content $EnvFile -Raw } else { "" }
    $prefix = if ($existing -and -not $existing.EndsWith("`n")) { "`r`n" } else { "" }
    Add-Content -Path $EnvFile -Value "$prefix`RAGI_SECRET_KEY=$secret" -Encoding ascii
    Write-Host "Generated RAGI_SECRET_KEY and saved it to $EnvFile (git-ignored). Keep a copy somewhere safe."
  }
}

$vars = [ordered]@{ "RAGI_DATABASE_URL" = $dbUrl; "RAGI_SECRET_KEY" = $secret }
# One environment per call: PowerShell turns "a,b" into a list and the CLI then sees "a b", which it rejects.
# Production is required; Preview is a convenience, so a failure there is only a warning.
$targets = @(@{ Name = "production"; Required = $true }, @{ Name = "preview"; Required = $false })
foreach ($name in $vars.Keys) {
  foreach ($t in $targets) {
    if ($DryRun) { Write-Host "(dry run) would set $name for $($t.Name) as a sensitive variable"; continue }
    Write-Host "Setting $name for $($t.Name) ..."
    $out = $vars[$name] | & npx --yes vercel env add $name --environment $t.Name --sensitive --force --yes --scope $Scope 2>&1
    if ($LASTEXITCODE -ne 0) {
      $detail = ($out | Where-Object { $_ -match '\S' -and $_ -notmatch 'claude-code-hint' } | Select-Object -Last 3) -join "`n"
      if ($t.Required) { throw "vercel env add $name ($($t.Name)) failed (exit $LASTEXITCODE):`n$detail`nIf it says you are not logged in, run: npx vercel login" }
      Write-Warning "Could not set $name for $($t.Name) (exit $LASTEXITCODE); production is unaffected.`n$detail"
    }
  }
}

if (-not $DryRun) {
  Write-Host ""
  Write-Host "Done. Both variables are set on the Vercel project."
  Write-Host "Next: tell Claude the environment is set, and it will deploy and verify the live site."
}
