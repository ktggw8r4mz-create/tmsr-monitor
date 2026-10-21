#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMSR 链上监控采集脚本（真实数据版）
每轮执行：读取 5 合约 + DEX 池状态 → 计算 16 项监控指标 → 输出 JSON 快照
用法：python3 tmsr_monitor.py [--json]
依赖：python3 + requests（无需 web3，直接 JSON-RPC）
"""
import json, sys, time, datetime, urllib.request, os
from concurrent.futures import ThreadPoolExecutor

RPCS = ["https://bsc-rpc.publicnode.com", "https://bsc.publicnode.com", "https://bsc.meowrpc.com", "https://1rpc.io/bnb"]
ADDR = {
  "token":    "0xD8D3cD314FdBB54435A6e7CCcca1adbbdf68674F",
  "light":    "0x651f0EF421EfDe887dF55f05b2C243008CdF5B49",
  "turbo":    "0xa5D430d8D33D2Ed95D4ce1A92b42E03EeC83bD96",
  "vault":    "0xD026b745B1096CdD0ba618eDC48a56Ce38939eEf",
  "withdraw": "0x99686192b091c212E613652DBfe3b003Bce7722A",
  "pair":     "0xb8a80acfb85d7e162d5b96f59ff2177f6d131371",
  "usdt":     "0x55d398326f99059fF775485246999027B3197955",
  "dead":     "0x000000000000000000000000000000000000dEaD",
  "initRec":  "0x53e3294cf3b04d7ef5f5afa984fc727d1b617ecc",
}
SIG = {
  "totalSupply":"0x18160ddd","owner":"0x8da5cb5b","balanceOf":"0x70a08231",
  "buyEnabled":"0xd4736baf","buyTaxBps":"0xf89d0016","baseSellTaxBps":"0xa4e0f6ab",
  "extraSellTax":"0xde610b28","twapPrice":"0x1bd0e2c2","dailyBasePrice":"0xef7d6bc1",
  "waitingFee":"0x1d18c39a","salePrice":"0xdf273d4e","purchaseUnit":"0xd9f2ec21",
  "burnBps":"0x352dcc51","totalOrders":"0x1e92c25b","salePaused":"0x3d5d2b2d",
  "treasuryPaused":"0x2c6a1875","nftTransferEnabled":"0xd122c69e","nftUrl":"0x855f18d8",
  "turboContract":"0x23764f9d","vaultContract":"0xd871c9d3","earningsWithdraw":"0x9383c179",
  "lockDuration":"0x6851d0d2","lockBps":"0x322cb15d","totalReserved":"0xa31a9030",
  "availableTmsr":"0x7b0a4a61","createPaused":"0x64f0d0b0","claimPaused":"0xf9bca5a2",
  "signAddr":"0x2d1e0dc8","lightEnergy":"0xc94aec1d","getReserves":"0x0902f1ac",
  "totalSupplyLP":"0x18160ddd","lpBalance":"0x70a08231","decimals":"0x313ce567",
}

def rpc_call(rpc, method, params, rpc_id=1):
    body = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":rpc_id}).encode()
    req = urllib.request.Request(rpc, data=body, headers={
        "Content-Type":"application/json",
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=12) as resp:
        d = json.loads(resp.read().decode())
    if "error" in d:
        raise RuntimeError(d["error"])
    return d["result"]

def call(rpc, to, data):
    return rpc_call(rpc, "eth_call", [{"to":to,"data":data}, "latest"])

def retry(fn, tries=2, sleep=0.8):
    last=None
    for i in range(tries):
        for rpc in RPCS:
            try:
                return fn(rpc)
            except Exception as e:
                last=e; continue
        if i < tries-1: time.sleep(sleep)
    raise last

def hex_to_int(h):
    if not h or h == "0x": return 0
    return int(h, 16)

def as_uint(h): return hex_to_int(h)
def as_bool(h): return hex_to_int(h) != 0
def dec18(n): return n / 1e18
def dec6(n): return n / 1e6

def pad64(s): return s.lower().replace("0x","").rjust(64,"0")
def bal_of(token, who): return retry(lambda r: call(r, token, SIG["balanceOf"] + pad64(who)))
def total_supply(token): return retry(lambda r: call(r, token, SIG["totalSupply"]))
def get_owner(contract): return retry(lambda r: call(r, contract, SIG["owner"]))

def dec_scale(token):
    """动态查询代币精度，失败默认 18"""
    try:
        d = as_uint(retry(lambda r: call(r, token, SIG["decimals"])))
        return 10 ** d if 0 < d <= 30 else 1e18
    except Exception:
        return 1e18

def main():
    out = {"ts": int(time.time()), "iso": datetime.datetime.now().isoformat(timespec="seconds"), "block": None}
    try:
        out["block"] = hex_to_int(retry(lambda r: rpc_call(r, "eth_blockNumber", [])))
    except Exception: out["block"] = None
    T = lambda a: ADDR[a]

    def run_safes(items):
        """并发执行字段查询：items = [(target_dict, key, fn)]，异常置 None"""
        def _do(it):
            d, k, fn = it
            try: d[k] = fn()
            except Exception: d[k] = None
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_do, items))

    # --- 全部字段查询（Token / Light / Turbo / Vault / Withdraw）并发 ---
    tok, lt, tb = {}, {}, {}
    items = []
    # Token
    items += [(tok,"totalSupply", lambda: dec18(as_uint(total_supply(T("token"))))),
              (tok,"owner", lambda: get_owner(T("token"))[:12]+"…"),
              (tok,"buyEnabled", lambda: as_bool(retry(lambda r: call(r, T("token"), SIG["buyEnabled"])))),
              (tok,"buyTaxBps", lambda: as_uint(retry(lambda r: call(r, T("token"), SIG["buyTaxBps"])))),
              (tok,"baseSellTaxBps", lambda: as_uint(retry(lambda r: call(r, T("token"), SIG["baseSellTaxBps"])))),
              (tok,"twapPrice", lambda: dec18(as_uint(retry(lambda r: call(r, T("token"), SIG["twapPrice"]))))),
              (tok,"dailyBasePrice", lambda: dec18(as_uint(retry(lambda r: call(r, T("token"), SIG["dailyBasePrice"]))))),
              (tok,"waitingFeeTmsr", lambda: dec18(as_uint(retry(lambda r: call(r, T("token"), SIG["waitingFee"]))))),
              (tok,"balVault", lambda: dec18(as_uint(bal_of(T("token"), T("vault"))))),
              (tok,"balDead", lambda: dec18(as_uint(bal_of(T("token"), T("dead"))))),
              (tok,"balInitRec", lambda: dec18(as_uint(bal_of(T("token"), T("initRec")))))]
    # LightEnergy
    items += [(lt,"salePrice", lambda: dec18(as_uint(retry(lambda r: call(r, T("light"), SIG["salePrice"]))))),
              (lt,"purchaseUnit", lambda: dec18(as_uint(retry(lambda r: call(r, T("light"), SIG["purchaseUnit"]))))),
              (lt,"burnBps", lambda: as_uint(retry(lambda r: call(r, T("light"), SIG["burnBps"])))),
              (lt,"totalOrders", lambda: as_uint(retry(lambda r: call(r, T("light"), SIG["totalOrders"])))),
              (lt,"salePaused", lambda: as_bool(retry(lambda r: call(r, T("light"), SIG["salePaused"])))),
              (lt,"treasuryPaused", lambda: as_bool(retry(lambda r: call(r, T("light"), SIG["treasuryPaused"])))),
              (lt,"balTmsr", lambda: dec18(as_uint(bal_of(T("token"), T("light"))))),
              (lt,"balUsdt", lambda: as_uint(bal_of(T("usdt"), T("light"))) / dec_scale(T("usdt")))]
    # Turbo
    items += [(tb,"lockDuration", lambda: as_uint(retry(lambda r: call(r, T("turbo"), SIG["lockDuration"])))),
              (tb,"lockBps", lambda: as_uint(retry(lambda r: call(r, T("turbo"), SIG["lockBps"])))),
              (tb,"totalReservedTmsr", lambda: dec18(as_uint(retry(lambda r: call(r, T("turbo"), SIG["totalReserved"]))))),
              (tb,"availableTmsr", lambda: dec18(as_uint(retry(lambda r: call(r, T("turbo"), SIG["availableTmsr"]))))),
              (tb,"balTmsr", lambda: dec18(as_uint(bal_of(T("token"), T("turbo")))))]
    # Vault / Withdraw
    vw, wd = {}, {}
    items += [(vw,"balTmsr", lambda: dec18(as_uint(bal_of(T("token"), T("vault"))))),
              (wd,"balTmsr", lambda: dec18(as_uint(bal_of(T("token"), T("withdraw")))))]
    run_safes(items)
    out["token"], out["light"], out["turbo"], out["vault"], out["withdraw"] = tok, lt, tb, vw, wd

    # --- Pair（独立并发任务） ---
    pr = {}
    def q_pair():
        d = {}
        res = retry(lambda r: rpc_call(r, "eth_call", [{"to":T("pair"),"data":SIG["getReserves"]}, "latest"]))
        raw = res[2:] if res.startswith("0x") else res
        r0 = int(raw[0:64], 16); r1 = int(raw[64:128], 16)
        d["reserveUsdt"] = dec18(r0); d["reserveTmsr"] = dec18(r1)
        d["dexPrice"] = round(dec18(r0)/dec18(r1), 6)
        d["lpTotal"] = dec18(as_uint(total_supply(T("pair"))))
        d["lpInitRec"] = dec18(as_uint(bal_of(T("pair"), T("initRec"))))
        d["lpLockedPct"] = round(100*d["lpInitRec"]/d["lpTotal"], 2) if d["lpTotal"] else None
        return d
    try:
        pr = q_pair()
    except Exception as e:
        pr = {"error": str(e)}
    out["pair"] = pr

    # --- 指标计算 ---
    try:
        tk = out.get("token", {}); lt = out.get("light", {}); tb = out.get("turbo", {}); pr = out.get("pair", {})
        m = {}
        if pr and "dexPrice" in pr:
            px = pr["dexPrice"]; m["dexPrice"] = px
        sp = lt.get("salePrice")
        if sp and m.get("dexPrice"):
            m["salePriceDevPct"] = round((sp - m["dexPrice"])/m["dexPrice"]*100, 1)
        if pr and "lpLockedPct" in pr:
            m["lpLockedPct"] = pr["lpLockedPct"]
        if tk and tk.get("totalSupply") and tk.get("balVault") is not None:
            m["vaultSharePct"] = round(100*tk["balVault"]/tk["totalSupply"], 2)
        if tb and tb.get("totalReservedTmsr") is not None and tb.get("availableTmsr") is not None:
            if tb["totalReservedTmsr"] > 0:
                m["settlementRatio"] = round(100*(tb["availableTmsr"]-tb["totalReservedTmsr"])/tb["availableTmsr"], 2)
            else:
                m["settlementRatio"] = 0
        # 健康度：基准 100，逐项扣分；数据缺失的维度不参与扣分
        health = 100; penalized = False
        if tk and tk.get("buyEnabled") is False: health -= 25; penalized = True
        if m.get("salePriceDevPct") is not None and abs(m["salePriceDevPct"]) > 30: health -= 25; penalized = True
        if m.get("vaultSharePct") is not None and m["vaultSharePct"] > 50: health -= 20; penalized = True
        if m.get("lpLockedPct") is not None and m["lpLockedPct"] < 10: health -= 20; penalized = True
        if lt and lt.get("totalOrders") == 0: health -= 15; penalized = True
        if penalized and health > 28: health = 28
        if not penalized: health = None  # 数据不足不评分
        m["health"] = health
        out["metrics"] = m
    except Exception as e:
        out["metrics"] = {"error": str(e)}

    # 落盘供推送/预测模块使用
    try:
        state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmsr_state.json")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
