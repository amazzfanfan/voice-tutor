import json
import mimetypes
from typing import List, Dict
from agno_agent.document.document_processor import DocumentProcessingAgent
from algo.config import my_logger
from algo.base_ai.ocr import ocr_result


async def attachment_processing_func(task_type: str = "summary", task_params: Dict[str, str] = None, paths: List[str] = []) -> str:
    """
    对attachments里的文件进行摘要、关键信息提取、基于内容的问答等处理。返回结构化的 Markdown 格式结果（包含处理类型、核心内容）

    参数:
        task_type: 处理类型 (summary/key_points/qa/validation/custom)
        task_params: 任务参数，如 {"question": "问题"} 或 {"instruction": "指令"}
        paths: 文件附件列表，如 ["aaa/bbb/ccc.pdf"]
    返回:
        处理结果 JSON 字符串
    """
    doc_processor = DocumentProcessingAgent()
    results = []

    DOCUMENT_MIME_TYPES = {
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/plain',
        'text/markdown',
    }

    for path in (paths or []):
        mime_type, _ = mimetypes.guess_type(path)

        # 核心逻辑：判断是否属于文档类型
        is_document = (
                mime_type in DOCUMENT_MIME_TYPES or
                (mime_type and (mime_type.startswith('text/') or 'application/vnd.' in mime_type))
        )

        if is_document:
            my_logger.info(f"工具[附件处理]正在解析文档: {path} ({mime_type})")
            try:
                doc_res = await doc_processor.process_document(
                    paths=[path],
                    task_type=task_type,
                    task_params=task_params or {}
                )
                results.append(doc_res)
            except Exception as e:
                my_logger.error(f"文档处理异常 {path}: {str(e)}")
                results.append({"file_path": path, "status": "error", "message": str(e)})
        else:
            # 如果是图片或其他非文档类型，直接跳过
            my_logger.info(f"工具[附件处理]跳过非文档文件: {path} (MIME: {mime_type})")
            continue

    return json.dumps(results, ensure_ascii=False)

attachment_processing_func.__name__ = "附件处理"
