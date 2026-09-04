import asyncio
import traceback

import numpy as np

from agno_agent.document.llm_utils import call_qwen_max, get_embeddings
from agno_agent.document.skills import SummarySkill, KeyPointsSkill, QASkill, DocumentValidationSkill, CustomSkill
from algo.app import project_app
from algo.config import FILE_CHUNK_URL, my_logger


class DocumentProcessingAgent:

    MAX_CONCURRENT = 10  # 最大并发数

    """
    子 Agent：负责具体的文档处理任务
    """
    def __init__(self):
        """
        初始化 DocumentProcessingAgent
        """
        # 初始化技能
        self.skills = {
            "summary": SummarySkill(),
            "key_points": KeyPointsSkill(),
            "qa": QASkill(),
            "validation": DocumentValidationSkill(),
            "custom": CustomSkill()
        }

    async def process_document(self, paths, task_type="summary", task_params=None):
        """
        入口函数：保持原有签名不变，内部调用 fetch 和 process 逻辑
        """
        try:
            # 1. 批量获取文档分块 (原有逻辑的第一部分)
            client = project_app.state.http_client
            response = await client.post(FILE_CHUNK_URL, json={"file_paths": paths})
            response.raise_for_status()
            processing_results = response.json()

            if not processing_results:
                return {"status": "error", "message": "No documents processed successfully"}

            # 2. 直接调用新增的第二个子函数
            return await self.process_chunks_logic(processing_results, task_type, task_params)

        except Exception as e:
            my_logger.info(f"Error processing document: {paths}, error:{traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    async def process_chunks_logic(self, processing_results, task_type="summary", task_params=None):
        """
        核心处理函数：直接接收分块结果并进行 AI 处理。
        """
        try:
            # 根据任务类型分发逻辑
            if task_type == "summary":
                return await self.process_summary(processing_results)
            elif task_type == "key_points":
                return await self.process_key_points(processing_results)
            elif task_type == "qa":
                return await self.process_qa(processing_results, task_params)
            elif task_type == "validation":
                return await self.process_validation(processing_results, task_params)
            elif task_type == "custom":
                return await self.process_custom(processing_results, task_params)
            else:
                return {"status": "error", "message": f"Unsupported task type: {task_type}"}
        except Exception as e:
            my_logger.info(f"Error in chunks logic: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    async def process_summary(self, processing_results):
        """
        极速生成摘要：仅针对核心分块进行总结
        """
        try:
            # 提取所有块
            all_chunks = []
            for result in processing_results:
                if result.get("success"):
                    # 确保提取的是块对象
                    all_chunks.extend(result.get("chunks", []))

            total_chunks = len(all_chunks)
            my_logger.info(f"开始生成摘要，原始分块数: {total_chunks}")

            # 只有当分块较多时才启动筛选，否则直接全量总结
            if total_chunks > 20:
                my_logger.info("检测到超长文档，启动实时语义筛选...")
                # 使用实时向量计算函数
                core_chunks = self._get_centroid_core_chunks(all_chunks, top_n=15)
            else:
                core_chunks = all_chunks

            my_logger.info(f"筛选完成，实际参与总结的精华块数: {len(core_chunks)}")

            # 并行处理筛选后的核心块
            tasks = []
            summary_skill = self.skills["summary"]
            for chunk in core_chunks:
                # 这里的 chunk 已经是筛选出的核心 text 块
                tasks.append(summary_skill.execute(chunk))

            batch_results = await asyncio.gather(*tasks)

            # 合并并进行最后一次精简
            summaries = [r.get("summary", "") for r in batch_results if r and r.get("summary")]
            combined_text = "\n".join(summaries)

            my_logger.info("核心摘要生成完毕。")
            return {
                "status": "success",
                "message": "Fast summary generated using real-time centroid filtering",
                "text": combined_text,
                "summary": combined_text
            }
        except Exception as e:
            my_logger.error(f"Error in fast summary: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    def _get_centroid_core_chunks(self, all_chunks, top_n=15):
        """
        通过实时计算向量中心点，提取信息稠密度最高的核心块
        """
        try:
            if not all_chunks:
                return []

            # 1. 提取文本内容
            texts = [c.get("text", "") for c in all_chunks if c.get("text")]
            if not texts:
                return all_chunks[:top_n]

            # 2. 实时计算向量 (Real-time Embedding)
            embeddings = get_embeddings(texts)

            # 3. 计算全文语义中心 (Centroid)
            all_embeddings_matrix = np.array(embeddings)
            centroid = np.mean(all_embeddings_matrix, axis=0)

            # 4. 计算每个块到中心的余弦相似度
            norm_centroid = np.linalg.norm(centroid)
            norm_embeddings = np.linalg.norm(all_embeddings_matrix, axis=1)

            similarities = np.dot(all_embeddings_matrix, centroid) / (norm_embeddings * norm_centroid)

            # 5. 组装评分并排序
            scores = []
            for i, sim in enumerate(similarities):
                scores.append((sim, i))

            scores.sort(key=lambda x: x[0], reverse=True)
            core_indices = [idx for _, idx in scores[:top_n]]

            # 6. 物理位置补全：强制包含第一块（背景）和最后一块（结论）
            final_indices = sorted(list(set([0, len(all_chunks) - 1] + core_indices)))

            my_logger.info(f"语义筛选完成，选中索引: {final_indices}")
            return [all_chunks[i] for i in final_indices]

        except Exception as e:
            my_logger.error(f"实时提取核心块失败，退回到前N块模式: {traceback.format_exc()}")
            return all_chunks[:top_n]

    async def process_key_points(self, processing_results):
        """
        提取关键信息

        Args:
            processing_results: 处理结果列表

        Returns:
            dict: 关键信息结果
        """
        try:
            # 收集所有需要处理的块，保持原始顺序
            all_chunks = []
            for result in processing_results:
                if result.get("success"):
                    chunks = result.get("chunks", [])
                    all_chunks.extend(chunks)

            total_chunks = len(all_chunks)
            my_logger.info(f"开始提取关键点，总计分块数: {total_chunks}")

            # 并行处理块，注意速率限制，同时保持顺序
            max_concurrent = self.MAX_CONCURRENT  # 最大并发数
            all_key_points = []

            # 分批处理
            for i in range(0, len(all_chunks), max_concurrent):
                batch_chunks = all_chunks[i:i + max_concurrent]

                progress = (i / total_chunks) * 100
                my_logger.info(f"进度: {progress:.2f}% | 处理分块批次 {i}...")

                tasks = []
                key_points_skill = self.skills["key_points"]

                # 创建任务
                for chunk in batch_chunks:
                    task = key_points_skill.execute(chunk)
                    tasks.append(task)

                # 执行批次
                batch_results = await asyncio.gather(*tasks)

                # 按批次顺序添加关键点，保持文档原始顺序
                for result in batch_results:
                    chunk_key_points = result.get("key_points", [])
                    all_key_points.extend(chunk_key_points)

                # 添加小延迟，避免速率限制
                if i + max_concurrent < len(all_chunks):
                    await asyncio.sleep(0.5)

            my_logger.info(f"关键点提取完成，原始数量: {len(all_key_points)}，开始去重...")

            # 去重，保持首次出现的顺序
            unique_key_points = []
            seen = set()
            for point in all_key_points:
                if point not in seen:
                    seen.add(point)
                    unique_key_points.append(point)

            # 限制关键信息数量
            max_key_points = 10
            final_key_points = unique_key_points[:max_key_points]

            # 构建返回结果
            key_points_text = "\n".join([f"- {point}" for point in final_key_points])

            my_logger.info("关键点处理最终完成。")

            return {
                "status": "success",
                "message": "Key points extracted successfully",
                "text": key_points_text,
                "key_points": final_key_points
            }
        except Exception as e:
            my_logger.info(f"Error extracting key points: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}


    async def process_qa(self, processing_results, task_params):
        """
        处理文档问答

        Args:
            processing_results: 处理结果列表
            task_params: 任务参数，包含问题

        Returns:
            dict: 问答结果
        """
        try:
            question = task_params.get("question", "") if task_params else ""
            if not question:
                return {"status": "error", "message": "Question is required for QA task"}

            # 提取问题关键词
            question_keywords = await self._extract_keywords_with_llm(question)

            my_logger.info(f"开始 QA 任务，问题: {question}, 关键词：{question_keywords}")

            # 向量化问题
            question_embedding = get_embeddings([question])[0]

            # 计算每个块与问题的相关性并排序
            relevant_chunks = []
            for result in processing_results:
                if result.get("success"):
                    chunks = result.get("chunks", [])
                    if not chunks: continue

                    chunk_texts = [c.get("text", "") for c in chunks]
                    chunk_embeddings = get_embeddings(chunk_texts)

                    norm_q = np.linalg.norm(question_embedding)

                    for i, chunk_text in enumerate(chunk_texts):
                        chunk_emb = chunk_embeddings[i]

                        # 计算向量相似度
                        vec_sim = np.dot(question_embedding, chunk_emb) / (
                                norm_q * np.linalg.norm(chunk_emb))

                        # 计算关键词匹配度
                        kw_matches = sum(1 for kw in question_keywords if kw in chunk_text)
                        kw_score = kw_matches / len(question_keywords) if question_keywords else 0

                        # 可根据效果调整权重
                        final_score = 0.5 * vec_sim + 0.5 * kw_score

                        if final_score > 0.2:
                            relevant_chunks.append((final_score, chunk_text))

            my_logger.info(f"检索完成：筛选出 {len(relevant_chunks)} 个相关块")

            # 按相关性排序并选择前几个最相关的块
            relevant_chunks.sort(reverse=True, key=lambda x: x[0])
            top_chunks = relevant_chunks[:10]
            my_logger.info(f"正在构建上下文，选取了前 {len(top_chunks)} 个最相关的分块")

            # 如果没有相关块，使用所有块的前几个
            if not top_chunks:
                all_chunks = []
                for result in processing_results:
                    if result.get("success"):
                        chunks = result.get("chunks", [])
                        for chunk in chunks:
                            all_chunks.append(chunk.get("text", ""))
                top_chunks = [(0, chunk) for chunk in all_chunks[:3]]

            # 合并相关块的文本
            combined_text = "\n".join([chunk_text for _, chunk_text in top_chunks])

            # 限制文本长度
            max_text_length = 150000
            if len(combined_text) > max_text_length:
                combined_text = combined_text[:max_text_length]

            # 使用问答技能
            my_logger.info(f"正在调用 QA 技能执行模型推理，发送文本长度: {len(combined_text)}")
            qa_skill = self.skills["qa"]
            qa_result = await qa_skill.execute({"text": combined_text}, question)
            my_logger.info("QA 任务处理完成")

            return {
                "status": "success",
                "message": "QA completed successfully",
                "text": qa_result.get("answer", ""),
                "answer": qa_result.get("answer", "")
            }
        except Exception as e:
            my_logger.info(f"Error processing QA: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    async def _extract_keywords_with_llm(self, question):
        prompt = f"""
        你是一个搜索专家。请从以下用户问题中提取 3-5 个用于全文检索的关键词或短语。
        要求：
        1. 包含核心实体名词和动作动词。
        2. 提供 1-2 个近义词或相关术语。
        3. 以逗号分隔，不要输出多余解释。

        问题：{question}
        """
        keywords_str = await call_qwen_max(prompt, temperature=0.1)
        return [k.strip() for k in keywords_str.replace("，", ",").split(",") if k.strip()]

    async def process_validation(self, processing_results, task_params):
        """
        检查文档完整性

        Args:
            processing_results: 处理结果列表
            task_params: 任务参数，包含必填内容项

        Returns:
            dict: 完整性检查结果
        """
        try:
            required_items = task_params.get("required_items", "") if task_params else ""
            if not required_items:
                return {"status": "error", "message": "Required items are required for validation task"}

            my_logger.info(f"开始文档验证任务，必填项: [{required_items}]")

            # 解析必填内容项
            required_items_list = [item.strip() for item in required_items.split(",")]

            # 收集所有块的文本
            all_chunks_text = []
            chunk_count = 0
            for result in processing_results:
                if result.get("success"):
                    chunks = result.get("chunks", [])
                    chunk_count += len(chunks)
                    for chunk in chunks:
                        all_chunks_text.append(chunk.get("text", ""))

            my_logger.info(f"已收集 {chunk_count} 个分块，正在合并文本...")

            # 合并文本并限制长度
            combined_text = "\n".join(all_chunks_text)
            max_text_length = 10000
            original_len = len(combined_text)
            if original_len > max_text_length:
                combined_text = combined_text[:max_text_length]
                my_logger.info(f"文本长度 ({original_len}) 超过限制，已截断至 {max_text_length} 字符")
            else:
                my_logger.info(f"合并完成，最终待校验文本长度: {original_len}")

            # 使用验证技能
            my_logger.info("正在调用 Validation 技能进行模型比对...")
            validation_skill = self.skills["validation"]
            validation_result = await validation_skill.execute({"text": combined_text}, required_items_list)

            my_logger.info(f"验证处理完成。找到项: {len(validation_result.get('found_items', []))}, 缺失项: {len(validation_result.get('missing_items', []))}")

            return {
                "status": "success",
                "message": "Validation completed successfully",
                "text": validation_result.get("validation_result", ""),
                "validation_result": validation_result.get("validation_result", ""),
                "found_items": validation_result.get("found_items", []),
                "missing_items": validation_result.get("missing_items", [])
            }
        except Exception as e:
            my_logger.info(f"Error processing validation: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    async def process_custom(self, processing_results, task_params):
        """
        执行自定义指令

        Args:
            processing_results: 处理结果列表
            task_params: 任务参数，包含自定义指令

        Returns:
            dict: 自定义指令执行结果
        """
        try:
            instruction = task_params.get("instruction", "") if task_params else ""
            if not instruction:
                return {"status": "error", "message": "Instruction is required for custom task"}

            my_logger.info(f"开始自定义任务，指令内容: {instruction[:50]}...")

            # 指令转陈述句
            search_query = await self._transform_instruction_to_query(instruction)
            my_logger.info(f"检索使用的陈述句: {search_query}")

            # 向量化检索词
            query_embedding = get_embeddings([search_query])[0]

            # 计算每个块与指令的相关性并排序
            relevant_chunks = []
            for result in processing_results:
                if result.get("success"):
                    chunks = result.get("chunks", [])
                    if not chunks: continue

                    # 提取文本列表
                    chunk_texts = [c.get("text", "") for c in chunks]
                    # 批量计算分块向量
                    chunk_embeddings = get_embeddings(chunk_texts)

                    # 计算余弦相似度
                    norm_query = np.linalg.norm(query_embedding)
                    for i, c_emb in enumerate(chunk_embeddings):
                        norm_c = np.linalg.norm(c_emb)
                        similarity = np.dot(query_embedding, c_emb) / (norm_query * norm_c)

                        if similarity > 0.2:
                            relevant_chunks.append((similarity, chunk_texts[i]))

            # 按相关性排序并选择前几个最相关的块
            relevant_chunks.sort(key=lambda x: x[0], reverse=True)
            top_chunks = [text for _, text in relevant_chunks[:10]]

            if not top_chunks:
                my_logger.warning("语义匹配未命中，使用默认前3块")
                all_texts = [c.get("text", "") for r in processing_results if r.get("success") for c in
                             r.get("chunks", [])]
                top_chunks = all_texts[:3]

            # 合并相关块的文本
            combined_context = "\n".join(top_chunks)

            # 使用自定义技能
            my_logger.info("正在调用 Custom 技能执行 AI 推理...")
            custom_skill = self.skills["custom"]
            custom_result = await custom_skill.execute({"text": combined_context}, instruction)
            my_logger.info("自定义指令执行成功")

            return {
                "status": "success",
                "message": "Custom instruction executed successfully",
                "text": custom_result.get("result", ""),
                "result": custom_result.get("result", "")
            }
        except Exception as e:
            my_logger.info(f"Error processing custom instruction: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    async def _transform_instruction_to_query(self, instruction):
        """
        将用户的操作指令转换为更适合检索的陈述性短语
        """
        prompt = f"""
        你是一个文档检索专家。请将用户的【操作指令】转化为 3 个可能出现在文档中的【陈述性搜索短语】。
        要求：
        1. 去掉"总结"、"提取"、"分析"等动词。
        2. 使用文档中可能出现的专业术语。
        3. 结果以逗号分隔，不要多余解释。

        用户指令："{instruction}"

        搜索短语示例：
        - 指令："分析高炉布料的安全性" -> 搜索短语："高炉布料工艺参数, 布料过程安全控制, 炉顶设备运行状态"
        """
        try:
            transformed_query = await call_qwen_max(prompt, temperature=0.3)
            if "Error" in transformed_query:
                return instruction
            return transformed_query
        except:
            return instruction

    async def process_permission_query(self, file_infos, task_params):
        """
        查询指定权限类型的文件

        Args:
            file_infos: 文件信息列表
            task_params: 任务参数，包含权限类型

        Returns:
            dict: 权限查询结果
        """
        try:
            permission_type = task_params.get("permission_type", "read") if task_params else "read"

            # 筛选符合权限要求的文件
            filtered_files = []
            for file_info in file_infos:
                permissions = file_info.get("permissions", {})
                has_edit = permissions.get("edit", False)
                has_read = permissions.get("read", False)
                has_download = permissions.get("download", False)

                # 权限逻辑：三种权限互斥
                if permission_type == "read":
                    if has_read and not has_edit:
                        filtered_files.append(file_info)
                elif permission_type == "download":
                    if has_download and not has_edit:
                        filtered_files.append(file_info)
                elif permission_type == "edit":
                    if has_edit:
                        filtered_files.append(file_info)

            # 生成文件链接列表
            file_links_text = "\n".join([f"- {file.get('filename')}: {file.get('file_link', '')}" for file in filtered_files])

            return {
                "status": "success",
                "message": f"Found {len(filtered_files)} files with {permission_type} permission",
                "text": f"找到 {len(filtered_files)} 个拥有{self._get_permission_name(permission_type)}的文件：\n{file_links_text}",
                "files": filtered_files,
                "count": len(filtered_files),
                "permission_type": permission_type
            }
        except Exception as e:
            my_logger.info(f"Error processing permission query: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    def _get_permission_name(self, permission_type):
        """
        获取权限类型的中文名称

        Args:
            permission_type: 权限类型

        Returns:
            str: 中文权限名称
        """
        permission_names = {
            "read": "读权限",
            "download": "下载权限",
            "edit": "编辑权限"
        }
        return permission_names.get(permission_type, permission_type)
