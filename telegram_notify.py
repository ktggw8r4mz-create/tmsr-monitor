#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMSR Telegram 推送模块
检测链上变动（任意地址余额 / 合约状态 / 价格），有变动即推送到 Telegram。
首次运行建立 baseline；之后每轮与 baseline 对比，超过阈值则推送并更新 baseline。
未配置 bot_token / chat_id 时降级为日志输出，不报错。
"""
import json, os, time, datetime, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "config.json")
BASE_PATH = os.path.join(BASE, "baseline.json")
STATE_PATH = os.path.join(BASE, "tmsr_state.json")
ALL_PATH = os.path.join(BASE, "all_addresses.json")
LOG_PATH = os.path.join(BASE, "logs", "notify.log")

def log(msg):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))

def load(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

def send_telegram(token, chat_id, text, proxy=None):
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(url, data=body)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else urllib.request.build_opener()
    with opener.open(req, timeout=25) as r:
        d = json.loads(r.read().decode())
    return d.get("ok", False)

def detect():
    """返回本轮变动清单 [(类型, 描述)]"""
    changes = []
    cfg = load(CFG_PATH, {})
    t = cfg.get("notify") or cfg
    state = load(STATE_PATH, {})
    alls = load(ALL_PATH, {})
    base = load(BASE_PATH, {"state": None, "all": None})
    # 1) 合约状态变动（buyEnabled / salePrice / totalOrders / 暂停开关等）
    if state and base.get("state") and base["state"] != state:
        keys = ["buyEnabled","salePrice","purchaseUnit","burnBps","totalOrders",
                "salePaused","treasuryPaused","lockDuration","lockBps",
                "totalReservedTmsr","availableTmsr","dexPrice","health"]
        for k in keys:
            old = None
            for d_ in (base["state"].get("token",{}), base["state"].get("light",{}),
                       base["state"].get("turbo",{}), base["state"].get("metrics",{}),
                       base["state"].get("pair",{})):
                if isinstance(d_, dict) and k in d_: old = d_[k]; break
            new = None
            for d_ in (state.get("token",{}), state.get("light",{}), state.get("turbo",{}),
                       state.get("metrics",{}), state.get("pair",{})):
                if isinstance(d_, dict) and k in d_: new = d_[k]; break
            if old is not None and new is not None and old != new:
                changes.append(("state", "合约状态变动 %s: %s -> %s" % (k, old, new)))
    # 2) 价格变动
    if state:
        m = state.get("metrics", {})
        if m and m.get("dexPrice") and base.get("state",{}).get("metrics",{}).get("dexPrice"):
            old_p = base["state"]["metrics"]["dexPrice"]; new_p = m["dexPrice"]
            pct = abs(new_p - old_p) / old_p * 100
            if pct >= t.get("price_change_pct", 3.0):
                changes.append(("price", "DEX 价格变动 %.4f%%: %.6f -> %.6f USDT" % (pct, old_p, new_p)))
    # 3) 全地址余额变动
    if alls and base.get("all") and base["all"].get("addresses"):
        old_map = base["all"]["addresses"]; new_map = alls["addresses"]
        for addr, rec in new_map.items():
            old = old_map.get(addr)
            if not old: continue
            for asset, thr in (("tmsr", t.get("tmsr_delta", 1.0)), ("usdt", t.get("usdt_delta", 1.0)),
                               ("lp", t.get("lp_delta", 0.1)), ("bnb", t.get("bnb_delta", 0.01))):
                ov = old.get(asset); nv = rec.get(asset)
                if ov is None or nv is None: continue
                d = abs(nv - ov)
                if d >= thr:
                    changes.append(("balance", "%s %s 变动 %s -> %s (Δ%s)" % (rec.get("name", addr[:10]), asset.upper(), _f(ov), _f(nv), _f(d))))
    return changes

def _f(n):
    if n is None: return "—"
    return ("%.6g" % n)

def build_message(changes, state):
    lines = ["TMSR 链上变动警报"]
    lines.append("时间: %s" % datetime.datetime.now().strftime("%m-%d %H:%M"))
    if state:
        m = state.get("metrics", {})
        if m:
            lines.append("健康度: %s/100 | DEX 价: %s USDT" % (m.get("health", "—"), m.get("dexPrice", "—")))
    lines.append("")
    for typ, desc in changes[:12]:
        lines.append(("- 合约" if typ == "state" else "- 价格" if typ == "price" else "- 余额") + " " + desc)
    if len(changes) > 12:
        lines.append("…共 %d 项变动" % len(changes))
    lines.append("")
    lines.append("监控: TMSR 链上监控中心 | 建议查看完整看板")
    return "\n".join(lines)

def build_heartbeat(state, predict):
    """无变动时的心跳消息：每 30 分钟必发，带关键指标，证明系统活着"""
    lines = ["TMSR 监控巡检（每 30 分钟）"]
    lines.append("时间: %s" % datetime.datetime.now().strftime("%m-%d %H:%M"))
    lines.append("状态: 无异常变动，系统运行正常")
    lines.append("")
    if state:
        m = state.get("metrics", {})
        if m:
            lines.append("健康度: %s/100 | DEX 价: %s USDT | LP 锁定: %s%%"
                         % (m.get("health", "—"), m.get("dexPrice", "—"), m.get("lpLockedPct", "—")))
    if predict:
        lines.append("综合风险: %s/100（%s）" % (predict.get("overall", "—"), predict.get("level", "—")))
        for a in (predict.get("alerts") or [])[:5]:
            lines.append("  %s %s: %s" % (a.get("id", ""), a.get("name", "")[:18], a.get("score", "—")))
    lines.append("")
    lines.append("监控: TMSR 链上监控中心 | 有变动将立即单独推送")
    return "\n".join(lines)

def main():
    cfg = load(CFG_PATH, {})
    tg = cfg.get("telegram") or {}
    token = (tg.get("bot_token") or cfg.get("bot_token") or "").strip()
    chat_id = (tg.get("chat_id") or cfg.get("chat_id") or "").strip()
    proxy = (tg.get("proxy") or cfg.get("proxy") or "").strip() or None
    state = load(STATE_PATH, {})
    alls = load(ALL_PATH, {})
    predict = load(os.path.join(BASE, "predict.json"), {})
    changes = detect()
    log("检测到 %d 项变动" % len(changes))
    # 更新 baseline（无论推送与否，保持连续）
    save(BASE_PATH, {"state": state, "all": alls, "ts": int(time.time())})
    # 有变动 → 变动警报；无变动 → 心跳消息（每 30 分钟必推一次）
    msg = build_message(changes, state) if changes else build_heartbeat(state, predict)
    if not token or not chat_id:
        log("Telegram 未配置（bot_token/chat_id 为空），本轮消息仅记录日志")
        print("[notify] 未配置 Telegram，跳过推送。消息内容:")
        print(msg)
        return
    try:
        ok = send_telegram(token, chat_id, msg, proxy)
        log("Telegram 推送 %s: %s" % ("成功" if ok else "失败", msg[:80]))
        print("[notify] 推送%s" % ("成功" if ok else "失败"))
    except Exception as e:
        log("Telegram 推送异常: %s" % e)
        print("[notify] 推送异常:", e)

if __name__ == "__main__":
    main()
