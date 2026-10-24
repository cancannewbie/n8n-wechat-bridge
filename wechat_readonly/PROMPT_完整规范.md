# 微信群图识图桥接 · 完整系统/运维提示词（规范）

> 版本：2026-10-24 · 适用目录 `C:\n8n-wechat-bridge` + n8n 工作流 `zlv4DMcVAEqr135U`（Excel 解析 → Minimax）  
> 用途：约束后续改代码、改工作流、排障时的目标与边界，避免再出现「假 PNG / 双模型 400 / 写表 [object Object]」类问题。

---

## 0. 一句话目标

在**不向微信发任何消息**的前提下，尽可能可靠地把「群聊新图片」与「网页表单上传图片」变成：  
① 标准 JPEG/PNG/GIF/WEBP → ② Minimax 识图（失败则 DeepSeek）→ ③ Telegram 原图+短讯 → ④ 本机 Excel 一行记录。

覆盖失败路径时，必须给出**可操作的中文原因**，而不是 `[object Object]` 或模糊的「格式无效」。

---

## 1. 系统边界（永远遵守）

### 1.1 允许做
- 只读扫描微信本地消息库 / attach `.dat`，解密后转标准图，POST 到本机 n8n webhook。
- 表单 `/form/image-recognize`、表格表单、Excel `append_api:8787`、Telegram 推送。
- Minimax 主识图，DeepSeek（`deepseek-flash`）兜底；限流可短重试后再切兜底。
- 群白名单（空=全群）、msgid 幂等、日志与备份。

### 1.2 永远不要做
- **禁止**用微信协议/UI 自动发消息、点赞、加好友、改资料。
- **禁止**把 API Key、AES 图密钥、`.dat` 原文、完整 base64 打进 Telegram 或公开日志。
- **禁止**在未验证魔数前，仅凭扩展名 / `Content-Type` / 文件名声称「是 PNG/JPEG」。
- **禁止**把 wxgf/HEVC/未知二进制直接当 `image/png` 或 `image/jpeg` 送给视觉模型。
- **禁止**扩大产品范围（朋友圈、文件传输助手自动回、发票专用字段强迫等）——除非用户明确要求。
- **禁止**因一次瞬时网络错误就把 msgid 永久标为已处理（永久失败除外，见失败分类）。

---

## 2. 架构与数据流

```
微信群新图
  → Windows wechat_readonly/monitor.py（轮询解密库）
  → 读 attach *.dat（V2 AES+XOR / XOR / V1）
  → dat_decrypt → 原始 blob + 魔数检测
  → image_convert.ensure_standard_image（wxgf/HEVC/BMP/未知 → ffmpeg → JPEG）
  → 再次魔数校验（必须是 jpg/png/gif/webp）
  → POST JSON {imageBase64,imageMime,msgid,...}
       → n8n http://YOUR_N8N_HOST:5678/webhook/wechat-image

并行入口：
  · 表单 /form/image-recognize（二进制上传，可有预览页）
  · 表格表单（Excel 解析路径，文字结果，不强制原图）

n8n 识图主链：
  规范化* → 准备图片请求（魔数+dataURL+双模型 body）
    → Minimax 识图（可短重试）
       成功 → 整理识图结果 → 组装写表 → append_api → 短文案 → TG 照片 → TG 文字
       失败 → DeepSeek 识图 → 同上（文案标 DeepSeek）
       双失败 → 整理失败消息 → TG 失败照片（尽量带原图）→ TG 失败文字
```

关键路径：
| 组件 | 路径 / 地址 |
|------|-------------|
| 桥接根目录 | `C:\n8n-wechat-bridge` |
| 监控 | `wechat_readonly\monitor.py` + `start_monitor.bat` / `stop_monitor.bat` |
| 配置 | `wechat_readonly\config.json` |
| 临时图 | `wechat_readonly\temp_images\` |
| 日志 | `wechat_readonly\logs\monitor_*.log` |
| 写表 API | `append_api.py` · `http://YOUR_N8N_HOST:5678` · `start_append_api_bg.bat` |
| Excel | `output\results.xlsx` |
| n8n | `YOUR_LAN_HOST:5678` · 工作流 id `zlv4DMcVAEqr135U` |

---

## 3. 输入契约

### 3.1 微信 webhook JSON（monitor → n8n）
必填：`source=wechat`，`msgid`，`imageBase64`，`imageMime`（须与真实魔数一致），`imageFileName`（扩展名与格式一致）。  
建议：`groupName/groupId/senderName/senderId/createTime/localDatPath`。

### 3.2 表单
用户上传文件；规范化后进入同一条「准备图片请求」链。可选 `instruction` 追加到识图提示。

### 3.3 群过滤
- `groups_only=true`：只处理群。
- `group_allowlist` / `group_allowlist_ids`：空数组 = 全群；非空 = 仅名单内。

---

## 4. 格式管线（硬规则，防「假 PNG」）

### 4.1 解密后立刻魔数检测（`dat_decrypt.detect_image_format`）
| 头部 | 判定 |
|------|------|
| `FF D8 FF` | jpg |
| `89 50 4E 47` | png |
| `GIF8` | gif |
| `RIFF....WEBP` | webp |
| `BM` | bmp（须转 JPEG 后再送模型） |
| `wxgf` | hevc/微信封装（**禁止**直接当图） |
| `00 00 00 01` / `00 00 01` 等 Annex-B | 疑似 hevc |
| `07 08 V2 08 07` / V1 | 仍是密文，说明解密失败 |
| 其他 | `bin` |

### 4.2 `ensure_standard_image` 职责
1. 若已是 jpg/png/gif/webp → 原样返回，mime 对齐。  
2. 若是 bmp / hevc / wxgf / bin → 用配置的 `ffmpeg_path`（或 PATH）尝试转 **JPEG**（多策略：直接 demux、`-f hevc`、跳过 wxgf 头 4/16/32/38/64 字节）。  
3. 转完必须再跑魔数：非标准则 `ValueError`，**中文**说明缺 ffmpeg / 转码失败 / 仍是 wxgf。  
4. 监控在 POST 前再断言一次魔数；失败则记日志，msgid 标永久失败（格式类），不轰炸 API。

### 4.3 n8n 侧二次闸门
「规范化微信图片」「规范化表单图片」「准备图片请求」均须按**字节魔数**判定；  
若仍是 wxgf/bin/hevc → **抛中文错**（归类 `FMT_INVALID`），不要调用 Minimax/DeepSeek。

### 4.4 MIME / 文件名
以魔数为准改写 `mimeType` 与扩展名；禁止信任上游自称的 `image/png`。

---

## 5. 模型级联

1. **主**：Minimax `MiniMax-M3`（`api.minimaxi.com`），`thinking.disabled`，温度 0.2。  
2. **限流/瞬时**：Minimax HTTP 节点开启短重试（建议最多 3 次、间隔约 5s），覆盖 429/5xx/超时。  
3. **兜底**：Minimax 仍失败 → DeepSeek `deepseek-flash`（`api.deepseek.com`），同一 dataURL。  
4. **双失败**：走失败通知；文案须同时摘要两侧错误（截断），带分类码。  
5. 成功结果 `provider` 记为 `minimax` 或 `deepseek`，Telegram 短讯标注模型名。

识图提示词原则：通用描述可见内容；不强迫发票字段；不要 JSON 外壳；不要「未识别」占位。

---

## 6. 幂等与重试

| 场景 | 行为 |
|------|------|
| 同一 `msgid` 已成功 POST | 跳过（`monitor_state.json` processed） |
| attach 尚未落盘 | 不标记 processed，下轮再试 |
| V2 缺 AES key | 不标记，等 `capture_image_key` |
| 解密失败（有 key 仍失败） | 标记 processed（永久），打日志 |
| 格式无法转换 | 标记 processed（永久），打中文原因 |
| webhook 网络错 / 5xx / 超时 | **不**标记，下轮重试 |
| webhook 4xx 业务拒绝（如重复） | 可标记，避免死循环；日志写清 |
| 模型 429 | 节点短重试 → 仍失败切 DeepSeek |
| append_api 宕机 | 识图仍算成功；TG 提示写表失败与启动命令 |

---

## 7. 输出行为

### 7.1 Telegram
- 成功：先发**原图**（caption 含短讯），再发文字短讯（若工作流如此配置）。  
- 失败：尽量仍发原图 + 失败短讯；无 binary 时照片节点 `continueOnFail`，文字仍要发出。  
- 短讯禁止 `[object Object]`：一切 error 对象必须 `formatErr` 抽 `message/description/status`。

### 7.2 Excel（`results.xlsx`）
列：time, source, group, sender, msgid, status, summary, readable_text, raw_file。  
summary 建议带 `[minimax]`/`[deepseek]`。  
写表地址：`POST http://YOUR_N8N_HOST:5678/append`。

### 7.3 表单
提交后可有预览 HTML；识别异步走同一模型链。

---

## 8. 失败分类与中文文案（taxonomy）

| 代码 | 含义 | 用户可见示例 | 处理 |
|------|------|--------------|------|
| `FMT_INVALID` | 魔数非标准图 | 图片不是 JPEG/PNG/GIF/WEBP（检测到 wxgf/HEVC）。请确认监控已转码后重发。 | 永久；修转换 |
| `FMT_NO_FFMPEG` | 需要转码但无 ffmpeg | 微信图为封装格式且未找到 ffmpeg，请安装或配置 ffmpeg_path | 永久直至环境修复后人工重发 |
| `DECRYPT_FAIL` | .dat 解密失败 | 图片解密失败，请确认已捕获 AES 图密钥 | 视情况 |
| `AES_KEY_MISSING` | 无 V2 key | 跳过并等待密钥（日志） | 不标记 |
| `MODEL_RATE_LIMIT` | 429 | Minimax 限流，已重试/已切 DeepSeek… | 自动 |
| `MODEL_BOTH_FAIL` | 双模型失败 | 识图失败：Minimax:…；DeepSeek:… | TG 通知 |
| `APPEND_DOWN` | 8787 不可达 | 识图成功但写表失败：请运行 start_append_api_bg.bat | 识图成功 |
| `WEBHOOK_TRANSIENT` | n8n/网络瞬时 | 日志；下轮重试 | 不标记 msgid |
| `MONITOR_DOWN` | 监控未跑 | （用户无 TG）任务管理器无 python / 无新日志 | 启 monitor |
| `UNKNOWN` | 其它 | 识图失败：…（截断 180 字） | TG |

整理失败消息节点必须：解析对象错误、拼接双模型摘要、尽量带回「准备图片请求」的 binary。

---

## 9. 运维清单

### 日常启动（本机 Windows）
1. 微信 PC 保持登录。  
2. `wechat_readonly\start_monitor.bat`（要看窗口）或保持后台 python；停：`stop_monitor.bat`。  
3. `start_append_api_bg.bat`（8787）。  
4. n8n 服务器 `YOUR_LAN_HOST:5678` 工作流保持 Active。

### 首次 / 密钥
- 图 AES：微信里打开几张图后跑 `start_capture_image_key.bat`。  
- DB 密钥：`extract_db_keys`（监控启动可自动 refresh）。

### 验证
1. 群里发一张普通 JPG/PNG。  
2. 再发一张曾失败的「朋友圈式/wxgf」图。  
3. 打开表单传图。  
4. 看 TG 原图+「识图成功（Minimax|DeepSeek）」；打开 `output\results.xlsx` 新行。  
5. 故意停 append_api，应看到写表失败中文提示且仍有识图结果。

### 日志位置
- `wechat_readonly\logs\monitor_stdout.log` / `monitor_stderr.log`  
- `logs\append_api.log`  
- n8n Executions 页面

---

## 10. 改动原则（给后续 Agent / 人）

1. 先对照本规范，再改代码或工作流。  
2. 任何「图片进模型」路径必须经过魔数闸门。  
3. 用户可见字符串全部中文、禁止 Object 字符串化敷衍。  
4. 改 n8n 前备份 `workflow_entity` / `/root/n8n-backups`。  
5. 不新增「自动回微信」能力。  
6. 本文件与实现不一致时：**先改实现迎合本规范**，或修订规范并注明日期。

---

## 11. 验收标准（Definition of Done）

- [ ] wxgf/HEVC 解密后不会以假 PNG 出站；出站魔数为 jpg/png/gif/webp。  
- [ ] Minimax 429 会短重试，仍失败才 DeepSeek。  
- [ ] 双失败 TG 有原图（若可得）+ 双侧错误摘要。  
- [ ] append_api 宕机时无 `[object Object]`。  
- [ ] msgid 幂等；瞬时 webhook 失败会重试。  
- [ ] 本规范文件存在于仓库根目录与 `wechat_readonly\` 副本。
