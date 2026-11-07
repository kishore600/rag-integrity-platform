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

# Runs the Vercel CLI with the secret on STDIN and no trailing newline, and captures stdout/stderr separately.
# (Piping a string through PowerShell appends a line ending that would end up inside the stored value, and Windows
# PowerShell 5.1 turns any text a program writes to stderr into a terminating error: the CLI prints its banner there.)
function Invoke-Vercel([string]$ArgLine, [string]$StdinValue) {
  $tmp = $null
  try {
    $cmd = "npx --yes vercel $ArgLine"
    if ($null -ne $StdinValue) {
      # The value goes in as raw bytes: no BOM and no trailing newline. (.NET's redirected-stdin writer emits a UTF-8
      # byte-order mark when the console is in UTF-8 mode, which would become an invisible first character of the
      # stored value, and PowerShell's pipeline appends a line ending.) `type` passes the bytes through untouched.
      $tmp = [System.IO.Path]::GetTempFileName()
      [System.IO.File]::WriteAllBytes($tmp, (New-Object System.Text.UTF8Encoding($false)).GetBytes($StdinValue))
      $cmd = "type `"$tmp`" | $cmd"
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/c $cmd"
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = ($null -eq $StdinValue)
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    if ($psi.RedirectStandardInput) { $p.StandardInput.Close() }
    $so = $p.StandardOutput.ReadToEndAsync()
    $se = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()
    return [pscustomobject]@{ ExitCode = $p.ExitCode; Output = ($so.Result + "`n" + $se.Result) }
  }
  finally {
    if ($tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }  # the secret never stays on disk
  }
}

$vars = [ordered]@{ "RAGI_DATABASE_URL" = $dbUrl; "RAGI_SECRET_KEY" = $secret }
# One environment per call. Production is required; Preview is a convenience, so a failure there is only a warning.
$targets = @(@{ Name = "production"; Required = $true }, @{ Name = "preview"; Required = $false })
foreach ($name in $vars.Keys) {
  foreach ($t in $targets) {
    if ($DryRun) { Write-Host "(dry run) would set $name for $($t.Name) as a sensitive variable"; continue }
    Write-Host "Setting $name for $($t.Name) ..."
    $r = Invoke-Vercel "env add $name --environment $($t.Name) --sensitive --force --yes --scope $Scope" $vars[$name]
    if ($r.ExitCode -ne 0) {
      $detail = (($r.Output -split "`r?`n") | Where-Object { $_ -match '\S' -and $_ -notmatch 'claude-code-hint' } | Select-Object -Last 4) -join "`n"
      if ($t.Required) { throw "vercel env add $name ($($t.Name)) failed (exit $($r.ExitCode)):`n$detail`nIf it says you are not logged in, run: npx vercel login" }
      Write-Warning "Could not set $name for $($t.Name) (exit $($r.ExitCode)); production is unaffected.`n$detail"
    }
  }
}

if (-not $DryRun) {
  Write-Host ""
  Write-Host "Done. Both variables are set on the Vercel project."
  Write-Host "Next: tell Claude the environment is set, and it will deploy and verify the live site."
}
