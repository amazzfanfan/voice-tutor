# agno_agent/tool.py
import threading
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from algo.datatype import AgentParam

# 运行时上下文（线程安全）
_runtime_context: Dict[str, Any] = {}
_context_lock = threading.RLock()


def set_tool_runtime_context(param: "AgentParam") -> None:
    """设置本次请求的工具运行时上下文"""
    with _context_lock:
        global _runtime_context
        _runtime_context.clear()
        _runtime_context.update({
            "query": param.query,
            "use_rag": param.use_rag,
            "use_web_search": param.use_web_search,
            "knowledge_base_root_ids": param.knowledge_base_root_ids or [],
            "public_knowledge_base_dirs": param.public_knowledge_base_dirs or [],
            "attachments": param.attachments or [],
            "documents": param.documents or [],
            "user_id": param.user_id,
            "rag_results": [],      # 知识库检索原始结果
            "web_results": [],      # 联网搜索原始结果
        })


def get_tool_runtime_context() -> Dict[str, Any]:
    """获取当前工具运行时上下文"""
    with _context_lock:
        # 返回副本，避免外部直接修改
        return dict(_runtime_context)


def clear_tool_runtime_context() -> None:
    """清理上下文"""
    with _context_lock:
        global _runtime_context
        _runtime_context.clear()


def update_tool_result(result_type: str, data: Any) -> None:
    """
    工具执行后更新结果
    """
    with _context_lock:
        if not isinstance(data, list):
            return

        if result_type == "rag":
            # 1. 获取当前已有的 RAG 结果列表
            current_rag_results = _runtime_context.setdefault("rag_results", [])

            # 2. 计算当前偏移量（已有多少条数据）
            start_index = len(current_rag_results)

            # 3. 重新为 RAG 数据分配全局唯一的 ID (R1, R2...)
            for i, item in enumerate(data):
                item['id'] = f"R{start_index + i + 1}"

            # 4. 追加到全局上下文
            current_rag_results.extend(data)

        elif result_type == "web":
            # 1. 获取当前已有的搜索结果列表
            current_web_results = _runtime_context.setdefault("web_results", [])

            # 2. 计算当前偏移量
            start_index = len(current_web_results)

            # 3. 重新为 Web 数据分配全局唯一的 ID (W1, W2...)
            for i, item in enumerate(data):
                item['id'] = f"W{start_index + i + 1}"

            # 4. 追加到全局上下文
            current_web_results.extend(data)