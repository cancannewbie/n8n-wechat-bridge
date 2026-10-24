# n8n-wechat-bridge

微信群「销售单」截图 → 本机只读解密/转码 → n8n 识图（**Minimax 主** + **DeepSeek 兜底**）→ Telegram 通知 → Excel 落表（红框字段 + 嵌图）。

仓库：https://github.com/cancannewbie/n8n-wechat-bridge

> **安全边界**：只读微信本地消息库与图片缓存，**绝不**向微信自动发消息、点赞或加好友。  
> 本仓库**不含**真实 API Key、数据库密钥、Telegram Token/Chat ID、内网 IP 或个人路径。

---

## 1. 功能概览

| 能力 | 说明 |
|------|------|
| 微信群新图监控 | Windows 后台轮询解密库与 attach `.dat`，标准图 POST 到 n8n webhook |
| 网页表单识图 | n8n Form `/form/image-recognize`，提交后可预览原图 |
| 双模型级联 | Minimax 主识图；429/失败短重试后自动切 DeepSeek `deepseek-flash` |
| 销售单红框字段 | 抽取：`商品编号`、`商品名称`、`数量`、`备注`、`摘要` |
| Excel 落表 | `output/results_销售单.xlsx`，六列（五字段 + `图片` 嵌缩略图） |
| Telegram | 成功/失败尽量附原图 + 中文短讯（禁止 `[object Object]`） |
| 格式闸门 | 魔数检测；wxgf/HEVC/BMP 经 ffmpeg 转 JPEG 后再送模型 |
| 无弹窗后台 | `start_monitor_bg.bat` / `start_append_api_bg.bat`（pythonw + 隐藏窗） |

---

## 2. 架构

```
微信 PC（登录）
  └─ wechat_readonly/monitor.py（后台 pythonw）
       ├─ 解密 message DB / attach *.dat
       ├─ image_convert.ensure_standard_image（魔数 + ffmpeg）
       └─ POST JSON → n8n /webhook/wechat-image

并行入口：n8n Form /form/image-recognize

n8n 工作流
  规范化 → 准备图片请求（魔数闸门 + dataURL）
    → Minimax（短重试）→ 成功
    → 失败 → DeepSeek → 成功 / 双失败
  → 解析销售单字段（可多商品多行）
  → POST 本机 append_api:8787
  → Telegram 原图 + 短讯

append_api.py → output/results_销售单.xlsx
  列：商品编号 | 商品名称 | 数量 | 备注 | 摘要 | 图片
```

---

## 3. 依赖

### 3.1 环境

- Windows 10/11（微信 PC 与监控建议同机）
- **Python 3.11+**（需 `python` 与 `pythonw`）
- **ffmpeg**（进 PATH，或在配置里写绝对路径）
- **微信 PC** 保持登录
- **n8n**（可导入本仓库 `n8n/workflow.json`）

### 3.2 Python 包

```bat
cd /d C:\n8n-wechat-bridge
pip install -r requirements.txt
pip install -r wechat_readonly\requirements.txt
```

根目录 `requirements.txt` 主要为 `openpyxl`（写表与嵌图）。  
`wechat_readonly/requirements.txt` 含 `requests`、`pycryptodome` 等（以文件为准）。

### 3.3 n8n 凭据

1. Minimax API Key（主识图）
2. DeepSeek API Key（兜底，`deepseek-flash`）
3. Telegram Bot Token + Chat ID

详见 [`n8n/CREDENTIALS.md`](n8n/CREDENTIALS.md)。

---

## 4. 快速开始

```bat
:: 1) 配置
copy wechat_readonly\config.example.json wechat_readonly\config.json
copy config.example.json config.json
:: 编辑上述 json：webhook_url、微信数据路径、ffmpeg_path

:: 2) 密钥
:: 微信已登录后：
wechat_readonly\extract_keys.bat
:: 在微信里打开几张群大图后：
wechat_readonly\start_capture_image_key.bat

:: 3) 导入 n8n/workflow.json，按 CREDENTIALS.md 绑凭据，改 append URL 与 Chat ID，Activate

:: 4) 日常启动（无黑窗）
start_append_api_bg.bat
wechat_readonly\start_monitor_bg.bat
```

停止监控：`wechat_readonly\stop_monitor.bat`。

---

## 5. 配置详解

### 5.1 `wechat_readonly/config.example.json`

| 字段 | 含义 | 示例 / 注意 |
|------|------|-------------|
| `webhook_url` | n8n 收图地址 | `http://YOUR_N8N_HOST:5678/webhook/wechat-image` |
| `wx_data_dir` | 微信数据根目录 | `C:\Users\你\xwechat_files\wxid_xxx` |
| `db_storage_dir` | 消息库 | `...\db_storage` |
| `attach_dir` | 图片 attach | `...\msg\attach` |
| `ffmpeg_path` | ffmpeg | `ffmpeg` 或绝对路径 |
| `groups_only` | 仅群聊 | `true` |
| `group_allowlist` | 群名白名单；**`[]` = 全群** | `[]` |
| `group_allowlist_ids` | 群 ID 白名单 | `[]` |
| `poll_interval_seconds` | 轮询秒数 | `5` |
| `decrypt_db_on_start` | 启动时刷新解密库 | `true` |
| `lookback_seconds_on_first_run` | 首次回溯；生产建议 `0` 只处理新图 | `0` |
| `dry_run` | 只扫描不 POST | `false` |
| `python_exe` | 解释器名 | `python` |
| `xor_key` / 空路径字段 | 默认相对 `state`/`temp_images` 等 | 保持空字符串即可 |

复制为 `config.json` 后填写；**不要提交** `config.json`。

### 5.2 根目录 `config.example.json`

用于可选的文件夹丢图监视（`bridge_folder_watch.py`）：

- `webhook_url`：同上  
- `append_api_url`：建议 `http://127.0.0.1:8787/append`  
- `watch_dir` / `processed_dir`：可留空用默认 `inbox` / `processed`

### 5.3 AES 图密钥与 DB 密钥

| 步骤 | 脚本 | 产出（均在 `wechat_readonly/state/`，勿提交） |
|------|------|-----------------------------------------------|
| DB 密钥 | `extract_keys.bat` | `all_keys.json`（参考 `all_keys.example.json`） |
| 图片 AES | 微信打开大图后 `start_capture_image_key.bat` | `found_image_keys*.txt` 等 |

无 AES 时 V2 `.dat` 会等待密钥，不永久占死 msgid。

---

## 6. n8n 工作流

1. Import → 选择 [`n8n/workflow.json`](n8n/workflow.json)（已脱敏）  
2. 创建并绑定 Minimax / DeepSeek / Telegram 凭据  
3. 修改写表 URL 为 `http://<桥接机>:8787/append`  
4. 填写 Telegram Chat ID  
5. **Activate**

| 入口 | 路径 |
|------|------|
| 微信 webhook | `POST /webhook/wechat-image` |
| 识图表单 | `/form/image-recognize` |

识图提示词约定只输出销售单红框 JSON：`摘要`、`商品[]`（`商品编号`/`商品名称`/`数量`）、`备注`。多商品拆多行写入 Excel。

---

## 7. Excel 输出

路径：`output\results_销售单.xlsx`

| 列名 | 来源 |
|------|------|
| 商品编号 | 红框「商品编号」 |
| 商品名称 | 红框「商品名称」 |
| 数量 | 红框「数量」 |
| 备注 | 红框「备注」 |
| 摘要 | 红框「摘要」（含收件信息等） |
| 图片 | 识别原图缩略图（单元格内嵌） |

不再写入 time/source/group 等元数据列。若 Excel 正打开该文件，可能临时写入 `results_销售单_写入中.xlsx`。

---

## 8. 日常运维

开机顺序：

1. 登录微信 PC  
2. `start_append_api_bg.bat`  
3. `wechat_readonly\start_monitor_bg.bat`  
4. 确认 n8n 工作流 Active  

排障才用带窗口的 `start_monitor.bat` / `start_append_api.bat`。

日志：

- `wechat_readonly\logs\monitor_stdout.log` / `monitor_stderr.log`
- `logs\append_api.log`
- n8n Executions

更多：[`OPS_运维速查.md`](OPS_运维速查.md)、[`验收清单.md`](验收清单.md)。

---

## 9. 失败分类（排障）

| 代码 | 现象 | 处理 |
|------|------|------|
| `FMT_INVALID` | 格式无效 / 假 PNG | 确认 ffmpeg 与转码后**重发** |
| `FMT_NO_FFMPEG` | wxgf/HEVC 无法转 | 安装或配置 `ffmpeg_path` |
| `DECRYPT_FAIL` | .dat 解不开 | 检查 AES；再跑 capture |
| `AES_KEY_MISSING` | 无 V2 key | 打开大图后 capture |
| `MODEL_RATE_LIMIT` | HTTP 429 | 自动重试 → DeepSeek |
| `MODEL_BOTH_FAIL` | 双模型失败 | 看 TG 双侧摘要；查 Key/额度 |
| `APPEND_DOWN` | 识图成功写表失败 | `start_append_api_bg.bat` |
| `WEBHOOK_TRANSIENT` | 网络瞬时 | msgid 不永久占用，下轮重试 |
| `MONITOR_DOWN` | 无新日志 | 启 `start_monitor_bg.bat` |

完整规范：[`PROMPT_完整规范.md`](PROMPT_完整规范.md)。

---

## 10. 目录结构

```
n8n-wechat-bridge/
├── README.md
├── README_安装与迁移.md
├── PROMPT_完整规范.md
├── OPS_运维速查.md
├── 验收清单.md
├── .gitignore
├── requirements.txt
├── append_api.py
├── bridge_common.py / bridge_folder_watch.py
├── config.example.json
├── start_append_api.bat / start_append_api_bg.bat / .ps1
├── n8n/workflow.json
├── n8n/CREDENTIALS.md
└── wechat_readonly/
    ├── monitor.py / image_convert.py / dat_decrypt.py / ...
    ├── config.example.json
    ├── start_monitor_bg.bat / stop_monitor.bat / ...
    ├── vendor/
    └── state/*.example.*
```

---

## 11. 安全

**禁止提交：** `all_keys.json`、真实 `found_image_keys*`、`temp_images/`、`decrypted/`、API Key、Telegram Token/Chat ID、内网 IP、含客户信息的 xlsx。  
`.gitignore` 已覆盖常见泄密路径；凭据只放在 n8n。

---

## 12. 相关文档

- [README_安装与迁移.md](README_安装与迁移.md)
- [PROMPT_完整规范.md](PROMPT_完整规范.md)
- [OPS_运维速查.md](OPS_运维速查.md)
- [验收清单.md](验收清单.md)
- [n8n/CREDENTIALS.md](n8n/CREDENTIALS.md)

## 免责声明

仅供在合法授权范围内做本地只读自动化。第三方解密与视觉 API 请遵守其条款。微信客户端变更可能导致失效。
