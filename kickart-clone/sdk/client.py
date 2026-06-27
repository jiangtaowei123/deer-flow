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

    # ============ 平台能力：认证 SSO ============

    def login(self, username: str, password: str = None) -> dict:
        """用户登录，返回 token"""
        return self._post("/api/auth/login", {"username": username, "password": password})

    def verify_token(self, token: str) -> dict:
        """验证 token"""
        return self._post("/api/auth/verify", {"token": token})

    def refresh_token(self, refresh_token: str) -> dict:
        """刷新 token"""
        return self._post("/api/auth/refresh", {"refresh_token": refresh_token})

    def logout(self, token: str) -> dict:
        """登出"""
        return self._post("/api/auth/logout", {"token": token})

    def list_users(self) -> list:
        """列出所有用户"""
        return self._get("/api/auth/users").get("users", [])

    def create_user(self, username: str, email: str, role: str = "user", tenant_id: str = "default") -> dict:
        """创建用户"""
        return self._post("/api/auth/users", {"username": username, "email": email, "role": role, "tenant_id": tenant_id})

    def get_sso_authorize_url(self, tenant_id: str = "default") -> dict:
        """获取 SSO 授权 URL"""
        return self._get(f"/api/auth/sso/authorize-url/{tenant_id}")

    # ============ 平台能力：租户管理 ============

    def list_tenants(self) -> list:
        """列出所有租户"""
        return self._get("/api/tenants").get("tenants", [])

    def create_tenant(self, name: str, plan: str = "free") -> dict:
        """创建租户"""
        return self._post("/api/tenants", {"name": name, "plan": plan})

    def get_tenant(self, tenant_id: str) -> dict:
        """获取租户详情"""
        return self._get(f"/api/tenants/{tenant_id}")

    def update_tenant(self, tenant_id: str, **kwargs) -> dict:
        """更新租户（name/plan/api_key）"""
        return self._put(f"/api/tenants/{tenant_id}", kwargs)

    def delete_tenant(self, tenant_id: str) -> dict:
        """删除租户"""
        return self._delete(f"/api/tenants/{tenant_id}")

    def check_tenant_quota(self, tenant_id: str) -> dict:
        """检查租户配额"""
        return self._get(f"/api/tenants/{tenant_id}/quota")

    # ============ 平台能力：LLM 路由 ============

    def get_llm_status(self) -> dict:
        """获取 LLM 路由状态"""
        return self._get("/api/llm/status")

    def llm_generate(self, prompt: str, purpose: str = "creative", model: str = None) -> dict:
        """LLM 文本生成"""
        payload = {"prompt": prompt, "purpose": purpose}
        if model:
            payload["model"] = model
        return self._post("/api/llm/generate", payload)

    def get_llm_usage(self) -> dict:
        """获取 LLM 用量统计"""
        return self._get("/api/llm/usage")

    # ============ 平台能力：A/B 测试 ============

    def list_experiments(self) -> list:
        """列出所有 A/B 实验"""
        return self._get("/api/abtest").get("experiments", [])

    def create_experiment(self, name: str, product_input: str, variants_config: list) -> dict:
        """创建 A/B 实验"""
        return self._post("/api/abtest", {"name": name, "product_input": product_input, "variants_config": variants_config})

    def get_experiment(self, experiment_id: str) -> dict:
        """获取实验详情"""
        return self._get(f"/api/abtest/{experiment_id}")

    def run_experiment(self, experiment_id: str) -> dict:
        """运行实验"""
        return self._post(f"/api/abtest/{experiment_id}/run", {})

    def record_experiment_metrics(self, experiment_id: str, variant_id: str, metrics: dict) -> dict:
        """记录实验变体指标"""
        return self._post(f"/api/abtest/{experiment_id}/metrics/{variant_id}", metrics)

    def analyze_experiment(self, experiment_id: str) -> dict:
        """分析实验结果"""
        return self._get(f"/api/abtest/{experiment_id}/analyze")

    # ============ 平台能力：对象存储 ============

    def list_storage_objects(self, prefix: str = "", category: str = None) -> list:
        """列出存储对象"""
        params = {"prefix": prefix}
        if category:
            params["category"] = category
        return self._get("/api/storage/objects", params=params).get("objects", [])

    def get_storage_stats(self) -> dict:
        """获取存储统计"""
        return self._get("/api/storage/stats")

    def upload_file(self, file_path: str, category: str = "general", tenant_id: str = "default") -> dict:
        """上传文件到对象存储"""
        if not self._session:
            raise KickartError("requests 库未安装")
        import os
        filename = os.path.basename(file_path)
        # 根据扩展名推断 MIME，避免被后端 MIME 白名单拒绝（requests 默认是 octet-stream）
        ext_to_mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
            ".json": "application/json", ".txt": "text/plain",
            ".md": "text/markdown", ".csv": "text/csv",
            ".pdf": "application/pdf", ".zip": "application/zip",
        }
        ext = os.path.splitext(filename)[1].lower()
        mime = ext_to_mime.get(ext, "application/octet-stream")
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, mime)}
            data = {"category": category, "tenant_id": tenant_id}
            url = self.base_url + "/api/storage/objects/upload"
            headers = {k: v for k, v in self._session.headers.items() if k.lower() != "content-type"}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            resp = requests.post(url, files=files, data=data, headers=headers, timeout=self.timeout)
            if resp.status_code >= 400:
                raise KickartAPIError(resp.status_code, resp.text)
            return resp.json()

    def delete_storage_object(self, key: str) -> dict:
        """删除存储对象"""
        return self._delete(f"/api/storage/objects/{key}")

    # ============ 平台能力：任务队列 ============

    def list_queue_tasks(self, status: str = None) -> list:
        """列出队列任务"""
        params = {"status": status} if status else {}
        return self._get("/api/queue/tasks", params=params).get("tasks", [])

    def submit_queue_task(self, func_name: str, args: list = None, priority: str = "normal") -> dict:
        """提交队列任务"""
        return self._post("/api/queue/tasks", {"func_name": func_name, "args": args or [], "priority": priority})

    def get_queue_stats(self) -> dict:
        """获取队列统计"""
        return self._get("/api/queue/stats")

    def start_workers(self, num_workers: int = 2) -> dict:
        """启动 Worker"""
        return self._post(f"/api/queue/workers/start?num_workers={num_workers}", {})

    def stop_workers(self) -> dict:
        """停止 Worker"""
        return self._post("/api/queue/workers/stop", {})

    # ============ 平台能力：Webhook ============

    def list_webhooks(self) -> list:
        """列出 Webhook 订阅"""
        return self._get("/api/webhooks").get("subscriptions", [])

    def create_webhook(self, event_type: str, target_url: str, secret: str = None) -> dict:
        """创建 Webhook 订阅"""
        payload = {"event_type": event_type, "target_url": target_url}
        if secret:
            payload["secret"] = secret
        return self._post("/api/webhooks", payload)

    def publish_webhook(self, event_type: str, payload: dict) -> dict:
        """发布 Webhook 事件"""
        return self._post("/api/webhooks/publish", {"event_type": event_type, "payload": payload})

    def list_webhook_deliveries(self, subscription_id: str = None) -> list:
        """列出 Webhook 投递记录"""
        params = {"subscription_id": subscription_id} if subscription_id else {}
        return self._get("/api/webhooks/deliveries", params=params).get("deliveries", [])

    # ============ 平台能力：监控告警 ============

    def get_monitoring_health(self) -> dict:
        """获取系统健康检查"""
        return self._get("/api/monitoring/health")

    def get_monitoring_dashboard(self) -> dict:
        """获取监控仪表盘"""
        return self._get("/api/monitoring/dashboard")

    def get_active_alerts(self) -> list:
        """获取活跃告警"""
        return self._get("/api/monitoring/alerts").get("alerts", [])

    def get_alert_history(self, limit: int = 100) -> list:
        """获取告警历史"""
        return self._get(f"/api/monitoring/alerts/history?limit={limit}").get("history", [])

    def list_monitoring_rules(self) -> list:
        """列出告警规则"""
        return self._get("/api/monitoring/rules").get("rules", [])

    def create_monitoring_rule(self, name: str, metric: str, condition: str, threshold: float, level: str = "warning") -> dict:
        """创建告警规则"""
        return self._post("/api/monitoring/rules", {
            "name": name, "metric": metric, "condition": condition,
            "threshold": threshold, "level": level,
        })

    def record_metric(self, metric_name: str, value: float, labels: dict = None) -> dict:
        """录入指标并评估告警规则"""
        return self._post(f"/api/monitoring/metrics/{metric_name}", {"value": value, "labels": labels or {}})

    def acknowledge_alert(self, rule_name: str) -> dict:
        """确认告警"""
        return self._post(f"/api/monitoring/alerts/{rule_name}/ack", {})

    # ============ 平台能力：JNPF 低代码 ============

    def get_jnpf_form_schema(self) -> dict:
        """获取 JNPF 创作表单 Schema"""
        return self._get("/api/jnpf/form-schema")

    def validate_jnpf_form(self, data: dict) -> dict:
        """校验 JNPF 表单"""
        return self._post("/api/jnpf/form-validate", {"data": data})

    def get_jnpf_workflow_definition(self) -> dict:
        """获取 JNPF 流程定义"""
        return self._get("/api/jnpf/workflow-definition")

    def run_jnpf_workflow(self, context: dict) -> dict:
        """运行 JNPF 流程（接入复利系统指令集）"""
        return self._post("/api/jnpf/workflow-run", {"context": context})

    # ============ 平台能力：复利系统 ============

    def list_compound_templates(self) -> list:
        """列出复利系统资产模板"""
        return self._get("/api/compound/templates").get("templates", [])

    def create_compound_template(self, name: str, description: str, asset_type: str, template_content: dict) -> dict:
        """创建资产模板"""
        return self._post("/api/compound/templates", {
            "name": name, "description": description, "asset_type": asset_type,
            "template_content": template_content,
        })

    def init_compound_defaults(self) -> dict:
        """初始化默认模板"""
        return self._post("/api/compound/templates/init-defaults", {})

    def list_compound_versions(self, asset_id: str) -> list:
        """列出资产版本"""
        return self._get(f"/api/compound/versions/{asset_id}").get("versions", [])

    def create_compound_version(self, asset_id: str, version: str, path: str, changelog: str = "") -> dict:
        """创建资产版本"""
        return self._post("/api/compound/versions", {
            "asset_id": asset_id, "version": version, "path": path, "changelog": changelog,
        })

    def compound_pipeline(self, steps: list) -> dict:
        """复利系统管道编排"""
        return self._post("/api/compound/compose/pipeline", {"steps": steps})

    def compound_parallel(self, instructions: list) -> dict:
        """复利系统并行编排"""
        return self._post("/api/compound/compose/parallel", {"instructions": instructions})

    # ============ 平台能力：国际化 i18n ============

    def get_supported_languages(self) -> list:
        """获取支持的语言列表"""
        return self._get("/api/i18n/languages").get("languages", [])

    def get_translations(self, lang: str = "zh-CN") -> dict:
        """获取翻译字典"""
        return self._get("/api/i18n/translations", params={"lang": lang})

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

    def _get(self, path: str, params: dict = None) -> dict:
        kwargs = {"params": params} if params else {}
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, json=data)

    def _put(self, path: str, data: dict) -> dict:
        return self._request("PUT", path, json=data)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

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
