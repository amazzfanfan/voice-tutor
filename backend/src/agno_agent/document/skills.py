from agno_agent.document.llm_utils import call_qwen_max


class Skill:
    """技能基类"""
    def __init__(self):
        self.skill_id = ""
        self.description = ""
        self.input_schema = {}
        self.output_schema = {}

    async def execute(self, *args, **kwargs):
        raise NotImplementedError("Subclass must implement execute method")


class SummarySkill(Skill):
    def __init__(self):
        self.skill_id = "summary_skill"
        self.description = "Summarize document chunks"
        self.input_schema = {"type": "object", "properties": {"chunk": {"type": "object"}}}
        self.output_schema = {"type": "object", "properties": {"summary": {"type": "string"}, "page": {"type": "integer"}}}

    async def execute(self, chunk):
        text = chunk.get("text", "")
        page = chunk.get("page", 0)
        prompt = f"请对以下文本进行要点提取，要点包括标红或者其他颜色的字、加粗的字体以及高亮标注的字体、画下划线的字、重要时间节点等，不要有遗漏、单句不全，最好是文件原句但如果太长就省略一下，提取出核心信息。\n\n注意：\n1. 只返回要点内容，不要添加任何前缀，如'响应：'、'回答：'等\n2. 为要点添加编号（但要合乎逻辑地添加）\n3. 每个要点占一行\n4. 对于结构化内容（如投标函、表格等），作为一个整体处理，不要拆分成多个要点（但也要判断是否有重要内容，否则不用输出）\n\n文本：{text}"
        summary = await call_qwen_max(prompt)
        return {"summary": summary, "page": page}


class KeyPointsSkill(Skill):
    def __init__(self):
        self.skill_id = "key_points_skill"
        self.description = "Extract key points from document chunks"
        self.input_schema = {"type": "object", "properties": {"chunk": {"type": "object"}}}
        self.output_schema = {"type": "object", "properties": {"key_points": {"type": "array"}, "page": {"type": "integer"}}}

    async def execute(self, chunk):
        text = chunk.get("text", "")
        page = chunk.get("page", 0)
        prompt = f"请从以下文本中提取3-5个关键信息点，每个点用简洁的语言表达：\n\n{text}"
        key_points_text = await call_qwen_max(prompt)
        key_points = [p.strip() for p in key_points_text.split("\n") if p.strip()]
        return {"key_points": key_points, "page": page}


class QASkill(Skill):
    def __init__(self):
        self.skill_id = "qa_skill"
        self.description = "Answer questions about document chunks"
        self.input_schema = {"type": "object", "properties": {"chunk": {"type": "object"}, "question": {"type": "string"}}}
        self.output_schema = {"type": "object", "properties": {"answer": {"type": "string"}, "page": {"type": "integer"}}}

    async def execute(self, chunk, question=None):
        text = chunk.get("text", "")
        page = chunk.get("page", 0)
        print(f"QASkill.execute: question = {question}")
        question = question or "这段文本的主要内容是什么？"
        print(f"QASkill.execute: 使用的问题 = {question}")
        prompt = f"基于以下文本，回答问题：{question}\n\n文本：{text}"
        answer = await call_qwen_max(prompt)
        return {"answer": answer, "page": page}


class CustomSkill(Skill):
    def __init__(self):
        self.skill_id = "custom_skill"
        self.description = "Execute custom instructions on document chunks"
        self.input_schema = {"type": "object", "properties": {"chunk": {"type": "object"}, "instruction": {"type": "string"}}}
        self.output_schema = {"type": "object", "properties": {"result": {"type": "string"}, "page": {"type": "integer"}}}

    async def execute(self, chunk, instruction=None):
        text = chunk.get("text", "")
        page = chunk.get("page", 0)
        instruction = instruction or "分析这段文本并提供见解"
        prompt = f"根据以下指令处理文本：{instruction}\n\n文本：{text}"
        result = await call_qwen_max(prompt)
        return {"result": result, "page": page}


class DocumentValidationSkill(Skill):
    def __init__(self):
        self.skill_id = "validation_skill"
        self.description = "Validate document structured content completeness"
        self.input_schema = {"type": "object", "properties": {"chunk": {"type": "object"}, "required_items": {"type": "array"}}}
        self.output_schema = {"type": "object", "properties": {"missing_items": {"type": "array"}, "found_items": {"type": "array"}, "validation_result": {"type": "string"}, "page": {"type": "integer"}}}

    async def execute(self, chunk, required_items=None):
        text = chunk.get("text", "")
        page = chunk.get("page", 0)
        required_items = required_items or []

        if not required_items:
            return {"validation_result": "未指定必填内容项", "missing_items": [], "found_items": [], "page": page}

        # 使用LLM进行文档结构化解析和校验
        prompt = f"请分析以下文档内容，检查是否包含以下必填内容项：{', '.join(required_items)}\n\n文档内容：{text}\n\n请输出：\n1. 找到的必填内容项（只列出名称，每个一行）\n2. 缺失的必填内容项（只列出名称，每个一行）\n3. 对每个找到的必填项的简要定位（如章节、位置等）"

        result = await call_qwen_max(prompt)

        # 解析LLM输出
        missing_items = []
        found_items = []
        location_info = []

        lines = result.split('\n')
        in_missing_section = False
        in_found_section = False
        in_location_section = False

        empty_indicators = ['无', '- 无', '(无)', '没有', 'none', 'None', 'NONE']

        for line in lines:
            line = line.strip()
            if '缺失的必填内容项' in line:
                in_missing_section = True
                in_found_section = False
                in_location_section = False
            elif '找到的必填内容项' in line:
                in_found_section = True
                in_missing_section = False
                in_location_section = False
            elif '对每个找到的必填项的简要定位' in line or '对每个必填项的简要定位' in line:
                in_location_section = True
                in_missing_section = False
                in_found_section = False
            elif line and in_missing_section:
                is_empty_indicator = any(indicator in line for indicator in empty_indicators)
                if is_empty_indicator:
                    continue

                found_item = False
                for item in required_items:
                    if item in line:
                        missing_items.append(item)
                        found_item = True
                        break
                if not found_item:
                    missing_items.append(line)
            elif line and in_found_section:
                found_item = False
                for item in required_items:
                    if item in line:
                        found_items.append(item)
                        found_item = True
                        break
            elif line and in_location_section:
                location_info.append(line)

        validation_result = ""
        if location_info:
            validation_result = "\n".join(location_info)

        return {
            "validation_result": validation_result,
            "missing_items": missing_items,
            "found_items": found_items,
            "page": page
        }
