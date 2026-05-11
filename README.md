# Streamlit Finance App

启动：

```bash
streamlit run app.py --server.port 8501 --server.address 127.0.0.1
```

由 Nginx 反向代理到外部访问。

样本回归检查：

```bash
.venv/bin/python tools/regression_check.py
```

输出包含两层：
- `structure`：字段识别结果
- `behavior`：数值列通过率、关键字段是否齐全
- `verdict`：是否通过最小回归门槛

当前内置样本目录：`/opt/shuju`

## 版本与回退

创建备份：

```bash
bash tools/create_backup.sh
```

回退到指定备份：

```bash
bash tools/rollback.sh backup-YYYYMMDD-HHMMSS
```

本次操作前备份：`/root/.openclaw/workspace/backups/streamlit-finance/backup-20260418-111334`
