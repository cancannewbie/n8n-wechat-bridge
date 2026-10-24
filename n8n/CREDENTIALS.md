# n8n 凭据配置说明

导入 `workflow.json` 后，在 n8n → Credentials 中创建以下三项，并在对应 HTTP / Telegram 节点中选用。

仓库目标地址建议：`https://github.com/cancannewbie/n8n-wechat-bridge`

## 1. Minimax（主识图）

- 类型：Header Auth 或 Generic Credential（按工作流节点要求）
- 常见写法：`Authorization: Bearer <MINIMAX_API_KEY>`
- Base URL：`https://api.minimaxi.com`（以账号控制台为准）
- 模型名：工作流默认 `MiniMax-M3`（可在节点中修改）
- 建议：关闭 thinking；温度约 `0.2`

将 API Key **只**保存在 n8n 凭据里，不要写进仓库或 `config.json`。

## 2. DeepSeek（兜底识图）

- Base URL：`https://api.deepseek.com`
- 模型：`deepseek-flash`（若控制台名称变更请同步改节点）
- Header：`Authorization: Bearer <DEEPSEEK_API_KEY>`

仅在 Minimax 短重试仍失败时调用。

## 3. Telegram

- 凭据类型：Telegram API
- Access Token：BotFather 发放的 Bot Token
- 工作流节点中的 **Chat ID**：改为你的目标群/私聊 ID

## 4. 写表地址（非凭据，但是必改）

节点「组装写表 / append」中的 URL 改为：

```text
http://127.0.0.1:8787/append
```

若 n8n 与微信桥不在同一台机器，改为桥接机局域网地址，并放行 8787。

## 5. 检查清单

- [ ] 三个凭据已创建且节点已选中
- [ ] Chat ID 正确
- [ ] append URL 指向正在运行的 `append_api`
- [ ] 工作流已 Active
- [ ] 测试 Form 与微信各一张图
