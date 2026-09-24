<#
.SYNOPSIS
    Put an SMUniversal Lab Suite icon on this machine's desktop.

.DESCRIPTION
    Run once per bench PC, from the checkout:

        powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1

    The shortcut starts the suite with no console window, through uv's
    windowless `uvw.exe` and the `smu-lab-suite-gui` entry point:

        uvw run --directory <this checkout> --extra bench smu-lab-suite-gui

    No console matters for safety, not only looks. A console beside the
    window is one more thing to close, and closing it kills Python
    outright - the window's own close path never runs, so the output is
    never switched off. With no console, the window's close button is
    the only way out, and it is the one that puts the instruments away.

    It points at this checkout wherever it lives, so a `git pull` is all
    an update needs: the next click runs the new code, and `uv run`
    installs anything the update added. `uv run` only ever adds what is
    missing; unlike `uv sync` it never removes a package this bench had
    installed for another reason.

    The packages are installed here, before the shortcut is made, so a
    missing uv or a failed install is reported in this console rather
    than by an icon that is clicked and does nothing.

.PARAMETER Extras
    Which optional package sets to install and run with. `bench` is the
    bench's standard set. Add `direct-gpib` on a machine with an NI
    GPIB-USB-HS adapter driven directly:  -Extras bench,direct-gpib

.PARAMETER Destination
    The folder to put the shortcut in. Defaults to this user's desktop,
    wherever Windows keeps it (OneDrive-redirected desktops included).

.PARAMETER StartMenu
    Also add the shortcut to this user's Start menu.
#>
param(
    [string[]] $Extras = @("bench"),
    [string] $Destination = [Environment]::GetFolderPath("Desktop"),
    [switch] $StartMenu,
    [string] $Name = "SMUniversal Lab Suite"
)

$ErrorActionPreference = "Stop"

# The checkout is the folder above this script's.
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Icon = Join-Path $Repo "smuniversal_lab_suite\assets\app_icon.ico"

if (-not (Test-Path (Join-Path $Repo "pyproject.toml"))) {
    throw "No pyproject.toml in $Repo - run this from inside the suite's checkout."
}

# uv's windowless twin. It ships beside uv.exe in every uv install.
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) {
    $Uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
}
if (-not (Test-Path $Uv)) {
    throw "uv is not installed. Install it from https://docs.astral.sh/uv/ and run this again."
}
$Uvw = Join-Path (Split-Path $Uv) "uvw.exe"
if (-not (Test-Path $Uvw)) {
    throw "Found uv at $Uv but no uvw.exe beside it. Update uv ('uv self update') and run this again."
}

# Run with -File, PowerShell hands "bench,direct-gpib" over as one
# string rather than a list, so commas are split here as well.
$Extras = @($Extras | ForEach-Object { $_ -split "," } |
            ForEach-Object { $_.Trim() } | Where-Object { $_ })
$ExtraArgs = @()
foreach ($extra in $Extras) { $ExtraArgs += @("--extra", $extra) }

# Install now, where an error can be read, rather than on the first
# click, where it could not.
Write-Host "Installing the suite's packages ($($Extras -join ', ')) ..."
& $Uv run --directory $Repo @ExtraArgs python -c "import smuniversal_lab_suite.core.launcher"
if ($LASTEXITCODE -ne 0) {
    throw "Installing the packages failed - see the messages above."
}

$Arguments = (@("run", "--directory", "`"$Repo`"") + $ExtraArgs +
              @("smu-lab-suite-gui")) -join " "

function New-SuiteShortcut([string] $Folder) {
    New-Item -ItemType Directory -Force -Path $Folder | Out-Null
    $Path = Join-Path $Folder "$Name.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut($Path)
    $Link.TargetPath = $Uvw
    $Link.Arguments = $Arguments
    $Link.WorkingDirectory = $Repo
    $Link.IconLocation = "$Icon,0"
    $Link.Description = "Measurement windows for the bench SMUs"
    $Link.Save()
    Write-Host "Shortcut: $Path"
}

New-SuiteShortcut $Destination
if ($StartMenu) {
    New-SuiteShortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "SMUniversal Lab Suite")
}
Write-Host "Runs: $Uvw $Arguments"
