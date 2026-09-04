import json

from algo import web_tools
from algo.web_tools import MyConfigParser, MyLogger
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
my_config_parser = web_tools.MyConfigParser(include_file_list=["config.ini"])
my_logger = MyLogger(log_name='MyLogger')
ENV = my_config_parser.get('env_config', 'env')

BACKEND_SERVER = my_config_parser.get('paths', 'backend_server')
MD_DOWNLOAD_URL = BACKEND_SERVER + my_config_parser.get('paths', 'md_download_url')
BACKEND_ACCESS_KEY = my_config_parser.get('paths', 'backend_access_key')

temp_dir_relative = my_config_parser.get('paths', 'temp_dir')
TEMP_DIR = PROJECT_ROOT / temp_dir_relative
# OCR功能
IMAGE_URL = my_config_parser.get('paths', 'image_url')
OCR_API_URL = my_config_parser.get('ocr_config', f'ocr_api_url_{ENV}')

# 读取minio配置
MINIO_HOST = my_config_parser.get('minio_config', f'endpoint_{ENV}')
MINIO_ACCESS_KEY = my_config_parser.get('minio_config', f'access_key_{ENV}')
MINIO_SECRET_KEY = my_config_parser.get('minio_config', f'secret_key_{ENV}')
MINIO_SECURE = my_config_parser.getboolean('minio_config', f'secure_{ENV}')
MINIO_BUCKET = my_config_parser.get('minio_config', f'bucket_name_{ENV}')

# 嵌入模型配置
EBD_MODEL_NAME = my_config_parser.get('embeddings_config', f'ebd_model_name_{ENV}')
EBD_MODEL_SERVER = my_config_parser.get('embeddings_config', f'ebd_model_server_{ENV}')
EBD_APIKEY = my_config_parser.get('embeddings_config', f'ebd_apikey_{ENV}')

# 文本生成模型配置
INTERNAL_MODEL_NAME = my_config_parser.get('llm_config', f'internal_model_name_{ENV}')
INTERNAL_OPENAI_API_BASE = my_config_parser.get('llm_config', f'internal_openai_api_base_{ENV}')
INTERNAL_OPENAI_API_KEY = my_config_parser.get('llm_config', f'internal_openai_api_key_{ENV}')

EXTERNAL_MODEL_NAME = my_config_parser.get('llm_config', f'external_model_name_{ENV}')
EXTERNAL_OPENAI_API_BASE = my_config_parser.get('llm_config', f'external_openai_api_base_{ENV}')
EXTERNAL_OPENAI_API_KEY = my_config_parser.get('llm_config', f'external_openai_api_key_{ENV}')

# Markdown文件目录
# FILES_PATH = "./files"
from pathlib import Path

FILES_PATH = str(Path(__file__).resolve().parent.parent / "files_to_es" / "files")

# 检索服务 URL（供 rag-agent 远程调用 retrieval-service）
RETRIEVAL_SERVER = my_config_parser.get('paths', 'retrieval_server', fallback=None)
RETRIEVE_CHUNK_URL = RETRIEVAL_SERVER + my_config_parser.get('paths', 'retrieve_chunk_url', fallback=None)
FILE_CHUNK_URL = RETRIEVAL_SERVER + my_config_parser.get('paths', 'file_chunk_url')
WEB_SEARCH_URL = RETRIEVAL_SERVER + my_config_parser.get('paths', 'web_search_url')