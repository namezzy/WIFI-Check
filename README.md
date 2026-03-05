# 🩺 WiFiDoctor

> 跨平台 WiFi 网络诊断工具 — 扫描、测速、诊断、报告，一条命令搞定。

支持 **Windows / Linux / macOS**，Python 3.9+。

---

## ✨ 功能一览

| 模块 | 说明 |
|------|------|
| 📡 **WiFi 扫描** | 列出所有可见网络：SSID、信号强度 (dBm)、信道、频段 (2.4/5 GHz)、加密方式 |
| 🔗 **连接信息** | 当前 SSID、本地 IP、网关、DNS、MAC 地址、连接时长 |
| ⚡ **速度测试** | 下载 / 上传速度、延迟 (ping)、抖动、丢包率 |
| 🌍 **公网 IP 检测** | 公网 IP、地理位置、ISP、运营商信息 |
| 🛡️ **IP 纯净度** | 代理/VPN/数据中心检测，0-100 纯净度评分，中文风险提示 |
| 🧠 **智能诊断** | 自动识别信号弱、信道拥堵、DNS 故障、高延迟等问题并给出优化建议 |
| 📊 **报告导出** | Rich 彩色终端输出 + JSON + Bootstrap 5 & Chart.js 交互式 HTML 报告 |

---

## 📦 安装

### Linux / macOS 一键安装（推荐）

```bash
chmod +x install.sh && sudo ./install.sh
```

安装后可在任意位置使用 `wificheck` 命令：

```bash
wificheck              # 完整诊断
wificheck --scan       # 仅扫描
wificheck --report     # 生成报告
```

### 手动安装（全平台）

```bash
pip install -r requirements.txt
python wifi_doctor.py
```

### 依赖

| 包名 | 用途 | 必需 |
|------|------|------|
| `psutil` | 系统与网络接口信息 | ✅ |
| `rich` | 终端美化输出 | ✅ |
| `speedtest-cli` | 网速测试 | ⬚ 可选 |
| `requests` | 公网 IP / 纯净度检测 | ⬚ 可选 |
| `python-dotenv` | 环境变量管理 | ⬚ 可选 |

> 缺少可选依赖时对应功能会自动跳过，不影响其他模块。

---

## 🚀 使用方法

```bash
python wifi_doctor.py                  # 完整诊断（默认）
python wifi_doctor.py --scan           # 仅扫描 WiFi 网络
python wifi_doctor.py --test           # 仅测速 + 延迟
python wifi_doctor.py --monitor        # 持续监控（默认 10 秒刷新）
python wifi_doctor.py --monitor --interval 5   # 自定义监控间隔
python wifi_doctor.py --report         # 完整诊断 + 导出 JSON & HTML 报告
```

### 命令行参数

| 参数 | 说明 |
|------|------|
| `--scan` | 仅扫描 WiFi 网络 |
| `--test` | 仅运行速度和延迟测试 |
| `--monitor` | 持续监控模式 |
| `--report` | 完整诊断并保存报告（JSON + HTML） |
| `--interval N` | 监控间隔秒数（默认 10） |

---

## 🏗️ 项目结构

```
WIFI-Check/
├── wifi_doctor.py          # 主程序（单文件，~2200 行）
│   ├── WiFiScanner         #   WiFi 网络扫描（Windows/Linux/macOS 三平台适配）
│   ├── ConnectionInfo      #   当前连接信息采集
│   ├── SpeedTester         #   速度 & 延迟测试
│   ├── PublicIPChecker     #   公网 IP 查询 & 纯净度评分
│   ├── DiagnosisEngine     #   智能诊断引擎
│   ├── ReportGenerator     #   终端 / JSON / HTML 报告生成
│   └── WiFiDoctor          #   主控制器，协调以上所有模块
├── install.sh              # Linux/macOS 一键安装脚本（venv + 全局命令）
├── requirements.txt        # Python 依赖
└── README.md               # 本文档
```

### 核心架构

```
WiFiDoctor (主控制器)
  ├── WiFiScanner         → 扫描周围 WiFi（调用 netsh / iw / airport）
  ├── ConnectionInfo      → 读取本机网络配置（psutil + 系统命令）
  ├── SpeedTester         → 测速 & ping 多个 DNS 节点
  ├── PublicIPChecker     → 查询公网 IP + 纯净度评分
  ├── DiagnosisEngine     → 规则引擎：汇总数据 → 生成诊断建议
  └── ReportGenerator     → 输出终端 Rich 报告 / 导出 JSON & HTML
```

---

## 🛡️ IP 纯净度评分

基准分 100，按以下规则扣分：

| 条件 | 扣分 | 说明 |
|------|------|------|
| 住宅 IP + 无代理/托管 | 0 | 满分，最佳状态 |
| 检测到代理 / VPN | −25 | 部分站点可能限制访问 |
| 数据中心 / 托管 IP | −25 | 非住宅网络，高风险 |
| 移动网络 IP | −5 | 共享出口 IP |
| ISP 含云服务商特征 | −10 | 可能被识别为机房 IP |

---

## 📄 HTML 报告

- 🎨 Bootstrap 5 现代 UI，暗色/亮色主题一键切换
- 📊 Chart.js 交互式图表：信号仪表盘、速度柱形图、延迟对比图、纯净度环形图
- 📱 响应式布局，移动端友好
- 🖨️ 一键打印

生成的报告文件保存在运行目录下：
```
wifi_report_YYYYMMDD_HHMMSS.json
wifi_report_YYYYMMDD_HHMMSS.html
```

---

## ⚠️ 平台说明

| 平台 | 注意事项 |
|------|----------|
| **Windows** | WiFi 扫描需要 WLAN 服务已启用；部分功能需管理员权限 |
| **Linux** | WiFi 扫描可能需要 `sudo`，需安装 `iw` 或 `iwlist` |
| **macOS** | 使用系统自带 `airport` 工具扫描 |

> 无网络连接时仍可查看本地 WiFi 信息，公网 IP 检测会自动跳过。

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)
