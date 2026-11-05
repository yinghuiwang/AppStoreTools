#!/usr/bin/env bash
# When sourced, set -euo pipefail would leak into the caller's shell and cause
# any subsequent failed command (e.g. a typo) to silently kill the session.
# Save current options and restore them at the end of this script.
# 管道用法：curl -fsSL https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.sh | bash
# 安装 PyPI 已发布的 asc-appstore-tools，不安装未发布分支。
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

  unset _asc_saved_opts _asc_sourced _asc_need_path_export _asc_need_local_bin_export _asc_restore_shell _asc_finish _asc_stop _asc_path_line_user _asc_path_line_local
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
      echo "  --branch, --ref VALUE  Install a specific GitHub branch, tag, or commit"
      echo "  -h, --help            Show this help"
      echo ""
      echo "Default install is from PyPI (asc-appstore-tools)."
      echo "This script targets macOS / Linux, including WSL."
      echo "Windows (PowerShell, not Git Bash):"
      echo "  irm https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.ps1 | iex"
      echo "Uninstall: pipx uninstall asc-appstore-tools"
      echo "           pip uninstall asc-appstore-tools"
      echo "           asc uninstall --yes"
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
  MINGW*|MSYS*|CYGWIN*)
    # WSL 的 uname 是 Linux，不会进到这里。
    echo "install.sh 不能在 Windows 原生环境（含 Git Bash）安装。"
    echo "请在 PowerShell 中执行："
    echo ""
    echo "  irm https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.ps1 | iex"
    echo ""
    echo "这一行安装的是 PyPI 已发布版本。Windows 定时任务和后台 web 的兼容改动尚未发布；构建/上传/发布在 Windows 上不可用。"
    _asc_stop 0
    ;;
  *)
    fatal "不支持的操作系统: $OS"
    echo "  若在 Windows 上，请在 PowerShell 中执行："
    echo "    irm https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.ps1 | iex"
    _asc_stop 1
    ;;
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

LOCAL_BIN="$HOME/.local/bin"
VENV_DIR="$HOME/.local/share/asc-appstore-tools/venv"
_asc_need_local_bin_export=0
PYPI_SPEC="asc-appstore-tools"
GITHUB_REPO="git+https://github.com/yinghuiwang/AppStoreTools.git"

mkdir -p "$LOCAL_BIN"

_asc_install_spec() {
  local spec="$1"
  local label="$2"
  if command -v pipx &>/dev/null; then
    if pipx install --force "$spec"; then
      info "asc-appstore-tools 安装成功（pipx / ${label}）"
      return 0
    fi
    return 1
  fi
  if "$PYTHON" -m pip install --user --upgrade "$spec"; then
    info "asc-appstore-tools 安装成功（--user / ${label}）"
    return 0
  fi
  warn "当前 Python 环境禁止直接 pip 安装，改用独立虚拟环境..."
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    if ! "$PYTHON" -m venv "$VENV_DIR"; then
      error "创建虚拟环境失败。"
      if [ "$PLATFORM" = "Linux" ]; then
        echo "  Debian/Ubuntu 可尝试：sudo apt install python3-venv"
      fi
      return 1
    fi
    "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
  fi
  if "$VENV_DIR/bin/python" -m pip install --upgrade --force-reinstall "$spec"; then
    ln -sf "$VENV_DIR/bin/asc" "$LOCAL_BIN/asc"
    info "asc-appstore-tools 安装成功（独立虚拟环境 / ${label}）"
    return 0
  fi
  return 1
}

if [ -n "$INSTALL_REF" ]; then
  echo "正在从 GitHub 安装 asc-appstore-tools ${INSTALL_REF} ..."
  if ! _asc_install_spec "${GITHUB_REPO}@${INSTALL_REF}" "GitHub ${INSTALL_REF}"; then
    fatal "GitHub 安装失败，请检查网络或权限后重试"
    _asc_stop 1
  fi
else
  echo "正在从 PyPI 安装 asc-appstore-tools ..."
  if ! _asc_install_spec "$PYPI_SPEC" "PyPI"; then
    warn "PyPI 安装失败，回退到 GitHub"
    LATEST_TAG=""
    if command -v curl &>/dev/null; then
      LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/yinghuiwang/AppStoreTools/releases/latest" 2>/dev/null \
        | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('tag_name',''))" 2>/dev/null || true)
    fi
    if [ -n "$LATEST_TAG" ]; then
      GITHUB_URL="${GITHUB_REPO}@${LATEST_TAG}"
      echo "正在从 GitHub 安装 asc-appstore-tools ${LATEST_TAG} ..."
    else
      GITHUB_URL="$GITHUB_REPO"
      echo "正在从 GitHub 安装 asc-appstore-tools (main) ..."
    fi
    if ! _asc_install_spec "$GITHUB_URL" "GitHub"; then
      fatal "安装失败，请检查网络或权限后重试"
      _asc_stop 1
    fi
  fi
fi

# ── 7. 检测 pip bin 目录并写入 PATH ──
USER_BIN=$("$PYTHON" -m site --user-base 2>/dev/null)/bin
_asc_need_path_export=0
_asc_path_line_user=""
_asc_path_line_local=""
if { [ -d "$USER_BIN" ] && [[ ":$PATH:" != *":$USER_BIN:"* ]]; } || { [ -d "$LOCAL_BIN" ] && [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; }; then
  # 写入 shell 配置文件（已有同一路径则不追加）
  SHELL_NAME="$(basename "${SHELL:-bash}")"
  if [ "$SHELL_NAME" = "zsh" ]; then
    RC_FILE="$HOME/.zshrc"
  elif [ "$SHELL_NAME" = "bash" ]; then
    RC_FILE="$HOME/.bash_profile"
  else
    RC_FILE="$HOME/.profile"
  fi

  if [ -d "$USER_BIN" ] && [[ ":$PATH:" != *":$USER_BIN:"* ]]; then
    _asc_path_line_user="export PATH=\"$USER_BIN:\$PATH\""
    if ! grep -qF "$USER_BIN" "$RC_FILE" 2>/dev/null; then
      echo "" >> "$RC_FILE"
      echo "# Added by asc-appstore-tools installer" >> "$RC_FILE"
      echo "export PATH=\"$USER_BIN:\$PATH\"" >> "$RC_FILE"
      info "已将 $USER_BIN 写入 $RC_FILE"
    fi
  fi

  if [ -d "$LOCAL_BIN" ] && [[ ":$PATH:" != *":$LOCAL_BIN:"* ]] && [ "$LOCAL_BIN" != "$USER_BIN" ]; then
    _asc_path_line_local="export PATH=\"$LOCAL_BIN:\$PATH\""
    if ! grep -qF "$LOCAL_BIN" "$RC_FILE" 2>/dev/null; then
      echo "" >> "$RC_FILE"
      echo "# Added by asc-appstore-tools installer" >> "$RC_FILE"
      echo "export PATH=\"$LOCAL_BIN:\$PATH\"" >> "$RC_FILE"
      info "已将 $LOCAL_BIN 写入 $RC_FILE"
    fi
  fi

  # 标记需要在父 shell 中 export（source 时生效；管道执行只影响本进程）
  _asc_need_path_export=1
  _asc_need_local_bin_export=1
fi

# ── 8. 验证安装 ──
if command -v asc &>/dev/null; then
  info "asc 命令可用：$(command -v asc)"
elif [ -x "${USER_BIN:-}/asc" ]; then
  info "asc 已安装：${USER_BIN}/asc"
elif [ -x "${LOCAL_BIN:-}/asc" ]; then
  info "asc 已安装：${LOCAL_BIN}/asc"
else
  warn "当前 PATH 中还没有 asc。"
fi

# ── 9. 收尾 ──
echo ""
echo "================================================"
echo -e "  ${GREEN}安装完成！${NC}"
echo "================================================"
echo ""
if [ -n "${_asc_path_line_user}" ] || [ -n "${_asc_path_line_local}" ]; then
  if [ "$_asc_sourced" = "1" ]; then
    echo -e "  ${YELLOW}提示：${NC}若当前终端还不能运行 asc，请执行：source ${RC_FILE}"
  else
    echo -e "  ${YELLOW}提示：${NC}这次是在管道里安装的，不会改你当前终端的 PATH。请新开一个终端再运行 asc。"
  fi
  echo "  需要加入 PATH 的内容如下（已写入 shell 配置；重复安装不会再追加）："
  echo ""
  if [ -n "${_asc_path_line_user}" ]; then
    echo "    ${_asc_path_line_user}"
  fi
  if [ -n "${_asc_path_line_local}" ]; then
    echo "    ${_asc_path_line_local}"
  fi
  echo ""
fi
echo "下一步：在你的项目目录中运行："
echo ""
echo "  asc install"
echo ""
echo "这将引导你配置 App Store Connect 凭证。"

# ── 10. 恢复调用方 shell 的选项，并应用 PATH ──
_asc_stop 0
