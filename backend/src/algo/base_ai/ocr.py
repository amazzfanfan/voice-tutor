import os
import re
import json
import shutil
import base64
import requests
from algo.app import project_app
from typing import AsyncGenerator, List, Any, Optional
from algo.config import OCR_API_URL, BACKEND_SERVER, IMAGE_URL, TEMP_DIR
from algo.base_ai.postprocess_markdown import html_to_md
import traceback


MID_STATUS_LLM_START = "<问题回答>"
MID_STATUS_LLM_END = "</问题回答>"

def get_image_base64(pic_path: str) -> str:
    """
    从 Minio 下载图片，转为 Base64，然后清理临时文件
    """
    try:
        # 1. 解析路径与构建临时目录
        _, file_id, file_name = pic_path.split('/')
        temp_dir = TEMP_DIR / file_id
        os.makedirs(temp_dir, exist_ok=True)
        image_local_path = temp_dir / file_name

        # 2. 从 Minio 下载到本地
        project_app.state.minio_client.download_file(pic_path, image_local_path)

        # 3. 读取并转为 Base64
        with open(image_local_path, "rb") as f:
            img_data = f.read()
            base64_str = base64.b64encode(img_data).decode("ascii")

        # 4. 彻底清理临时目录
        shutil.rmtree(temp_dir)

        return base64_str

    except Exception as e:
        # 发生异常时也尝试清理（如果目录已创建）
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return f"处理失败: {str(e)}"

def download_image(url: str, save_path: str = ".", timeout: int = 10, headers: Optional[dict] = None) -> bool:
    """
    通过 HTTP GET 下载图片并保存到本地
    :param url: 图片地址
    :param save_dir: 保存目录（不存在会自动创建）
    :param timeout: 单次请求超时秒数
    :param headers: 可选自定义请求头（防反爬）
    :return: 保存后的绝对路径
    :raises: requests.exceptions.HTTPError / IOError
    """
    if headers is None:
        # 默认带个常见 UA，减少 403 概率
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }

    # 流式下载，避免大图一次性读爆内存
    try:
        with requests.get(url, headers=headers, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()                      # 非 2xx 直接抛异常
            # 从响应头或 URL 里抠文件名
            fname = url.split('=')[-1]
            content_disp = resp.headers.get("Content-Disposition")
            if content_disp and "filename=" in content_disp:
                fname = content_disp.split("filename=")[-1].strip('"')
            if not fname:                                # 兜底
                fname = "downloaded.jpg"

            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception:
        traceback.print_exc()
        return False

def get_ocr_result(image_path, output_dir):
    # 对本地图像进行Base64编码
    with open(image_path, "rb") as file:
        image_bytes = file.read()
        image_data = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "file": image_data, # Base64编码的文件内容或者文件URL
        "fileType": 1, # 文件类型，1表示图像文件
    }

    # 调用API
    response = requests.post(OCR_API_URL, json=payload)

    # 处理接口返回数据
    assert response.status_code == 200
    result = response.json()["result"]
    image_paths = []
    for i, res in enumerate(result["layoutParsingResults"]):
        md_dir = output_dir
        (md_dir / "doc.md").write_text(res["markdown"]["text"], encoding="utf-8")
        for img_path, img in res["markdown"]["images"].items():
            img_path = md_dir / img_path
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img_path.write_bytes(base64.b64decode(img))
            image_paths.append(img_path)
        return md_dir/'doc.md', image_paths


def ocr_result(pictures: List[str])-> str:
    """
    对 .png、.jpg、.jpeg、.bmp 格式图片文件，进行OCR图片提取文字

    参数:
        pictures: 图片文件路径列表，支持 .png、.jpg、.jpeg、.bmp 格式
    返回:
        提取文字结果
    """
    results = ""
    local_temp_dir = ""
    if pictures:
        picture_count = len(pictures)
        for idx, pic in enumerate(pictures):
            _, file_id, file_name = pic.split('/')
            # 下载图片
            temp_dir = TEMP_DIR / f"{file_id}"
            local_temp_dir = temp_dir
            os.makedirs(temp_dir, exist_ok=True)
            image_local_path = TEMP_DIR / f"{file_id}" / f"{file_name}"
            project_app.state.minio_client.download_file(pic, image_local_path)
            try:
                markdown_path, image_paths = get_ocr_result(image_local_path, temp_dir)
                markdown_content = markdown_path.read_text(encoding='utf-8')
                # 如果有图片需上传minio
                if image_paths:
                    for img_path in image_paths:
                        upload_path = f"algo-chat-file/{file_id}/images/{img_path.name}"
                        project_app.state.minio_client.upload_file(img_path, upload_path)
                        # 替换markdown中的图片路径
                        markdown_content = re.sub(f'<img src="imgs/{img_path.name}', f'<img src="{IMAGE_URL}?resourceId={file_id}&imageId={img_path.name}', markdown_content)
                markdown_content = html_to_md(markdown_content)
                pat = re.compile(r'(?<!\|)[ \t]*\n[ \t]*(?!\|)(?=.*\S)', re.X)
                markdown_content = pat.sub('', markdown_content)
                if picture_count > 1:
                    results += f"第{idx+1}张图的识别结果：\n\n{markdown_content}"
                else:
                    results += f"图片识别结果：\n\n{markdown_content}"
            except AssertionError:
                    results += "OCR识别图片失败"

            results += '\n\n'
            # print(results)
        
        # 删除临时文件
        shutil.rmtree(local_temp_dir)
        current_content = "%s%s%s" % (MID_STATUS_LLM_START, results, MID_STATUS_LLM_END)
        answer = {"answers": [{"type": "text", "content": current_content}]}
        return answer
    else:
        answer = {"answers": [{"type": "error", "content": "请至少上传1张图片"}]}
        return answer

ocr_result.__name__ = "图片识别"