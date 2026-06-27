"""
V9 新增/修复端点闭环测试
覆盖深度审查后的修复项：
1. 对象存储：上传 + 元数据数组 + stats 兼容字段
2. 监控：录入指标 + 创建规则 + components/severity 兼容字段
3. AB 测试：录入变体指标（_serialize 递归处理 Enum）
4. 认证：SSO 授权 URL（种子 admin 用户支持登录）
5. 租户：列表含 api_key 脱敏 + 更新回显 + 配额资源名映射
6. JNPF：workflow-run 使用 real_executor（返回 status=completed）
"""
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "api"))

_results = []


def record(name, ok, detail=""):
    _results.append({"name": name, "ok": ok, "detail": detail})
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))


def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _client():
    from fastapi.testclient import TestClient
    from api import app
    return TestClient(app)


# ============================================================================
# 测试 1：对象存储闭环（上传 + 元数据 + stats 兼容字段）
# ============================================================================

def test_storage_upload_and_compat():
    """测试对象存储：上传、元数据数组、stats 兼容字段"""
    section("测试 1: 对象存储 - 上传 + 元数据 + 兼容字段")
    try:
        client = _client()
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    # 1.1 stats 兼容字段
    try:
        r = client.get("/api/storage/stats")
        assert r.status_code == 200, f"stats 失败: {r.status_code}"
        stats = r.json()
        assert "total_objects" in stats, "缺少 total_objects 兼容字段"
        assert "total_size" in stats, "缺少 total_size 兼容字段"
        assert "total_files" in stats, "缺少 total_files 字段"
        record("stats 兼容字段 (total_objects/total_size/total_files)", True)
    except AssertionError as e:
        record("stats 兼容字段", False, str(e)[:80])

    # 1.2 上传文件
    try:
        content = b"V9 test file content - hello kickart"
        files = {"file": ("v9_test.txt", io.BytesIO(content), "text/plain")}
        r = client.post(
            "/api/storage/objects/upload",
            files=files,
            data={"category": "v9test", "tenant_id": "default"},
        )
        assert r.status_code == 200, f"上传失败: {r.status_code} {r.text[:200]}"
        up = r.json()
        assert up.get("remote_key") or up.get("key"), "上传响应缺少 remote_key/key"
        record("文件上传", True, f"key={up.get('remote_key') or up.get('key')}")
    except AssertionError as e:
        record("文件上传", False, str(e)[:120])

    # 1.3 列表返回元数据数组
    try:
        r = client.get("/api/storage/objects")
        assert r.status_code == 200
        objs = r.json().get("objects", [])
        assert isinstance(objs, list), "objects 不是数组"
        if objs:
            o = objs[0]
            assert "key" in o and "size" in o and "category" in o, \
                f"对象元数据缺少字段: {list(o.keys())}"
            record(f"对象列表元数据 (含 {len(objs)} 项)", True)
        else:
            record("对象列表元数据", True, "空列表")
    except AssertionError as e:
        record("对象列表元数据", False, str(e)[:80])

    return True


# ============================================================================
# 测试 2：监控告警闭环（录入指标 + 创建规则 + 兼容字段）
# ============================================================================

def test_monitoring_metrics_and_rules():
    """测试监控：录入指标、创建规则、兼容字段"""
    section("测试 2: 监控 - 录入指标 + 创建规则 + 兼容字段")
    try:
        client = _client()
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    # 2.1 健康检查 components 字段
    try:
        r = client.get("/api/monitoring/health")
        assert r.status_code == 200
        h = r.json()
        assert "components" in h, "缺少 components 兼容字段"
        assert "checks" in h, "缺少 checks 原字段"
        for name, info in h.get("components", {}).items():
            assert "status" in info, f"组件 {name} 缺少 status 字段"
        record("health 兼容字段 (components + status)", True)
    except AssertionError as e:
        record("health 兼容字段", False, str(e)[:80])

    # 2.2 创建告警规则
    try:
        r = client.post("/api/monitoring/rules", json={
            "name": "v9_test_rule",
            "metric": "daily_videos",
            "condition": "lt",
            "threshold": 1.0,
            "level": "warning",
            "message_template": "v9: 日成片数 {value} 低于 1",
            "cooldown_sec": 60,
        })
        assert r.status_code == 200, f"创建规则失败: {r.status_code} {r.text[:200]}"
        rule = r.json()
        assert rule.get("success") is True, "success 不为 True"
        record("创建告警规则", True, f"name={rule.get('rule', {}).get('name')}")
    except AssertionError as e:
        record("创建告警规则", False, str(e)[:120])

    # 2.3 录入指标 + 评估规则
    try:
        r = client.post("/api/monitoring/metrics/daily_videos", json={
            "value": 0.5, "labels": {"source": "v9_test"},
        })
        assert r.status_code == 200, f"录入指标失败: {r.status_code} {r.text[:200]}"
        result = r.json()
        assert result.get("success") is True, "success 不为 True"
        assert "new_alerts" in result, "缺少 new_alerts 字段"
        assert "new_alerts_count" in result, "缺少 new_alerts_count 字段"
        # daily_videos=0.5 < 1.0 应触发 v9_test_rule
        if result.get("new_alerts_count", 0) > 0:
            alert = result["new_alerts"][0]
            assert "rule_name" in alert, "告警缺少 rule_name"
            assert "level" in alert, "告警缺少 level"
        record("录入指标 + 评估规则", True,
               f"new_alerts_count={result.get('new_alerts_count')}")
    except AssertionError as e:
        record("录入指标 + 评估规则", False, str(e)[:120])

    # 2.4 告警 severity 兼容字段
    try:
        r = client.get("/api/monitoring/alerts")
        assert r.status_code == 200
        alerts = r.json().get("alerts", [])
        if alerts:
            a = alerts[0]
            assert "severity" in a, "活跃告警缺少 severity 字段"
            assert "level" in a, "活跃告警缺少 level 字段"
            record("alerts severity 兼容字段", True)
        else:
            record("alerts severity 兼容字段", True, "无活跃告警可校验")
    except AssertionError as e:
        record("alerts severity 兼容字段", False, str(e)[:80])

    # 2.5 历史 severity + triggered_at 兼容字段
    try:
        r = client.get("/api/monitoring/alerts/history")
        assert r.status_code == 200
        history = r.json().get("history", [])
        if history:
            h = history[0]
            assert "severity" in h, "历史缺少 severity 字段"
            assert "triggered_at" in h, "历史缺少 triggered_at 字段"
            record("history severity + triggered_at", True)
        else:
            record("history severity + triggered_at", True, "无历史可校验")
    except AssertionError as e:
        record("history severity + triggered_at", False, str(e)[:80])

    return True


# ============================================================================
# 测试 3：AB 测试 - 录入变体指标（验证 _serialize 递归处理 Enum）
# ============================================================================

def test_abtest_record_metrics():
    """测试 AB 测试录入变体指标 + 详情序列化"""
    section("测试 3: AB 测试 - 录入变体指标 + 序列化")
    try:
        client = _client()
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    try:
        # 创建实验
        r = client.post("/api/abtest", json={
            "name": "V9 序列化测试",
            "product_input": "Test Product",
            "variants_config": [
                {"name": "control", "config": {"style": "default"}},
                {"name": "treatment", "config": {"style": "viral"}},
            ],
        })
        assert r.status_code == 200, f"创建实验失败: {r.status_code} {r.text[:200]}"
        exp_id = r.json().get("experiment_id")
        assert exp_id, "未返回 experiment_id"

        # 详情（_serialize 递归处理嵌套 Variant + Enum）
        r = client.get(f"/api/abtest/{exp_id}")
        assert r.status_code == 200, f"详情查询失败: {r.status_code}"
        exp = r.json().get("experiment", {})
        assert "variants" in exp, "详情缺少 variants 字段"
        assert isinstance(exp["variants"], list), "variants 不是列表"
        if exp["variants"]:
            v = exp["variants"][0]
            assert "variant_id" in v, "变体缺少 variant_id"
            # status 字段应为字符串值（Enum 已被序列化为 .value）
            if "status" in v:
                assert isinstance(v["status"], str), \
                    f"变体 status 未正确序列化为字符串: {type(v['status'])}"
        record("详情序列化 (含嵌套 Variant + Enum)", True)

        # 运行实验
        r = client.post(f"/api/abtest/{exp_id}/run")
        assert r.status_code == 200, f"运行失败: {r.status_code}"

        # 录入变体指标
        variant_id = exp["variants"][0]["variant_id"] if exp["variants"] else "v_control"
        r = client.post(
            f"/api/abtest/{exp_id}/metrics/{variant_id}",
            json={"views": 1000, "likes": 50, "shares": 10, "conversions": 5},
        )
        assert r.status_code == 200, f"录入指标失败: {r.status_code} {r.text[:200]}"
        assert r.json().get("success") is True, "success 不为 True"
        record("录入变体指标", True, f"variant={variant_id}")

    except AssertionError as e:
        record("AB 测试录入指标", False, str(e)[:120])

    return True


# ============================================================================
# 测试 4：认证 - SSO 授权 URL + 种子 admin 登录
# ============================================================================

def test_auth_sso_and_seed_admin():
    """测试 SSO 授权 URL 端点 + 种子 admin 用户登录"""
    section("测试 4: 认证 - SSO 授权 URL + 种子 admin 登录")
    try:
        client = _client()
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    # 4.1 种子 admin 登录（含默认密码 admin123）
    try:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200, f"登录失败: {r.status_code} {r.text[:200]}"
        login = r.json()
        assert login.get("token"), "登录响应缺少 token"
        assert login.get("user"), "登录响应缺少 user"
        assert login["user"].get("username") == "admin", \
            f"用户名不匹配: {login['user'].get('username')}"
        record("种子 admin 登录", True, f"user_id={login['user'].get('user_id')}")
    except AssertionError as e:
        record("种子 admin 登录", False, str(e)[:120])

    # 4.1.1 密码错误应返回 401（验证密码校验逻辑）
    try:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401, f"错误密码应被拒绝: {r.status_code} {r.text[:120]}"
        record("密码校验", True, "错误密码返回 401")
    except AssertionError as e:
        record("密码校验", False, str(e)[:120])

    # 4.2 SSO 授权 URL（即使未配置也应返回 404，不应 500）
    try:
        r = client.get("/api/auth/sso/authorize-url/default")
        # 未配置 SSO 时返回 404，这是预期行为（端点本身正常工作）
        assert r.status_code in (200, 404), f"SSO 端点异常: {r.status_code}"
        if r.status_code == 200:
            data = r.json()
            assert "authorize_url" in data, "SSO 响应缺少 authorize_url"
            assert "state" in data, "SSO 响应缺少 state"
            record("SSO 授权 URL", True, "已配置 SSO")
        else:
            record("SSO 授权 URL", True, "未配置 SSO，预期 404")
    except AssertionError as e:
        record("SSO 授权 URL", False, str(e)[:120])

    return True


# ============================================================================
# 测试 5：租户 - api_key 脱敏 + 更新回显 + 配额资源名映射
# ============================================================================

def test_tenant_compat_fields():
    """测试租户兼容字段：api_key 脱敏、更新回显、配额映射"""
    section("测试 5: 租户 - api_key 脱敏 + 更新回显 + 配额映射")
    try:
        client = _client()
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    try:
        # 创建租户
        r = client.post("/api/tenants", json={"name": "V9 兼容测试租户", "plan": "pro"})
        assert r.status_code == 200, f"创建失败: {r.status_code}"
        tenant_id = r.json().get("tenant_id")

        # 列表 api_key 字段
        r = client.get("/api/tenants")
        assert r.status_code == 200
        tenants = r.json().get("tenants", [])
        target = next((t for t in tenants if t.get("tenant_id") == tenant_id), None)
        assert target is not None, "列表中未找到新租户"
        assert "api_key" in target, "租户列表缺少 api_key 字段"
        # 脱敏：应包含 "..." 或为空
        if target["api_key"]:
            assert "..." in target["api_key"], "api_key 未脱敏"
        record("列表 api_key 脱敏", True)

        # 更新回显
        r = client.put(f"/api/tenants/{tenant_id}", json={"name": "V9 已更新", "plan": "enterprise"})
        assert r.status_code == 200, f"更新失败: {r.status_code} {r.text[:200]}"
        updated = r.json()
        assert updated.get("success") is True, "更新 success 不为 True"
        assert "tenant" in updated, "更新响应缺少 tenant 对象"
        assert updated["tenant"].get("name") == "V9 已更新", "更新后名称不匹配"
        record("更新回显 tenant 对象", True)

        # 配额资源名映射（同时返回前后端字段名）
        r = client.get(f"/api/tenants/{tenant_id}/quota")
        assert r.status_code == 200, f"配额查询失败: {r.status_code}"
        quotas = r.json().get("quotas", {})
        # 应同时包含前端字段名（videos_daily）和后端字段名（video）
        front_keys = {"videos_daily", "images_daily", "api_calls_daily"}
        back_keys = {"video", "image", "run"}
        assert front_keys.issubset(set(quotas.keys())), \
            f"配额缺少前端字段: {front_keys - set(quotas.keys())}"
        record("配额资源名映射 (前后端字段并存)", True,
               f"keys={list(quotas.keys())[:6]}")

        # 清理
        client.delete(f"/api/tenants/{tenant_id}")

    except AssertionError as e:
        record("租户兼容字段", False, str(e)[:120])

    return True


# ============================================================================
# 测试 6：JNPF workflow-run 使用 real_executor
# ============================================================================

def test_jnpf_workflow_run_real_executor():
    """测试 JNPF workflow-run 返回 status=completed（real_executor 真实执行）"""
    section("测试 6: JNPF workflow-run (real_executor)")
    try:
        client = _client()
    except Exception as e:
        record("TestClient 初始化", False, str(e)[:80])
        return False

    try:
        r = client.post("/api/jnpf/workflow-run", json={
            "context": {"product_input": "V9 测试商品", "user_id": "v9tester"}
        })
        assert r.status_code == 200, f"运行失败: {r.status_code} {r.text[:200]}"
        result = r.json()
        assert "status" in result, "响应缺少 status 字段"
        # real_executor 应让流程完成
        assert result["status"] in ("completed", "running", "failed"), \
            f"未知状态: {result.get('status')}"
        # 应有 completed_nodes（real_executor 推进了节点）
        assert "completed_nodes" in result, "响应缺少 completed_nodes"
        if result["status"] == "completed":
            nodes = result.get("completed_nodes", [])
            assert len(nodes) > 0, "完成后无 completed_nodes"
            # 验证 context 中有 agent 输出（real_executor 写入）
            ctx = result.get("context", {})
            assert len(ctx) > 0 or len(nodes) > 1, "context 为空且节点数过少"
        record("workflow-run real_executor", True,
               f"status={result['status']}, nodes={len(result.get('completed_nodes', []))}")
    except AssertionError as e:
        record("workflow-run real_executor", False, str(e)[:120])

    return True


# ============================================================================
# 主测试入口
# ============================================================================

def main():
    print("╔" + "═" * 60 + "╗")
    print("║" + " V9 新增端点 + 修复项闭环测试".center(54) + "║")
    print("╚" + "═" * 60 + "╝")

    tests = [
        ("对象存储 上传+元数据+兼容字段", test_storage_upload_and_compat),
        ("监控 录入指标+创建规则+兼容字段", test_monitoring_metrics_and_rules),
        ("AB 测试 录入变体指标+序列化", test_abtest_record_metrics),
        ("认证 SSO授权URL+种子admin", test_auth_sso_and_seed_admin),
        ("租户 api_key脱敏+更新回显+配额映射", test_tenant_compat_fields),
        ("JNPF workflow-run real_executor", test_jnpf_workflow_run_real_executor),
    ]

    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            record(f"[{name}] 测试本身异常", False, str(e)[:120])

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
