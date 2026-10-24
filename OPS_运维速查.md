# 运维速查（识图桥接）

完整规范见：PROMPT_完整规范.md

## 必开进程（本机 Windows）

1. **微信 PC** 保持登录  
2. **监控**：C:\n8n-wechat-bridge\wechat_readonly\start_monitor.bat  
   - 停止：stop_monitor.bat  
   - 日志：wechat_readonly\logs\monitor_stdout.log  
3. **写表**：C:\n8n-wechat-bridge\start_append_api_bg.bat（端口 8787）  
   - 健康检查：浏览器打开 http://YOUR_N8N_HOST:5678/health  
4. **n8n**：http://YOUR_N8N_HOST:5678 工作流「Excel 解析 → Minimax」保持 Active  

## 出站结果

- Telegram：原图 + 短讯  
- Excel：C:\n8n-wechat-bridge\output\results.xlsx  

## 常见故障

| 现象 | 处理 |
|------|------|
| 任务栏无黑窗 | 监控可能在后台；看 state\monitor.pid 或日志 |
| 识图成功但写表失败 | 运行 start_append_api_bg.bat |
| 双模型格式无效 | 确认监控已更新（含 ffmpeg 转 JPEG），群里**重发**该图 |
| Minimax 429 | 已自动短重试并切 DeepSeek；少刷即可 |
| 无新图进 n8n | 微信是否开着、监控是否在跑、群是否在白名单 |

## 重测步骤

1. 群发一张普通照片  
2. 再发一张曾失败的图  
3. 打开 http://YOUR_N8N_HOST:5678/form/image-recognize 传一张  
4. 看 Telegram 与 
esults.xlsx 新行  

## 后台无窗口启动（2026-10-24）

弹窗根因：每张图 ffmpeg 转码、以及每分钟 extract_db_keys 子进程未带 CREATE_NO_WINDOW。

日常请用：
- `wechat_readonly\start_monitor_bg.bat`（pythonw，无黑窗）
- `start_append_api_bg.bat`（pythonw，无黑窗）
- 停监控：`wechat_readonly\stop_monitor.bat`
- 需要看实时日志时才用带窗口的 `start_monitor.bat`

