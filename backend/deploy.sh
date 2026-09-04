#!/bin/bash
# ================================================
# 一键部署脚本 - 测试环境用的，使用脚本前 chmod +x deploy.sh
# ================================================

# 1. 定义变量（方便后续修改）
ENV_NAME="app-rag-agent-me"
PORT=18000
LOG_FILE="logs/app.log"

echo "🚀 开始一键部署 ..."

# 2. 激活 Conda 环境
source $(conda info --base)/etc/profile.d/conda.sh
conda activate $ENV_NAME
echo "✅ 已切换至环境: $ENV_NAME"


# 3. 查找并清理旧进程
PID=$(lsof -t -i:$PORT)
if [ -z "$PID" ]; then
    echo "ℹ️ 端口 $PORT 未被占用，无需清理。"
else
    echo "⚠️ 发现端口 $PORT 被进程 $PID 占用，正在停止..."
    kill -9 $PID
    sleep 2    # 多等1秒，确保端口完全释放
fi

echo "📡 正在使用 启动服务..."
# 服务器测试运行指令
nohup python -u run_web_api.py > $LOG_FILE 2>&1 &

# 5. 检查启动结果
if [ $? -eq 0 ]; then
    echo "服务启动成功！"
    echo "   - 端口: ${PORT}"
    echo "日志文件: $LOG_FILE"
    echo "查看实时日志请执行: tail -f $LOG_FILE"
else
    echo "部署命令执行失败，请检查错误信息。"
fi
