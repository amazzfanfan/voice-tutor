import uvicorn
import sys

# 添加多个可能的路径
sys.path.append("/home/app/src")
sys.path.append("src")
# Pycharm用户右键src目录，将目录标记为源代码根目录和资源根
from algo import web_api

app = web_api.project_app

# nohup python -u run_web_api.py > logs/app.log 2>&1 &
if __name__ == "__main__":
    # 本地开发直接使用 Uvicorn；生产部署可通过 entrypoint.sh 启动 Gunicorn。
    uvicorn.run("run_web_api:app", host="0.0.0.0", port=18000, reload=False)
