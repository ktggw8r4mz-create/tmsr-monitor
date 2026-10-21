#!/bin/bash
# TMSR 本机可视化 Web 服务安装/重装脚本
set -e
DIR="/Users/hule/Doubao/chats/2026-10-19/new-chat-1/TMSR监控模型"
AGENTS="$HOME/Library/LaunchAgents"
cp "$DIR/com.hule.tmsr.web.plist" "$AGENTS/com.hule.tmsr.web.plist"
launchctl unload "$AGENTS/com.hule.tmsr.web.plist" 2>/dev/null || true
launchctl load "$AGENTS/com.hule.tmsr.web.plist"
echo "OK：可视化服务已启动 → http://127.0.0.1:8017"
