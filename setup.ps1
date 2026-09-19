<#
    Set this machine up to run Jarvis, and say what it could not do.

        powershell -ExecutionPolicy Bypass -File setup.ps1

    Written for the school laptop: a Dell Vostro 15 3530 with no NVIDIA card,
    starting from a folder that arrived as a zip — which means without voices/,
    because the two Piper voices are 111 MB and do not travel in it.

    Every step checks the real state before and after, rather than trusting
    that a command that printed nothing did something. A step that cannot
    finish says so at the end instead of scrolling past.
#>

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$failed = @()
$did = @()

function Step($name) { Write-Host "`n=== $name ===" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "  OK    $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "  ----  $msg" -ForegroundColor Yellow }
function Bad($msg)   { Write-Host "  FAIL  $msg" -ForegroundColor Red; $script:failed += $msg }

function Have($exe) { [bool](Get-Command $exe -ErrorAction SilentlyContinue) }

<# winget is on Windows 11 and on updated Windows 10. Where it is missing the
   installer is a download and a click, so print the link rather than trying to
   be clever about it. #>
function Install-With-Winget($id, $label, $url) {
    if (-not (Have "winget")) {
        Bad "$label is missing, and winget is not here to install it. Get it from $url"
        return $false
    }
    Write-Host "  installing $label with winget (this takes a few minutes)…"
    winget install --id $id --accept-source-agreements --accept-package-agreements --silent | Out-Null
    # winget puts things on PATH for new shells, not for this one.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
    return $true
}

# ---------------------------------------------------------------- the three
Step "What is already installed"

if (Have "node") { Ok "Node $(node --version)" }
else {
    if (Install-With-Winget "OpenJS.NodeJS.LTS" "Node.js LTS" "https://nodejs.org") {
        if (Have "node") { Ok "Node $(node --version)"; $did += "Node.js" }
        else { Bad "Node still not on PATH — open a new terminal and run this again" }
    }
}

$py = $null
foreach ($c in @("python", "py")) {
    if (Have $c) { try { if ((& $c --version 2>&1) -match "Python 3") { $py = $c; break } } catch {} }
}
if ($py) { Ok "$(& $py --version)" }
else {
    if (Install-With-Winget "Python.Python.3.13" "Python 3.13" "https://python.org") {
        if (Have "python") { $py = "python"; Ok "$(python --version)"; $did += "Python" }
        else { Bad "Python still not on PATH — tick 'Add python.exe to PATH' in the installer" }
    }
}

if (Have "ollama") { Ok "Ollama $((ollama --version) -replace '.*version is ','')" }
else {
    if (Install-With-Winget "Ollama.Ollama" "Ollama" "https://ollama.com") {
        if (Have "ollama") { Ok "Ollama installed"; $did += "Ollama" }
        else { Bad "Ollama still not on PATH — open a new terminal and run this again" }
    }
}

# ---------------------------------------------------------------- the model
Step "The model"

if (Have "ollama") {
    $model = "qwen3:4b-instruct-2507-q4_K_M"
    # Read the model the app actually asks for, so this file does not drift
    # from ui/app.js the next time the model changes.
    $appJs = Join-Path $root "ui\app.js"
    if (Test-Path $appJs) {
        $m = [regex]::Match((Get-Content $appJs -Raw), 'jarvis-model"\) \|\| "([^"]+)"')
        if ($m.Success) { $model = $m.Groups[1].Value }
    }

    $have = ""
    try { $have = (ollama list | Out-String) } catch {}
    if ($have -match [regex]::Escape($model)) {
        Ok "$model is already here"
    } else {
        Write-Host "  pulling $model (2.5 GB — this is the long one)…"
        ollama pull $model
        if ((ollama list | Out-String) -match [regex]::Escape($model)) { Ok "$model pulled"; $did += $model }
        else { Bad "the pull did not leave $model behind — check the network and run: ollama pull $model" }
    }
} else {
    Bad "no Ollama, so no model. Jarvis cannot answer anything without it."
}

# ---------------------------------------------------------------- packages
Step "Python packages"

if ($py) {
    & $py -m pip install --quiet --disable-pip-version-check faster-whisper piper-tts openwakeword sounddevice numpy
    $missing = @()
    foreach ($mod in @("faster_whisper", "piper", "openwakeword", "sounddevice", "numpy")) {
        & $py -c "import $mod" 2>$null
        if ($LASTEXITCODE -ne 0) { $missing += $mod }
    }
    if ($missing.Count -eq 0) { Ok "faster-whisper, piper-tts, openwakeword, sounddevice, numpy" }
    else { Bad "these did not import after installing: $($missing -join ', ')" }
} else {
    Bad "no Python, so no speech-to-text and no voice"
}

Step "npm packages"

if (Have "npm") {
    Push-Location $root
    npm install --no-audit --no-fund | Out-Null
    Pop-Location
    if (Test-Path (Join-Path $root "node_modules\electron")) { Ok "electron and electron-builder" }
    else { Bad "npm install finished without leaving node_modules\electron behind" }
} else {
    Bad "no npm, so the window cannot start"
}

# ---------------------------------------------------------------- the voices
Step "Piper voices"

<#  The zip does not carry voices/ — 111 MB of it. Without them Jarvis still
    talks, through the browser's own voice, which in Hebrew is the reason these
    models were added in the first place.

    These paths are what huggingface.co/rhasspy/piper-voices served last. If a
    download comes back small or unreadable, the layout there moved: open the
    repo, find the voice, and copy the path. Nothing here guesses — a bad file
    is reported, never left in voices/ to fail later as a broken model. #>
$voicesDir = Join-Path $root "voices"
$base = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
$voices = @(
    @{ name = "en_GB-alan-medium";      path = "en/en_GB/alan/medium" },
    @{ name = "he_IL-saspeech-medium";  path = "he/he_IL/saspeech/medium" }
)

New-Item -ItemType Directory -Force -Path $voicesDir | Out-Null
foreach ($v in $voices) {
    $onnx = Join-Path $voicesDir "$($v.name).onnx"
    $json = "$onnx.json"
    if ((Test-Path $onnx) -and ((Get-Item $onnx).Length -gt 5MB)) { Ok "$($v.name) already here"; continue }

    # Only what is missing. The .onnx.json config files are committed to this
    # repo — the 63 MB .onnx models are the part git does not carry — so a moved
    # path upstream must never be allowed to overwrite a config that is fine.
    foreach ($file in @("$($v.name).onnx", "$($v.name).onnx.json")) {
        $dest = Join-Path $voicesDir $file
        if (Test-Path $dest) { continue }
        $url = "$base/$($v.path)/$file"
        try {
            Write-Host "  downloading $file…"
            Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        } catch {
            Bad "could not download $file — $($_.Exception.Message)"
            Remove-Item $dest -ErrorAction SilentlyContinue
        }
    }

    # A 404 page saves as a file too, so check what actually landed.
    $good = $true
    if (-not (Test-Path $onnx) -or (Get-Item $onnx).Length -lt 5MB) {
        Bad "$($v.name).onnx is missing or far too small — the path at $base/$($v.path) has moved"
        $good = $false
    }
    if (Test-Path $json) {
        try { Get-Content $json -Raw | ConvertFrom-Json | Out-Null }
        catch { Bad "$($v.name).onnx.json is not JSON — the download returned a web page"; $good = $false }
    } else { $good = $false }

    if ($good) { Ok "$($v.name)"; $did += "voice $($v.name)" }
    else { Remove-Item $onnx -ErrorAction SilentlyContinue }   # keep the committed .json
}

# ---------------------------------------------------------------- proof
Step "Does it work"

if (Have "node") {
    Push-Location $root
    $out = (node test_jarvis.js | Out-String)
    Pop-Location
    if ($out -match "all passed") { Ok "test_jarvis.js — all passed" }
    else { Bad "test_jarvis.js reported failures — run it on its own to see them" }
}

# openWakeWord downloads its pretrained models on first use, which is a thing
# to find out now rather than while someone is watching.
if ($py) {
    & $py -c "from openwakeword import utils; utils.download_models(['hey_jarvis'])" 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "the 'Hey Jarvis' wake word model is downloaded" }
    else { Warn "could not fetch the wake word model — the button will say so when you press it" }
}

# ---------------------------------------------------------------- what is left
Step "Where this leaves you"

if ($did.Count)    { Write-Host "  installed: $($did -join ', ')" }
if ($failed.Count) {
    Write-Host "`n  Did not finish:" -ForegroundColor Red
    foreach ($f in $failed) { Write-Host "    - $f" -ForegroundColor Red }
} else {
    Write-Host "`n  Everything this script checks is in place." -ForegroundColor Green
}

Write-Host @"

Next, in this order:

  node bench.js      time three questions, the first one cold — this is the
                     number to know before the demo, and it is the CPU doing
                     all of it here
  npm start          the window itself

"@
