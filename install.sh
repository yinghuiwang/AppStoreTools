#!/usr/bin/env bash
# When sourced, set -euo pipefail would leak into the caller's shell and cause
# any subsequent failed command (e.g. a typo) to silently kill the session.
# Save current options and restore them at the end of this script.
_asc_saved_opts="$-"
set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }
# Use 'return' instead of 'exit' so sourcing this script doesn't kill the shell.
fatal()   { error "$*"; return 1; }

echo "================================================"
echo "  App Store Connect Tools — 安装程序"
echo "================================================"
echo ""

# ── 1. 检测操作系统 ──
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macOS" ;;
  Linux)  PLATFORM="Linux" ;;
  *)      fatal "不支持的操作系统: $OS" ;;
esac
info "操作系统: $PLATFORM"

# ── 2. 检查 Python 3.9+ ──
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    MAJOR=$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || true)
    MINOR=$("$cmd" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || true)
    if [ "${MAJOR:-0}" -gt 3 ] || { [ "${MAJOR:-0}" -eq 3 ] && [ "${MINOR:-0}" -ge 9 ]; }; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  error "未找到 Python 3.9 或更高版本。"
  if [ "$PLATFORM" = "macOS" ]; then
    echo "  安装方式：brew install python@3.12"
    echo "  或使用 pyenv：https://github.com/pyenv/pyenv"
  else
    echo "  安装方式：sudo apt install python3  （Debian/Ubuntu）"
    echo "  或使用 pyenv：https://github.com/pyenv/pyenv"
  fi
  return 1
fi
info "Python: $($PYTHON --version)"

# ── 3. 检查 pip ──
if ! "$PYTHON" -m pip --version &>/dev/null; then
  warn "pip 未安装，尝试自动修复..."
  if "$PYTHON" -m ensurepip --upgrade &>/dev/null; then
    info "pip 已通过 ensurepip 安装"
  else
    error "pip 安装失败，请手动安装："
    echo "  https://pip.pypa.io/en/stable/installation/"
    return 1
  fi
else
  info "pip: $($PYTHON -m pip --version | cut -d' ' -f1-2)"
fi

# ── 4. 检查 git（非阻断）──
if ! command -v git &>/dev/null; then
  warn "git 未安装（非必须，但建议安装）"
  if [ "$PLATFORM" = "macOS" ]; then
    echo "  安装方式：brew install git"
  else
    echo "  安装方式：sudo apt install git"
  fi
else
  info "git: $(git --version)"
fi

# ── 5. 检查 brew（仅 macOS，非阻断）──
if [ "$PLATFORM" = "macOS" ] && ! command -v brew &>/dev/null; then
  warn "Homebrew 未安装（可选）"
  echo "  安装方式：https://brew.sh"
fi

# ── 6. 安装 asc-appstore-tools ──
echo ""
echo "正在从 GitHub 安装 asc-appstore-tools ..."
GITHUB_URL="git+https://github.com/yinghuiwang/AppStoreTools.git"
if "$PYTHON" -m pip install "$GITHUB_URL" 2>/dev/null; then
  info "asc-appstore-tools 安装成功"
elif "$PYTHON" -m pip install --user "$GITHUB_URL"; then
  info "asc-appstore-tools 安装成功（--user 模式）"
else
  fatal "pip install 失败，请检查网络或权限后重试"
fi

# ── 7. 检测 pip bin 目录并写入 PATH ──
USER_BIN=$("$PYTHON" -m site --user-base 2>/dev/null)/bin
_asc_need_path_export=0
if [ -d "$USER_BIN" ] && [[ ":$PATH:" != *":$USER_BIN:"* ]]; then
  # 写入 shell 配置文件
  SHELL_NAME="$(basename "${SHELL:-bash}")"
  if [ "$SHELL_NAME" = "zsh" ]; then
    RC_FILE="$HOME/.zshrc"
  elif [ "$SHELL_NAME" = "bash" ]; then
    RC_FILE="$HOME/.bash_profile"
  else
    RC_FILE="$HOME/.profile"
  fi

  EXPORT_LINE="export PATH=\"$USER_BIN:\$PATH\""
  if ! grep -qF "$USER_BIN" "$RC_FILE" 2>/dev/null; then
    echo "" >> "$RC_FILE"
    echo "# Added by asc-appstore-tools installer" >> "$RC_FILE"
    echo "$EXPORT_LINE" >> "$RC_FILE"
    info "已将 $USER_BIN 写入 $RC_FILE"
  fi

  # 标记需要在父 shell 中 export（不能在这里做，因为下面要恢复 set 选项）
  _asc_need_path_export=1
fi

# ── 8. 验证安装 ──
if command -v asc &>/dev/null; then
  info "asc 命令可用：$(command -v asc)"
else
  warn "asc 命令在当前会话不可用，请运行："
  echo "  source $RC_FILE"
  echo "  或重新打开终端"
fi

# ── 9. 收尾 ──
echo ""
echo "================================================"
echo -e "  ${GREEN}安装完成！${NC}"
echo "================================================"
echo ""
if [ -n "${RC_FILE:-}" ]; then
  if command -v asc &>/dev/null; then
    info "asc 命令已在当前 shell 可用"
  else
    echo -e "  ${YELLOW}提示：${NC}如果 asc 命令还不可用，请执行："
    echo ""
    echo "    source $RC_FILE"
    echo ""
    echo "  或重新打开终端。"
    echo ""
  fi
fi
echo "下一步：在你的项目目录中运行："
echo ""
echo "  asc install"
echo ""
echo "这将引导你配置 App Store Connect 凭证。"

# ── 10. 恢复调用方 shell 的选项，并应用 PATH ──
# Restore the caller's shell options that were active before this script ran.
# This prevents set -euo pipefail from leaking into the interactive shell when
# the script is sourced (source <(...)), which would cause any mistyped command
# to terminate the entire shell session.
[[ "$_asc_saved_opts" != *e* ]] && set +e
[[ "$_asc_saved_opts" != *u* ]] && set +u
set +o pipefail 2>/dev/null || true
unset _asc_saved_opts

# Apply PATH to the current (parent) shell now that options are safe again.
if [ "${_asc_need_path_export:-0}" = "1" ] && [ -d "${USER_BIN:-}" ]; then
  export PATH="$USER_BIN:$PATH"
fi
unset _asc_need_path_export
