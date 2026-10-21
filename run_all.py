#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMSR 本机监控主入口（launchd 每 5 分钟调用一次）
顺序：monitor_all（全地址快照）→ tmsr_monitor（指标+状态）→ predict（预测）→ notify（变动推送）
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

def main():
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
    # 两个采集脚本并行（互不依赖），随后串行执行预测与推送
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(run, "monitor_all", "monitor_all.py")
        f2 = ex.submit(run, "tmsr_monitor", "tmsr_monitor.py")
        f1.result(); f2.result()
    run("predict", "predict.py")
    run("notify", "telegram_notify.py")

if __name__ == "__main__":
    main()
