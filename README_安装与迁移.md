# 微信群图识图桥接 · 可移植安装与迁移

> 仓库：https://github.com/cancannewbie/n8n-wechat-bridge
> 详细步骤与字段说明以根目录 [README.md](README.md) 为准；本文是换机速查。


把「微信 PC 只读监控 → n8n 识图（Minimax / DeepSeek）→ Telegram + 本机 Excel」整套迁到任意 Windows 机器。

## 你需要准备

| 组件 | 说明 |
|------|------|
| Windows 10/11 | 安装并登录 **微信 PC**（建议 4.x） |
| Python 3.11+ | `python` 在 PATH 中可用（`python --version`） |
| ffmpeg | 在 PATH，或稍后在 `wechat_readonly\config.json` 填 `ffmpeg_path` |
| n8n | 可在本机或另一台机；需能被 Windows 访问，且 n8n 能回访 Windows 的 `:8787` |
| API | Minimax、DeepSeek、Telegram Bot |

## 目录说明（解压后）

```
n8n-wechat-bridge-portable/
  append_api.py / start_append_api_bg.bat   # 写 Excel
  bridge_folder_watch.py                   # 可选：inbox 文件夹投放
  config.example.json / config.json
  wechat_readonly/                         # 群图监控（只读解密）
    config.example.json / config.json
    start_monitor.bat / stop_monitor.bat
    start_capture_image_key.bat
    extract_keys.bat
  n8n/workflow.json + CREDENTIALS.md       # 导入 n8n
  PROMPT_完整规范.md / OPS_运维速查.md / 验收清单.md
  README_安装与迁移.md                     # 本文件
```

**本包不含**：真实 API Key、数据库密钥、AES 图密钥、解密出的聊天库、个人 `temp_images`。

## 安装步骤（按顺序）

### 1. 解压

解压到任意目录，例如 `D:\n8n-wechat-bridge\`。以下用 `BRIDGE` 表示该目录。

### 2. Python 依赖

```bat
cd /d BRIDGE
python -m pip install -r requirements.txt
cd wechat_readonly
python -m pip install -r requirements.txt
```

### 3. 填写微信侧配置

1. 复制对照：`wechat_readonly\config.example.json` → 已自带 `config.json`，直接改。
2. 必改：
   - `webhook_url` → `http://<你的n8n主机>:5678/webhook/wechat-image`
   - `wx_data_dir` / `db_storage_dir` / `attach_dir` → 本机 `xwechat_files\<你的wxid目录>\...`
3. 建议：`ffmpeg_path` 填 `ffmpeg`（已在 PATH）或完整 `ffmpeg.exe` 路径。
4. `group_allowlist` 留空 = 监控所有群；需要收窄再填群名。
5. 空的 `decrypted_dir` / `temp_image_dir` / `state_dir` / `keys_file` / `image_keys_file`：若程序要求绝对路径，请改成：

```json
"decrypted_dir": "D:\\n8n-wechat-bridge\\wechat_readonly\\decrypted",
"temp_image_dir": "D:\\n8n-wechat-bridge\\wechat_readonly\\temp_images",
"state_dir": "D:\\n8n-wechat-bridge\\wechat_readonly\\state",
"keys_file": "D:\\n8n-wechat-bridge\\wechat_readonly\\state\\all_keys.json",
"image_keys_file": "D:\\n8n-wechat-bridge\\wechat_readonly\\state\\found_image_keys.txt"
```

根目录 `config.json`（文件夹投放用）同样把 `webhook_url` 改成你的 n8n；`watch_dir`/`processed_dir`/`results_xlsx` 可填：

```json
"watch_dir": "D:\\n8n-wechat-bridge\\inbox",
"processed_dir": "D:\\n8n-wechat-bridge\\processed",
"results_xlsx": "D:\\n8n-wechat-bridge\\output\\results.xlsx"
```

### 4. 捕获密钥（每台微信新机器做一次）

1. 微信保持登录。
2. 双击 `wechat_readonly\extract_keys.bat`（写 DB 密钥到 `state\all_keys.json`）。
3. 在微信里打开 2～3 张**大图**，同时运行 `wechat_readonly\start_capture_image_key.bat`（AES 图密钥写入 `found_image_keys.txt`）。

### 5. 导入 n8n 工作流

1. n8n → Import → `n8n\workflow.json`。
2. 按 `n8n\CREDENTIALS.md` 创建 Minimax / DeepSeek / Telegram 三个凭据并绑到节点。
3. 把工作流里的占位符改成真实值：
   - `YOUR_WINDOWS_HOST:8787` → 跑 append_api 的 Windows IP
   - `YOUR_TELEGRAM_CHAT_ID` → 你的 chat id
4. 激活工作流。

### 6. 启动本机服务

```bat
BRIDGE\start_append_api_bg.bat
BRIDGE\wechat_readonly\start_monitor.bat
```

可选：`start_folder_watch.bat`（往 `inbox\` 丢图）。

### 7. 验收

按根目录 `验收清单.md` 逐项打勾（至少：群发普通图、重发曾失败的封装图、表单传一张、看 Telegram 与 `output\results.xlsx`）。

## 迁移到另一台机器

1. 复制本便携目录（或重新解压 zip）。
2. **不要**复制旧机器的 `state\all_keys.json` / `found_image_keys.txt` 当真密钥长期共用（微信账号/机器不同需重捕）。
3. 重新填写路径与 webhook；在新微信会话上重新 `extract_keys` + `capture_image_key`。
4. n8n 若也是新实例：重新导入 `workflow.json` 并重建凭据。

## 日常运维

见 `OPS_运维速查.md`。完整行为约束见 `PROMPT_完整规范.md`。

## 明确不会做的事

- 不向微信自动发消息 / UI 操控发图。
- 不把 Key、完整 base64、聊天解密库打进 Telegram 或公开日志。
