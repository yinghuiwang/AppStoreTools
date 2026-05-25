#!/usr/bin/env bash
# When sourced, set -euo pipefail would leak into the caller's shell and cause
# any subsequent failed command (e.g. a typo) to silently kill the session.
# Save current options and restore them at the end of this script.
_asc_saved_opts="$-"
set -euo pipefail
_asc_sourced=0
(return 0 2>/dev/null) && _asc_sourced=1

_asc_restore_shell() {
  # Restore the caller's shell options that were active before this script ran.
  # This prevents set -euo pipefail from leaking into the interactive shell when
  # the script is sourced (source <(...)), including early failure paths.
  [[ "$_asc_saved_opts" != *e* ]] && set +e
  [[ "$_asc_saved_opts" != *u* ]] && set +u
  set +o pipefail 2>/dev/null || true

  # Apply PATH to the current (parent) shell now that options are safe again.
  if [ "${_asc_need_path_export:-0}" = "1" ] && [ -d "${USER_BIN:-}" ]; then
    export PATH="$USER_BIN:$PATH"
  fi
  if [ "${_asc_need_local_bin_export:-0}" = "1" ] && [ -d "${LOCAL_BIN:-}" ]; then
    export PATH="$LOCAL_BIN:$PATH"
  fi
}

_asc_finish() {
  local _asc_status="${1:-0}"
  local _asc_was_sourced="$_asc_sourced"

  _asc_restore_shell

  unset _asc_saved_opts _asc_sourced _asc_need_path_export _asc_need_local_bin_export _asc_restore_shell _asc_finish _asc_stop
  if [ "$_asc_was_sourced" = "1" ]; then
    local _asc_return_status="$_asc_status"
    return "$_asc_return_status"
  fi
  local _asc_exit_status="$_asc_status"
  exit "$_asc_exit_status"
}

_asc_stop() {
  local _asc_stop_status="${1:-0}"
  _asc_finish "$_asc_stop_status"
  return "$_asc_stop_status" 2>/dev/null || exit "$_asc_stop_status"
}

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }
fatal()   { error "$*"; }

INSTALL_REF="${ASC_INSTALL_REF:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch|--ref)
      if [ -z "${2:-}" ]; then
        fatal "$1 需要指定分支、tag 或 commit"
        _asc_stop 1
      fi
      INSTALL_REF="$2"
      shift 2
      ;;
    -h|--help)
      echo "App Store Connect Tools installer"
      echo ""
      echo "Usage:"
      echo "  curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh | bash"
      echo "  curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh | bash -s -- --branch BRANCH"
      echo ""
      echo "Options:"
      echo "  --branch, --ref VALUE  Install a specific branch, tag, or commit"
      echo "  -h, --help            Show this help"
      _asc_stop 0
      ;;
    *)
      fatal "未知参数: $1"
      _asc_stop 1
      ;;
  esac
done

echo "================================================"
echo "  App Store Connect Tools — 安装程序"
echo "================================================"
echo ""

# ── 1. 检测操作系统 ──
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macOS" ;;
  Linux)  PLATFORM="Linux" ;;
  *)      fatal "不支持的操作系统: $OS"; _asc_stop 1 ;;
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
  _asc_stop 1
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
    _asc_stop 1
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

if [ -n "$INSTALL_REF" ]; then
  GITHUB_URL="git+https://github.com/yinghuiwang/AppStoreTools.git@${INSTALL_REF}"
  echo "正在从 GitHub 安装 asc-appstore-tools ${INSTALL_REF} ..."
else
  echo "正在获取最新版本信息..."

  # 通过 GitHub Releases API 获取最新 tag
  LATEST_TAG=""
  if command -v curl &>/dev/null; then
    LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/yinghuiwang/AppStoreTools/releases/latest" 2>/dev/null \
      | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('tag_name',''))" 2>/dev/null || true)
  fi

  if [ -n "$LATEST_TAG" ]; then
    GITHUB_URL="git+https://github.com/yinghuiwang/AppStoreTools.git@${LATEST_TAG}"
    echo "正在从 GitHub 安装 asc-appstore-tools ${LATEST_TAG} ..."
  else
    GITHUB_URL="git+https://github.com/yinghuiwang/AppStoreTools.git"
    echo "正在从 GitHub 安装 asc-appstore-tools (main) ..."
  fi
fi

LOCAL_BIN="$HOME/.local/bin"
VENV_DIR="$HOME/.local/share/asc-appstore-tools/venv"
_asc_need_local_bin_export=0

mkdir -p "$LOCAL_BIN"

if command -v pipx &>/dev/null; then
  if pipx install --force "$GITHUB_URL"; then
    info "asc-appstore-tools 安装成功（pipx）"
  else
    fatal "pipx install 失败，请检查网络或权限后重试"
    _asc_stop 1
  fi
elif "$PYTHON" -m pip install --user --upgrade "$GITHUB_URL" 2>/dev/null; then
  info "asc-appstore-tools 安装成功（--user 模式）"
else
  warn "当前 Python 环境禁止直接 pip 安装，改用独立虚拟环境..."
  if ! "$PYTHON" -m venv "$VENV_DIR"; then
    error "创建虚拟环境失败。"
    if [ "$PLATFORM" = "Linux" ]; then
      echo "  Debian/Ubuntu 可尝试：sudo apt install python3-venv"
    fi
    _asc_stop 1
  fi

  VENV_PYTHON="$VENV_DIR/bin/python"
  "$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
  if "$VENV_PYTHON" -m pip install --upgrade --force-reinstall "$GITHUB_URL"; then
    ln -sf "$VENV_DIR/bin/asc" "$LOCAL_BIN/asc"
    info "asc-appstore-tools 安装成功（独立虚拟环境）"
  else
    fatal "虚拟环境内 pip install 失败，请检查网络后重试"
    _asc_stop 1
  fi
fi

# ── 7. 检测 pip bin 目录并写入 PATH ──
USER_BIN=$("$PYTHON" -m site --user-base 2>/dev/null)/bin
_asc_need_path_export=0
if { [ -d "$USER_BIN" ] && [[ ":$PATH:" != *":$USER_BIN:"* ]]; } || { [ -d "$LOCAL_BIN" ] && [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; }; then
  # 写入 shell 配置文件
  SHELL_NAME="$(basename "${SHELL:-bash}")"
  if [ "$SHELL_NAME" = "zsh" ]; then
    RC_FILE="$HOME/.zshrc"
  elif [ "$SHELL_NAME" = "bash" ]; then
    RC_FILE="$HOME/.bash_profile"
  else
    RC_FILE="$HOME/.profile"
  fi

  if [ -d "$USER_BIN" ] && [[ ":$PATH:" != *":$USER_BIN:"* ]] && ! grep -qF "$USER_BIN" "$RC_FILE" 2>/dev/null; then
    echo "" >> "$RC_FILE"
    echo "# Added by asc-appstore-tools installer" >> "$RC_FILE"
    echo "export PATH=\"$USER_BIN:\$PATH\"" >> "$RC_FILE"
    info "已将 $USER_BIN 写入 $RC_FILE"
  fi

  if [ -d "$LOCAL_BIN" ] && [[ ":$PATH:" != *":$LOCAL_BIN:"* ]] && ! grep -qF "$LOCAL_BIN" "$RC_FILE" 2>/dev/null; then
    echo "" >> "$RC_FILE"
    echo "# Added by asc-appstore-tools installer" >> "$RC_FILE"
    echo "export PATH=\"$LOCAL_BIN:\$PATH\"" >> "$RC_FILE"
    info "已将 $LOCAL_BIN 写入 $RC_FILE"
  fi

  # 标记需要在父 shell 中 export（不能在这里做，因为下面要恢复 set 选项）
  _asc_need_path_export=1
  _asc_need_local_bin_export=1
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
_asc_stop 0
