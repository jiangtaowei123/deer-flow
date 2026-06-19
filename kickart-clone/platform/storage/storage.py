"""
对象存储集成 - 产物云端存储与 CDN 分发
支持：本地存储 / S3 兼容 / 阿里云 OSS / 腾讯云 COS
统一接口：upload / download / delete / get_url
"""
import hashlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# 添加 observability 路径
_OBS_PATH = Path(__file__).parent.parent / "platform" / "observability"
if str(_OBS_PATH) not in sys.path:
    sys.path.insert(0, str(_OBS_PATH))

from logger import get_logger

logger = get_logger(__name__)


# ============ 存储后端基类 ============

class StorageBackend:
    """存储后端基类"""

    def upload(self, local_path: str, remote_key: str) -> str:
        raise NotImplementedError

    def download(self, remote_key: str, local_path: str) -> str:
        raise NotImplementedError

    def delete(self, remote_key: str) -> bool:
        raise NotImplementedError

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        raise NotImplementedError

    def exists(self, remote_key: str) -> bool:
        raise NotImplementedError

    def list_objects(self, prefix: str = "") -> list:
        raise NotImplementedError


# ============ 本地存储 ============

class LocalStorage(StorageBackend):
    """本地文件存储"""

    def __init__(self, base_dir: str = "/mnt/user-data/workspace/storage"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = os.environ.get("STORAGE_BASE_URL", "http://localhost:8765/files")

    def upload(self, local_path: str, remote_key: str) -> str:
        remote_path = self.base_dir / remote_key
        remote_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(local_path, remote_path)
        logger.info(f"本地存储上传: {remote_key} ({remote_path.stat().st_size} bytes)")
        return remote_key

    def download(self, remote_key: str, local_path: str) -> str:
        remote_path = self.base_dir / remote_key
        if not remote_path.exists():
            raise FileNotFoundError(f"文件不存在: {remote_key}")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(remote_path, local_path)
        return local_path

    def delete(self, remote_key: str) -> bool:
        remote_path = self.base_dir / remote_key
        if remote_path.exists():
            remote_path.unlink()
            return True
        return False

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        return f"{self.base_url}/{remote_key}"

    def exists(self, remote_key: str) -> bool:
        return (self.base_dir / remote_key).exists()

    def list_objects(self, prefix: str = "") -> list:
        search_path = self.base_dir / prefix
        if search_path.is_dir():
            return [str(p.relative_to(self.base_dir)) for p in search_path.rglob("*") if p.is_file()]
        return [
            str(p.relative_to(self.base_dir))
            for p in self.base_dir.rglob(prefix + "*")
            if p.is_file()
        ]


# ============ S3 兼容存储 ============

class S3Storage(StorageBackend):
    """S3 兼容存储（AWS S3 / MinIO / R2 等）"""

    def __init__(
        self,
        endpoint_url: str = None,
        access_key: str = None,
        secret_key: str = None,
        bucket: str = "kickart",
        region: str = "us-east-1",
    ):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url or os.environ.get("S3_ENDPOINT"),
            aws_access_key_id=access_key or os.environ.get("S3_ACCESS_KEY"),
            aws_secret_access_key=secret_key or os.environ.get("S3_SECRET_KEY"),
            region_name=region,
        )
        # 确保 bucket 存在
        try:
            self.s3.head_bucket(Bucket=bucket)
        except Exception:
            self.s3.create_bucket(Bucket=bucket)
        logger.info(f"S3 存储已连接: bucket={bucket}")

    def upload(self, local_path: str, remote_key: str) -> str:
        self.s3.upload_file(local_path, self.bucket, remote_key)
        logger.info(f"S3 上传: {remote_key}")
        return remote_key

    def download(self, remote_key: str, local_path: str) -> str:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(self.bucket, remote_key, local_path)
        return local_path

    def delete(self, remote_key: str) -> bool:
        self.s3.delete_object(Bucket=self.bucket, Key=remote_key)
        return True

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": remote_key},
            ExpiresIn=expires,
        )

    def exists(self, remote_key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=remote_key)
            return True
        except Exception:
            return False

    def list_objects(self, prefix: str = "") -> list:
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [obj["Key"] for obj in resp.get("Contents", [])]


# ============ 阿里云 OSS ============

class OSSStorage(StorageBackend):
    """阿里云 OSS 存储"""

    def __init__(
        self,
        access_key: str = None,
        secret_key: str = None,
        endpoint: str = None,
        bucket: str = "kickart",
    ):
        import oss2
        auth = oss2.Auth(
            access_key or os.environ.get("OSS_ACCESS_KEY"),
            secret_key or os.environ.get("OSS_SECRET_KEY"),
        )
        self.bucket = oss2.Bucket(
            auth,
            endpoint or os.environ.get("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com"),
            bucket,
        )
        logger.info(f"OSS 存储已连接: bucket={bucket}")

    def upload(self, local_path: str, remote_key: str) -> str:
        self.bucket.put_object_from_file(remote_key, local_path)
        return remote_key

    def download(self, remote_key: str, local_path: str) -> str:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.bucket.get_object_to_file(remote_key, local_path)
        return local_path

    def delete(self, remote_key: str) -> bool:
        self.bucket.delete_object(remote_key)
        return True

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        return self.bucket.sign_url("GET", remote_key, expires)

    def exists(self, remote_key: str) -> bool:
        return self.bucket.object_exists(remote_key)

    def list_objects(self, prefix: str = "") -> list:
        return [obj.key for obj in oss2.ObjectIterator(self.bucket, prefix=prefix)]


# ============ 存储管理器 ============

class StorageManager:
    """
    存储管理器
    - 自动选择后端
    - 文件去重（基于 hash）
    - 元数据管理
    - CDN URL 生成
    """

    def __init__(self, backend: str = "auto", **kwargs):
        self.backend_name = backend
        self.backend: StorageBackend = self._select_backend(backend, **kwargs)
        self._metadata: dict[str, dict] = {}

    def _select_backend(self, backend: str, **kwargs) -> StorageBackend:
        if backend == "s3" or (backend == "auto" and os.environ.get("S3_ACCESS_KEY")):
            try:
                return S3Storage(**kwargs)
            except ImportError:
                logger.warning("boto3 未安装，回退到本地存储")
            except Exception as e:
                logger.warning(f"S3 连接失败，回退到本地: {e}")

        if backend == "oss" or (backend == "auto" and os.environ.get("OSS_ACCESS_KEY")):
            try:
                return OSSStorage(**kwargs)
            except ImportError:
                logger.warning("oss2 未安装，回退到本地存储")
            except Exception as e:
                logger.warning(f"OSS 连接失败，回退到本地: {e}")

        return LocalStorage(base_dir=kwargs.get("base_dir", "/mnt/user-data/workspace/storage"))

    def upload(
        self,
        local_path: str,
        remote_key: str = None,
        category: str = "general",
        tenant_id: str = "default",
        deduplicate: bool = True,
    ) -> dict:
        """
        上传文件

        Args:
            local_path: 本地文件路径
            remote_key: 远程 key（None 则自动生成）
            category: 分类（video/image/audio/document）
            tenant_id: 租户 ID
            deduplicate: 是否去重

        Returns:
            上传结果（含 url、key、size、hash）
        """
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"本地文件不存在: {local_path}")

        # 计算 hash
        file_hash = self._compute_hash(local_path)
        file_size = local_path.stat().st_size

        # 去重检查
        if deduplicate:
            for key, meta in self._metadata.items():
                if meta.get("hash") == file_hash:
                    logger.info(f"文件去重命中: {key}")
                    return {
                        "success": True,
                        "remote_key": key,
                        "url": self.backend.get_url(key),
                        "size": file_size,
                        "hash": file_hash,
                        "deduplicated": True,
                    }

        # 生成 remote_key
        if not remote_key:
            ext = local_path.suffix
            date_str = datetime.now().strftime("%Y/%m/%d")
            remote_key = f"{tenant_id}/{category}/{date_str}/{file_hash[:16]}{ext}"

        # 上传
        self.backend.upload(str(local_path), remote_key)

        # 记录元数据
        metadata = {
            "remote_key": remote_key,
            "url": self.backend.get_url(remote_key),
            "size": file_size,
            "hash": file_hash,
            "category": category,
            "tenant_id": tenant_id,
            "original_name": local_path.name,
            "uploaded_at": datetime.now().isoformat(),
        }
        self._metadata[remote_key] = metadata

        logger.info(f"文件上传成功: {remote_key} ({file_size} bytes)")
        return {"success": True, **metadata, "deduplicated": False}

    def download(self, remote_key: str, local_path: str = None) -> str:
        """下载文件"""
        if local_path is None:
            local_path = f"/tmp/kickart_download_{int(time.time())}_{Path(remote_key).name}"
        return self.backend.download(remote_key, local_path)

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        """获取访问 URL"""
        return self.backend.get_url(remote_key, expires)

    def delete(self, remote_key: str) -> bool:
        """删除文件"""
        self._metadata.pop(remote_key, None)
        return self.backend.delete(remote_key)

    def exists(self, remote_key: str) -> bool:
        """检查文件是否存在"""
        return self.backend.exists(remote_key)

    def list_objects(self, prefix: str = "", category: str = None, tenant_id: str = None) -> list:
        """列出对象"""
        objects = self.backend.list_objects(prefix)
        if category or tenant_id:
            objects = [
                key for key in objects
                if (not category or f"/{category}/" in key)
                and (not tenant_id or key.startswith(f"{tenant_id}/"))
            ]
        return objects

    def get_metadata(self, remote_key: str) -> dict:
        """获取元数据"""
        return self._metadata.get(remote_key, {})

    def get_stats(self) -> dict:
        """获取存储统计"""
        total_size = sum(m.get("size", 0) for m in self._metadata.values())
        categories = {}
        for m in self._metadata.values():
            cat = m.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_files": len(self._metadata),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "categories": categories,
            "backend": self.backend_name,
        }

    def _compute_hash(self, file_path: Path) -> str:
        """计算文件 hash"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()


# ============ 全局存储单例 ============

_global_storage: Optional[StorageManager] = None


def get_storage(backend: str = "auto", **kwargs) -> StorageManager:
    """获取全局存储管理器"""
    global _global_storage
    if _global_storage is None:
        _global_storage = StorageManager(backend=backend, **kwargs)
    return _global_storage
