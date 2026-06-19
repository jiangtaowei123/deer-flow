"""
Kickart Python SDK - 开发者友好 API
封装所有平台能力，提供简洁的 Python 接口

用法：
    from sdk import KickartClient

    client = KickartClient(api_key="kk_xxx")
    result = client.create_video("优雅夏季连衣裙")
"""
import json
import os
import time
from typing import Optional

try:
    import requests
except ImportError:
    requests = None


class KickartError(Exception):
    """Kickart SDK 基础异常"""
    pass


class KickartAPIError(KickartError):
    """API 调用异常"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class KickartClient:
    """
    Kickart 营销创作平台 Python SDK

    Args:
        base_url: API 地址（默认 http://localhost:8765）
        api_key: API Key（多租户鉴权）
        timeout: 请求超时（秒）
    """

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        timeout: int = 300,
    ):
        self.base_url = (base_url or os.environ.get("KICKART_API_URL", "http://localhost:8765")).rstrip("/")
        self.api_key = api_key or os.environ.get("KICKART_API_KEY")
        self.timeout = timeout
        self._session = requests.Session() if requests else None

        if self._session:
            self._session.headers.update({
                "Content-Type": "application/json",
                "User-Agent": "kickart-sdk-python/1.0.0",
            })
            if self.api_key:
                self._session.headers["X-API-Key"] = self.api_key

    # ============ 核心创作 API ============

    def create_video(
        self,
        product_input: str,
        num_scenes: int = 6,
        aspect_ratio: str = "9:16",
        voice: str = "xiaoxiao",
        sync: bool = True,
    ) -> dict:
        """
        创建营销视频

        Args:
            product_input: 商品 URL/ID/描述
            num_scenes: 场景数（3-10）
            aspect_ratio: 宽高比
            voice: TTS 音色
            sync: True=同步等待完成，False=异步立即返回

        Returns:
            创作结果
        """
        return self._orchestrate(
            input_value=product_input,
            workflow="video",
            num_scenes=num_scenes,
            aspect_ratio=aspect_ratio,
            voice=voice,
            sync=sync,
        )

    def create_images(
        self,
        product_input: str,
        num_scenes: int = 6,
        sync: bool = True,
    ) -> dict:
        """创建批量图片"""
        return self._orchestrate(
            input_value=product_input,
            workflow="image",
            num_scenes=num_scenes,
            sync=sync,
        )

    def create_storyboard(
        self,
        product_input: str,
        num_scenes: int = 6,
        aspect_ratio: str = "9:16",
    ) -> dict:
        """仅生成分镜"""
        return self._orchestrate(
            input_value=product_input,
            workflow="storyboard",
            num_scenes=num_scenes,
            aspect_ratio=aspect_ratio,
            sync=True,
        )

    def _orchestrate(self, sync: bool, **kwargs) -> dict:
        endpoint = "/orchestrate/sync" if sync else "/orchestrate"
        return self._post(endpoint, kwargs)

    # ============ 查询 API ============

    def get_run(self, run_id: str) -> dict:
        """查询运行状态"""
        return self._get(f"/orchestrate/{run_id}")

    def list_runs(self) -> list:
        """列出所有运行"""
        data = self._get("/orchestrate")
        return data.get("runs", [])

    def wait_for_completion(self, run_id: str, poll_interval: float = 2.0, timeout: int = 600) -> dict:
        """等待异步任务完成"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.get_run(run_id)
            if result.get("status") in ("success", "failed"):
                return result
            time.sleep(poll_interval)
        raise KickartError(f"等待超时: {run_id} ({timeout}s)")

    # ============ 场景模板 API ============

    def list_scenes(self) -> list:
        """列出场景模板"""
        return self._get("/scenes").get("scenes", [])

    # ============ 健康检查 API ============

    def health(self) -> dict:
        """健康检查"""
        return self._get("/health")

    # ============ 批量操作 ============

    def batch_create_videos(
        self,
        products: list[str],
        max_concurrent: int = 3,
    ) -> list[dict]:
        """
        批量创建视频

        Args:
            products: 商品输入列表
            max_concurrent: 最大并发数

        Returns:
            结果列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {
                executor.submit(self.create_video, p): p
                for p in products
            }
            for future in as_completed(futures):
                product = futures[future]
                try:
                    result = future.result()
                    results.append({"product": product, "success": True, "result": result})
                except Exception as e:
                    results.append({"product": product, "success": False, "error": str(e)})
        return results

    # ============ 内部方法 ============

    def _get(self, path: str) -> dict:
        return self._request("GET", path)

    def _post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, json=data)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self._session:
            raise KickartError("requests 库未安装")

        url = self.base_url + path
        try:
            resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
            if resp.status_code >= 400:
                try:
                    err = resp.json()
                    msg = err.get("detail", err.get("message", resp.text))
                except Exception:
                    msg = resp.text
                raise KickartAPIError(resp.status_code, msg)
            return resp.json()
        except requests.exceptions.ConnectionError:
            raise KickartError(f"无法连接到 API: {self.base_url}")
        except requests.exceptions.Timeout:
            raise KickartError(f"请求超时: {self.timeout}s")


# ============ 便捷函数 ============

def quick_create_video(product_input: str, **kwargs) -> dict:
    """快速创建视频（使用默认配置）"""
    client = KickartClient()
    return client.create_video(product_input, **kwargs)


def quick_create_images(product_input: str, **kwargs) -> dict:
    """快速创建图片"""
    client = KickartClient()
    return client.create_images(product_input, **kwargs)
