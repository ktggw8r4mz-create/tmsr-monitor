#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMSR 风险预测模块
基于链上实时状态，对 5 类系统性风险事件输出概率评分（0-100）与触发条件。
输出：predict.json（供整站/推送读取）+ 控制台可读预测卡片。
说明：本模块为基于监控信号的规则推断（资金面/结构面风险），非价格预测，不构成投资建议。
"""
import json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ALL_PATH = os.path.join(BASE, "all_addresses.json")
STATE_PATH = os.path.join(BASE, "tmsr_state.json")
OUT_PATH = os.path.join(BASE, "predict.json")

def load(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, int(x)))

def main():
    alls = load(ALL_PATH)
    state = load(STATE_PATH)
    addr = alls.get("addresses", {})
    pool = alls.get("pool", {})
    tok = state.get("token", {})
    lt = state.get("light", {})
    tb = state.get("turbo", {})
    met = state.get("metrics", {})

    def bal(name):
        for k, v in addr.items():
            if name in v.get("name", ""):
                return v
        return {}
    vault = bal("vault合约")
    light = bal("light合约")
    init = bal("initialRecipient")
    wd = bal("withdraw合约")
    turbo = bal("turbo合约")

    dex_price = met.get("dexPrice") or pool.get("price")
    sale_price = lt.get("salePrice") if lt.get("salePrice") is not None else 0.05  # 多轮实测基线
    orders = lt.get("totalOrders")
    buy_enabled = tok.get("buyEnabled")
    reserved = tb.get("totalReservedTmsr")
    available = tb.get("availableTmsr")
    if available is None and turbo.get("tmsr") is not None:
        available = turbo["tmsr"]  # 余额即当前可用上限

    preds = []

    # P1 开放销售套利抽干
    score = 15
    if sale_price and dex_price:
        dev = (sale_price - dex_price) / dex_price * 100
        if dev < -10: score += 45
        if dev < -50: score += 25
    if lt.get("salePaused") is False: score += 15
    if orders in (0, None): score += 10      # 未开张=随时可开
    preds.append({
        "id": "P1", "name": "开放销售 → 库存被套利抽干",
        "score": clamp(score), "horizon": "若 openSale 触发后 1-6h",
        "trigger": "salePaused=false 且开放销售",
        "desc": "官网售价 %s vs 市价 %s，倒挂 %s%%；一旦放行，套利循环将抽干光能 %s 枚 TMSR 库存并砸穿池价。" % (
            sale_price, dex_price, (round((sale_price-dex_price)/dex_price*100,1) if sale_price and dex_price else "—"),
            light.get("tmsr"))
    })

    # P2 owner 后门提币
    score = 35
    if vault.get("tmsr") and vault["tmsr"] > 1e8: score += 25
    if wd.get("tmsr") and wd["tmsr"] > 1e4: score += 10
    if light.get("usdt"): score += 5
    preds.append({
        "id": "P2", "name": "owner 后门提币（金库/提现/光能）",
        "score": clamp(score), "horizon": "随时（无时间锁）",
        "trigger": "Vault.withdraw / Light.withdrawToken / Withdraw.rescueToken 被调用",
        "desc": "金库 %s 枚 + 提现 %s 枚 + 光能 %s USDT 可被各自 owner 一键转走；任何合约余额单块骤降即为触发。" % (
            vault.get("tmsr"), wd.get("tmsr"), light.get("usdt"))
    })

    # P3 撤池归零
    score = 25
    if init.get("lp") and pool.get("lpTotal"):
        share = init["lp"] / pool["lpTotal"] * 100
        if share > 90: score += 50
        if share > 50: score += 20
        if sale_price and dex_price and sale_price < dex_price: score += 10
    preds.append({
        "id": "P3", "name": "initialRecipient 撤池归零",
        "score": clamp(score), "horizon": "随时（LP 未锁）",
        "trigger": "initialRecipient LP 余额下降",
        "desc": "其持有 %s LP（占比 %s%%）未锁定，卖出即抽干 %s USDT / %s TMSR 深度。" % (
            init.get("lp"), (round(init["lp"]/pool["lpTotal"]*100,1) if init.get("lp") and pool.get("lpTotal") else "—"),
            pool.get("usdt"), pool.get("tmsr"))
    })

    # P4 涡轮偿付缺口
    score = 10
    if reserved and available:
        if reserved >= available * 0.5: score += 40
        if reserved >= available: score += 40
    if tb.get("balTmsr") is not None and available and available > tb["balTmsr"]: score += 20
    preds.append({
        "id": "P4", "name": "涡轮集中兑付 → 偿付缺口",
        "score": clamp(score), "horizon": "订单批量创建后",
        "trigger": "totalReservedTmsr 接近合约余额",
        "desc": "买1兑2每单净缺口 1 份；当前未兑 %s 枚 / 可用 %s 枚，先到先得，余额不足即拒付。" % (reserved, available)
    })

    # P5 参数突变（黑名单/税率/开关）
    score = 30
    if buy_enabled is False: score += 15
    if lt.get("salePaused") is False: score += 10
    preds.append({
        "id": "P5", "name": "owner 参数突变（开关/税率/黑名单）",
        "score": clamp(score), "horizon": "随时（单点权限）",
        "trigger": "buyEnabled / setSellTaxBps / 黑名单集合变化",
        "desc": "买入开关当前 %s；卖税可动态升至 50%%；owner 可无预警定向冻结地址。" % ("开启" if buy_enabled else "关闭")
    })

    overall = clamp(sum(p["score"] for p in preds) / len(preds))
    level = "极高" if overall >= 70 else "高" if overall >= 50 else "中" if overall >= 30 else "低"
    out = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall": overall, "level": level,
        "alerts": preds,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("TMSR 风险预测 | %s | 综合风险: %s/100（%s）" % (out["generated_at"], overall, level))
    for p in preds:
        print("  [%s] %-24s 评分 %s/100 | 触发: %s" % (p["id"], p["name"], p["score"], p["trigger"]))
        print("       %s" % p["desc"])

if __name__ == "__main__":
    main()
