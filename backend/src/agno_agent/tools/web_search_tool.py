# src/agno_agent/tools/web_search_tool.py

# -*- coding: utf-8 -*-
"""
@File    : web_search_tool.py
@Desc    : 联网搜索工具（async），通过 httpx 调用 retrieval 服务的 web_search 接口
"""
from typing import Dict, List, Any

from algo.app import project_app
from algo.config import WEB_SEARCH_URL, my_logger
from agno_agent.tool import update_tool_result


async def get_web_search_results(query: str) -> List[Dict[str, Any]]:
    """
    联网搜索工具：调用 retrieval 服务的 IQS 搜索接口

    参数:
        query: 搜索查询词
    返回:
        搜索结果数组，每项含 id, title, url, content, is_error, score
    """
    my_logger.info(f"联网搜索输入: {query}")

    try:
        response = await project_app.state.http_client.post(
            WEB_SEARCH_URL,
            json={"query": query},
        )
        response.raise_for_status()
        results = response.json()
    except Exception as e:
        my_logger.error(f"调用 retrieval 联网搜索接口失败: {str(e)}")
        return [{"title": "搜索异常", "url": "", "content": f"请求失败: {str(e)}", "is_error": True, "score": 0}]

    if not results:
        my_logger.warning(f"搜索无结果: {query}")
        results = [{"title": "搜索无结果", "url": "", "content": "未找到相关实时网络信息。", "is_error": True, "score": 0}]

    # 分配全局唯一的 W1/W2... ID 并写入工具上下文
    update_tool_result("web", results)

    my_logger.info(f"联网搜索完成，有效结果: {len(results)}")
    return results


get_web_search_results.__name__ = "联网搜索"