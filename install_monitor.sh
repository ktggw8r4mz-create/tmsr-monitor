#!/bin/bash
# TMSR 本机监控安装脚本：注册 launchd 定时任务（每 5 分钟）
set -e
DIR="/Users/hule/Doubao/chats/2026-10-19/new-chat-1/TMSR监控模型"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"
cp "$DIR/com.hule.tmsr.monitor.plist" "$AGENTS/com.hule.tmsr.monitor.plist"
launchctl unload "$AGENTS/com.hule.tmsr.monitor.plist" 2>/dev/null || true
launchctl load "$AGENTS/com.hule.tmsr.monitor.plist"
echo "OK：已注册并启动 com.hule.tmsr.monitor（每 5 分钟执行一次）"
echo "查看状态：launchctl list | grep tmsr"
echo "立即手动跑一轮：/usr/bin/python3 \"$DIR/run_all.py\""
