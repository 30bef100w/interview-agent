$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

$imgDir = Join-Path $dir "images"
New-Item -ItemType Directory -Force -Path $imgDir | Out-Null

# 默认使用 images/ 下已有截图；仅当 PROMO_USE_ASSETS=1 时从 Cursor assets 覆盖
if ($env:PROMO_USE_ASSETS -eq "1") {
  $assets = Join-Path $dir "..\..\..\.cursor\projects\d-student-project-work-project-face-agent\assets"
  $assetsAlt = "C:\Users\21236\.cursor\projects\d-student-project-work-project-face-agent\assets"
  if (-not (Test-Path $assets)) { $assets = $assetsAlt }
  if (Test-Path $assets) {
    $map = @{
      "00-landing.png" = "*image-fe8042be*"
      "01-dashboard.png" = "*image-1dc3cfef*"
      "02-new-interview.png" = "*image-252e1f94*"
      "03-custom-settings.png" = "*image-71cc607e*"
      "04-target-company.png" = "*image-42c6f67c*"
      "05-history.png" = "*image-5c97d967*"
      "06-growth.png" = "*image-e2194111*"
      "07-targeted-practice.png" = "*image-cedf9cc9*"
      "08-radar-weakness.png" = "*image-475ff808*"
      "09-interview-chat.png" = "*image-c5f62127*"
      "10-coding.png" = "*image-11bca58d*"
      "11-report.png" = "*image-5d35ea8e*"
      "12-report-questions.png" = "*image-31bbf1a8*"
    }
    foreach ($kv in $map.GetEnumerator()) {
      $src = Get-ChildItem $assets -Filter $kv.Value -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($src) { Copy-Item $src.FullName (Join-Path $imgDir $kv.Key) -Force }
    }
  }
}

# 可选：同步参考截图 / Playwright 实时截取
#   $env:PROMO_CAPTURE = "1"           # 默认从用户参考图高清同步
#   $env:PROMO_MODE = "live"           # 或尝试 Playwright 实时截
if ($env:PROMO_CAPTURE -eq "1" -or $env:PROMO_MODE -eq "live") {
  Write-Host "Syncing / capturing promo screenshots ..."
  python (Join-Path $dir "capture_screenshots.py")
}

Write-Host "Compiling 深问产品介绍.tex with XeLaTeX ..."
xelatex -interaction=nonstopmode "深问产品介绍.tex" | Out-Null
xelatex -interaction=nonstopmode "深问产品介绍.tex" | Out-Null

$pdf = Join-Path $dir "深问产品介绍.pdf"
if (Test-Path $pdf) {
  Write-Host "OK -> $pdf ($([math]::Round((Get-Item $pdf).Length/1MB,2)) MB)"
} else {
  Write-Error "PDF not generated. Check LaTeX log."
}
