"""
V8 商用级完整闭环 - 端到端测试
验证：
1. 后端 API 路由模块能正确导入所有 12 个平台模块（避免同名 manager.py 冲突）
2. 前端 15 个页面对应的所有 API 调用都有后端端点支撑
3. FastAPI TestClient 测试每个端点能正常响应
4. 前后端闭环：API 端点可响应、前端页面可加载、关键链路（创建→查询→删除）完整
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "api"))

# 测试结果统计
_results = []


def record(name, ok, detail=""):
    _results.append({"name": name, "ok": ok, "detail": detail})
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))


def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# ============================================================================
# 测试 1：后端模块导入完整性（关键：同名 manager.py 不冲突）
# ============================================================================

def test_platform_module_loading():
    """测试所有 12 个平台模块可独立加载（修复同名 manager.py 冲突）"""
    section("测试 1: 平台模块导入完整性（同名 manager.py 隔离）")

    # 清理 sys.modules 中的旧 "manager" 缓存
    for k in list(sys.modules.keys()):
        if k == "manager" or k.startswith("platform_"):
            del sys.modules[k]

    from platform_routes import _load_platform_module

    expect = {
        "sso": "SSOManager",
        "webhook_manager": "WebhookManager",
        "translator": "Translator",
        "llm_router_mod": "LLMRouter",
        "llm_providers": "PROVIDER_REGISTRY",
        "abtest_manager": "ABTestManager",
        "task_queue_mod": "get_task_queue",
        "storage_mod": "get_storage",
        "compound_extension": "CompoundSystemExtension",
        "jnpf_deep": "JNPFDeepIntegration",
        "tenant_manager": "TenantManager",
        "monitor_mod": "MonitoringSystem",
    }

    all_ok = True
    for key, expected_attr in expect.items():
        try:
            mod = _load_platform_module(key)
            assert hasattr(mod, expected_attr), f"缺少属性 {expected_attr}"
        except Exception as e:
            record(f"加载 {key}", False, str(e)[:80])
            all_ok = False
            continue
        record(f"加载 {key}", True)

    # 关键：三个 manager.py 不应互相污染
    webhook_mod = _load_platform_module("webhook_manager")
    abtest_mod = _load_platform_module("abtest_manager")
    tenant_mod = _load_platform_module("tenant_manager")
    record("WebhookManager ≠ ABTestManager ≠ TenantManager",
           webhook_mod.WebhookManager is not abtest_mod.ABTestManager
           and abtest_mod.ABTestManager is not tenant_mod.TenantManager)

    return all_ok


# ============================================================================
# 测试 2：FastAPI 应用可启动并暴露所有路由
# ============================================================================

def test_fastapi_app_routes():
    """测试 FastAPI 应用启动 + 所有路由注册"""
    section("测试 2: FastAPI 应用启动 + 路由注册")

    try:
        from api import app
    except Exception as e:
        record("FastAPI app 导入", False, str(e)[:120])
        return False
    record("FastAPI app 导入", True)

    # 收集所有路由路径
    all_paths = set()
    def _collect(routes):
        for route in routes:
            if hasattr(route, "path"):
                all_paths.add(route.path)
            # 处理 _IncludedRouter（FastAPI 新版包装）
            if hasattr(route, "original_router"):
                _collect(route.original_router.routes)
            if hasattr(route, "routes"):
                _collect(route.routes)
    _collect(app.routes)

    print(f"  ℹ️  路由总数: {len(all_paths)}")

    # 关键端点必须存在
    required = [
        "/api/auth/login", "/api/auth/users", "/api/auth/sso/callback",
        "/api/webhooks", "/api/webhooks/publish", "/api/webhooks/dead-letters",
        "/api/i18n/languages", "/api/i18n/translations",
        "/api/llm/status", "/api/llm/providers", "/api/llm/generate",
        "/api/abtest", "/api/queue/tasks", "/api/storage/objects",
        "/api/compound/templates", "/api/jnpf/form-schema",
        "/api/tenants", "/api/monitoring/health", "/api/monitoring/dashboard",
        "/api/monitoring/alerts",
        "/", "/health", "/scenes", "/generate", "/tasks", "/orchestrate",
    ]
    missing = [p for p in required if p not in all_paths]
    if missing:
        record("关键端点齐全", False, f"缺失: {missing[:3]}")
        return False
    record(f"关键端点齐全 ({len(required)} 项)", True)
    return True


# ============================================================================
# 测试 3：前端页面与后端 API 的映射关系
# ============================================================================

def test_frontend_backend_mapping():
    """测试前端 15 个页面调用的 API 都有后端支撑"""
    section("测试 3: 前端页面 → 后端 API 闭环映射")

    frontend = PROJECT_ROOT / "frontend" / "index.html"
    if not frontend.exists():
        record("前端文件存在", False, "frontend/index.html 不存在")
        return False
    record("前端文件存在", True)

    content = frontend.read_text(encoding="utf-8")

    # 验证 15 个页面 div
    import re
    pages = set(re.findall(r'id="page-([a-z]+)"', content))
    expected_pages = {
        "dashboard", "create", "runs", "scenes",
        "llm", "abtest",
        "auth", "webhooks", "tenants", "storage", "queue",
        "jnpf", "compound",
        "health", "monitoring",
    }
    missing_pages = expected_pages - pages
    if missing_pages:
        record(f"15 个页面齐全", False, f"缺失: {missing_pages}")
        return False
    record(f"15 个页面齐全", True)

    # 提取所有 API 调用路径
    api_calls = set(re.findall(r"api\(['\"]([^'\"]+)['\"]", content))
    api_calls.update(re.findall(r"fetch\(['\"]/?api/([^'\"/?]+)", content))
    print(f"  ℹ️  前端 API 调用数: {len(api_calls)}")

    # 验证前端调用的每个 API 在后端都有对应端点
    # 由于前端使用相对路径，需要检查路径前缀
    from api import app
    backend_apis = set()
    def _collect(routes):
        for route in routes:
            if hasattr(route, "path"):
                backend_apis.add(route.path)
            if hasattr(route, "original_router"):
                _collect(route.original_router.routes)
            if hasattr(route, "routes"):
                _collect(route.routes)
    _collect(app.routes)

    # 提取后端 API 的简化形式（去掉前缀）
    backend_apis_simplified = set()
    for p in backend_apis:
        # /api/auth/users → auth/users
        if p.startswith("/api/"):
            backend_apis_simplified.add(p[5:])
        elif p.startswith("/"):
            backend_apis_simplified.add(p[1:])

    # 检查前端调用的 API 是否都有后端支撑
    unmatched = []
    for call in api_calls:
        # 跳过带变量参数的（如 'auth/users/' + id）
        if "${" in call or "+" in call:
            continue
        # 简单匹配：调用路径是否在后端路径中
        matched = False
        for api in backend_apis_simplified:
            if call == api or call.startswith(api + "/") or api.startswith(call + "/"):
                matched = True
                break
            # 处理动态参数：abtest/123/analyze 应匹配 abtest/{id}/analyze
            api_pattern = re.sub(r"/[^/{}]+/", "/{id}/", api)
            api_pattern = re.sub(r"/[^/{}]+$", "/{id}", api_pattern)
            if call == api_pattern:
                matched = True
                break
        if not matched:
            # 一些前端调用可能是复合路径（如 'abtest/' + id + '/run'）
            # 检查基础路径
            base = call.split("/")[0] if "/" in call else call
            if any(base in api for api in backend_apis_simplified):
                continue
            unmatched.append(call)

    if unmatched:
        record("前端 API 全部有后端支撑", False, f"未匹配: {unmatched[:5]}")
    else:
        record(f"前端 API 全部有后端支撑 ({len(api_calls)} 项)", True)
    return len(unmatched) == 0


# ============================================================================
# 测试 4：FastAPI TestClient 实际调用 GET 端点
# ============================================================================

def test_get_endpoints_via_testclient():
    """使用 TestClient 实际调用所有 GET 端点"""
    section("测试 4: TestClient GET 端点闭环")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:120])
        return False
    record("TestClient 初始化", True)

    # GET 端点清单（应返回 200，部分端点带必要 query）
    get_endpoints = [
        "/api/auth/users",
        "/api/webhooks",
        "/api/webhooks/deliveries",
        "/api/webhooks/dead-letters",
        "/api/i18n/languages",
        "/api/i18n/translations",
        "/api/i18n/translate?key=app.title",
        "/api/llm/status",
        "/api/llm/providers",
        "/api/llm/purposes",
        "/api/llm/usage",
        "/api/llm/recent",
        "/api/abtest",
        "/api/queue/tasks",
        "/api/storage/objects",
        "/api/storage/stats",
        "/api/compound/templates",
        "/api/jnpf/form-schema",
        "/api/jnpf/workflow-definition",
        "/api/tenants",
        "/api/monitoring/health",
        "/api/monitoring/dashboard",
        "/api/monitoring/alerts",
        "/api/monitoring/alerts/history",
        "/api/monitoring/rules",
        "/health",
        "/scenes",
    ]

    ok_count = 0
    fail_list = []
    for ep in get_endpoints:
        try:
            r = client.get(ep)
            if r.status_code == 200:
                ok_count += 1
            else:
                fail_list.append(f"{ep} -> {r.status_code}")
        except Exception as e:
            fail_list.append(f"{ep} -> EXC: {str(e)[:50]}")

    record(f"GET 端点可用 ({ok_count}/{len(get_endpoints)})",
           ok_count == len(get_endpoints),
           "; ".join(fail_list[:3]) if fail_list else "")
    return ok_count == len(get_endpoints)


# ============================================================================
# 测试 5：关键链路闭环（创建→查询→删除）
# ============================================================================

def test_create_query_delete_loop():
    """测试租户、Webhook、用户创建→查询→删除的完整闭环"""
    section("测试 5: 创建→查询→删除 闭环")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    # --- 5.1 租户闭环 ---
    try:
        # 创建
        r = client.post("/api/tenants", json={"name": "测试租户", "plan": "pro"})
        assert r.status_code == 200, f"创建租户失败: {r.status_code} {r.text}"
        tenant_id = r.json().get("tenant_id")
        assert tenant_id, "未返回 tenant_id"

        # 查询列表
        r = client.get("/api/tenants")
        assert r.status_code == 200
        assert any(t.get("tenant_id") == tenant_id for t in r.json().get("tenants", [])), "列表中未找到新租户"

        # 查询单个
        r = client.get(f"/api/tenants/{tenant_id}")
        assert r.status_code == 200

        # 配额查询
        r = client.get(f"/api/tenants/{tenant_id}/quota")
        assert r.status_code == 200

        # 删除
        r = client.delete(f"/api/tenants/{tenant_id}")
        assert r.status_code == 200

        record("租户 闭环（创建/查询/配额/删除）", True)
    except AssertionError as e:
        record("租户 闭环", False, str(e)[:80])

    # --- 5.2 用户闭环 ---
    try:
        # 先创建租户
        r = client.post("/api/tenants", json={"name": "用户测试租户", "plan": "free"})
        tenant_id = r.json()["tenant_id"]

        # 创建用户
        r = client.post("/api/auth/users", json={
            "username": "tester_v8", "email": "tester@v8.com",
            "tenant_id": tenant_id, "role": "viewer",
        })
        assert r.status_code == 200, f"创建用户失败: {r.status_code} {r.text}"
        user_id = r.json().get("user_id")

        # 查询列表
        r = client.get(f"/api/auth/users?tenant_id={tenant_id}")
        assert r.status_code == 200
        assert any(u.get("user_id") == user_id for u in r.json().get("users", [])), "用户列表中未找到"

        # 更新角色
        r = client.put(f"/api/auth/users/{user_id}/role", json={"role": "admin"})
        assert r.status_code == 200

        # 查询权限
        r = client.get(f"/api/auth/permissions/{user_id}")
        assert r.status_code == 200

        record("用户 闭环（创建/列表/改角色/权限）", True)
    except AssertionError as e:
        record("用户 闭环", False, str(e)[:80])

    # --- 5.3 Webhook 闭环 ---
    try:
        # 先准备租户
        r = client.post("/api/tenants", json={"name": "Webhook测试租户", "plan": "pro"})
        tenant_id = r.json()["tenant_id"]

        # 创建订阅
        r = client.post("/api/webhooks", json={
            "tenant_id": tenant_id,
            "url": "https://example.com/hook",
            "events": ["workflow.completed", "workflow.failed"],
            "max_retries": 3,
            "timeout_sec": 10,
        })
        assert r.status_code == 200, f"创建 Webhook 失败: {r.status_code} {r.text}"
        sub_id = r.json().get("subscription_id")

        # 查询列表
        r = client.get(f"/api/webhooks?tenant_id={tenant_id}")
        assert r.status_code == 200

        # 发布事件
        r = client.post("/api/webhooks/publish", json={
            "event_type": "workflow.completed",
            "payload": {"run_id": "test-run-1"},
            "tenant_id": tenant_id,
        })
        assert r.status_code == 200

        # 查询投递记录
        r = client.get("/api/webhooks/deliveries")
        assert r.status_code == 200

        # 查询死信
        r = client.get("/api/webhooks/dead-letters")
        assert r.status_code == 200

        # 取消订阅
        r = client.delete(f"/api/webhooks/{sub_id}")
        assert r.status_code == 200

        record("Webhook 闭环（订阅/发布/查询/取消）", True)
    except AssertionError as e:
        record("Webhook 闭环", False, str(e)[:80])

    # --- 5.4 复利模板闭环 ---
    try:
        # 创建模板
        r = client.post("/api/compound/templates", json={
            "name": "测试模板",
            "description": "V8 测试",
            "asset_type": "template",
            "content": {"fields": [{"name": "title", "type": "string"}]},
            "params_schema": {},
        })
        assert r.status_code == 200, f"创建模板失败: {r.status_code} {r.text}"
        tpl_id = r.json().get("template_id")

        # 查询列表
        r = client.get("/api/compound/templates")
        assert r.status_code == 200
        assert any(t.get("template_id") == tpl_id for t in r.json().get("templates", []))

        # 实例化
        r = client.post("/api/compound/templates/instantiate", json={
            "template_id": tpl_id, "params": {"title": "测试实例"},
        })
        assert r.status_code == 200

        record("复利模板 闭环（创建/列表/实例化）", True)
    except AssertionError as e:
        record("复利模板 闭环", False, str(e)[:80])

    # --- 5.5 AB 测试闭环 ---
    try:
        # 创建实验
        r = client.post("/api/abtest", json={
            "name": "V8 测试实验",
            "product_input": "Test Product",
            "variants_config": [
                {"name": "control", "config": {"style": "default"}},
                {"name": "treatment", "config": {"style": "viral"}},
            ],
        })
        assert r.status_code == 200, f"创建实验失败: {r.status_code} {r.text}"
        exp_id = r.json().get("experiment_id")

        # 查询列表
        r = client.get("/api/abtest")
        assert r.status_code == 200

        # 查询单个
        r = client.get(f"/api/abtest/{exp_id}")
        assert r.status_code == 200

        # 分析
        r = client.get(f"/api/abtest/{exp_id}/analyze")
        assert r.status_code == 200

        record("AB 测试 闭环（创建/列表/查询/分析）", True)
    except AssertionError as e:
        record("AB 测试 闭环", False, str(e)[:80])

    return True


# ============================================================================
# 测试 6：i18n 多语言切换闭环
# ============================================================================

def test_i18n_loop():
    """测试 i18n 语言切换闭环"""
    section("测试 6: i18n 多语言闭环")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    try:
        # 列出语言
        r = client.get("/api/i18n/languages")
        assert r.status_code == 200
        langs = r.json().get("languages", [])
        assert len(langs) >= 3, f"语言数不足: {len(langs)}"
        record(f"支持语言数 ({len(langs)})", True)

        # 切换语言
        for lang in ["zh-CN", "en-US", "ja-JP"]:
            r = client.put("/api/i18n/language", json={"lang": lang})
            if r.status_code == 200:
                record(f"切换到 {lang}", True)
            else:
                record(f"切换到 {lang}", False, f"状态码 {r.status_code}")

        # 翻译单个键
        r = client.get("/api/i18n/translate?key=app.title&lang=zh-CN")
        assert r.status_code == 200
        record("翻译键", True)

        # 导出全部翻译
        r = client.get("/api/i18n/translations")
        assert r.status_code == 200
        record("导出翻译", True)

    except AssertionError as e:
        record("i18n 闭环", False, str(e)[:80])
        return False
    return True


# ============================================================================
# 测试 7：LLM 路由端点闭环（mock 实际调用）
# ============================================================================

def test_llm_router_loop():
    """测试 LLM 路由端点闭环（mock 网络请求）"""
    section("测试 7: LLM 路由端点闭环")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    # 7.1 状态查询
    try:
        r = client.get("/api/llm/status")
        assert r.status_code == 200
        status = r.json()
        assert "strategy" in status
        record("路由器状态", True, f"策略={status.get('strategy')}")
    except AssertionError as e:
        record("路由器状态", False, str(e)[:80])

    # 7.2 提供商列表
    try:
        r = client.get("/api/llm/providers")
        assert r.status_code == 200
        record("提供商列表", True)
    except AssertionError as e:
        record("提供商列表", False, str(e)[:80])

    # 7.3 用途列表
    try:
        r = client.get("/api/llm/purposes")
        assert r.status_code == 200
        purposes = r.json().get("purposes", [])
        purpose_ids = [p.get("purpose") for p in purposes if isinstance(p, dict)]
        assert "aigc_marketing" in purpose_ids, f"用途列表缺少 aigc_marketing: {purpose_ids}"
        record(f"用途列表 ({len(purposes)} 项)", True)
    except AssertionError as e:
        record("用途列表", False, str(e)[:80])

    # 7.4 用量统计
    try:
        r = client.get("/api/llm/usage")
        assert r.status_code == 200
        record("用量统计", True)
    except AssertionError as e:
        record("用量统计", False, str(e)[:80])

    # 7.5 mock 生成调用（重置单例 + 设置环境变量 + mock requests）
    try:
        # 重置 platform_routes 中的 _llm_router 单例，使其重新初始化
        import platform_routes as _pr
        _pr._llm_router = None

        # 设置环境变量
        env_backup = dict(os.environ)
        os.environ["DEEPSEEK_KEY_AIGC"] = "sk_test_v8"
        os.environ["DEEPSEEK_KEY_JNPF"] = "sk_test_jnpf"
        os.environ["DEEPSEEK_KEY_ECOMMERCE"] = "sk_test_ecom"
        os.environ["GLM_KEY_ECOMMERCE"] = "glm_test"
        os.environ["ARK_KEY_DEFAULT"] = "ark_test"
        os.environ["ARK_KEY_BACKUP"] = "ark_test_2"
        os.environ["STABILITY_KEY"] = "stab_test"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "V8 测试创意"}}],
            "usage": {"total_tokens": 30},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_response):
            r = client.post("/api/llm/generate", json={
                "system_prompt": "你是营销创意助手",
                "user_prompt": "为运动鞋写一段营销文案",
                "purpose": "aigc_marketing",
                "temperature": 0.8,
                "max_tokens": 200,
            })
        os.environ.clear()
        os.environ.update(env_backup)

        assert r.status_code == 200, f"生成失败: {r.status_code} {r.text[:200]}"
        result = r.json()
        assert result.get("text") == "V8 测试创意", f"返回内容不匹配: {result.get('text')}"
        record("LLM 文本生成（mock）", True, f"provider={result.get('provider_id')}")
    except AssertionError as e:
        record("LLM 文本生成", False, str(e)[:120])
    finally:
        os.environ.clear()
        os.environ.update(env_backup) if 'env_backup' in dir() else None

    return True


# ============================================================================
# 测试 8：JNPF 表单引擎闭环
# ============================================================================

def test_jnpf_loop():
    """测试 JNPF 表单引擎闭环"""
    section("测试 8: JNPF 表单/流程闭环")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    # 8.1 获取表单 Schema
    try:
        r = client.get("/api/jnpf/form-schema")
        assert r.status_code == 200, f"Schema 失败: {r.status_code}"
        schema = r.json()
        assert "fields" in schema or "id" in schema, f"Schema 缺少字段: {list(schema.keys())[:5]}"
        record("表单 Schema", True)
    except AssertionError as e:
        record("表单 Schema", False, str(e)[:80])

    # 8.2 表单校验
    try:
        r = client.post("/api/jnpf/form-validate", json={
            "data": {"product_input": "测试商品", "workflow": "video"}
        })
        assert r.status_code == 200
        record("表单校验", True)
    except AssertionError as e:
        record("表单校验", False, str(e)[:80])

    # 8.3 联动规则
    try:
        r = client.post("/api/jnpf/form-rules", json={
            "data": {"workflow": "image", "aspect_ratio": "1:1"}
        })
        assert r.status_code == 200
        record("联动规则", True)
    except AssertionError as e:
        record("联动规则", False, str(e)[:80])

    # 8.4 流程定义
    try:
        r = client.get("/api/jnpf/workflow-definition")
        assert r.status_code == 200
        nodes = r.json().get("nodes", [])
        assert len(nodes) > 0, "流程节点为空"
        record(f"流程定义 ({len(nodes)} 节点)", True)
    except AssertionError as e:
        record("流程定义", False, str(e)[:80])

    # 8.5 运行流程
    try:
        r = client.post("/api/jnpf/workflow-run", json={
            "context": {"product_input": "测试商品", "user_id": "v8tester"}
        })
        assert r.status_code == 200, f"运行流程失败: {r.status_code} {r.text[:200]}"
        record("运行流程", True)
    except AssertionError as e:
        record("运行流程", False, str(e)[:80])

    return True


# ============================================================================
# 测试 9：监控告警闭环
# ============================================================================

def test_monitoring_loop():
    """测试监控告警闭环"""
    section("测试 9: 监控告警闭环")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    try:
        # 健康检查
        r = client.get("/api/monitoring/health")
        assert r.status_code == 200
        record("健康检查", True)

        # 仪表盘
        r = client.get("/api/monitoring/dashboard")
        assert r.status_code == 200
        record("仪表盘", True)

        # 活跃告警
        r = client.get("/api/monitoring/alerts")
        assert r.status_code == 200
        record("活跃告警", True)

        # 告警历史
        r = client.get("/api/monitoring/alerts/history")
        assert r.status_code == 200
        record("告警历史", True)

        # 告警规则
        r = client.get("/api/monitoring/rules")
        assert r.status_code == 200
        rules = r.json().get("rules", [])
        assert len(rules) > 0, "无告警规则"
        record(f"告警规则 ({len(rules)} 条)", True)

        # 指标查询
        rule_names = [r.get("name") for r in rules if isinstance(r, dict) and "name" in r]
        if rule_names:
            r = client.get(f"/api/monitoring/metrics/{rule_names[0]}")
            assert r.status_code == 200
            record("指标查询", True)

    except AssertionError as e:
        record("监控告警闭环", False, str(e)[:80])
        return False
    return True


# ============================================================================
# 测试 10：前端首页可加载
# ============================================================================

def test_frontend_homepage():
    """测试前端首页可加载（GET /）"""
    section("测试 10: 前端首页加载")

    try:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200, f"首页状态码: {r.status_code}"
        assert "Kickart" in r.text or "kickart" in r.text.lower(), "首页未包含 Kickart"
        assert "page-dashboard" in r.text, "首页未包含 dashboard 页面 div"
        assert "page-monitoring" in r.text, "首页未包含 monitoring 页面 div"
        # 验证 15 个页面 div 都在
        for p in ["dashboard", "create", "runs", "scenes", "llm", "abtest",
                  "auth", "webhooks", "tenants", "storage", "queue",
                  "jnpf", "compound", "health", "monitoring"]:
            assert f"page-{p}" in r.text, f"首页缺少 page-{p}"
        record("首页加载 + 15 页面 div 齐全", True)
        return True
    except AssertionError as e:
        record("首页加载", False, str(e)[:80])
        return False
    except Exception as e:
        record("首页加载", False, f"异常: {str(e)[:80]}")
        return False


# ============================================================================
# 主测试入口
# ============================================================================

def main():
    print("╔" + "═" * 60 + "╗")
    print("║" + " V8 商用级完整闭环 - 端到端测试".center(58) + "║")
    print("╚" + "═" * 60 + "╝")

    tests = [
        ("平台模块导入完整性", test_platform_module_loading),
        ("FastAPI 应用 + 路由注册", test_fastapi_app_routes),
        ("前后端 API 映射", test_frontend_backend_mapping),
        ("GET 端点 TestClient 闭环", test_get_endpoints_via_testclient),
        ("创建→查询→删除 闭环", test_create_query_delete_loop),
        ("i18n 多语言闭环", test_i18n_loop),
        ("LLM 路由端点闭环", test_llm_router_loop),
        ("JNPF 表单引擎闭环", test_jnpf_loop),
        ("监控告警闭环", test_monitoring_loop),
        ("前端首页加载", test_frontend_homepage),
    ]

    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            record(f"[{name}] 测试本身异常", False, str(e)[:120])

    # 汇总
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    total = len(_results)
    passed = sum(1 for r in _results if r["ok"])
    failed = total - passed
    print(f"  通过: {passed}/{total}")
    if failed:
        print(f"  失败: {failed}")
        for r in _results:
            if not r["ok"]:
                print(f"    ❌ {r['name']} — {r['detail']}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
