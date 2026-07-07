# scripts/verify.ps1
# =============================================================================
# 简历帮 — 全量验证脚本（pre-push hook 入口）
#
# 跑三步全量验证，任意一步失败立刻退出（exit 1）挡 push：
#   1. 后端 pytest      — D:\python3.11\python.exe -m pytest backend/tests/ -v
#   2. 前端 vue-tsc     — npx vue-tsc --noEmit（类型检查）
#   3. 前端 npm run build — Vite 打包（产物到 frontend/dist/）
#
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
#
# 设计原则：
#   - PowerShell 5.1 兼容（避免 && / ?? / $LASTEXITCODE? 等 PS 7+ 语法）
#   - 不用 where python（避免撞错解释器），强制绝对路径 D:\python3.11\python.exe
#   - 不跑 npm install（node_modules 假设已装；install 慢 + 网络不稳）
#   - 任何抛错立刻冒泡（$ErrorActionPreference = 'Stop'）
#   - 文件需 UTF-8 with BOM（PS 5.1 默认 GBK 读无 BOM UTF-8 会乱码）
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- 1. 准备工作目录 ---------------------------------------------------------
# git hook 在仓库根目录调这个脚本，相对路径才是稳定的
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Resolve-Path (Join-Path $ScriptRoot '..')
Set-Location -LiteralPath $RepoRoot

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  简历帮 — 全量验证" -ForegroundColor Cyan
Write-Host "  Repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# --- 2. 工具链版本自检（失败时给清晰提示）-----------------------------------
$PythonExe = 'D:\python3.11\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "[FAIL] 找不到 Python: $PythonExe" -ForegroundColor Red
    Write-Host "       调试：确认 Python 3.11 装在 D:\python3.11\，或修改本脚本第一行的 \$PythonExe。" -ForegroundColor Yellow
    exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] 找不到 node / npm。请先安装 Node.js（LTS，建议 18+）。" -ForegroundColor Red
    Write-Host "       下载：https://nodejs.org/" -ForegroundColor Yellow
    exit 1
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] 找不到 npx。Node.js 自带 npx，确认安装完整。" -ForegroundColor Red
    exit 1
}

# --- 3. 后端 pytest ----------------------------------------------------------
Write-Host "[1/3] 后端 pytest（基线 948 passed + 0 skipped，R6-G 2026-07-03 实测）" -ForegroundColor Yellow
Write-Host "      $PythonExe -m pytest backend/tests/ -v" -ForegroundColor DarkGray
Write-Host ""

try {
    & $PythonExe -m pytest backend/tests/ -v
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[FAIL] pytest 退出码 $LASTEXITCODE" -ForegroundColor Red
        Write-Host "       调试：cd backend ; $PythonExe -m pytest tests/ -v 看详细输出" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host ""
    Write-Host "[FAIL] pytest 抛错：$_" -ForegroundColor Red
    Write-Host "       调试：cd backend ; $PythonExe -m pytest tests/ -v 看详细输出" -ForegroundColor Yellow
    exit 1
}
Write-Host ""
Write-Host "[OK] pytest 全绿" -ForegroundColor Green
Write-Host ""

# --- 4. 前端 vue-tsc 类型检查 ------------------------------------------------
Write-Host "[2/3] 前端 vue-tsc --noEmit（类型检查）" -ForegroundColor Yellow
Write-Host "      cd frontend ; npx vue-tsc --noEmit" -ForegroundColor DarkGray
Write-Host ""

try {
    Push-Location -LiteralPath (Join-Path $RepoRoot 'frontend')
    try {
        & npx --no-install vue-tsc --noEmit
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "[FAIL] vue-tsc 退出码 $LASTEXITCODE（有类型错误）" -ForegroundColor Red
            Write-Host "       调试：cd frontend ; npx vue-tsc --noEmit 看详细错误位置" -ForegroundColor Yellow
            exit 1
        }
    } finally {
        Pop-Location
    }
} catch {
    Write-Host ""
    Write-Host "[FAIL] vue-tsc 抛错：$_" -ForegroundColor Red
    Write-Host "       调试：cd frontend ; npx vue-tsc --noEmit 看详细错误" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] vue-tsc 0 error" -ForegroundColor Green
Write-Host ""

# --- 5. 前端 npm run build ----------------------------------------------------
Write-Host "[3/3] 前端 npm run build（Vite 打包）" -ForegroundColor Yellow
Write-Host "      cd frontend ; npm run build" -ForegroundColor DarkGray
Write-Host ""

try {
    Push-Location -LiteralPath (Join-Path $RepoRoot 'frontend')
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "[FAIL] npm run build 退出码 $LASTEXITCODE" -ForegroundColor Red
            Write-Host "       调试：cd frontend ; npm run build 看 Vite 详细报错" -ForegroundColor Yellow
            exit 1
        }
    } finally {
        Pop-Location
    }
} catch {
    Write-Host ""
    Write-Host "[FAIL] npm run build 抛错：$_" -ForegroundColor Red
    Write-Host "       调试：cd frontend ; npm run build 看 Vite 详细报错" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] npm run build 成功（产物 frontend/dist/）" -ForegroundColor Green
Write-Host ""

# --- 6. 全部通过 -------------------------------------------------------------
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "  ✅ 全量验证通过 — 可以 push" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
exit 0

