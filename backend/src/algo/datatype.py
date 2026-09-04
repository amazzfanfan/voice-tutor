from typing import Any, Optional, Dict, List, Literal
from pydantic import BaseModel, Field

from datetime import datetime


class DocumentFile(BaseModel):
    """文档文件模型，用于知识库文件和当前打开文件"""
    id: str = Field(description="文件的唯一标识符")


class AttachmentFile(BaseModel):
    """附件文件模型"""
    path: str = Field(description="附件文件的路径")


class Meta(BaseModel):
    source: str
    version: str


class Extra(BaseModel):
    """请求额外参数"""
    selected_model: Literal["EXTERNAL", "INTERNAL"] = Field(
        default="EXTERNAL", description="模型选择，EXTERNAL 表示外部模型，INTERNAL 表示内部模型"
    )
    use_web_search: bool = Field(default=False, description="是否启用联网搜索")
    use_rag: bool = Field(default=False, description="是否启用知识库检索增强（RAG）")
    public_knowledge_base_dirs: Optional[list[str]] = Field(
        default_factory=list, description="公共知识库目录列表"
    )
    knowledge_base_files: Optional[list[DocumentFile]] = Field(
        default_factory=list, description="知识库文件列表"
    )
    knowledge_base_root_ids: Optional[list[str]] = Field(
        default_factory=list, description="知识库目录 ID 列表，用于指定检索的知识库范围"
    )
    attachments: Optional[list[AttachmentFile]] = Field(
        default_factory=list, description="用户上传的附件列表"
    )
    focused_open_file: Optional[DocumentFile] = Field(
        default_factory=list, description="当前打开的聚焦文件"
    )


class ChatTopParam(BaseModel):
    user_id: str
    session_id: str
    run_id: str
    query: str
    extra: Optional[Extra] = None


class Task(BaseModel):
    name: str
    params: ChatTopParam


class MeParam(BaseModel):
    meta: Meta
    task: Task


class AgentParam(BaseModel):
    """Agent 请求参数模型，用于传递给大模型的上下文信息"""
    query: str = Field(description="用户的查询问题")
    use_rag: bool = Field(default=False, description="是否启用知识库检索增强（RAG）")
    use_web_search: bool = Field(default=False, description="是否启用联网搜索")
    knowledge_base_root_ids: Optional[list[str]] = Field(
        default=None, description="知识库目录 ID 列表，用于指定检索的知识库范围"
    )
    public_knowledge_base_dirs: Optional[list[str]] = Field(
        default=None, description="公共知识库目录列表"
    )
    attachments: Optional[list[AttachmentFile]] = Field(
        default=None, description="用户上传的附件列表"
    )
    documents: Optional[list[DocumentFile]] = Field(
        default=None, description="需要阅读的文档列表（包含知识库文件和当前打开文件）"
    )
    user_id: str = Field(description="用户唯一标识符")

class SubagentDataEvent(BaseModel):
    event: str = "SubagentData"
    agent_name: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())