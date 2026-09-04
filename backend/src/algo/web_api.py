# src/algo/web_api.py

# -*- coding: utf-8 -*-
"""
@File    : web_api.py
@Desc    : 基于FastAPI框架的任务接口，使用Gunicorn+FastAPI作为服务框架
# 本文件无法直接运行，启动文件是项目根路径的 run_web_api.py
"""

import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from sse_starlette import EventSourceResponse
from agno.run.workflow import WorkflowErrorEvent

from agno_agent.agent import QAAgent
from algo.app import project_app
from algo.config import my_logger
from algo.datatype import MeParam, AgentParam

main_router = APIRouter()

async def sse_error_stream(error_message: str):
    yield WorkflowErrorEvent(error=error_message).to_json(separators=None, indent=None)

@project_app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    my_logger.error(f"validation exception: {exc}")
    return EventSourceResponse(sse_error_stream("参数校验失败"))

@project_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    my_logger.error(f"Unhandled exception: {exc}")
    return EventSourceResponse(sse_error_stream(str(exc)))


@project_app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    my_logger.error(f"HTTP exception: {exc.status_code} - {exc.detail}")
    return EventSourceResponse(sse_error_stream(f"HTTP {exc.status_code}: {exc.detail}"))

@main_router.post('/app-rag-agent-me/rag-chat')
def rag_query_chat(me_param: MeParam, request: Request):
    params = me_param.task.params
    extra = params.extra
    my_logger.info(f"收到对话请求，参数：{params.model_dump_json(indent=None)}")
    
    agent = QAAgent(extra.selected_model)
    attachments = list(extra.attachments or [])

    # 只有当知识库 ID 或 公共知识库目录不为空时，才启用 RAG
    extra.use_rag = bool(extra.knowledge_base_root_ids) or bool(extra.public_knowledge_base_dirs)

    # 新建文档处理列表
    documents = []
    if extra.focused_open_file:
        documents.append(extra.focused_open_file)
    if isinstance(extra.knowledge_base_files, list):
        documents.extend(extra.knowledge_base_files)

    # 构造agent请求参数
    agent_param = AgentParam(
        query=params.query,
        use_rag=extra.use_rag,
        use_web_search=extra.use_web_search,
        knowledge_base_root_ids=extra.knowledge_base_root_ids,
        public_knowledge_base_dirs=extra.public_knowledge_base_dirs,
        attachments=attachments,
        documents=documents,
        user_id=params.user_id,
    )

    my_logger.info(f"agent输入参数： {agent_param.model_dump_json()}")
    return EventSourceResponse(agent.stream_run(agent_param, request, session_id=params.session_id, run_id=params.run_id))


# Mount voice tutor router
from voice.server import voice_router
project_app.include_router(voice_router)

# 挂载路由到 FastAPI 应用
project_app.include_router(main_router)