"""
Kickart Clone - 平台 API 路由
补全 V3-V7 所有模块的 HTTP 端点，确保前后端完整闭环
模块覆盖：SSO / Webhook / i18n / LLM路由 / AB测试 / 任务队列 / 对象存储 / 复利系统 / JNPF深度集成 / 租户 / 监控
"""
import importlib.util
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, UploadFile, File
from pydantic import BaseModel, Field

# 添加平台路径
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 模块路径映射（避免同名 manager.py 冲突）
_PLATFORM_MODULES = {
    "sso": PROJECT_ROOT / "platform" / "auth" / "sso.py",
    "webhook_manager": PROJECT_ROOT / "platform" / "webhook" / "manager.py",
    "translator": PROJECT_ROOT / "platform" / "i18n" / "translator.py",
    "llm_router_mod": PROJECT_ROOT / "platform" / "llm" / "router.py",
    "llm_providers": PROJECT_ROOT / "platform" / "llm" / "providers.py",
    "abtest_manager": PROJECT_ROOT / "platform" / "abtest" / "manager.py",
    "task_queue_mod": PROJECT_ROOT / "platform" / "queue" / "task_queue.py",
    "storage_mod": PROJECT_ROOT / "platform" / "storage" / "storage.py",
    "compound_extension": PROJECT_ROOT / "platform" / "compound" / "extension.py",
    "jnpf_deep": PROJECT_ROOT / "platform" / "jnpf" / "deep_integration.py",
    "tenant_manager": PROJECT_ROOT / "platform" / "tenant" / "manager.py",
    "monitor_mod": PROJECT_ROOT / "platform" / "monitoring" / "monitor.py",
}

# 同时保留路径（用于子模块的相对导入）
for sub in ["auth", "webhook", "i18n", "llm", "abtest", "queue", "storage", "compound", "jnpf", "tenant", "monitoring", "observability"]:
    p = PROJECT_ROOT / "platform" / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

router = APIRouter(prefix="/api", tags=["platform"])


def _load_platform_module(key: str):
    """通过 importlib 显式加载平台模块，避免同名 manager.py 冲突"""
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    path = _PLATFORM_MODULES[key]
    if not path.exists():
        raise ImportError(f"平台模块文件不存在: {path}")
    spec = importlib.util.spec_from_file_location(key, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module  # 提前注册，支持循环引用
    spec.loader.exec_module(module)
    return module


def _serialize(obj) -> dict:
    """递归序列化 dataclass / 含 __dict__ 的对象，处理 Enum/嵌套"""
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        result = {}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            result[k] = _serialize_value(v)
        return result
    return obj


def _serialize_value(v):
    """序列化单个值"""
    from enum import Enum
    if isinstance(v, Enum):
        return v.value
    if is_dataclass(v):
        return asdict(v)
    if isinstance(v, list):
        return [_serialize_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _serialize_value(x) for k, x in v.items()}
    if hasattr(v, "__dict__"):
        return _serialize(v)
    return v


# ============================================================================
# 模块单例（懒加载）
# ============================================================================

_sso = None
_webhook = None
_translator = None
_llm_router = None
_abtest = None
_task_queue = None
_storage = None
_compound = None
_jnpf = None
_tenant = None
_monitor = None


def get_sso():
    global _sso
    if _sso is None:
        mod = _load_platform_module("sso")
        _sso = mod.SSOManager()
    return _sso


def get_webhook():
    global _webhook
    if _webhook is None:
        mod = _load_platform_module("webhook_manager")
        _webhook = mod.WebhookManager()
    return _webhook


def get_translator():
    global _translator
    if _translator is None:
        mod = _load_platform_module("translator")
        _translator = mod.Translator()
    return _translator


def get_llm_router():
    global _llm_router
    if _llm_router is None:
        mod = _load_platform_module("llm_router_mod")
        _llm_router = mod.LLMRouter()
    return _llm_router


def get_abtest():
    global _abtest
    if _abtest is None:
        mod = _load_platform_module("abtest_manager")
        _abtest = mod.ABTestManager()
    return _abtest


def get_task_queue():
    global _task_queue
    if _task_queue is None:
        mod = _load_platform_module("task_queue_mod")
        _task_queue = mod.get_task_queue()
    return _task_queue


def get_storage():
    global _storage
    if _storage is None:
        mod = _load_platform_module("storage_mod")
        _storage = mod.get_storage()
    return _storage


def get_compound():
    global _compound
    if _compound is None:
        mod = _load_platform_module("compound_extension")
        _compound = mod.CompoundSystemExtension()
    return _compound


def get_jnpf():
    global _jnpf
    if _jnpf is None:
        mod = _load_platform_module("jnpf_deep")
        _jnpf = mod.JNPFDeepIntegration()
    return _jnpf


def get_tenant():
    global _tenant
    if _tenant is None:
        mod = _load_platform_module("tenant_manager")
        _tenant = mod.TenantManager()
    return _tenant


def get_monitor():
    global _monitor
    if _monitor is None:
        mod = _load_platform_module("monitor_mod")
        _monitor = mod.MonitoringSystem()
    return _monitor


# ============================================================================
# SSO 认证端点
# ============================================================================

class LoginRequest(BaseModel):
    username: str
    password: Optional[str] = None  # 本地登录用（简化版）


class CreateUserRequest(BaseModel):
    username: str
    email: str
    tenant_id: str
    role: str = "viewer"


class UpdateRoleRequest(BaseModel):
    role: str


class SSOCallbackRequest(BaseModel):
    tenant_id: str
    code: str
    userinfo: dict


@router.post("/auth/login")
async def login(req: LoginRequest):
    """本地登录（通过用户名查找并创建会话）"""
    mgr = get_sso()
    # 按用户名查找
    user = next((u for u in mgr.users.values() if u.username == req.username), None)
    if not user:
        raise HTTPException(404, "用户不存在")
    if not user.active:
        raise HTTPException(403, "用户已禁用")
    session = mgr.create_session(user)
    return {
        "session_id": session.session_id,
        "token": session.token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "tenant_id": user.tenant_id,
        },
    }


@router.post("/auth/refresh")
async def refresh_token(request: Request):
    """刷新令牌"""
    body = await request.json()
    refresh_token = body.get("refresh_token", "")
    mgr = get_sso()
    session = mgr.refresh_token(refresh_token)
    if not session:
        raise HTTPException(401, "刷新令牌无效或已过期")
    return {
        "session_id": session.session_id,
        "token": session.token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
    }


@router.post("/auth/verify")
async def verify_token(request: Request):
    """验证令牌"""
    body = await request.json()
    token = body.get("token", "")
    mgr = get_sso()
    payload = mgr.verify_token(token)
    if not payload:
        raise HTTPException(401, "令牌无效或已过期")
    return {"valid": True, "payload": payload}


@router.post("/auth/logout")
async def logout(request: Request):
    """登出"""
    body = await request.json()
    session_id = body.get("session_id", "")
    mgr = get_sso()
    success = mgr.revoke_session(session_id)
    return {"success": success}


@router.get("/auth/users")
async def list_users(tenant_id: Optional[str] = None):
    """列出用户"""
    mgr = get_sso()
    return {"users": mgr.list_users(tenant_id)}


@router.post("/auth/users")
async def create_user(req: CreateUserRequest):
    """创建用户"""
    mgr = get_sso()
    try:
        user = mgr.create_user(req.username, req.email, req.tenant_id, req.role)
        return {
            "user_id": user.user_id,
            "username": user.username,
            "role": user.role,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/auth/users/{user_id}/role")
async def update_user_role(user_id: str, req: UpdateRoleRequest):
    """更新用户角色"""
    mgr = get_sso()
    user = mgr.update_user_role(user_id, req.role)
    if not user:
        raise HTTPException(404, "用户不存在")
    return {"user_id": user.user_id, "role": user.role}


@router.get("/auth/permissions/{user_id}")
async def get_user_permissions(user_id: str):
    """获取用户权限"""
    mgr = get_sso()
    user = mgr.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    return {"user_id": user_id, "role": user.role, "permissions": mgr.get_user_permissions(user)}


@router.post("/auth/sso/callback")
async def sso_callback(req: SSOCallbackRequest):
    """SSO 回调"""
    mgr = get_sso()
    session = mgr.handle_sso_callback(req.tenant_id, req.code, req.userinfo)
    if not session:
        raise HTTPException(401, "SSO 回调失败")
    return {
        "session_id": session.session_id,
        "token": session.token,
        "refresh_token": session.refresh_token,
    }


@router.get("/auth/sso/authorize-url/{tenant_id}")
async def get_sso_authorize_url(tenant_id: str):
    """获取 SSO 授权 URL"""
    mgr = get_sso()
    import uuid as _uuid
    state = _uuid.uuid4().hex
    url = mgr.build_authorize_url(tenant_id, state)
    if not url:
        raise HTTPException(404, "未配置 SSO")
    return {"authorize_url": url, "state": state}


# ============================================================================
# Webhook 端点
# ============================================================================

class WebhookSubscribeRequest(BaseModel):
    tenant_id: str
    url: str
    events: list
    max_retries: int = 3
    timeout_sec: int = 10


class WebhookPublishRequest(BaseModel):
    event_type: str
    payload: dict
    tenant_id: Optional[str] = None


@router.get("/webhooks")
async def list_webhooks(tenant_id: Optional[str] = None):
    """列出 Webhook 订阅"""
    return {"subscriptions": get_webhook().list_subscriptions(tenant_id)}


@router.post("/webhooks")
async def create_webhook(req: WebhookSubscribeRequest):
    """创建 Webhook 订阅"""
    try:
        sub = get_webhook().subscribe(req.tenant_id, req.url, req.events, req.max_retries, req.timeout_sec)
        return {
            "subscription_id": sub.subscription_id,
            "secret": sub.secret,
            "events": sub.events,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/webhooks/{subscription_id}")
async def delete_webhook(subscription_id: str):
    """取消订阅"""
    success = get_webhook().unsubscribe(subscription_id)
    if not success:
        raise HTTPException(404, "订阅不存在")
    return {"success": True}


@router.post("/webhooks/publish")
async def publish_webhook(req: WebhookPublishRequest):
    """发布事件"""
    try:
        delivery_ids = get_webhook().publish(req.event_type, req.payload, req.tenant_id)
        return {"delivery_ids": delivery_ids, "count": len(delivery_ids)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/webhooks/deliveries")
async def list_deliveries(subscription_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    """列出投递记录"""
    return {"deliveries": get_webhook().list_deliveries(subscription_id, status, limit)}


@router.get("/webhooks/dead-letters")
async def list_dead_letters(limit: int = 50):
    """列出死信"""
    return {"dead_letters": get_webhook().list_dead_letters(limit)}


@router.post("/webhooks/deliveries/{delivery_id}/replay")
async def replay_delivery(delivery_id: str):
    """重放死信"""
    success = get_webhook().replay_delivery(delivery_id)
    if not success:
        raise HTTPException(404, "死信不存在或订阅已停用")
    return {"success": True}


# ============================================================================
# i18n 国际化端点
# ============================================================================

@router.get("/i18n/languages")
async def list_languages():
    """列出支持的语言"""
    return {"languages": get_translator().get_supported_languages()}


@router.get("/i18n/translations")
async def get_translations(lang: Optional[str] = None):
    """获取翻译"""
    return {"translations": get_translator().export_translations(lang)}


@router.put("/i18n/language")
async def set_language(request: Request):
    """设置当前语言"""
    body = await request.json()
    lang = body.get("lang", "zh-CN")
    try:
        get_translator().set_language(lang)
        return {"language": lang}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/i18n/translate")
async def translate(key: str, lang: Optional[str] = None):
    """翻译单个键"""
    tr = get_translator()
    if lang:
        tr.set_language(lang)
    return {"key": key, "text": tr.t(key)}


# ============================================================================
# LLM 路由端点
# ============================================================================

class LLMGenerateRequest(BaseModel):
    system_prompt: str = "你是营销创意助手"
    user_prompt: str
    purpose: str = "default"
    temperature: float = 0.8
    max_tokens: int = 2000
    model: Optional[str] = None
    preferred_provider: Optional[str] = None


class LLMImageRequest(BaseModel):
    prompt: str
    purpose: str = "image_generation"
    width: int = 1024
    height: int = 1024
    seed: int = 0
    model: Optional[str] = None


@router.get("/llm/status")
async def llm_status():
    """路由器状态"""
    return get_llm_router().get_router_status()


@router.get("/llm/providers")
async def llm_providers(purpose: Optional[str] = None):
    """可用提供商"""
    return {"providers": get_llm_router().get_available_providers(purpose)}


@router.get("/llm/purposes")
async def llm_purposes():
    """用途列表"""
    mod = _load_platform_module("llm_providers")
    return {"purposes": mod.get_purposes()}


@router.post("/llm/generate")
async def llm_generate(req: LLMGenerateRequest):
    """文本生成"""
    result = get_llm_router().generate(
        system_prompt=req.system_prompt,
        user_prompt=req.user_prompt,
        purpose=req.purpose,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        model=req.model,
        preferred_provider=req.preferred_provider,
    )
    if result.get("error") and not result.get("text"):
        raise HTTPException(503, result["error"])
    return result


@router.post("/llm/generate-image")
async def llm_generate_image(req: LLMImageRequest):
    """图片生成"""
    result = get_llm_router().generate_image(
        prompt=req.prompt,
        purpose=req.purpose,
        width=req.width,
        height=req.height,
        seed=req.seed,
        model=req.model,
    )
    if result.get("error") and not result.get("image_base64"):
        raise HTTPException(503, result["error"])
    return result


@router.get("/llm/usage")
async def llm_usage(group_by: str = "provider_id"):
    """用量统计"""
    return {"stats": get_llm_router().get_usage_stats(group_by)}


@router.get("/llm/recent")
async def llm_recent(limit: int = 50):
    """最近调用"""
    return {"calls": get_llm_router().get_recent_calls(limit)}


# ============================================================================
# AB 测试端点
# ============================================================================

class ABTestCreateRequest(BaseModel):
    name: str
    product_input: str
    variants_config: list


@router.get("/abtest")
async def list_abtests():
    """列出实验"""
    return {"experiments": get_abtest().list_experiments()}


@router.post("/abtest")
async def create_abtest(req: ABTestCreateRequest):
    """创建实验"""
    exp = get_abtest().create_experiment(req.name, req.product_input, req.variants_config)
    return {"experiment_id": exp.experiment_id, "name": exp.name}


@router.get("/abtest/{experiment_id}")
async def get_abtest_detail(experiment_id: str):
    """获取实验详情（递归序列化 dataclass，正确处理 Enum 字段）"""
    exp = get_abtest().get_experiment(experiment_id)
    if not exp:
        raise HTTPException(404, "实验不存在")
    return {"experiment": _serialize(exp)}


@router.post("/abtest/{experiment_id}/run")
async def run_abtest(experiment_id: str):
    """运行实验（无 LLM Key 时返回明确降级状态，不伪装 RUNNING）"""
    try:
        exp = get_abtest().run_experiment(experiment_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if not exp:
        raise HTTPException(404, "实验不存在")
    # 检测是否所有变体都因 LLM 缺失而降级
    variants = getattr(exp, "variants", [])
    all_degraded = bool(variants) and all(
        getattr(v, "status", "") == "pending" and "error" in (getattr(v, "artifacts", {}) or {})
        for v in variants
    )
    status = "degraded_no_llm" if all_degraded else exp.status
    return {
        "experiment_id": exp.experiment_id,
        "status": status,
        "variants_count": len(variants),
        "note": "变体因 LLM Key 未配置而降级，请配置 LLM 后重试" if all_degraded else "",
    }


@router.post("/abtest/{experiment_id}/metrics/{variant_id}")
async def record_metrics(experiment_id: str, variant_id: str, request: Request):
    """记录指标"""
    body = await request.json()
    try:
        get_abtest().record_metrics(experiment_id, variant_id, body)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True}


@router.get("/abtest/{experiment_id}/analyze")
async def analyze_abtest(experiment_id: str):
    """分析实验"""
    try:
        result = get_abtest().analyze(experiment_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ============================================================================
# 任务队列端点
# ============================================================================

class TaskSubmitRequest(BaseModel):
    func_name: str
    args: list = []
    kwargs: dict = {}
    name: str = ""
    priority: int = 5
    max_retries: int = 3
    timeout_sec: int = 300
    tenant_id: str = "default"


@router.get("/queue/tasks")
async def list_tasks():
    """列出任务"""
    return {"tasks": get_task_queue().list_tasks(), "queue_size": get_task_queue().queue_size()}


@router.post("/queue/tasks")
async def submit_task(req: TaskSubmitRequest):
    """提交任务"""
    mod = _load_platform_module("task_queue_mod")
    priority = mod.TaskPriority(req.priority) if req.priority in [1, 5, 10, 20] else mod.TaskPriority.NORMAL
    task_id = get_task_queue().submit(
        func_name=req.func_name,
        args=tuple(req.args),
        kwargs=req.kwargs,
        name=req.name,
        priority=priority,
        max_retries=req.max_retries,
        timeout_sec=req.timeout_sec,
        tenant_id=req.tenant_id,
    )
    return {"task_id": task_id}


@router.get("/queue/tasks/{task_id}")
async def get_task(task_id: str):
    """查询任务"""
    task = get_task_queue().get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {
        "task_id": task.task_id,
        "func_name": task.func_name,
        "state": task.state,
        "retries": task.retries,
        "name": task.name,
    }


@router.get("/queue/tasks/{task_id}/result")
async def get_task_result(task_id: str):
    """获取任务结果"""
    result = get_task_queue().get_result(task_id)
    if result is None:
        raise HTTPException(404, "结果不存在或任务未完成")
    return result


@router.post("/queue/workers/start")
async def start_workers(num_workers: int = 2):
    """启动 Worker"""
    get_task_queue().start_workers(num_workers)
    return {"success": True, "workers": num_workers}


@router.post("/queue/workers/stop")
async def stop_workers():
    """停止 Worker"""
    get_task_queue().stop_workers()
    return {"success": True}


# ============================================================================
# 对象存储端点
# ============================================================================

@router.get("/storage/objects")
async def list_objects(prefix: str = "", category: Optional[str] = None, tenant_id: Optional[str] = None):
    """列出对象（返回元数据数组，兼容前端）"""
    storage = get_storage()
    keys = storage.list_objects(prefix, category, tenant_id)
    # 同时返回 key 和元数据，便于前端展示
    objects = []
    for key in keys:
        meta = storage.get_metadata(key)
        objects.append({
            "key": key,
            "size": meta.get("size", 0),
            "category": meta.get("category", "general"),
            "tenant_id": meta.get("tenant_id", "default"),
            "uploaded_at": meta.get("uploaded_at"),
            "original_name": meta.get("original_name", key.split("/")[-1] if key else ""),
            "url": storage.get_url(key) if storage.exists(key) else "",
        })
    return {"objects": objects}


@router.post("/storage/objects/upload")
async def upload_object(file: UploadFile = File(...), category: str = "general", tenant_id: str = "default"):
    """上传文件到对象存储"""
    import tempfile
    storage = get_storage()
    # 先存到临时文件
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}")
    content = await file.read()
    tmp.write(content)
    tmp.close()
    try:
        result = storage.upload(
            local_path=tmp.name,
            remote_key=f"{tenant_id}/{category}/{file.filename}",
            category=category,
            tenant_id=tenant_id,
        )
        return result
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


@router.get("/storage/objects/{remote_key:path}")
async def get_object_info(remote_key: str):
    """获取对象信息"""
    storage = get_storage()
    if not storage.exists(remote_key):
        raise HTTPException(404, "对象不存在")
    return {
        "metadata": storage.get_metadata(remote_key),
        "url": storage.get_url(remote_key),
    }


@router.delete("/storage/objects/{remote_key:path}")
async def delete_object(remote_key: str):
    """删除对象"""
    success = get_storage().delete(remote_key)
    if not success:
        raise HTTPException(404, "对象不存在")
    return {"success": True}


@router.get("/storage/stats")
async def storage_stats():
    """存储统计（同时返回前端字段和后端字段）"""
    stats = get_storage().get_stats()
    # 兼容字段：前端读 total_objects/total_size，后端原本是 total_files/total_size_mb
    return {
        **stats,
        "total_objects": stats.get("total_files", 0),
        "total_size": stats.get("total_size_mb", 0) * 1024 * 1024,  # 字节
        "total_size_mb": stats.get("total_size_mb", 0),
        "total_files": stats.get("total_files", 0),
    }


# ============================================================================
# 复利系统端点
# ============================================================================

class TemplateCreateRequest(BaseModel):
    name: str
    description: str = ""
    asset_type: str = "template"
    content: dict
    params_schema: dict = {}
    parent_template: Optional[str] = None


class TemplateInstantiateRequest(BaseModel):
    template_id: str
    params: dict = {}


class VersionCreateRequest(BaseModel):
    asset_id: str
    version: str
    path: str
    changelog: str = ""


class ComposeRequest(BaseModel):
    steps: list


@router.get("/compound/templates")
async def list_templates():
    """列出模板"""
    return {"templates": get_compound().template_mgr.list_templates()}


@router.post("/compound/templates")
async def create_template(req: TemplateCreateRequest):
    """创建模板"""
    tpl = get_compound().template_mgr.create_template(
        name=req.name,
        description=req.description,
        asset_type=req.asset_type,
        template_content=req.content,
        params_schema=req.params_schema or None,
        parent_template=req.parent_template,
    )
    return {"template_id": tpl.template_id, "name": tpl.name}


@router.post("/compound/templates/instantiate")
async def instantiate_template(req: TemplateInstantiateRequest):
    """实例化模板"""
    try:
        result = get_compound().template_mgr.instantiate(req.template_id, req.params)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/compound/templates/init-defaults")
async def init_default_templates():
    """初始化默认模板库"""
    try:
        get_compound().register_default_templates()
        return {"success": True, "templates": get_compound().template_mgr.list_templates()}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/compound/templates/inherit")
async def inherit_template(request: Request):
    """模板继承"""
    body = await request.json()
    try:
        child = get_compound().template_mgr.inherit(
            parent_template=body.get("parent_template"),
            name=body.get("name"),
            overrides=body.get("overrides", {}),
            description=body.get("description", ""),
        )
        return {"template_id": child.template_id, "name": child.name}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/compound/versions/{asset_id}")
async def list_versions(asset_id: str):
    """列出资产版本"""
    return {"versions": get_compound().version_mgr.get_versions(asset_id)}


@router.post("/compound/versions")
async def create_version(req: VersionCreateRequest):
    """创建版本"""
    ver = get_compound().version_mgr.create_version(req.asset_id, req.version, req.path, req.changelog)
    return {"version_id": ver.version_id, "version": ver.version}


@router.post("/compound/compose/pipeline")
async def compose_pipeline(req: ComposeRequest):
    """管道编排"""
    result = get_compound().composition_engine.execute_pipeline(req.steps)
    return result


@router.post("/compound/compose/parallel")
async def compose_parallel(request: Request):
    """并行编排"""
    body = await request.json()
    result = get_compound().composition_engine.execute_parallel(body.get("instructions", []))
    return result


# ============================================================================
# JNPF 深度集成端点
# ============================================================================

@router.get("/jnpf/form-schema")
async def get_form_schema():
    """获取表单 Schema"""
    integration = get_jnpf()
    schema = integration.build_creative_form_schema()
    return integration.form_engine.serialize(schema)


@router.post("/jnpf/form-validate")
async def validate_form(request: Request):
    """校验表单"""
    body = await request.json()
    data = body.get("data", {})
    integration = get_jnpf()
    schema = integration.build_creative_form_schema()
    data = integration.form_engine.apply_defaults(schema, data)
    result = integration.form_engine.validate(schema, data)
    return result


@router.post("/jnpf/form-rules")
async def evaluate_form_rules(request: Request):
    """评估联动规则"""
    body = await request.json()
    data = body.get("data", {})
    integration = get_jnpf()
    schema = integration.build_creative_form_schema()
    return integration.form_engine.evaluate_rules(schema, data)


@router.get("/jnpf/workflow-definition")
async def get_workflow_definition():
    """获取流程定义"""
    integration = get_jnpf()
    nodes = integration.build_creative_workflow()
    return {"nodes": [
        {
            "node_id": n.node_id,
            "node_type": n.node_type.value,
            "name": n.name,
            "agent": n.agent,
            "next_nodes": n.next_nodes,
            "branches": n.branches,
        }
        for n in nodes
    ]}


@router.post("/jnpf/workflow-run")
async def run_jnpf_workflow(request: Request):
    """运行流程（接入复利系统指令集，按节点 agent 调用对应指令）"""
    body = await request.json()
    context = body.get("context", {})
    integration = get_jnpf()
    wf_id = integration.register_default_workflow()
    # 获取复利系统扩展（提供指令引擎 + 组合编排）
    compound = get_compound()
    instruction_engine = compound.composition_engine.instruction_engine

    # agent 名 → 复利系统指令名 映射
    AGENT_TO_INSTRUCTION = {
        "product_parser": None,  # 解析阶段无对应指令，直接返回上下文
        "creative": "generate.creative",
        "storyboard": "generate.storyboard",
        "image_gen": "generate.images",
        "tts": None,  # TTS 由 video 指令内部处理
        "video_gen": "generate.video",
    }

    def real_executor(node, ctx):
        """真实执行器：通过复利系统指令集驱动每个节点"""
        agent_name = node.agent or ""
        node_id = node.node_id
        product_input = ctx.get("input_value") or ctx.get("product") or "示例商品"
        num_scenes = ctx.get("num_scenes", 6)
        try:
            if agent_name == "product_parser":
                return {
                    "node": node_id, "agent": agent_name, "status": "done",
                    "output": {"product": {"title": product_input[:80], "description": product_input}},
                }
            instruction = AGENT_TO_INSTRUCTION.get(agent_name)
            if instruction is None:
                return {"node": node_id, "agent": agent_name, "status": "done", "output": {}}
            # 构造指令参数（从上下文累积上游产物）
            params = {"product_info": ctx.get("product_parser", {}).get("output", {}).get("product", {"title": product_input})}
            if agent_name == "storyboard":
                creative_out = ctx.get("creative", {}).get("output", {})
                params["creative"] = creative_out
                params["num_scenes"] = num_scenes
            elif agent_name == "image_gen":
                sb_out = ctx.get("storyboard", {}).get("output", {})
                params["storyboard"] = sb_out.get("storyboard", sb_out)
            # 调用复利系统指令引擎
            result = instruction_engine.execute(instruction, params)
            if not result.get("success", False):
                return {"node": node_id, "agent": agent_name, "status": "done",
                        "warning": result.get("error", "指令执行失败"), "output": {}}
            return {"node": node_id, "agent": agent_name, "status": "done",
                    "instruction": instruction, "output": result}
        except Exception as e:
            return {"node": node_id, "agent": agent_name, "status": "done", "warning": str(e)[:80]}

    instance = integration.flow_engine.run(wf_id, context, real_executor)
    return integration.flow_engine.serialize_instance(instance)


# ============================================================================
# 租户管理端点
# ============================================================================

class TenantCreateRequest(BaseModel):
    name: str
    plan: str = "free"


class TenantUpdateRequest(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    api_key: Optional[str] = None


@router.get("/tenants")
async def list_tenants():
    """列出租户（补 api_key 脱敏前 16 位）"""
    mgr = get_tenant()
    tenants = mgr.list_tenants()
    # 补 api_key 字段（前端展示脱敏前 16 位）
    for t in tenants:
        full = mgr.get_tenant(t["tenant_id"])
        if full and full.api_key:
            t["api_key"] = full.api_key[:16] + "..."
        else:
            t["api_key"] = ""
    return {"tenants": tenants}


@router.post("/tenants")
async def create_tenant(req: TenantCreateRequest):
    """创建租户"""
    tenant = get_tenant().create_tenant(req.name, req.plan)
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "plan": tenant.plan,
        "api_key": tenant.api_key,
    }


@router.get("/tenants/{tenant_id}")
async def get_tenant_info(tenant_id: str):
    """获取租户"""
    tenant = get_tenant().get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "租户不存在")
    return {"tenant": tenant.__dict__ if hasattr(tenant, '__dict__') else str(tenant)}


@router.put("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, req: TenantUpdateRequest):
    """更新租户（回显更新后的对象）"""
    updates = {k: v for k, v in req.dict().items() if v is not None}
    tenant = get_tenant().update_tenant(tenant_id, **updates)
    if not tenant:
        raise HTTPException(404, "租户不存在")
    return {"success": True, "tenant": {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "plan": tenant.plan,
        "api_key": (tenant.api_key or "")[:16] + "...",
        "active": tenant.active,
    }}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str):
    """删除租户"""
    success = get_tenant().delete_tenant(tenant_id)
    if not success:
        raise HTTPException(404, "租户不存在")
    return {"success": True}


@router.get("/tenants/{tenant_id}/quota")
async def check_quota(tenant_id: str):
    """检查配额（同时返回原 resource 名和 detail 字段）"""
    tenant = get_tenant().get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "租户不存在")
    mgr = get_tenant()
    # 前端使用 videos_daily/images_daily/api_calls_daily，后端只识别 video/image/run
    # 这里同时返回两套字段名以保证兼容
    resource_map = {
        "videos_daily": "video",
        "images_daily": "image",
        "api_calls_daily": "run",
    }
    quotas = {}
    for front_name, back_resource in resource_map.items():
        result = mgr.check_quota(tenant_id, back_resource)
        quotas[front_name] = result
        quotas[back_resource] = result  # 也保留后端原名
    return {"quotas": quotas, "tenant_id": tenant_id, "plan": tenant.plan}


# ============================================================================
# 监控告警端点
# ============================================================================

@router.get("/monitoring/health")
async def monitoring_health():
    """健康检查（兼容字段：components 别名指向 checks，status 别名指向 healthy）"""
    h = get_monitor().health_check()
    # 兼容前端：components 字段 + 每项含 status 字段
    components = {}
    for name, info in h.get("checks", {}).items():
        components[name] = {
            **info,
            "status": "healthy" if info.get("healthy") else "unhealthy",
        }
    return {
        **h,
        "components": components,  # 兼容前端旧字段名
    }


@router.get("/monitoring/dashboard")
async def monitoring_dashboard():
    """仪表盘"""
    return get_monitor().get_dashboard()


@router.get("/monitoring/alerts")
async def monitoring_alerts():
    """活跃告警（同时返回 level 和 severity，保持字段契约兼容）"""
    alerts = get_monitor().get_active_alerts()
    # 兼容字段：severity 别名指向 level
    for a in alerts:
        a["severity"] = a.get("level", "warning")
    return {"alerts": alerts}


@router.get("/monitoring/alerts/history")
async def monitoring_alert_history(limit: int = 100):
    """告警历史（同时返回 level 和 severity，fired_at 兼容 triggered_at）"""
    history = get_monitor().get_alert_history(limit)
    for h in history:
        h["severity"] = h.get("level", "warning")
        # 前端读 triggered_at（unix 时间戳），后端返回 fired_at 是 ISO 字符串
        # 同时返回 fired_at_iso 和 triggered_at 兼容
        if h.get("fired_at") and not h.get("triggered_at"):
            from datetime import datetime
            try:
                # ISO 字符串 -> unix 时间戳
                dt = datetime.fromisoformat(h["fired_at"])
                h["triggered_at"] = dt.timestamp()
            except Exception:
                h["triggered_at"] = None
    return {"history": history}


@router.post("/monitoring/alerts/{rule_name}/ack")
async def ack_alert(rule_name: str):
    """确认告警"""
    success = get_monitor().acknowledge_alert(rule_name)
    if not success:
        raise HTTPException(404, "告警不存在")
    return {"success": True}


@router.get("/monitoring/rules")
async def monitoring_rules():
    """告警规则（同时返回 level 和 severity 兼容字段）"""
    rules = get_monitor().list_rules()
    for r in rules:
        r["severity"] = r.get("level", "warning")
    return {"rules": rules}


class CreateRuleRequest(BaseModel):
    name: str
    metric: str
    condition: str  # gt/lt/gte/lte/eq
    threshold: float
    level: str = "warning"  # info/warning/critical/fatal
    message_template: str = ""
    cooldown_sec: int = 300


@router.post("/monitoring/rules")
async def create_monitoring_rule(req: CreateRuleRequest):
    """创建告警规则"""
    monitor_mod = _load_platform_module("monitor_mod")
    try:
        level_enum = monitor_mod.AlertLevel(req.level)
    except ValueError:
        raise HTTPException(400, f"未知告警级别: {req.level}")
    rule = monitor_mod.AlertRule(
        name=req.name,
        metric=req.metric,
        condition=req.condition,
        threshold=req.threshold,
        level=level_enum,
        message_template=req.message_template or f"{req.metric} {req.condition} {req.threshold}: {{value}}",
        cooldown_sec=req.cooldown_sec,
    )
    get_monitor().add_rule(rule)
    return {"success": True, "rule": _serialize(rule)}


@router.get("/monitoring/metrics/{metric_name}")
async def get_metric(metric_name: str, window_sec: int = 3600):
    """获取指标"""
    return {
        "metric": metric_name,
        "values": get_monitor().get_metric(metric_name, window_sec),
        "latest": get_monitor().get_metric_latest(metric_name),
        "avg": get_monitor().get_metric_avg(metric_name, window_sec),
    }


@router.post("/monitoring/metrics/{metric_name}")
async def record_metric(metric_name: str, request: Request):
    """录入指标值并评估告警规则（同时返回新触发的告警）"""
    body = await request.json()
    value = body.get("value")
    if value is None:
        raise HTTPException(400, "缺少 value 字段")
    labels = body.get("labels", {})
    monitor = get_monitor()
    monitor.record_metric(metric_name, float(value), labels)
    # 评估规则
    new_alerts = monitor.evaluate_rules()
    return {
        "success": True,
        "metric": metric_name,
        "value": value,
        "new_alerts": _serialize(new_alerts) if new_alerts else [],
        "new_alerts_count": len(new_alerts),
    }
