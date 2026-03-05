#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🩺 WiFiDoctor - WiFi 网络诊断工具 v2.0
========================================
功能：WiFi 扫描、连接信息、速度测试、公网IP与IP纯净度检测、智能诊断、美观报告
平台：Windows / Linux / macOS
作者：WiFiDoctor Team
"""

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:
    print("❌ 缺少依赖: psutil，请运行 pip install -r requirements.txt")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.layout import Layout
    from rich.text import Text
    from rich.live import Live
    from rich import box
except ImportError:
    print("❌ 缺少依赖: rich，请运行 pip install -r requirements.txt")
    sys.exit(1)

try:
    import speedtest
except ImportError:
    speedtest = None  # 速度测试为可选功能

try:
    import requests
except ImportError:
    requests = None  # 公网 IP 检测为可选功能

# ============================================================
# 全局常量和配置
# ============================================================

SYSTEM = platform.system()  # "Windows", "Linux", "Darwin"
console = Console()

# 延迟测试目标服务器
PING_TARGETS = {
    "Google DNS": "8.8.8.8",
    "Cloudflare DNS": "1.1.1.1",
    "Baidu DNS": "180.76.76.76",
}

# 诊断阈值
THRESHOLDS = {
    "signal_weak": -70,         # dBm，低于此值为信号弱
    "signal_very_weak": -80,    # dBm，低于此值为信号极弱
    "latency_high": 100,        # ms，高于此值为高延迟
    "latency_very_high": 200,   # ms
    "packet_loss_high": 5,      # %，高于此值为高丢包
    "channel_congestion": 3,    # 同信道 AP 数量超过此值为拥堵
    "speed_slow_dl": 10,        # Mbps，下载速度低于此值为慢
    "speed_slow_ul": 5,         # Mbps，上传速度低于此值为慢
}


# ============================================================
# 工具函数
# ============================================================

def run_command(cmd: str, timeout: int = 15, shell: bool = True) -> Tuple[str, str, int]:
    """执行系统命令，返回 (stdout, stderr, returncode)"""
    try:
        # 在 Windows 上隐藏子进程窗口
        startupinfo = None
        if SYSTEM == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        result = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True,
            timeout=timeout, startupinfo=startupinfo,
            encoding="utf-8", errors="replace"
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "命令执行超时", -1
    except Exception as e:
        return "", str(e), -1


def rssi_to_quality(rssi: int) -> int:
    """将 RSSI (dBm) 转换为信号质量百分比 (0-100)"""
    if rssi >= -50:
        return 100
    elif rssi <= -100:
        return 0
    else:
        return 2 * (rssi + 100)


def channel_to_band(channel: int) -> str:
    """根据信道号判断频段"""
    if 1 <= channel <= 14:
        return "2.4 GHz"
    elif 36 <= channel <= 177:
        return "5 GHz"
    elif channel > 177:
        return "6 GHz"
    return "未知"


def safe_int(value: str, default: int = 0) -> int:
    """安全的整数转换"""
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return default


def safe_float(value: str, default: float = 0.0) -> float:
    """安全的浮点数转换"""
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return default


# ============================================================
# 模块 1: WiFi 扫描
# ============================================================

class WiFiScanner:
    """WiFi 网络扫描器 - 跨平台实现"""

    def __init__(self):
        self.networks: List[Dict[str, Any]] = []
        self.current_ssid: Optional[str] = None
        self.current_bssid: Optional[str] = None

    def scan(self) -> List[Dict[str, Any]]:
        """扫描所有可见 WiFi 网络"""
        self._get_current_connection()

        if SYSTEM == "Windows":
            self._scan_windows()
        elif SYSTEM == "Linux":
            self._scan_linux()
        elif SYSTEM == "Darwin":
            self._scan_macos()
        else:
            console.print(f"[red]❌ 不支持的操作系统: {SYSTEM}[/red]")

        return self.networks

    def _get_current_connection(self):
        """获取当前连接的 WiFi 信息"""
        if SYSTEM == "Windows":
            stdout, _, rc = run_command("netsh wlan show interfaces")
            if rc == 0:
                for line in stdout.splitlines():
                    line = line.strip()
                    if "SSID" in line and "BSSID" not in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            self.current_ssid = parts[1].strip()
                    elif "BSSID" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            self.current_bssid = parts[1].strip()
        elif SYSTEM == "Linux":
            stdout, _, rc = run_command("iwgetid -r")
            if rc == 0 and stdout:
                self.current_ssid = stdout.strip()
            stdout2, _, rc2 = run_command("iwgetid -a -r")
            if rc2 == 0 and stdout2:
                self.current_bssid = stdout2.strip()
        elif SYSTEM == "Darwin":
            # macOS: 使用 airport 或 networksetup
            airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            stdout, _, rc = run_command(f"{airport} -I")
            if rc == 0:
                for line in stdout.splitlines():
                    line = line.strip()
                    if line.startswith("SSID:"):
                        self.current_ssid = line.split(":", 1)[1].strip()
                    elif line.startswith("BSSID:"):
                        self.current_bssid = line.split(":", 1)[1].strip()

    def _scan_windows(self):
        """Windows 平台扫描"""
        stdout, stderr, rc = run_command("netsh wlan show networks mode=bssid")
        if rc != 0:
            console.print(f"[red]❌ WiFi 扫描失败: {stderr}[/red]")
            console.print("[yellow]💡 提示: 请确保 WLAN 服务已启用[/yellow]")
            return

        # 解析 netsh 输出
        current_network: Dict[str, Any] = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            # 匹配 SSID（排除 BSSID 行）
            if line.startswith("SSID") and "BSSID" not in line:
                # 保存上一个网络
                if current_network.get("bssid"):
                    self.networks.append(current_network)
                ssid_match = re.match(r"SSID\s+\d+\s*:\s*(.*)", line)
                if ssid_match:
                    current_network = {
                        "ssid": ssid_match.group(1).strip() or "<隐藏网络>",
                        "bssid": "",
                        "rssi": 0,
                        "quality": 0,
                        "channel": 0,
                        "band": "",
                        "security": "",
                        "is_current": False,
                    }
            elif "BSSID" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    bssid = parts[1].strip()
                    # 如果同一个 SSID 下有多个 BSSID，创建新条目
                    if current_network.get("bssid"):
                        self.networks.append(current_network)
                        current_network = dict(current_network)  # 浅拷贝
                    current_network["bssid"] = bssid
                    current_network["is_current"] = (
                        bssid.lower() == (self.current_bssid or "").lower()
                    )
            elif line.startswith("Signal") or line.startswith("信号"):
                # "Signal : 85%" 或 "信号 : 85%"
                match = re.search(r"(\d+)%", line)
                if match:
                    quality = int(match.group(1))
                    current_network["quality"] = quality
                    # 将百分比转回近似 RSSI: quality = 2*(rssi+100) => rssi = quality/2 - 100
                    current_network["rssi"] = int(quality / 2 - 100)
            elif line.startswith("Channel") or line.startswith("频道") or line.startswith("信道"):
                match = re.search(r"(\d+)", line)
                if match:
                    ch = int(match.group(1))
                    current_network["channel"] = ch
                    current_network["band"] = channel_to_band(ch)
            elif ("Authentication" in line or "身份验证" in line or
                  "认证" in line):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    current_network["security"] = parts[1].strip()
            elif ("Encryption" in line or "加密" in line):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    enc = parts[1].strip()
                    if current_network.get("security"):
                        current_network["security"] += f" / {enc}"
                    else:
                        current_network["security"] = enc

        # 保存最后一个网络
        if current_network.get("bssid"):
            self.networks.append(current_network)

    def _scan_linux(self):
        """Linux 平台扫描"""
        # 尝试使用 iw 命令
        stdout, stderr, rc = run_command("sudo iw dev wlan0 scan 2>/dev/null || iw dev wlan0 scan 2>/dev/null || iwlist wlan0 scan 2>/dev/null")
        if rc != 0:
            # 尝试 nmcli
            stdout, stderr, rc = run_command("nmcli -t -f SSID,BSSID,SIGNAL,CHAN,SECURITY dev wifi list")
            if rc == 0:
                self._parse_nmcli(stdout)
                return
            console.print(f"[red]❌ WiFi 扫描失败，请检查权限或安装 iw/nmcli[/red]")
            return

        if "iw" in stdout or "BSS " in stdout:
            self._parse_iw(stdout)
        else:
            self._parse_iwlist(stdout)

    def _parse_nmcli(self, stdout: str):
        """解析 nmcli 输出"""
        for line in stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 5:
                ssid = parts[0].strip().replace("\\:", ":") or "<隐藏网络>"
                bssid = parts[1].strip()
                signal = safe_int(parts[2])
                channel = safe_int(parts[3])
                security = parts[4].strip()

                rssi = int(signal / 2 - 100) if signal > 0 else -100

                self.networks.append({
                    "ssid": ssid,
                    "bssid": bssid,
                    "rssi": rssi,
                    "quality": signal,
                    "channel": channel,
                    "band": channel_to_band(channel),
                    "security": security or "Open",
                    "is_current": ssid == self.current_ssid,
                })

    def _parse_iw(self, stdout: str):
        """解析 iw scan 输出"""
        current: Dict[str, Any] = {}
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("BSS "):
                if current.get("bssid"):
                    self.networks.append(current)
                bssid_match = re.match(r"BSS\s+([0-9a-fA-F:]+)", line)
                bssid = bssid_match.group(1) if bssid_match else ""
                current = {
                    "ssid": "<隐藏网络>", "bssid": bssid,
                    "rssi": -100, "quality": 0, "channel": 0,
                    "band": "", "security": "Open", "is_current": False,
                }
            elif line.startswith("SSID:"):
                ssid = line.split(":", 1)[1].strip()
                if ssid:
                    current["ssid"] = ssid
                    current["is_current"] = ssid == self.current_ssid
            elif line.startswith("signal:"):
                match = re.search(r"(-?\d+\.?\d*)", line)
                if match:
                    rssi = int(float(match.group(1)))
                    current["rssi"] = rssi
                    current["quality"] = rssi_to_quality(rssi)
            elif "primary channel:" in line.lower() or line.startswith("* channel"):
                match = re.search(r"(\d+)", line)
                if match:
                    ch = int(match.group(1))
                    current["channel"] = ch
                    current["band"] = channel_to_band(ch)
            elif "WPA" in line or "RSN" in line:
                current["security"] = "WPA2/WPA3" if "RSN" in line else "WPA"

        if current.get("bssid"):
            self.networks.append(current)

    def _parse_iwlist(self, stdout: str):
        """解析 iwlist scan 输出"""
        cells = re.split(r"Cell \d+", stdout)
        for cell in cells[1:]:
            network: Dict[str, Any] = {
                "ssid": "<隐藏网络>", "bssid": "", "rssi": -100,
                "quality": 0, "channel": 0, "band": "",
                "security": "Open", "is_current": False,
            }
            # BSSID
            bssid_match = re.search(r"Address:\s*([0-9A-Fa-f:]+)", cell)
            if bssid_match:
                network["bssid"] = bssid_match.group(1)
            # SSID
            ssid_match = re.search(r'ESSID:"([^"]*)"', cell)
            if ssid_match and ssid_match.group(1):
                network["ssid"] = ssid_match.group(1)
                network["is_current"] = network["ssid"] == self.current_ssid
            # 信号
            qual_match = re.search(r"Signal level[=:]?\s*(-?\d+)", cell)
            if qual_match:
                rssi = int(qual_match.group(1))
                network["rssi"] = rssi
                network["quality"] = rssi_to_quality(rssi)
            # 信道
            ch_match = re.search(r"Channel[:\s]+(\d+)", cell)
            if ch_match:
                ch = int(ch_match.group(1))
                network["channel"] = ch
                network["band"] = channel_to_band(ch)
            # 加密
            if "WPA2" in cell:
                network["security"] = "WPA2"
            elif "WPA" in cell:
                network["security"] = "WPA"
            elif "on" in cell.lower() and "Encryption key:on" in cell:
                network["security"] = "WEP"

            self.networks.append(network)

    def _scan_macos(self):
        """macOS 平台扫描"""
        airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
        stdout, stderr, rc = run_command(f"{airport} -s")
        if rc != 0:
            console.print(f"[red]❌ WiFi 扫描失败: {stderr}[/red]")
            return

        lines = stdout.splitlines()
        if len(lines) < 2:
            return

        # 解析表头确定列位置
        header = lines[0]
        for line in lines[1:]:
            if not line.strip():
                continue
            # airport -s 输出格式: SSID BSSID RSSI CHANNEL HT CC SECURITY
            parts = line.split()
            if len(parts) >= 7:
                ssid = parts[0]
                bssid = parts[1]
                rssi = safe_int(parts[2], -100)
                # 信道可能是 "36,+1" 这样的格式
                ch_str = parts[3].split(",")[0]
                channel = safe_int(ch_str)
                security = " ".join(parts[6:]) if len(parts) > 6 else "Open"

                self.networks.append({
                    "ssid": ssid,
                    "bssid": bssid,
                    "rssi": rssi,
                    "quality": rssi_to_quality(rssi),
                    "channel": channel,
                    "band": channel_to_band(channel),
                    "security": security or "Open",
                    "is_current": ssid == self.current_ssid,
                })


# ============================================================
# 模块 2: 当前连接信息
# ============================================================

class ConnectionInfo:
    """获取当前 WiFi 连接的详细信息"""

    def __init__(self):
        self.info: Dict[str, Any] = {}

    def gather(self) -> Dict[str, Any]:
        """收集当前连接信息"""
        self.info = {
            "ssid": self._get_ssid(),
            "interface": self._get_interface(),
            "ip_address": "",
            "gateway": "",
            "dns_servers": [],
            "mac_address": "",
            "uptime": "",
            "connected": False,
        }
        self._get_network_details()
        return self.info

    def _get_ssid(self) -> str:
        """获取当前连接的 SSID"""
        if SYSTEM == "Windows":
            stdout, _, rc = run_command("netsh wlan show interfaces")
            if rc == 0:
                for line in stdout.splitlines():
                    line = line.strip()
                    if "SSID" in line and "BSSID" not in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2 and parts[1].strip():
                            return parts[1].strip()
        elif SYSTEM == "Linux":
            stdout, _, rc = run_command("iwgetid -r")
            if rc == 0 and stdout.strip():
                return stdout.strip()
        elif SYSTEM == "Darwin":
            airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            stdout, _, rc = run_command(f"{airport} -I")
            if rc == 0:
                for line in stdout.splitlines():
                    if "SSID:" in line and "BSSID:" not in line:
                        return line.split(":", 1)[1].strip()
        return "<未连接>"

    def _get_interface(self) -> str:
        """获取 WiFi 网络接口名称"""
        # 通过 psutil 查找无线接口
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()

        for iface_name, iface_stats in stats.items():
            if not iface_stats.isup:
                continue
            # 常见无线接口名称模式
            lower = iface_name.lower()
            if any(kw in lower for kw in ["wi-fi", "wifi", "wlan", "wireless", "wlp", "en0"]):
                return iface_name

        # 回退：返回第一个活跃的非回环接口
        for iface_name, iface_stats in stats.items():
            if iface_stats.isup and iface_name.lower() not in ("lo", "loopback"):
                if iface_name in addrs:
                    return iface_name
        return "未知"

    def _get_network_details(self):
        """获取 IP、网关、DNS、MAC 等详细信息"""
        iface = self.info["interface"]

        # 获取 IP 和 MAC 地址（通过 psutil）
        addrs = psutil.net_if_addrs()
        if iface in addrs:
            for addr in addrs[iface]:
                if addr.family == socket.AF_INET:
                    self.info["ip_address"] = addr.address
                    self.info["connected"] = True
                elif addr.family == psutil.AF_LINK:
                    self.info["mac_address"] = addr.address

        # 获取网关
        self.info["gateway"] = self._get_gateway()

        # 获取 DNS
        self.info["dns_servers"] = self._get_dns()

        # 获取连接时长
        self.info["uptime"] = self._get_uptime()

    def _get_gateway(self) -> str:
        """获取默认网关"""
        if SYSTEM == "Windows":
            stdout, _, rc = run_command("ipconfig")
            if rc == 0:
                # 查找默认网关
                lines = stdout.splitlines()
                for i, line in enumerate(lines):
                    if "Default Gateway" in line or "默认网关" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2 and parts[1].strip():
                            return parts[1].strip()
        elif SYSTEM in ("Linux", "Darwin"):
            stdout, _, rc = run_command("ip route show default 2>/dev/null || route -n get default 2>/dev/null")
            if rc == 0:
                match = re.search(r"(?:default via|gateway:)\s*([0-9.]+)", stdout)
                if match:
                    return match.group(1)

        # 回退: 使用 psutil（部分平台支持）
        try:
            gateways = psutil.net_if_addrs()  # psutil 无直接网关接口，此为占位
        except Exception:
            pass
        return "未知"

    def _get_dns(self) -> List[str]:
        """获取 DNS 服务器列表"""
        dns_list = []
        if SYSTEM == "Windows":
            stdout, _, rc = run_command("ipconfig /all")
            if rc == 0:
                in_wifi_section = False
                for line in stdout.splitlines():
                    lower = line.lower().strip()
                    if "wi-fi" in lower or "wireless" in lower or "wlan" in lower:
                        in_wifi_section = True
                    elif in_wifi_section and ("dns" in lower):
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            dns = parts[1].strip()
                            if dns and re.match(r"\d+\.\d+\.\d+\.\d+", dns):
                                dns_list.append(dns)
                    elif in_wifi_section and dns_list and re.match(r"\s+\d+\.\d+\.\d+\.\d+", line):
                        dns_list.append(line.strip())
                    elif line.strip() == "" and in_wifi_section and dns_list:
                        break
        elif SYSTEM in ("Linux", "Darwin"):
            # 读取 /etc/resolv.conf
            try:
                with open("/etc/resolv.conf", "r") as f:
                    for line in f:
                        if line.strip().startswith("nameserver"):
                            parts = line.split()
                            if len(parts) >= 2:
                                dns_list.append(parts[1])
            except FileNotFoundError:
                pass
            # 如果为空，尝试 systemd-resolve
            if not dns_list:
                stdout, _, rc = run_command("resolvectl status 2>/dev/null | grep 'DNS Servers'")
                if rc == 0:
                    for line in stdout.splitlines():
                        match = re.findall(r"(\d+\.\d+\.\d+\.\d+)", line)
                        dns_list.extend(match)

        return dns_list if dns_list else ["未知"]

    def _get_uptime(self) -> str:
        """获取网络接口连接时长（近似）"""
        if SYSTEM == "Windows":
            stdout, _, rc = run_command("netsh wlan show interfaces")
            if rc == 0:
                # Windows 没有直接显示连接时间，使用系统启动时间近似
                boot_time = datetime.fromtimestamp(psutil.boot_time())
                uptime = datetime.now() - boot_time
                return str(timedelta(seconds=int(uptime.total_seconds())))
        elif SYSTEM == "Linux":
            # 检查 /proc/net/wireless 的访问时间
            try:
                iface = self.info.get("interface", "wlan0")
                stdout, _, rc = run_command(f"cat /sys/class/net/{iface}/operstate")
                if rc == 0 and "up" in stdout:
                    # 使用 uptime 近似
                    boot_time = datetime.fromtimestamp(psutil.boot_time())
                    uptime = datetime.now() - boot_time
                    return str(timedelta(seconds=int(uptime.total_seconds())))
            except Exception:
                pass
        elif SYSTEM == "Darwin":
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            return str(timedelta(seconds=int(uptime.total_seconds())))

        return "未知"


# ============================================================
# 模块 3: 速度和延迟测试
# ============================================================

class SpeedTester:
    """网络速度和延迟测试"""

    def __init__(self):
        self.results: Dict[str, Any] = {
            "download_mbps": 0.0,
            "upload_mbps": 0.0,
            "ping_ms": 0.0,
            "jitter_ms": 0.0,
            "packet_loss_pct": 0.0,
            "latency_details": {},
            "server": "",
            "speed_test_ok": False,
        }

    def run_all(self) -> Dict[str, Any]:
        """运行所有测试"""
        console.print()
        console.print(Panel("⚡ 正在运行网络测试...", style="bold cyan"))

        # 延迟和丢包测试
        self._test_latency()

        # 速度测试
        self._test_speed()

        return self.results

    def _test_latency(self):
        """对多个服务器进行延迟和丢包测试"""
        all_latencies = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[bold]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("🏓 延迟测试", total=len(PING_TARGETS))

            for name, ip in PING_TARGETS.items():
                progress.update(task, description=f"🏓 Ping {name} ({ip})")
                avg_ms, loss, latencies = self._ping(ip)
                self.results["latency_details"][name] = {
                    "ip": ip,
                    "avg_ms": round(avg_ms, 2),
                    "packet_loss_pct": round(loss, 2),
                }
                all_latencies.extend(latencies)
                progress.advance(task)

        # 计算综合指标
        if all_latencies:
            self.results["ping_ms"] = round(sum(all_latencies) / len(all_latencies), 2)
            # 抖动 = 相邻延迟差的平均值
            if len(all_latencies) > 1:
                diffs = [abs(all_latencies[i] - all_latencies[i - 1]) for i in range(1, len(all_latencies))]
                self.results["jitter_ms"] = round(sum(diffs) / len(diffs), 2)

        # 综合丢包率
        total_loss = [v["packet_loss_pct"] for v in self.results["latency_details"].values()]
        if total_loss:
            self.results["packet_loss_pct"] = round(sum(total_loss) / len(total_loss), 2)

    def _ping(self, host: str, count: int = 10) -> Tuple[float, float, List[float]]:
        """Ping 指定主机，返回 (平均延迟ms, 丢包率%, 延迟列表)"""
        latencies: List[float] = []
        lost = 0

        if SYSTEM == "Windows":
            cmd = f"ping -n {count} -w 2000 {host}"
        else:
            cmd = f"ping -c {count} -W 2 {host}"

        stdout, _, rc = run_command(cmd, timeout=30)

        if rc != 0 and not stdout:
            return 999.0, 100.0, []

        # 解析延迟
        if SYSTEM == "Windows":
            # 提取每次 ping 的时间
            for match in re.finditer(r"[=<](\d+)\s*ms", stdout):
                latencies.append(float(match.group(1)))
            # 丢包率
            loss_match = re.search(r"\((\d+)%\s*(?:loss|丢失)\)", stdout)
            if loss_match:
                lost = float(loss_match.group(1))
            elif latencies:
                lost = ((count - len(latencies)) / count) * 100
            else:
                lost = 100.0
        else:
            # Linux/macOS: 提取 rtt 统计
            for match in re.finditer(r"time[=<]\s*([0-9.]+)\s*ms", stdout):
                latencies.append(float(match.group(1)))
            loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", stdout)
            if loss_match:
                lost = float(loss_match.group(1))
            elif latencies:
                lost = ((count - len(latencies)) / count) * 100
            else:
                lost = 100.0

        avg = sum(latencies) / len(latencies) if latencies else 999.0
        return avg, lost, latencies

    def _test_speed(self):
        """使用 speedtest-cli 测试上下行速度"""
        if speedtest is None:
            console.print("[yellow]⚠️  speedtest-cli 未安装，跳过速度测试[/yellow]")
            console.print("[dim]   安装方法: pip install speedtest-cli[/dim]")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("📡 正在选择最佳服务器...", total=None)

            try:
                st = speedtest.Speedtest()
                st.get_best_server()
                server = st.best
                self.results["server"] = f"{server.get('sponsor', '未知')} ({server.get('name', '')})"

                progress.update(task, description="⬇️  测试下载速度...")
                dl = st.download()
                self.results["download_mbps"] = round(dl / 1_000_000, 2)

                progress.update(task, description="⬆️  测试上传速度...")
                ul = st.upload()
                self.results["upload_mbps"] = round(ul / 1_000_000, 2)

                # speedtest 也提供 ping
                self.results["speed_test_ok"] = True
                if hasattr(st.results, "ping") and st.results.ping:
                    # 不覆盖我们自己的多服务器 ping 结果，仅记录
                    self.results["speedtest_ping_ms"] = round(st.results.ping, 2)

            except speedtest.SpeedtestBestServerFailure:
                console.print("[yellow]⚠️  无法找到合适的测速服务器[/yellow]")
            except speedtest.ConfigRetrievalError:
                console.print("[yellow]⚠️  无法获取 speedtest 配置，请检查网络连接[/yellow]")
            except Exception as e:
                console.print(f"[yellow]⚠️  速度测试失败: {e}[/yellow]")


# ============================================================
# 模块 4: 公网 IP 与 IP 纯净度检测
# ============================================================

class PublicIPChecker:
    """公网 IP 信息获取与纯净度分析"""

    def __init__(self):
        self.info: Dict[str, Any] = {
            "public_ip": "",
            "country": "",
            "city": "",
            "isp": "",
            "org": "",
            "as_number": "",
            "proxy": False,
            "hosting": False,
            "mobile": False,
            "ip_type": "未知",
            "purity_score": 0,
            "purity_label": "",
            "purity_detail": "",
            "risk_warnings": [],
            "check_ok": False,
        }

    def check(self) -> Dict[str, Any]:
        """获取公网 IP 信息并分析纯净度"""
        if requests is None:
            console.print("[yellow]⚠️  requests 未安装，跳过公网 IP 检测[/yellow]")
            console.print("[dim]   安装方法: pip install requests[/dim]")
            return self.info

        console.print()
        console.print(Panel("🌍 正在检测公网 IP 与纯净度...", style="bold cyan"))

        # 第一步：获取公网 IP
        public_ip = self._get_public_ip()
        if not public_ip:
            console.print("[yellow]⚠️  无法获取公网 IP，请检查网络连接[/yellow]")
            return self.info

        self.info["public_ip"] = public_ip

        # 第二步：获取 IP 详细信息（地理位置 + 纯净度字段）
        self._get_ip_details(public_ip)

        # 第三步：计算纯净度分数
        self._calculate_purity()

        self.info["check_ok"] = True
        return self.info

    def _get_public_ip(self) -> str:
        """通过多个 API 获取公网 IP，保证可靠性"""
        apis = [
            ("https://api.ipify.org?format=json", "ip"),
            ("https://httpbin.org/ip", "origin"),
            ("https://api.ip.sb/ip", None),
        ]

        for url, key in apis:
            try:
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    if key:
                        data = resp.json()
                        ip = data.get(key, "").strip()
                    else:
                        ip = resp.text.strip()
                    if ip and re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                        return ip
            except Exception:
                continue
        return ""

    def _get_ip_details(self, ip: str):
        """调用 ip-api.com 获取 IP 详细信息"""
        try:
            # ip-api.com 支持 proxy/hosting/mobile 字段
            url = f"http://ip-api.com/json/{ip}?fields=status,message,country,city,isp,org,as,proxy,hosting,mobile,query"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    self.info["country"] = data.get("country", "未知")
                    self.info["city"] = data.get("city", "未知")
                    self.info["isp"] = data.get("isp", "未知")
                    self.info["org"] = data.get("org", "未知")
                    self.info["as_number"] = data.get("as", "")
                    self.info["proxy"] = data.get("proxy", False)
                    self.info["hosting"] = data.get("hosting", False)
                    self.info["mobile"] = data.get("mobile", False)
        except Exception as e:
            console.print(f"[yellow]⚠️  IP 信息查询部分失败: {e}[/yellow]")

    def _calculate_purity(self):
        """计算 IP 纯净度分数 (0-100)"""
        score = 100
        warnings: List[str] = []

        # 判断 IP 类型
        is_proxy = self.info.get("proxy", False)
        is_hosting = self.info.get("hosting", False)
        is_mobile = self.info.get("mobile", False)

        # 确定 IP 类型标签
        if is_hosting and is_proxy:
            self.info["ip_type"] = "数据中心代理IP"
        elif is_hosting:
            self.info["ip_type"] = "数据中心IP"
        elif is_proxy:
            self.info["ip_type"] = "代理IP"
        elif is_mobile:
            self.info["ip_type"] = "移动网络IP"
        else:
            self.info["ip_type"] = "住宅IP"

        # 代理扣分
        if is_proxy:
            score -= 25
            warnings.append("⚠️ 检测到代理/VPN，可能影响部分网站正常访问和账号安全")

        # 数据中心/托管 IP 扣分
        if is_hosting:
            score -= 25
            warnings.append("⚠️ 数据中心IP，非住宅网络，部分平台可能标记为高风险")

        # 移动网络小幅扣分（共享出口 IP）
        if is_mobile:
            score -= 5
            warnings.append("ℹ️ 移动网络IP，出口 IP 可能被大量用户共享")

        # ISP 中包含常见云服务商关键词额外扣分
        isp_lower = (self.info.get("isp", "") + " " + self.info.get("org", "")).lower()
        cloud_keywords = ["amazon", "aws", "google cloud", "microsoft azure", "digitalocean",
                          "linode", "vultr", "ovh", "hetzner", "alibaba cloud", "tencent cloud",
                          "cloudflare", "oracle cloud"]
        for kw in cloud_keywords:
            if kw in isp_lower:
                if not is_hosting:  # 避免重复扣分
                    score -= 10
                warnings.append(f"⚠️ ISP/组织包含云服务商特征 ({kw.title()})，可能被识别为机房IP")
                break

        # 确保分数在合理范围
        score = max(0, min(100, score))
        self.info["purity_score"] = score
        self.info["risk_warnings"] = warnings

        # 纯净度等级标签
        if score >= 90:
            self.info["purity_label"] = "🟢 优秀"
            self.info["purity_detail"] = "住宅IP，纯净度高，适合所有场景"
        elif score >= 70:
            self.info["purity_label"] = "🟡 一般"
            self.info["purity_detail"] = "IP纯净度中等，部分敏感平台可能限制"
        elif score >= 50:
            self.info["purity_label"] = "🟠 较低"
            self.info["purity_detail"] = "IP纯净度较低，建议切换网络环境"
        else:
            self.info["purity_label"] = "🔴 差"
            self.info["purity_detail"] = "IP纯净度极低，强烈建议更换网络"


# ============================================================
# 模块 5: 智能诊断引擎
# ============================================================

class DiagnosisEngine:
    """智能诊断引擎 - 分析网络状况并给出中文建议"""

    def __init__(self):
        self.issues: List[Dict[str, Any]] = []
        self.score: int = 100  # 满分 100

    def diagnose(
        self,
        networks: List[Dict[str, Any]],
        conn_info: Dict[str, Any],
        speed_results: Dict[str, Any],
        ip_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        综合诊断，返回 (健康评分, 问题列表)
        每个问题: {"level": "error/warning/info", "title": str, "detail": str, "suggestion": str}
        """
        self.issues = []
        self.score = 100

        # 检查是否连接到 WiFi
        if not conn_info.get("connected") or conn_info.get("ssid") == "<未连接>":
            self._add_issue("error", "未连接 WiFi",
                            "当前设备未连接到任何 WiFi 网络",
                            "请检查 WiFi 是否开启，并连接到可用网络", 30)
            return self.score, self.issues

        # 1. 信号强度诊断
        self._check_signal(networks, conn_info)

        # 2. 信道拥堵检测
        self._check_channel_congestion(networks, conn_info)

        # 3. 互联网连通性
        self._check_internet()

        # 4. DNS 诊断
        self._check_dns(conn_info)

        # 5. 延迟诊断
        self._check_latency(speed_results)

        # 6. 丢包诊断
        self._check_packet_loss(speed_results)

        # 7. 速度诊断
        self._check_speed(speed_results)

        # 8. IP 纯净度诊断（新增）
        if ip_info:
            self._check_ip_purity(ip_info)

        # 确保分数不低于 0
        self.score = max(0, self.score)

        return self.score, self.issues

    def _add_issue(self, level: str, title: str, detail: str, suggestion: str, penalty: int = 0):
        """添加一个诊断问题"""
        self.issues.append({
            "level": level,
            "title": title,
            "detail": detail,
            "suggestion": suggestion,
        })
        self.score -= penalty

    def _check_signal(self, networks: List[Dict[str, Any]], conn_info: Dict[str, Any]):
        """信号强度检测"""
        current = [n for n in networks if n.get("is_current")]
        if not current:
            return

        rssi = current[0].get("rssi", 0)
        quality = current[0].get("quality", 0)
        band = current[0].get("band", "")

        if rssi < THRESHOLDS["signal_very_weak"]:
            self._add_issue(
                "error", "📶 信号极弱",
                f"当前信号强度: {rssi} dBm（质量 {quality}%），严重影响网络性能",
                "建议：1) 靠近路由器 2) 移除信号路径上的障碍物 3) 考虑添加 WiFi 信号放大器",
                25,
            )
        elif rssi < THRESHOLDS["signal_weak"]:
            self._add_issue(
                "warning", "📶 信号较弱",
                f"当前信号强度: {rssi} dBm（质量 {quality}%），可能影响网速和稳定性",
                "信号较弱，建议靠近路由器或切换 5GHz 频段" if band == "2.4 GHz"
                else "信号较弱，建议靠近路由器或减少障碍物",
                15,
            )

    def _check_channel_congestion(self, networks: List[Dict[str, Any]], conn_info: Dict[str, Any]):
        """信道拥堵检测"""
        current = [n for n in networks if n.get("is_current")]
        if not current:
            return

        my_channel = current[0].get("channel", 0)
        if my_channel == 0:
            return

        # 统计同信道的 AP 数量
        same_channel = [n for n in networks if n.get("channel") == my_channel and not n.get("is_current")]
        count = len(same_channel)

        if count >= THRESHOLDS["channel_congestion"]:
            band = current[0].get("band", "")
            self._add_issue(
                "warning", "📻 信道拥堵",
                f"当前信道 {my_channel} 上有 {count} 个其他 AP，可能导致干扰和速度下降",
                f"当前使用 {band} 频段信道 {my_channel}，建议在路由器设置中切换到较少使用的信道"
                + ("，或切换到 5GHz 频段" if band == "2.4 GHz" else ""),
                10,
            )

    def _check_internet(self):
        """互联网连通性检测"""
        # 快速测试：尝试连接几个知名 IP
        test_hosts = [("8.8.8.8", 53), ("1.1.1.1", 53), ("114.114.114.114", 53)]
        reachable = False

        for host, port in test_hosts:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.close()
                reachable = True
                break
            except (socket.timeout, OSError):
                continue

        if not reachable:
            self._add_issue(
                "error", "🌐 无法连接互联网",
                "已连接 WiFi，但无法访问外部网络",
                "建议：1) 检查路由器是否正常连接到互联网 2) 重启路由器 3) 检查是否需要登录认证页面",
                30,
            )

    def _check_dns(self, conn_info: Dict[str, Any]):
        """DNS 解析检测"""
        test_domains = ["www.baidu.com", "www.google.com", "www.cloudflare.com"]
        resolved = 0

        for domain in test_domains:
            try:
                socket.setdefaulttimeout(3)
                socket.getaddrinfo(domain, 80)
                resolved += 1
            except (socket.gaierror, socket.timeout, OSError):
                continue

        if resolved == 0:
            self._add_issue(
                "error", "🔍 DNS 解析失败",
                "无法解析任何域名，DNS 服务可能故障",
                "建议：1) 在网络设置中手动指定 DNS 为 223.5.5.5（阿里）或 8.8.8.8（Google）2) 重启路由器",
                20,
            )
        elif resolved < len(test_domains):
            self._add_issue(
                "warning", "🔍 DNS 部分故障",
                f"仅能解析 {resolved}/{len(test_domains)} 个测试域名",
                "建议更换 DNS 服务器为 223.5.5.5 或 8.8.8.8",
                5,
            )

    def _check_latency(self, speed_results: Dict[str, Any]):
        """延迟检测"""
        ping = speed_results.get("ping_ms", 0)
        jitter = speed_results.get("jitter_ms", 0)

        if ping >= THRESHOLDS["latency_very_high"]:
            self._add_issue(
                "error", "⏱️ 延迟极高",
                f"平均延迟 {ping}ms，抖动 {jitter}ms，严重影响实时应用（视频通话/游戏）",
                "建议：1) 检查是否有大量设备占用带宽 2) 重启路由器 3) 联系运营商检查线路",
                20,
            )
        elif ping >= THRESHOLDS["latency_high"]:
            self._add_issue(
                "warning", "⏱️ 延迟偏高",
                f"平均延迟 {ping}ms，抖动 {jitter}ms，可能影响实时应用",
                "网络延迟偏高，建议减少同时连接设备数量或检查是否有后台大流量下载",
                10,
            )

    def _check_packet_loss(self, speed_results: Dict[str, Any]):
        """丢包率检测"""
        loss = speed_results.get("packet_loss_pct", 0)

        if loss > THRESHOLDS["packet_loss_high"]:
            self._add_issue(
                "error" if loss > 15 else "warning",
                "📦 丢包率高",
                f"平均丢包率 {loss}%，网络连接不稳定",
                "建议：1) 检查信号强度 2) 远离电磁干扰源（微波炉等）3) 检查网线连接是否松动",
                15 if loss > 15 else 8,
            )

    def _check_speed(self, speed_results: Dict[str, Any]):
        """速度检测"""
        if not speed_results.get("speed_test_ok"):
            return

        dl = speed_results.get("download_mbps", 0)
        ul = speed_results.get("upload_mbps", 0)

        if dl < THRESHOLDS["speed_slow_dl"]:
            self._add_issue(
                "warning", "⬇️ 下载速度慢",
                f"下载速度 {dl} Mbps，低于正常水平",
                "建议：1) 检查是否有其他设备占用带宽 2) 联系运营商确认套餐速率 3) 尝试切换 5GHz 频段",
                10,
            )

        if ul < THRESHOLDS["speed_slow_ul"]:
            self._add_issue(
                "warning", "⬆️ 上传速度慢",
                f"上传速度 {ul} Mbps，低于正常水平",
                "建议检查运营商套餐中的上传带宽限制",
                5,
            )

    def _check_ip_purity(self, ip_info: Dict[str, Any]):
        """IP 纯净度诊断"""
        if not ip_info.get("check_ok"):
            return

        purity = ip_info.get("purity_score", 100)
        ip_type = ip_info.get("ip_type", "未知")
        public_ip = ip_info.get("public_ip", "")

        if purity < 50:
            self._add_issue(
                "error", "🌐 IP 纯净度极低",
                f"公网IP {public_ip} 类型: {ip_type}，纯净度 {purity}/100",
                "当前IP被标记为高风险，建议：1) 断开代理/VPN 2) 切换到家庭宽带 3) 联系运营商确认IP类型",
                15,
            )
        elif purity < 70:
            self._add_issue(
                "warning", "🌐 IP 纯净度偏低",
                f"公网IP {public_ip} 类型: {ip_type}，纯净度 {purity}/100",
                "IP存在风险标记，部分平台可能限制访问，建议切换网络环境",
                8,
            )
        elif purity < 90:
            self._add_issue(
                "info", "🌐 IP 纯净度一般",
                f"公网IP {public_ip} 类型: {ip_type}，纯净度 {purity}/100",
                "IP基本正常，少数敏感平台可能有限制",
                0,
            )

        # 额外检查：内网 IP 泄漏到公网（NAT 相关警告）
        if ip_info.get("proxy") and not ip_info.get("hosting"):
            self._add_issue(
                "warning", "🔒 代理/VPN 检测",
                "当前网络被检测到使用代理或VPN",
                "如非本人设置，请检查是否有恶意软件篡改网络设置",
                5,
            )


# ============================================================
# 模块 6: 报告生成
# ============================================================

class ReportGenerator:
    """生成美观的终端报告和文件报告"""

    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def display_scan_results(self, networks: List[Dict[str, Any]]):
        """在终端显示 WiFi 扫描结果"""
        if not networks:
            console.print("[yellow]⚠️  未发现任何 WiFi 网络[/yellow]")
            return

        table = Table(
            title="📡 WiFi 网络扫描结果",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold cyan",
        )
        table.add_column("", style="bold", width=3)
        table.add_column("SSID", style="bold white", min_width=15)
        table.add_column("BSSID", style="dim")
        table.add_column("信号(dBm)", justify="center")
        table.add_column("质量", justify="center")
        table.add_column("信道", justify="center")
        table.add_column("频段", justify="center")
        table.add_column("加密方式", style="dim")

        # 按信号强度排序
        sorted_nets = sorted(networks, key=lambda x: x.get("rssi", -100), reverse=True)

        for net in sorted_nets:
            rssi = net.get("rssi", -100)
            quality = net.get("quality", 0)
            is_current = net.get("is_current", False)

            # 信号颜色
            if rssi >= -50:
                sig_color = "green"
                sig_icon = "🟢"
            elif rssi >= -60:
                sig_color = "green"
                sig_icon = "🟢"
            elif rssi >= -70:
                sig_color = "yellow"
                sig_icon = "🟡"
            else:
                sig_color = "red"
                sig_icon = "🔴"

            # 当前连接标记
            marker = "▶" if is_current else ""
            row_style = "bold green" if is_current else ""

            # 质量条
            bar_len = quality // 10
            quality_bar = "█" * bar_len + "░" * (10 - bar_len)

            table.add_row(
                marker,
                net.get("ssid", ""),
                net.get("bssid", ""),
                f"[{sig_color}]{rssi}[/{sig_color}]",
                f"[{sig_color}]{quality_bar} {quality}%[/{sig_color}]",
                str(net.get("channel", "")),
                net.get("band", ""),
                net.get("security", ""),
                style=row_style,
            )

        console.print()
        console.print(table)
        console.print(f"[dim]  ▶ 表示当前连接的网络  |  共发现 {len(networks)} 个网络[/dim]")

    def display_connection_info(self, info: Dict[str, Any]):
        """显示当前连接信息"""
        table = Table(
            title="🔗 当前连接信息",
            box=box.ROUNDED,
            show_header=False,
            title_style="bold cyan",
            min_width=50,
        )
        table.add_column("项目", style="bold", min_width=15)
        table.add_column("值", style="white")

        rows = [
            ("WiFi 名称 (SSID)", info.get("ssid", "未知")),
            ("网络接口", info.get("interface", "未知")),
            ("IP 地址", info.get("ip_address", "未知")),
            ("默认网关", info.get("gateway", "未知")),
            ("DNS 服务器", ", ".join(info.get("dns_servers", ["未知"]))),
            ("MAC 地址", info.get("mac_address", "未知")),
            ("连接时长", info.get("uptime", "未知")),
        ]

        for label, value in rows:
            table.add_row(label, str(value))

        console.print()
        console.print(table)

    def display_speed_results(self, results: Dict[str, Any]):
        """显示速度和延迟测试结果"""
        table = Table(
            title="⚡ 速度与延迟测试",
            box=box.ROUNDED,
            show_header=False,
            title_style="bold cyan",
            min_width=50,
        )
        table.add_column("指标", style="bold", min_width=15)
        table.add_column("结果", style="white")

        # 下载速度
        dl = results.get("download_mbps", 0)
        dl_color = "green" if dl >= 50 else "yellow" if dl >= 10 else "red"
        table.add_row("⬇️  下载速度", f"[{dl_color}]{dl} Mbps[/{dl_color}]")

        # 上传速度
        ul = results.get("upload_mbps", 0)
        ul_color = "green" if ul >= 20 else "yellow" if ul >= 5 else "red"
        table.add_row("⬆️  上传速度", f"[{ul_color}]{ul} Mbps[/{ul_color}]")

        # 延迟
        ping = results.get("ping_ms", 0)
        ping_color = "green" if ping < 50 else "yellow" if ping < 100 else "red"
        table.add_row("🏓 平均延迟", f"[{ping_color}]{ping} ms[/{ping_color}]")

        # 抖动
        jitter = results.get("jitter_ms", 0)
        jitter_color = "green" if jitter < 10 else "yellow" if jitter < 30 else "red"
        table.add_row("📊 抖动", f"[{jitter_color}]{jitter} ms[/{jitter_color}]")

        # 丢包
        loss = results.get("packet_loss_pct", 0)
        loss_color = "green" if loss < 1 else "yellow" if loss < 5 else "red"
        table.add_row("📦 丢包率", f"[{loss_color}]{loss}%[/{loss_color}]")

        if results.get("server"):
            table.add_row("🖥️  测速服务器", results["server"])

        console.print()
        console.print(table)

        # 各服务器延迟详情
        details = results.get("latency_details", {})
        if details:
            detail_table = Table(
                title="🏓 各服务器延迟详情",
                box=box.SIMPLE,
                title_style="bold",
            )
            detail_table.add_column("服务器", style="bold")
            detail_table.add_column("IP", style="dim")
            detail_table.add_column("延迟", justify="center")
            detail_table.add_column("丢包", justify="center")

            for name, info in details.items():
                avg = info.get("avg_ms", 0)
                ploss = info.get("packet_loss_pct", 0)
                lat_color = "green" if avg < 50 else "yellow" if avg < 100 else "red"
                loss_c = "green" if ploss < 1 else "yellow" if ploss < 5 else "red"

                detail_table.add_row(
                    name,
                    info.get("ip", ""),
                    f"[{lat_color}]{avg} ms[/{lat_color}]",
                    f"[{loss_c}]{ploss}%[/{loss_c}]",
                )

            console.print()
            console.print(detail_table)

    def display_ip_info(self, ip_info: Dict[str, Any]):
        """显示公网 IP 和纯净度信息"""
        if not ip_info.get("check_ok"):
            return

        purity = ip_info.get("purity_score", 0)
        if purity >= 90:
            p_color = "green"
        elif purity >= 70:
            p_color = "yellow"
        elif purity >= 50:
            p_color = "bright_red"
        else:
            p_color = "red"

        # IP 信息表
        table = Table(
            title="🌍 公网 IP 与纯净度分析",
            box=box.ROUNDED,
            show_header=False,
            title_style="bold cyan",
            min_width=50,
        )
        table.add_column("项目", style="bold", min_width=15)
        table.add_column("值", style="white")

        table.add_row("🌐 公网 IP", ip_info.get("public_ip", "未知"))
        table.add_row("🏳️ 国家", ip_info.get("country", "未知"))
        table.add_row("🏙️ 城市", ip_info.get("city", "未知"))
        table.add_row("📡 ISP", ip_info.get("isp", "未知"))
        table.add_row("🏢 组织", ip_info.get("org", "未知"))
        table.add_row("🔢 AS号", ip_info.get("as_number", "未知"))
        table.add_row("📱 IP类型", ip_info.get("ip_type", "未知"))

        # 纯净度评分
        bar_len = purity // 5
        purity_bar = "█" * bar_len + "░" * (20 - bar_len)
        table.add_row("🛡️ 纯净度", f"[{p_color}]{purity_bar} {purity}/100[/{p_color}]")
        table.add_row("📊 等级", ip_info.get("purity_label", "未知"))

        console.print()
        console.print(table)

        # 风险警告
        warnings = ip_info.get("risk_warnings", [])
        if warnings:
            console.print()
            for w in warnings:
                console.print(f"  [{p_color}]{w}[/{p_color}]")
        else:
            console.print(f"\n  [green]✅ {ip_info.get('purity_detail', 'IP纯净度良好')}[/green]")

        console.print()

    def display_diagnosis(self, score: int, issues: List[Dict[str, Any]]):
        """显示诊断结果"""
        # 总体评分和状态
        if score >= 80:
            emoji = "✅"
            status = "网络状况良好"
            color = "green"
        elif score >= 60:
            emoji = "⚠️"
            status = "网络状况一般"
            color = "yellow"
        else:
            emoji = "❌"
            status = "网络状况较差"
            color = "red"

        # 评分面板
        score_bar = "█" * (score // 5) + "░" * (20 - score // 5)
        panel_content = (
            f"\n  {emoji}  [bold {color}]{status}[/bold {color}]\n\n"
            f"  健康评分: [{color}]{score_bar} {score}/100[/{color}]\n"
        )

        console.print()
        console.print(Panel(
            panel_content,
            title="🧠 智能诊断结果",
            border_style=color,
            padding=(0, 2),
        ))

        # 问题列表
        if not issues:
            console.print("\n  [green]🎉 未发现任何网络问题，一切正常！[/green]\n")
            return

        for issue in issues:
            level = issue["level"]
            if level == "error":
                icon = "❌"
                style = "red"
            elif level == "warning":
                icon = "⚠️"
                style = "yellow"
            else:
                icon = "ℹ️"
                style = "blue"

            console.print(f"\n  {icon}  [{style} bold]{issue['title']}[/{style} bold]")
            console.print(f"     [dim]{issue['detail']}[/dim]")
            console.print(f"     💡 [{style}]{issue['suggestion']}[/{style}]")

        console.print()

    def save_json(self, data: Dict[str, Any], filename: Optional[str] = None) -> str:
        """保存报告为 JSON 文件"""
        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wifi_report_{ts}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        return filename

    def save_html(self, data: Dict[str, Any], filename: Optional[str] = None) -> str:
        """保存报告为精美 HTML 文件（Bootstrap 5 + Chart.js）"""
        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wifi_report_{ts}.html"

        score = data.get("diagnosis", {}).get("score", 0)
        issues = data.get("diagnosis", {}).get("issues", [])
        conn = data.get("connection", {})
        speed = data.get("speed_test", {})
        networks = data.get("networks", [])
        ip_info = data.get("public_ip", {})

        # 评分颜色
        if score >= 80:
            score_color = "#198754"
            score_bg = "bg-success"
            status_text = "✅ 网络状况良好"
            status_badge = "success"
        elif score >= 60:
            score_color = "#ffc107"
            score_bg = "bg-warning"
            status_text = "⚠️ 网络状况一般"
            status_badge = "warning"
        else:
            score_color = "#dc3545"
            score_bg = "bg-danger"
            status_text = "❌ 网络状况较差"
            status_badge = "danger"

        # IP 纯净度颜色
        purity = ip_info.get("purity_score", 0)
        if purity >= 90:
            purity_color = "#198754"
            purity_badge = "success"
        elif purity >= 70:
            purity_color = "#ffc107"
            purity_badge = "warning"
        elif purity >= 50:
            purity_color = "#fd7e14"
            purity_badge = "warning"
        else:
            purity_color = "#dc3545"
            purity_badge = "danger"

        # 构建诊断问题 HTML
        issues_html = ""
        for issue in issues:
            level = issue["level"]
            alert_class = "danger" if level == "error" else "warning" if level == "warning" else "info"
            icon = "❌" if level == "error" else "⚠️" if level == "warning" else "ℹ️"
            issues_html += f"""
                <div class="alert alert-{alert_class} mb-2" role="alert">
                    <strong>{icon} {issue['title']}</strong><br>
                    <small class="text-muted">{issue['detail']}</small><br>
                    <span class="text-{alert_class}">💡 {issue['suggestion']}</span>
                </div>"""

        # 构建网络表格行
        net_rows = ""
        for net in sorted(networks, key=lambda x: x.get("rssi", -100), reverse=True):
            is_cur = net.get("is_current", False)
            marker = '<span class="badge bg-success">当前</span> ' if is_cur else ""
            rssi = net.get("rssi", -100)
            quality = net.get("quality", 0)
            if rssi >= -60:
                sig_badge = "success"
            elif rssi >= -70:
                sig_badge = "warning"
            else:
                sig_badge = "danger"
            row_class = 'class="table-success"' if is_cur else ""
            net_rows += f"""
                <tr {row_class}>
                    <td>{marker}{net.get('ssid', '')}</td>
                    <td><code>{net.get('bssid', '')}</code></td>
                    <td><span class="badge bg-{sig_badge}">{rssi} dBm</span></td>
                    <td>
                        <div class="progress" style="height:18px;min-width:80px;">
                            <div class="progress-bar bg-{sig_badge}" style="width:{quality}%">{quality}%</div>
                        </div>
                    </td>
                    <td>{net.get('channel', '')}</td>
                    <td><span class="badge bg-secondary">{net.get('band', '')}</span></td>
                    <td>{net.get('security', '')}</td>
                </tr>"""

        # IP 纯净度卡片
        ip_card_html = ""
        if ip_info.get("check_ok"):
            warnings_html = ""
            for w in ip_info.get("risk_warnings", []):
                warnings_html += f'<li class="list-group-item list-group-item-{purity_badge} py-1"><small>{w}</small></li>'
            if not warnings_html:
                warnings_html = f'<li class="list-group-item list-group-item-success py-1"><small>✅ {ip_info.get("purity_detail", "IP纯净度良好")}</small></li>'

            ip_card_html = f"""
            <div class="col-md-6">
                <div class="card border-{purity_badge} h-100">
                    <div class="card-header bg-{purity_badge} {"text-dark" if purity_badge == "warning" else "text-white"}">
                        <h5 class="mb-0">🛡️ IP 纯净度分析</h5>
                    </div>
                    <div class="card-body text-center">
                        <div style="position:relative;width:180px;height:180px;margin:0 auto;">
                            <canvas id="purityChart"></canvas>
                            <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:2em;font-weight:bold;color:{purity_color};">{purity}</div>
                        </div>
                        <h5 class="mt-2">{ip_info.get('purity_label', '')}</h5>
                        <p class="text-muted mb-1"><small>{ip_info.get('purity_detail', '')}</small></p>
                    </div>
                    <ul class="list-group list-group-flush">
                        <li class="list-group-item d-flex justify-content-between"><span>公网 IP</span><strong>{ip_info.get('public_ip', 'N/A')}</strong></li>
                        <li class="list-group-item d-flex justify-content-between"><span>IP 类型</span><span class="badge bg-{purity_badge}">{ip_info.get('ip_type', '未知')}</span></li>
                        <li class="list-group-item d-flex justify-content-between"><span>国家/城市</span><span>{ip_info.get('country', '')}/{ip_info.get('city', '')}</span></li>
                        <li class="list-group-item d-flex justify-content-between"><span>ISP</span><span>{ip_info.get('isp', 'N/A')}</span></li>
                        <li class="list-group-item d-flex justify-content-between"><span>组织</span><span>{ip_info.get('org', 'N/A')}</span></li>
                    </ul>
                    <div class="card-footer p-0">
                        <ul class="list-group list-group-flush">{warnings_html}</ul>
                    </div>
                </div>
            </div>"""

        # 延迟详情 JSON for Chart.js
        latency_labels_js = json.dumps([n for n in speed.get("latency_details", {}).keys()], ensure_ascii=False)
        latency_values_js = json.dumps([v.get("avg_ms", 0) for v in speed.get("latency_details", {}).values()])
        latency_loss_js = json.dumps([v.get("packet_loss_pct", 0) for v in speed.get("latency_details", {}).values()])

        # 当前信号信息
        current_net = next((n for n in networks if n.get("is_current")), {})
        current_rssi = current_net.get("rssi", -100)
        current_quality = current_net.get("quality", 0)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN" data-bs-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🩺 WiFiDoctor 诊断报告</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>
        :root {{ --score-color: {score_color}; --purity-color: {purity_color}; }}
        body {{ background: #f0f2f5; }}
        [data-bs-theme="dark"] body {{ background: #1a1d23; }}
        .hero-score {{ font-size: 4rem; font-weight: 800; color: var(--score-color); line-height: 1; }}
        .card {{ border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); border: none; }}
        .card-header {{ border-radius: 12px 12px 0 0 !important; }}
        .stat-value {{ font-size: 1.6rem; font-weight: 700; }}
        .stat-label {{ font-size: 0.8rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.5px; }}
        .table {{ margin-bottom: 0; }}
        .chart-container {{ position: relative; height: 220px; }}
        @media print {{
            .no-print {{ display: none !important; }}
            .card {{ box-shadow: none; border: 1px solid #dee2e6; }}
        }}
        @media (max-width: 768px) {{
            .hero-score {{ font-size: 3rem; }}
            .stat-value {{ font-size: 1.2rem; }}
        }}
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-sm bg-body-tertiary mb-4 no-print">
        <div class="container">
            <span class="navbar-brand fw-bold">🩺 WiFiDoctor</span>
            <div class="d-flex align-items-center gap-2">
                <small class="text-muted">{self.timestamp}</small>
                <button class="btn btn-sm btn-outline-secondary" onclick="toggleTheme()">🌙 主题</button>
                <button class="btn btn-sm btn-outline-primary" onclick="window.print()">🖨️ 打印</button>
            </div>
        </div>
    </nav>

    <div class="container pb-5">
        <!-- 总评分 Hero -->
        <div class="card mb-4">
            <div class="card-body text-center py-4">
                <div class="hero-score">{score}<small style="font-size:0.4em;color:#6c757d">/100</small></div>
                <h3 class="mt-2"><span class="badge bg-{status_badge} fs-5">{status_text}</span></h3>
                <p class="text-muted mb-0">WiFi 网络健康评分 · {data.get('platform', '')}</p>
            </div>
        </div>

        <!-- 速度+信号 两列 -->
        <div class="row g-3 mb-4">
            <!-- 速度卡片 -->
            <div class="col-md-8">
                <div class="card h-100">
                    <div class="card-header bg-primary text-white"><h5 class="mb-0">⚡ 速度与延迟</h5></div>
                    <div class="card-body">
                        <div class="row text-center mb-3">
                            <div class="col-4">
                                <div class="stat-value text-primary">{speed.get('download_mbps', 0)}</div>
                                <div class="stat-label">下载 Mbps</div>
                            </div>
                            <div class="col-4">
                                <div class="stat-value text-success">{speed.get('upload_mbps', 0)}</div>
                                <div class="stat-label">上传 Mbps</div>
                            </div>
                            <div class="col-4">
                                <div class="stat-value text-warning">{speed.get('ping_ms', 0)}</div>
                                <div class="stat-label">延迟 ms</div>
                            </div>
                        </div>
                        <div class="row text-center mb-3">
                            <div class="col-4">
                                <div class="stat-value text-info">{speed.get('jitter_ms', 0)}</div>
                                <div class="stat-label">抖动 ms</div>
                            </div>
                            <div class="col-4">
                                <div class="stat-value text-danger">{speed.get('packet_loss_pct', 0)}%</div>
                                <div class="stat-label">丢包率</div>
                            </div>
                            <div class="col-4">
                                <small class="text-muted">{speed.get('server', 'N/A')}</small>
                                <div class="stat-label">测速服务器</div>
                            </div>
                        </div>
                        <div class="chart-container"><canvas id="speedChart"></canvas></div>
                    </div>
                </div>
            </div>
            <!-- 信号强度仪表盘 -->
            <div class="col-md-4">
                <div class="card h-100">
                    <div class="card-header bg-info text-white"><h5 class="mb-0">📶 信号强度</h5></div>
                    <div class="card-body text-center">
                        <div style="position:relative;width:180px;height:180px;margin:0 auto;">
                            <canvas id="signalGauge"></canvas>
                            <div style="position:absolute;top:55%;left:50%;transform:translate(-50%,-50%);">
                                <div style="font-size:2.2em;font-weight:bold;">{current_quality}%</div>
                                <div style="font-size:0.85em;color:#6c757d;">{current_rssi} dBm</div>
                            </div>
                        </div>
                        <h6 class="mt-2">{current_net.get('ssid', 'N/A')}</h6>
                        <span class="badge bg-secondary">{current_net.get('band', '')}</span>
                        <span class="badge bg-secondary">信道 {current_net.get('channel', 'N/A')}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 连接信息 + IP纯净度 -->
        <div class="row g-3 mb-4">
            <div class="col-md-{'6' if ip_info.get('check_ok') else '12'}">
                <div class="card h-100">
                    <div class="card-header bg-dark text-white"><h5 class="mb-0">🔗 连接信息</h5></div>
                    <ul class="list-group list-group-flush">
                        <li class="list-group-item d-flex justify-content-between"><span>WiFi 名称</span><strong>{conn.get('ssid', 'N/A')}</strong></li>
                        <li class="list-group-item d-flex justify-content-between"><span>内网 IP</span><code>{conn.get('ip_address', 'N/A')}</code></li>
                        <li class="list-group-item d-flex justify-content-between"><span>默认网关</span><code>{conn.get('gateway', 'N/A')}</code></li>
                        <li class="list-group-item d-flex justify-content-between"><span>DNS 服务器</span><span>{', '.join(conn.get('dns_servers', ['N/A']))}</span></li>
                        <li class="list-group-item d-flex justify-content-between"><span>MAC 地址</span><code>{conn.get('mac_address', 'N/A')}</code></li>
                        <li class="list-group-item d-flex justify-content-between"><span>网络接口</span><span>{conn.get('interface', 'N/A')}</span></li>
                        <li class="list-group-item d-flex justify-content-between"><span>连接时长</span><span>{conn.get('uptime', 'N/A')}</span></li>
                    </ul>
                </div>
            </div>
            {ip_card_html}
        </div>

        <!-- 延迟图表 -->
        <div class="card mb-4">
            <div class="card-header bg-warning text-dark"><h5 class="mb-0">🏓 各服务器延迟对比</h5></div>
            <div class="card-body">
                <div class="chart-container"><canvas id="latencyChart"></canvas></div>
            </div>
        </div>

        <!-- 诊断结果 -->
        <div class="card mb-4">
            <div class="card-header bg-{status_badge} {"text-dark" if status_badge == "warning" else "text-white"}">
                <h5 class="mb-0">🧠 智能诊断结果</h5>
            </div>
            <div class="card-body">
                {issues_html if issues_html else '<div class="alert alert-success">🎉 未发现任何网络问题，一切正常！</div>'}
            </div>
        </div>

        <!-- WiFi 网络列表 -->
        <div class="card mb-4">
            <div class="card-header bg-body-secondary"><h5 class="mb-0">📡 WiFi 网络列表（共 {len(networks)} 个）</h5></div>
            <div class="table-responsive">
                <table class="table table-hover align-middle">
                    <thead class="table-light">
                        <tr><th>SSID</th><th>BSSID</th><th>信号</th><th>质量</th><th>信道</th><th>频段</th><th>加密方式</th></tr>
                    </thead>
                    <tbody>{net_rows}</tbody>
                </table>
            </div>
        </div>

        <!-- 页脚 -->
        <div class="text-center text-muted py-3">
            <small>🩺 WiFiDoctor v2.0 - WiFi 网络诊断工具 | 报告生成时间: {self.timestamp}</small>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // 主题切换
        function toggleTheme() {{
            const html = document.documentElement;
            html.dataset.bsTheme = html.dataset.bsTheme === 'dark' ? 'light' : 'dark';
        }}

        // 信号仪表盘
        new Chart(document.getElementById('signalGauge'), {{
            type: 'doughnut',
            data: {{
                datasets: [{{
                    data: [{current_quality}, {100 - current_quality}],
                    backgroundColor: [
                        {current_quality} >= 70 ? '#198754' : {current_quality} >= 40 ? '#ffc107' : '#dc3545',
                        '#e9ecef'
                    ],
                    borderWidth: 0,
                    circumference: 270,
                    rotation: 225,
                }}]
            }},
            options: {{
                cutout: '78%',
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }}
            }}
        }});

        // 速度柱形图
        new Chart(document.getElementById('speedChart'), {{
            type: 'bar',
            data: {{
                labels: ['下载速度 (Mbps)', '上传速度 (Mbps)', '延迟 (ms)', '抖动 (ms)'],
                datasets: [{{
                    data: [{speed.get('download_mbps', 0)}, {speed.get('upload_mbps', 0)}, {speed.get('ping_ms', 0)}, {speed.get('jitter_ms', 0)}],
                    backgroundColor: ['#0d6efd', '#198754', '#ffc107', '#0dcaf0'],
                    borderRadius: 8,
                    barPercentage: 0.6,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ y: {{ beginAtZero: true, grid: {{ color: 'rgba(0,0,0,0.05)' }} }} }}
            }}
        }});

        // 延迟对比图
        new Chart(document.getElementById('latencyChart'), {{
            type: 'bar',
            data: {{
                labels: {latency_labels_js},
                datasets: [
                    {{
                        label: '延迟 (ms)',
                        data: {latency_values_js},
                        backgroundColor: 'rgba(13,110,253,0.7)',
                        borderRadius: 6,
                        yAxisID: 'y',
                    }},
                    {{
                        label: '丢包率 (%)',
                        data: {latency_loss_js},
                        backgroundColor: 'rgba(220,53,69,0.7)',
                        borderRadius: 6,
                        yAxisID: 'y1',
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top' }} }},
                scales: {{
                    y: {{ beginAtZero: true, position: 'left', title: {{ display: true, text: '延迟 (ms)' }} }},
                    y1: {{ beginAtZero: true, position: 'right', title: {{ display: true, text: '丢包率 (%)' }}, grid: {{ drawOnChartArea: false }} }}
                }}
            }}
        }});

        // IP 纯净度环形图
        const purityCanvas = document.getElementById('purityChart');
        if (purityCanvas) {{
            new Chart(purityCanvas, {{
                type: 'doughnut',
                data: {{
                    datasets: [{{
                        data: [{purity}, {100 - purity}],
                        backgroundColor: ['{purity_color}', '#e9ecef'],
                        borderWidth: 0,
                    }}]
                }},
                options: {{
                    cutout: '75%',
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }}
                }}
            }});
        }}
    </script>
</body>
</html>"""

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)

        return filename


# ============================================================
# 主控制器
# ============================================================

class WiFiDoctor:
    """WiFiDoctor 主控制器 - 协调所有模块"""

    def __init__(self):
        self.scanner = WiFiScanner()
        self.conn_info_gatherer = ConnectionInfo()
        self.speed_tester = SpeedTester()
        self.ip_checker = PublicIPChecker()
        self.diagnosis_engine = DiagnosisEngine()
        self.report = ReportGenerator()

        # 存储各模块结果
        self.networks: List[Dict[str, Any]] = []
        self.conn_info: Dict[str, Any] = {}
        self.speed_results: Dict[str, Any] = {}
        self.ip_info: Dict[str, Any] = {}
        self.score: int = 0
        self.issues: List[Dict[str, Any]] = []

    def print_banner(self):
        """打印程序横幅"""
        banner = """
[bold cyan]
  ██╗    ██╗██╗███████╗██╗    ██████╗  ██████╗  ██████╗████████╗ ██████╗ ██████╗
  ██║    ██║██║██╔════╝██║    ██╔══██╗██╔═══██╗██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗
  ██║ █╗ ██║██║█████╗  ██║    ██║  ██║██║   ██║██║        ██║   ██║   ██║██████╔╝
  ██║███╗██║██║██╔══╝  ██║    ██║  ██║██║   ██║██║        ██║   ██║   ██║██╔══██╗
  ╚███╔███╔╝██║██║     ██║    ██████╔╝╚██████╔╝╚██████╗   ██║   ╚██████╔╝██║  ██║
   ╚══╝╚══╝ ╚═╝╚═╝     ╚═╝    ╚═════╝  ╚═════╝  ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
[/bold cyan]
[dim]  🩺 WiFi 网络诊断工具 v2.0  |  {platform}  |  {time}[/dim]
""".format(platform=f"{SYSTEM} {platform.release()}", time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        console.print(banner)

    def run_scan(self):
        """运行 WiFi 扫描"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("📡 正在扫描 WiFi 网络...", total=None)
            self.networks = self.scanner.scan()
            progress.update(task, description=f"📡 扫描完成，发现 {len(self.networks)} 个网络")

        self.report.display_scan_results(self.networks)

    def run_connection_info(self):
        """获取并显示连接信息"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("🔗 获取连接信息...", total=None)
            self.conn_info = self.conn_info_gatherer.gather()
            progress.update(task, description="🔗 连接信息获取完成")

        self.report.display_connection_info(self.conn_info)

    def run_speed_test(self):
        """运行速度和延迟测试"""
        self.speed_results = self.speed_tester.run_all()
        self.report.display_speed_results(self.speed_results)

    def run_ip_check(self):
        """运行公网 IP 与纯净度检测"""
        self.ip_checker = PublicIPChecker()
        self.ip_info = self.ip_checker.check()
        self.report.display_ip_info(self.ip_info)

    def run_diagnosis(self):
        """运行智能诊断"""
        # 确保已收集必要数据
        if not self.conn_info:
            self.conn_info = self.conn_info_gatherer.gather()
        if not self.networks:
            self.networks = self.scanner.scan()

        self.score, self.issues = self.diagnosis_engine.diagnose(
            self.networks, self.conn_info, self.speed_results, self.ip_info
        )
        self.report.display_diagnosis(self.score, self.issues)

    def run_full_diagnosis(self):
        """运行完整诊断流程"""
        self.print_banner()
        console.print(Panel(
            "[bold]开始完整网络诊断...[/bold]\n"
            "  1️⃣  扫描 WiFi 网络\n"
            "  2️⃣  获取连接信息\n"
            "  3️⃣  速度与延迟测试\n"
            "  4️⃣  公网 IP 与纯净度检测\n"
            "  5️⃣  智能诊断分析",
            title="📋 诊断流程",
            border_style="cyan",
        ))

        self.run_scan()
        self.run_connection_info()
        self.run_speed_test()
        self.run_ip_check()
        self.run_diagnosis()

    def save_report(self) -> Tuple[str, str]:
        """保存诊断报告"""
        data = {
            "timestamp": self.report.timestamp,
            "platform": f"{SYSTEM} {platform.release()}",
            "connection": self.conn_info,
            "networks": self.networks,
            "speed_test": self.speed_results,
            "public_ip": self.ip_info,
            "diagnosis": {
                "score": self.score,
                "issues": self.issues,
            },
        }

        json_file = self.report.save_json(data)
        html_file = self.report.save_html(data)

        console.print()
        console.print(Panel(
            f"  📄 JSON 报告: [bold cyan]{json_file}[/bold cyan]\n"
            f"  🌐 HTML 报告: [bold cyan]{html_file}[/bold cyan]",
            title="💾 报告已保存",
            border_style="green",
        ))

        return json_file, html_file

    def run_monitor(self, interval: int = 10):
        """持续监控模式 - 每次刷新所有指标"""
        self.print_banner()
        console.print(Panel(
            f"[bold]持续监控模式[/bold] - 每 {interval} 秒刷新全部指标\n"
            "  📡 WiFi 扫描 · ⚡ 延迟测试 · 🌍 公网 IP · 🛡️ 纯净度\n"
            "按 [bold red]Ctrl+C[/bold red] 停止",
            title="🔄 监控模式",
            border_style="cyan",
        ))

        try:
            cycle = 0
            while True:
                cycle += 1
                console.print(f"\n[bold]━━━ 第 {cycle} 次检测 ━━━[/bold] "
                              f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]")

                # 1. 快速扫描和连接信息
                self.networks = self.scanner.scan()
                self.conn_info = self.conn_info_gatherer.gather()

                # 2. 快速 ping 测试
                quick_tester = SpeedTester()
                quick_tester._test_latency()
                self.speed_results = quick_tester.results

                # 3. 公网 IP 与纯净度检测
                try:
                    ip_checker = PublicIPChecker()
                    self.ip_info = ip_checker.check()
                except Exception:
                    pass  # 网络不可用时静默跳过

                # 显示紧凑信息
                self._display_monitor_summary()

                # 4. 快速诊断
                self.score, self.issues = self.diagnosis_engine.diagnose(
                    self.networks, self.conn_info, self.speed_results, self.ip_info
                )

                # 仅显示有问题时的诊断
                if self.issues:
                    for issue in self.issues:
                        level_icon = "❌" if issue["level"] == "error" else "⚠️" if issue["level"] == "warning" else "ℹ️"
                        console.print(f"  {level_icon} {issue['title']}: {issue['suggestion']}")

                # 等待
                console.print(f"\n[dim]下次检测: {interval} 秒后...[/dim]")
                time.sleep(interval)

        except KeyboardInterrupt:
            console.print("\n[yellow]🛑 监控已停止[/yellow]")

    def _display_monitor_summary(self):
        """显示监控模式的紧凑摘要"""
        ssid = self.conn_info.get("ssid", "未知")
        ip = self.conn_info.get("ip_address", "未知")
        ping = self.speed_results.get("ping_ms", 0)
        loss = self.speed_results.get("packet_loss_pct", 0)

        # 查找当前网络信号
        current_nets = [n for n in self.networks if n.get("is_current")]
        rssi = current_nets[0].get("rssi", 0) if current_nets else 0
        quality = current_nets[0].get("quality", 0) if current_nets else 0

        # 公网 IP 信息
        pub_ip = self.ip_info.get("public_ip", "N/A") if self.ip_info else "N/A"
        purity = self.ip_info.get("purity_score", 0) if self.ip_info else 0
        ip_type = self.ip_info.get("ip_type", "未知") if self.ip_info else "未知"

        # 紧凑表格
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("", style="bold")
        table.add_column("")

        sig_color = "green" if rssi >= -60 else "yellow" if rssi >= -70 else "red"
        ping_color = "green" if ping < 50 else "yellow" if ping < 100 else "red"
        loss_color = "green" if loss < 1 else "yellow" if loss < 5 else "red"
        purity_color = "green" if purity >= 90 else "yellow" if purity >= 70 else "red"

        table.add_row("📡 SSID", f"{ssid}  |  内网IP: {ip}")
        table.add_row("📶 信号", f"[{sig_color}]{rssi} dBm ({quality}%)[/{sig_color}]")
        table.add_row("🏓 延迟", f"[{ping_color}]{ping} ms[/{ping_color}]  |  📦 丢包: [{loss_color}]{loss}%[/{loss_color}]")
        table.add_row("🌍 公网IP", f"{pub_ip}  |  🛡️ 纯净度: [{purity_color}]{purity}/100[/{purity_color}] ({ip_type})")

        console.print(table)


# ============================================================
# CLI 入口
# ============================================================

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="🩺 WiFiDoctor - WiFi 网络诊断工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python wifi_doctor.py              # 完整诊断
  python wifi_doctor.py --scan       # 仅扫描网络
  python wifi_doctor.py --test       # 仅测速
  python wifi_doctor.py --monitor    # 持续监控
  python wifi_doctor.py --report     # 完整诊断并保存报告
        """,
    )

    parser.add_argument("--scan", action="store_true", help="仅扫描 WiFi 网络")
    parser.add_argument("--test", action="store_true", help="仅运行速度和延迟测试")
    parser.add_argument("--monitor", action="store_true", help="持续监控模式")
    parser.add_argument("--report", action="store_true", help="完整诊断并保存报告（JSON + HTML）")
    parser.add_argument("--interval", type=int, default=10, help="监控间隔秒数（默认 10）")

    args = parser.parse_args()
    doctor = WiFiDoctor()

    try:
        if args.scan:
            # 仅扫描模式
            doctor.print_banner()
            doctor.run_scan()

        elif args.test:
            # 仅测速模式
            doctor.print_banner()
            doctor.run_connection_info()
            doctor.run_speed_test()
            doctor.run_diagnosis()

        elif args.monitor:
            # 持续监控
            doctor.run_monitor(interval=args.interval)

        elif args.report:
            # 完整诊断 + 保存报告
            doctor.run_full_diagnosis()
            doctor.save_report()

        else:
            # 默认：完整诊断
            doctor.run_full_diagnosis()

    except KeyboardInterrupt:
        console.print("\n[yellow]🛑 用户中断，程序退出[/yellow]")
        sys.exit(0)
    except PermissionError:
        console.print("[red]❌ 权限不足，部分功能需要管理员/root 权限运行[/red]")
        console.print("[yellow]💡 Windows: 以管理员身份运行命令提示符[/yellow]")
        console.print("[yellow]💡 Linux/macOS: 使用 sudo python wifi_doctor.py[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ 发生未知错误: {e}[/red]")
        console.print("[dim]请检查网络适配器是否可用[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
