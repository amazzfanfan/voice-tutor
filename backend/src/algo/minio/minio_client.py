# src/algo/minio/minio_client.py
from minio import Minio
from minio.error import S3Error

from algo.config import MINIO_HOST, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,MINIO_SECURE, MINIO_BUCKET, my_logger

minio_client = None

class MinIOClient:
    """A wrapper class for the MinIO client."""
    def __init__(self):
        self.bucket_name = MINIO_BUCKET
        try:
            self.client = Minio(
                endpoint=MINIO_HOST,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_SECURE
            )
            self._ensure_bucket()
        except Exception as e:
            my_logger.info(f"❌ MinIO client 初始化失败: {e}")
            raise

    def _ensure_bucket(self):
        """Ensures the bucket exists before operations."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                my_logger.info(f"✅ MinIO 的桶： '{self.bucket_name}' 不存在，已新建。")
        except S3Error as e:
            my_logger.info(f"❌ 新建MinIO的桶'{self.bucket_name}'失败: {e}")
            raise


    def upload_file(self, source_path: str, object_name: str):
        """将本地文件上传到MinIO"""
        try:
           
            self.client.fput_object(self.bucket_name, object_name, source_path)
            
          
            # print(f"✅ 文件 '{source_path}' 已上传到 MinIO: '{self.bucket_name}/{object_name}'")
        except S3Error as e:
            my_logger.info(f"❌ 上传文件到MinIO失败: {e}")
            

    def download_file(self, object_name: str, destination_path: str) -> bool:
        """从MinIO下载文件到本地"""
        try:
            self.client.fget_object(self.bucket_name, object_name, destination_path)
            # print(f"✅ 文件 '{object_name}' 已从MinIO下载到 '{destination_path}'")
            return True
        except S3Error as e:
            my_logger.info(f"❌ 从MinIO下载文件 '{self.bucket_name}/{object_name}' 失败。服务器返回的详细错误是: {e}")
            return False


def init_minio_client():
    """Initializes the MinIO client singleton on app startup."""
    global minio_client
    if minio_client is None:
        # print("🚀 正在初始化 MinIO client...")
        minio_client = MinIOClient()
        my_logger.info("✅ MinIO client 初始化完成。")
    return minio_client

def get_minio_client():
    """Returns the initialized MinIO client instance."""
    if minio_client is None:
        raise RuntimeError("MinIO client 没有被初始化，请先调用 init_minio_client() 进行初始化。")
    return minio_client