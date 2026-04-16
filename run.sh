#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/upload_to_appstore.py"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
CONFIG_DIR="$SCRIPT_DIR/config"
ENV_FILE="$CONFIG_DIR/.env"
ENV_EXAMPLE="$CONFIG_DIR/.env.example"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; }

show_help() {
    echo -e "${BOLD}App Store Connect 上传工具${NC}"
    echo ""
    echo -e "${CYAN}用法:${NC}"
    echo "  ./run.sh [命令] [选项]"
    echo ""
    echo -e "${CYAN}命令:${NC}"
    echo -e "  ${BOLD}upload${NC}              上传全部（元数据 + 截图）          ${GREEN}← 默认${NC}"
    echo -e "  ${BOLD}metadata${NC}            仅上传元数据（名称、描述、关键词等）"
    echo -e "  ${BOLD}screenshots${NC}         仅上传截图"
    echo -e "  ${BOLD}whats-new${NC}           更新版本描述 (What's New)"
    echo -e "  ${BOLD}check${NC}               仅检查环境和配置，不执行上传"
    echo -e "  ${BOLD}help${NC}                显示此帮助信息"
    echo ""
    echo -e "${CYAN}选项:${NC}"
    echo "  --dry-run             预览模式，不实际上传"
    echo "  --csv PATH            CSV 元数据文件路径 (默认: data/appstore_info.csv)"
    echo "  --screenshots PATH    截图目录路径 (默认: data/screenshots)"
    echo "  --display-type TYPE   截图设备类型 (如 APP_IPHONE_67)，不指定则自动检测"
    echo ""
    echo -e "${CYAN}更新版本描述 (whats-new) 选项:${NC}"
    echo "  --text TEXT           更新描述文本，对所有语言生效"
    echo "  --file PATH           从文件读取多语言更新描述"
    echo "  --locales LOCALES     限定语言，逗号分隔 (如 zh-Hans,en-US)"
    echo ""
    echo -e "${CYAN}示例:${NC}"
    echo "  ./run.sh                                  上传全部"
    echo "  ./run.sh upload --dry-run                 预览上传内容"
    echo "  ./run.sh metadata                         仅上传元数据"
    echo "  ./run.sh screenshots                      仅上传截图"
    echo "  ./run.sh screenshots --display-type APP_IPHONE_67"
    echo "  ./run.sh whats-new --text \"修复已知问题\"     所有语言使用同一描述"
    echo "  ./run.sh whats-new --text \"Bug fixes\" --locales en-US"
    echo "  ./run.sh whats-new --file data/whats_new.txt"
    echo "  ./run.sh check                            检查环境配置"
    echo ""
    echo -e "${CYAN}更新描述文件格式 (whats_new.txt):${NC}"
    echo "  zh-Hans:"
    echo "  - 修复已知问题"
    echo "  - 提升视频生成速度"
    echo "  ---"
    echo "  en-US:"
    echo "  - Bug fixes"
    echo "  - Faster video generation"
    echo ""
}

# ── 无参数或 help 命令时显示帮助 ──
if [ $# -eq 0 ] || [ "${1:-}" = "help" ] || [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    show_help
    exit 0
fi

# ── 解析命令 ──
COMMAND="${1:-upload}"
shift

check_env() {
    # ── 检查 Python ──
    PYTHON=""
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
                PYTHON="$cmd"
                info "Python: $("$PYTHON" --version)"
                break
            fi
        fi
    done

    if [ -z "$PYTHON" ]; then
        error "需要 Python 3.9+，请先安装"
        exit 1
    fi

    # ── 检查并安装依赖 ──
    MISSING=0
    for pkg in jwt requests PIL dotenv cryptography; do
        mod="$pkg"
        if ! "$PYTHON" -c "import $mod" 2>/dev/null; then
            MISSING=1
            break
        fi
    done

    if [ "$MISSING" -eq 1 ]; then
        warn "检测到缺少依赖，正在安装..."
        if "$PYTHON" -m pip install --quiet -r "$REQUIREMENTS"; then
            info "依赖安装完成"
        else
            error "依赖安装失败，请手动执行: pip install -r $REQUIREMENTS"
            exit 1
        fi
    else
        info "依赖已就绪"
    fi

    # ── 检查 .env 配置 ──
    if [ ! -f "$ENV_FILE" ]; then
        warn ".env 文件不存在"
        if [ -f "$ENV_EXAMPLE" ]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            warn "已从 .env.example 创建 .env，请编辑后重新运行:"
            warn "  vim $ENV_FILE"
            exit 1
        else
            error "找不到 .env 和 .env.example，请手动创建 .env 配置文件"
            exit 1
        fi
    fi

    MISSING_KEYS=()
    for key in ISSUER_ID KEY_ID KEY_FILE APP_ID; do
        val=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-)
        if [ -z "$val" ] || echo "$val" | grep -qE '^(xxxxxxxx|XXXXXXXXXX|你的|1234567890)'; then
            MISSING_KEYS+=("$key")
        fi
    done

    if [ ${#MISSING_KEYS[@]} -gt 0 ]; then
        error "以下配置项未填写: ${MISSING_KEYS[*]}"
        warn "请编辑 .env 文件: vim $ENV_FILE"
        exit 1
    fi

    KEY_FILE_VAL=$(grep "^KEY_FILE=" "$ENV_FILE" | head -1 | cut -d= -f2-)
    if [[ "$KEY_FILE_VAL" != /* ]]; then
        KEY_FILE_VAL="$CONFIG_DIR/$KEY_FILE_VAL"
    fi
    if [ ! -f "$KEY_FILE_VAL" ]; then
        error "私钥文件不存在: $KEY_FILE_VAL"
        exit 1
    fi
    info "配置检查通过"
}

# ── 执行命令 ──
check_env

case "$COMMAND" in
    check)
        echo ""
        info "环境和配置全部正常，可以运行上传命令。"
        ;;
    upload)
        echo ""
        exec "$PYTHON" "$PYTHON_SCRIPT" "$@"
        ;;
    metadata)
        echo ""
        exec "$PYTHON" "$PYTHON_SCRIPT" --metadata-only "$@"
        ;;
    screenshots)
        echo ""
        exec "$PYTHON" "$PYTHON_SCRIPT" --screenshots-only "$@"
        ;;
    whats-new)
        WHATS_NEW_ARGS=()
        while [ $# -gt 0 ]; do
            case "$1" in
                --text)     WHATS_NEW_ARGS+=(--whats-new "$2"); shift 2 ;;
                --file)     WHATS_NEW_ARGS+=(--whats-new-file "$2"); shift 2 ;;
                --locales)  WHATS_NEW_ARGS+=(--whats-new-locales "$2"); shift 2 ;;
                *)          WHATS_NEW_ARGS+=("$1"); shift ;;
            esac
        done
        if [ ${#WHATS_NEW_ARGS[@]} -eq 0 ]; then
            error "请指定更新内容: --text \"描述\" 或 --file 文件路径"
            echo ""
            echo "示例:"
            echo "  ./run.sh whats-new --text \"修复已知问题\""
            echo "  ./run.sh whats-new --file data/whats_new.txt"
            exit 1
        fi
        echo ""
        exec "$PYTHON" "$PYTHON_SCRIPT" "${WHATS_NEW_ARGS[@]}"
        ;;
    *)
        error "未知命令: $COMMAND"
        echo ""
        show_help
        exit 1
        ;;
esac
