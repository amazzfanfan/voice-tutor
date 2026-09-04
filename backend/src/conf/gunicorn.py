# gunicron服务器配置，不要删除本文件

# 工作进程
workers = 4
# 监听内网端口
bind = "0.0.0.0:18000"
# 设置超时时间120s。默认为30s
timeout = 3000
# 使用异步 worker 类（适配 FastAPI 的高并发）
worker_class = "uvicorn.workers.UvicornWorker"
