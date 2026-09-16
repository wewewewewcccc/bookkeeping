# AI 记账助手

轻量级私有化部署：上传小票照片 → qwen2.5-vl 视觉模型直接识别图片并提取账单 → 入库 MySQL → 汇总统计。

## 运行

1. 修改 `.env` 中的 MySQL 密码（可选，默认本地使用）
2. 启动：

```bash
docker compose up -d --build
```

3. 首次需拉取模型（CPU 可跑，建议 8GB 内存）：

```bash
docker exec bookkeeping-ollama ollama pull qwen2.5vl:3b
```

4. 打开 http://localhost:6640 ，上传小票图片即可自动记账。

## 组件

| 容器 | 说明 |
|---|---|
| web | FastAPI 后端 + 前端页面（端口 8000） |
| mysql | 数据库 8.4，数据持久化于 docker volume |
| ollama | 本地视觉 LLM 服务（qwen2.5-vl），CPU 推理 |

图片文件保存在 `data/images/`。
