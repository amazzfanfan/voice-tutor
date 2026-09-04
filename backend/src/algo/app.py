from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from algo.config import my_logger
from algo.web_tools import register_static
from .minio.minio_client import init_minio_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化资源"""
    my_logger.info("--- 应用启动 ---")

    try:
        # 实例化各个模块，并保存返回的实例
        # # 将实例存储在 app.state 中，方便后续使用

        my_logger.info("🔧 实例化各个模块...")
        app.state.minio_client = init_minio_client()
        app.state.http_client = httpx.AsyncClient(timeout=60.0)


        my_logger.info("✅ 资源初始化完成。")

    except Exception as e:
        my_logger.info(f"❌ 初始化失败，请检查配置或服务连接: {e}")
        raise SystemExit(f"启动失败: {e}")  # 初始化失败时应直接退出

    yield  # 必须有 yield，yield 前是 startup，yield 后是 shutdown

    """应用关闭时清理资源"""
    await app.state.http_client.aclose()

    # Cleanup voice sessions
    try:
        from voice.server import session_manager
        session_manager.shutdown()
    except Exception as e:
        my_logger.warning(f"Voice session cleanup failed: {e}")

    my_logger.info("✅ 资源清理完成。")
    my_logger.info("--- 应用关闭 ---")



project_app = FastAPI(
    title="数据问答Agent",
    description="基于FastAPI的数据问答Agent",
    version="1.0.0",
    lifespan=lifespan,
)
project_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源的跨域请求（开发环境常用）
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)
register_static(project_app)