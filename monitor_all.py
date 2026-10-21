#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMSR 全地址全资产深挖采集（monitor_all.py 数据源）
对全部关联地址读取 TMSR / USDT / LP / BNB 余额矩阵 + 税费豁免名单，
尝试历史事件日志（getLogs，公共 RPC 尽力而为）。
输出：all_addresses.json（含每地址四币种余额、总净值、逐轮 delta 记录）
"""
import json, time, datetime, urllib.request, os, sys
from concurrent.futures import ThreadPoolExecutor

RPCS = ["https://bsc-rpc.publicnode.com", "https://bsc.publicnode.com",
        "https://bsc.meowrpc.com", "https://bsc-mainnet.public.blastapi.io",
        "https://1rpc.io/bnb"]
ARCHIVE_RPCS = ["https://bsc-mainnet.public.blastapi.io", "https://bsc-rpc.publicnode.com"]

TOKEN  = "0xD8D3cD314FdBB54435A6e7CCcca1adbbdf68674F"
USDT   = "0x55d398326f99059fF775485246999027B3197955"
PAIR   = "0xb8a80acfb85d7e162d5b96f59ff2177f6d131371"
LIGHT  = "0x651f0EF421EfDe887dF55f05b2C243008CdF5B49"
TURBO  = "0xa5D430d8D33D2Ed95D4ce1A92b42E03EeC83bD96"
VAULT  = "0xD026b745B1096CdD0ba618eDC48a56Ce38939eEf"
WITHD  = "0x99686192b091c212E613652DBfe3b003Bce7722A"
DEAD   = "0x000000000000000000000000000000000000dEaD"

# 全部关联地址（含角色标注）
ADDRS = [
  ("token合约", TOKEN), ("light合约", LIGHT), ("turbo合约", TURBO),
  ("vault合约", VAULT), ("withdraw合约", WITHD),
  ("token owner/tradingController", "0xb566b5aea04a35962fecf0e439ec1f66205c4884"),
  ("initialRecipient(21亿初始接收)", "0x53e3294cf3b04d7ef5f5afa984fc727d1b617ecc"),
  ("marketingWallet", "0x7d037e47b9fa8216203ec16ddb1dc7cf7d206638"),
  ("light owner", "0x8203d38b229259bf3d1e50587986c8209112709b"),
  ("turbo owner", "0xdcded4392e6a8063c4e36d463d70037e5e464d9a"),
  ("turbo signAddr", "0x6791b0540753323bfaf297e05e3c191cd3e02eac"),
  ("vault owner", "0x7761bcefeaa573a023f43ccf563b647d0b653e55"),
  ("withdraw owner", "0x91fc60e038775d156bb9c1f897736e4e38a1d626"),
  ("withdraw signAddr", "0xb427c4b585bafd7b6c4bb1e2556ab47a0621fde5"),
  ("DEX pair", PAIR),
  ("死地址", DEAD),
]
UA = {"Content-Type":"application/json",
      "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SIG = {"balanceOf":"0x70a08231","decimals":"0x313ce567","getReserves":"0x0902f1ac",
       "totalSupply":"0x18160ddd","isExcluded":"0xd84a6e84"}

def rpc_call(rpc, method, params, rid=1):
    body = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":rid}).encode()
    req = urllib.request.Request(rpc, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.loads(r.read().decode())
    if "error" in d: raise RuntimeError(d["error"]["message"])
    return d["result"]

def call(rpc, to, data):
    return rpc_call(rpc, "eth_call", [{"to":to,"data":data}, "latest"])

def retry(fn, tries=2, sleep=0.6):
    last=None
    for i in range(tries):
        for rpc_ in RPCS:
            try: return fn(rpc_)
            except Exception as e: last=e; continue
        if i < tries-1: time.sleep(sleep)
    raise last

def h2i(h):
    return int(h, 16) if h and h != "0x" else 0
def pad(a): return a.lower().replace("0x","").rjust(64,"0")
def bal(token, who):
    return h2i(retry(lambda r: call(r, token, SIG["balanceOf"]+pad(who))))
def dec(token, raw):
    try:
        d = h2i(retry(lambda r: call(r, token, SIG["decimals"])))
        return raw / (10 ** d) if 0 < d <= 30 else raw / 1e18
    except Exception:
        return raw / 1e18

def _safe(fn):
    try: return fn()
    except Exception: return None

def query_addr(item):
    name, addr = item
    rec = {"name": name, "address": addr}
    rec["tmsr"] = _safe(lambda: dec(TOKEN, bal(TOKEN, addr)))
    rec["usdt"] = _safe(lambda: dec(USDT, bal(USDT, addr)))
    rec["lp"]   = _safe(lambda: dec(PAIR, bal(PAIR, addr)))
    rec["bnb"]  = _safe(lambda: h2i(retry(lambda r: rpc_call(r, "eth_getBalance", [addr, "latest"]))) / 1e18)
    return rec

def main():
    out = {"ts": int(time.time()), "iso": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "block": None, "addresses": {}}
    try:
        out["block"] = h2i(retry(lambda r: rpc_call(r, "eth_blockNumber", [])))
    except Exception: pass
    # 1) 全地址矩阵（并发）
    with ThreadPoolExecutor(max_workers=8) as ex:
        for rec in ex.map(query_addr, ADDRS):
            out["addresses"][rec["address"]] = rec
    # 2) pair 池子状态
    try:
        res = retry(lambda r: rpc_call(r, "eth_call", [{"to":PAIR,"data":SIG["getReserves"]}, "latest"]))
        raw = res[2:]; r0 = int(raw[0:64],16); r1 = int(raw[64:128],16)
        out["pool"] = {"usdt": r0/1e18, "tmsr": r1/1e18,
                       "price": round(r0/r1, 6) if r1 else None,
                       "lpTotal": dec(PAIR, h2i(retry(lambda r: call(r, PAIR, SIG["totalSupply"]))))}
    except Exception as e:
        out["pool"] = {"error": str(e)}
    # 3) 税费豁免名单（token.isExcludedFromFees，并发）
    def q_excl(item):
        name, addr = item
        try:
            return (addr, name, bool(h2i(retry(lambda r: call(r, TOKEN, SIG["isExcluded"]+pad(addr))))))
        except Exception:
            return (addr, name, None)
    excl = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for addr, name, v in ex.map(q_excl, ADDRS):
            excl[name] = v
    out["excluded"] = excl
    # 4) 历史事件日志（尽力而为，Transfer 最近 200 条）
    topics = ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]
    logs = {"ok": False, "count": 0, "sample": [], "error": None}
    try:
        latest = out["block"] or h2i(retry(lambda r: rpc_call(r, "eth_blockNumber", [])))
        for ar in ARCHIVE_RPCS:
            try:
                res = rpc_call(ar, "eth_getLogs", [{"address": TOKEN, "topics": [topics], "fromBlock": hex(latest-2000), "toBlock": "latest"}])
                logs["ok"] = True; logs["count"] = len(res)
                logs["sample"] = [{"block": l.get("blockNumber"), "from": "0x"+l.get("topics",["",""])[1][-40:], "to": "0x"+l.get("topics",["","",""])[2][-40:], "data": l.get("data","")[:20]} for l in res[:10]]
                break
            except Exception as e:
                logs["error"] = str(e); continue
    except Exception as e:
        logs["error"] = str(e)
    out["logs"] = logs
    # 5) 保存
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_addresses.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"block": out["block"], "pool": out.get("pool"), "logs_ok": logs["ok"],
                       "logs_count": logs["count"], "excluded_count": sum(1 for v in excl.values() if v is True),
                       "matrix": {k: {kk: vv for kk, vv in v.items() if kk in ("tmsr","usdt","lp","bnb")} for k, v in out["addresses"].items()}}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
