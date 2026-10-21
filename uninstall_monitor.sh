#!/bin/bash
# TMSR 本机监控卸载脚本：停止并移除定时任务（文件保留）
AGENTS="$HOME/Library/LaunchAgents/com.hule.tmsr.monitor.plist"
launchctl unload "$AGENTS" 2>/dev/null || true
rm -f "$AGENTS"
echo "OK：已停止并移除 com.hule.tmsr.monitor 定时任务（监控文件未删除）"
