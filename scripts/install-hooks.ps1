# scripts/install-hooks.ps1
# =============================================================================
# 简历帮 — 一键安装 pre-push hook
#
# 把 git 的 hooks 目录指向仓库内的 scripts/hooks/：
#   git config core.hooksPath scripts/hooks
#
# 这样 hooks 跟着仓库版本走（不被 .git/ 忽略），新克隆后跑一次就生效。
#
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1
#
# 幂等：已经配置过的话直接提示，不重复执行。
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Resolve-Path (Join-Path $ScriptRoot '..')
Set-Location -LiteralPath $RepoRoot

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  简历帮 — 安装 pre-push hook" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# --- 1. 确认仓库根目录（必须在 .git 所在目录跑）-----------------------------
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git'))) {
    Write-Host "[FAIL] 当前目录不是 git 仓库根：$RepoRoot" -ForegroundColor Red
    Write-Host "       请在仓库根目录跑这个脚本。" -ForegroundColor Yellow
    exit 1
}

# --- 2. 确认 hook 脚本存在 ---------------------------------------------------
$HookPath = Join-Path $RepoRoot 'scripts/hooks/pre-push'
if (-not (Test-Path -LiteralPath $HookPath)) {
    Write-Host "[FAIL] 找不到 $HookPath" -ForegroundColor Red
    Write-Host "       请确认 scripts/hooks/pre-push 已 commit 到仓库。" -ForegroundColor Yellow
    exit 1
}

# --- 3. 幂等检查：已经指向对的就跳过 ----------------------------------------
$CurrentHooksPath = git config --get core.hooksPath
$ExpectedHooksPath = 'scripts/hooks'
if ($CurrentHooksPath -eq $ExpectedHooksPath) {
    Write-Host "[OK] core.hooksPath 已经指向 '$ExpectedHooksPath'，无需重复配置" -ForegroundColor Green
} else {
    git config core.hooksPath $ExpectedHooksPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] git config core.hooksPath 失败" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] 已设置 core.hooksPath = '$ExpectedHooksPath'" -ForegroundColor Green
}

# --- 4. 自检：列出生效的 hooks 路径 ------------------------------------------
Write-Host ""
Write-Host "当前生效配置：" -ForegroundColor Yellow
Write-Host "  core.hooksPath = $(git config --get core.hooksPath)" -ForegroundColor DarkGray
Write-Host ""

# --- 5. 友好收尾提示 --------------------------------------------------------
Write-Host "已完成。pre-push 自动跑 pytest + vue-tsc + build。" -ForegroundColor Green
Write-Host ""
Write-Host "下次 git push 时会自动验证，失败会挡 push。" -ForegroundColor White
Write-Host "  跳过 hook（紧急情况）：git push --no-verify" -ForegroundColor DarkGray
Write-Host ""
Write-Host "手动跑验证（不依赖 hook）：" -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts/verify.ps1" -ForegroundColor DarkGray
Write-Host ""
exit 0
