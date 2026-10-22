#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMSR 本机监控主入口（launchd 每 30 分钟调用一次）
顺序：monitor_all（全地址快照）→ tmsr_monitor（指标+状态）→ predict（预测）→ notify（变动推送）→ git_push（同步 GitHub Pages）
任意一步失败不中断后续步骤。
"""
import subprocess, sys, os, datetime
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
PY = "/usr/bin/python3"
LOG = os.path.join(BASE, "logs", "run.log")

def run(name, script):
    try:
        r = subprocess.run([PY, os.path.join(BASE, script)],
                           capture_output=True, text=True, timeout=420)
        ok = r.returncode == 0
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name, "OK" if ok else "FAIL rc=%d" % r.returncode))
            if not ok:
                f.write((r.stderr or r.stdout or "")[-500:] + "\n")
        return ok
    except subprocess.TimeoutExpired:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s TIMEOUT\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name))
        return False

def git_push():
    """更新后的 JSON 快照自动推送到 GitHub（保持 Pages 公网页面数据新鲜）"""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    def log_line(s):
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), s))
    try:
        r = subprocess.run(["git", "add", "all_addresses.json", "baseline.json", "tmsr_state.json", "predict.json"],
                           cwd=BASE, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log_line("git add FAIL: %s" % (r.stderr or "")[-300:])
            return False
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=BASE, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            log_line("git push SKIP 无数据变更")
            return True
        r = subprocess.run(["git", "commit", "-m", "链上快照更新 %s" % stamp],
                           cwd=BASE, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log_line("git commit FAIL: %s" % (r.stderr or "")[-300:])
            return False
        r = subprocess.run(["git", "push", "origin", "main"], cwd=BASE, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            log_line("git push FAIL: %s" % (r.stderr or "")[-300:])
            return False
        log_line("git push OK 快照已同步 GitHub Pages")
        return True
    except Exception as e:
        log_line("git_push EXC: %s" % e)
        return False

def main():
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
    # 两个采集脚本并行（互不依赖），随后串行执行预测与推送
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(run, "monitor_all", "monitor_all.py")
        f2 = ex.submit(run, "tmsr_monitor", "tmsr_monitor.py")
        f1.result(); f2.result()
    run("predict", "predict.py")
    run("notify", "telegram_notify.py")
    git_push()

if __name__ == "__main__":
    main()
