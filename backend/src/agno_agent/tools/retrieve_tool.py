from typing import Optional, Any, List

from agno_agent.tool import update_tool_result
from algo.app import project_app
from algo.config import RETRIEVE_CHUNK_URL, my_logger


async def knowledge_retrieve_auto_tool(
    query: str,
    file_ids: Optional[List[str]] = None,
    knowledge_base_root_ids: Optional[List[str]] = None,
    public_knowledge_base_dirs: Optional[List[str]] = None,
    request_timeout_sec: Optional[float] = None,
) -> list[Any]:
    """
    知识库检索工具（async 通过 retrieval-service 远程调用）。

    参数:
        query: 搜索查询语句
        file_ids: 可选，文件 ID 列表，用于限定具体文件。
        knowledge_base_root_ids: 可选，知识库目录 ID 列表，用于指定检索的知识库范围。
        public_knowledge_base_dirs: 可选，公共知识库目录列表。
        request_timeout_sec: 可选，仅覆盖本次 HTTP 请求超时。
    """
    my_logger.info(
        f"知识库工具参数：query={query}, file_ids={file_ids}, "
        f"knowledge_base_root_ids={knowledge_base_root_ids}, "
        f"public_knowledge_base_dirs={public_knowledge_base_dirs}"
    )

    scoped_file_ids = list(file_ids) if file_ids else []
    root_ids = list(knowledge_base_root_ids) if knowledge_base_root_ids else []
    public_dirs = list(public_knowledge_base_dirs) if public_knowledge_base_dirs else []

    url = RETRIEVE_CHUNK_URL
    payload = {
        "query": query,
        "file_ids": scoped_file_ids,
        "base_root_ids": root_ids,
        "public_dbs": public_dirs,
    }
    my_logger.info(f"异步调用检索服务: {url}")
    client = project_app.state.http_client
    request_kwargs = {}
    if request_timeout_sec is not None:
        request_kwargs["timeout"] = request_timeout_sec
    response = await client.post(url, json=payload, **request_kwargs)
    response.raise_for_status()
    final_results = response.json()
    my_logger.info(f"检索服务返回 {len(final_results)} 条结果")


    for item in final_results:
        # 1. 提取值：优先取 'content_text'，没有则取 'text'，再没有则为 None
        content_val = item.get('content_text') if item.get('content_text') is not None else item.get('text')

        # 2. 设置新键 'content'
        item['content'] = content_val

        # 3. 设置新键 'title'，值为 'file_name' 的内容
        item['filename'] = item.get('file_name')

        # 4. 安全地删除旧键
        for key in ['content_text', 'text']:
            if key in item:
                del item[key]

    update_tool_result("rag", final_results)

    return final_results


knowledge_retrieve_auto_tool.__name__ = "知识库检索"
