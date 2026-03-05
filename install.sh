#!/usr/bin/env bash
# ============================================================
# 🩺 WiFiDoctor 安装脚本
# 功能：安装依赖 + 创建全局命令 wificheck
# 用法：chmod +x install.sh && sudo ./install.sh
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=""
VENV_DIR="$SCRIPT_DIR/.venv"
LINK_PATH="/usr/local/bin/wificheck"

echo -e "${CYAN}🩺 WiFiDoctor 安装程序${NC}"
echo "================================================"

# ---------- 1. 检测 Python 3 ----------
echo -e "${YELLOW}[1/4] 检测 Python 环境...${NC}"
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}❌ 未找到 Python 3.9+，请先安装 Python${NC}"
    echo "   Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "   CentOS/RHEL:   sudo yum install python3"
    echo "   Arch:           sudo pacman -S python"
    exit 1
fi

echo -e "   ✅ 找到 $($PYTHON --version)"

# ---------- 2. 创建虚拟环境 & 安装依赖 ----------
echo -e "${YELLOW}[2/4] 创建虚拟环境并安装依赖...${NC}"
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
deactivate
echo -e "   ✅ 依赖安装完成"

# ---------- 3. 生成启动脚本 ----------
echo -e "${YELLOW}[3/4] 生成启动脚本...${NC}"
cat > "$SCRIPT_DIR/wificheck" << 'LAUNCHER'
#!/usr/bin/env bash
# WiFiDoctor 启动器 —— 自动激活虚拟环境并运行
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
python "$SCRIPT_DIR/wifi_doctor.py" "$@"
deactivate 2>/dev/null
LAUNCHER
chmod +x "$SCRIPT_DIR/wificheck"
echo -e "   ✅ 启动脚本已生成: $SCRIPT_DIR/wificheck"

# ---------- 4. 创建全局软链接 ----------
echo -e "${YELLOW}[4/4] 创建全局命令...${NC}"
if [ "$(id -u)" -eq 0 ]; then
    ln -sf "$SCRIPT_DIR/wificheck" "$LINK_PATH"
    echo -e "   ✅ 已创建全局命令: ${GREEN}wificheck${NC}"
else
    echo -e "   ${YELLOW}⚠️  非 root 用户，跳过全局命令安装${NC}"
    echo -e "   你可以手动执行:  sudo ln -sf $SCRIPT_DIR/wificheck $LINK_PATH"
    echo -e "   或直接运行:      $SCRIPT_DIR/wificheck"
fi

echo ""
echo "================================================"
echo -e "${GREEN}🎉 安装完成！使用方法：${NC}"
echo ""
echo -e "  ${CYAN}wificheck${NC}              # 完整诊断"
echo -e "  ${CYAN}wificheck --scan${NC}       # 仅扫描 WiFi"
echo -e "  ${CYAN}wificheck --test${NC}       # 仅测速"
echo -e "  ${CYAN}wificheck --monitor${NC}    # 持续监控"
echo -e "  ${CYAN}wificheck --report${NC}     # 生成报告"
echo ""
