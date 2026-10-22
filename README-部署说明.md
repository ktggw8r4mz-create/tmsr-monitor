# TMSR 本机监控系统 · 使用说明

已部署在 macOS 本机（launchd 常驻），无需手动干预。

## 零、本机可视化界面（已就绪）

浏览器打开：**http://127.0.0.1:8017**

- 本机常驻 HTTP 服务（`com.hubayi.tmsr.web`，开机自启，仅本机可访问）
- 页面每 60 秒自动读取最新 `all_addresses.json / tmsr_state.json / predict.json`，指标、健康度、预测评分实时刷新
- 手机想访问：把浏览器地址换成 Mac 的局域网 IP（如 http://192.168.x.x:8017，需把 plist 的 --bind 改为 0.0.0.0 后重装）
- 端口冲突可改：编辑 `com.hubayi.tmsr.web.plist` 的 8017 后 `bash install_web.sh` 重装

## 一、当前运行状态

- 定时任务：`com.hubayi.tmsr.monitor`（已加载运行，每 24 小时执行一次）
- 执行链路（每 24 小时）：monitor_all（16 地址×4 资产快照）→‖ tmsr_monitor（16 项指标，并行）→ predict（5 项风险预测）→ notify（变动推送）
- 全部为只读查询（eth_call / eth_getBalance），不触碰私钥、不发起交易
- 日志：`logs/run.log`（每步成败）、`logs/launchd.out.log` / `logs/launchd.err.log`

## 二、Telegram 推送（已激活）

- **状态：已配置完成**（bot_token、chat_id、proxy 已写入 config.json，测试推送已验证）
- 国内网络通过本机代理访问 Telegram（proxy: http://127.0.0.1:7890，已自动探测配置；更换代理后改 config.json 的 proxy 字段）
- 推送内容：任意地址任意资产余额变动（阈值在 config.json 可调）、合约状态变更（买入开关/售价/订单数/暂停开关）、DEX 价格变动 >3%
- 手动验证：`/usr/bin/python3 telegram_notify.py`

## 三、预测功能（已内置）

每轮自动重算 5 项风险事件概率，写入 `predict.json`，监控中心"预测"页自动读取：

| 编号 | 事件 | 触发信号 |
|---|---|---|
| P1 | 开放销售 → 库存被套利抽干 | salePaused=false 且开放销售 |
| P2 | owner 后门提币（金库/提现/光能） | 任一合约余额单块骤降 |
| P3 | initialRecipient 撤池归零 | initialRecipient LP 余额下降 |
| P4 | 涡轮集中兑付 → 偿付缺口 | totalReservedTmsr 接近合约余额 |
| P5 | owner 参数突变（税率/黑名单/开关） | buyEnabled / 税率 / 黑名单变化 |

说明：评分为资金面/结构面信号的规则推断，反映"事件发生的结构性概率"，非价格预测，不构成投资建议。

## 四、启停与排障

```bash
# 查看任务状态
launchctl list | grep tmsr
# 手动跑一轮（验证链路）
/usr/bin/python3 run_all.py
# 卸载（停止定时，文件保留）
bash uninstall_monitor.sh
# 重新安装
bash install_monitor.sh
```

常见问题：
- `run.log` 显示某步 FAIL/TIMEOUT：多为公共 RPC 限流，下一轮会自动重试；持续失败再检查网络。
- 推送未收到：确认 token/chat_id 已填、机器人已 /start 过、`notify.log` 中推送结果。
- 想更密/更疏：修改 `com.hubayi.tmsr.monitor.plist` 的 StartInterval（秒）后重装。

## 五、监控覆盖（全量清单）

- 16 个关联地址 × TMSR/USDT/LP/BNB 四类资产
- 5 条资金流转路径（金库→光能注资 / treasury 护盘 / 涡轮兑付 / 提现发放 / owner 后门）
- 16 项指标 + 5 个红灯 + 5 个情景 + 5 项风险预测
- 待接入：历史行为（24h 量、owner 变更史）需 BscScan API Key 或 archive 节点
