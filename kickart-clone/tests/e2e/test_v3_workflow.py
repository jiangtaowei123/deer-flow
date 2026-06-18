"""
V3 端到端测试 - 平台化
测试 JNPF6.2 适配层、复利系统指令集、多租户、监控告警
"""
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "jnpf"))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "compound"))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "tenant"))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "monitoring"))


def test_jnpf_adapter():
    """测试 1: JNPF6.2 适配层"""
    print("\n" + "=" * 60)
    print("🔧 测试 1: JNPF6.2 适配层")
    print("=" * 60)

    from adapter import JNPFAdapter

    with tempfile.TemporaryDirectory(prefix="v3_jnpf_") as work_dir:
        adapter = JNPFAdapter(output_dir=work_dir)

        # 测试应用清单
        manifest = adapter.get_app_manifest()
        assert manifest["app_id"] == "kickart-clone"
        assert manifest["platform"]["platform"] == "JNPF6.2"
        assert manifest["platform"]["version"] == "6.2.0"
        print(f"  ✅ 应用清单: {manifest['name']} v{manifest['version']}")
        print(f"  ✅ 平台: {manifest['platform']['platform']} {manifest['platform']['version']}")

        # 测试表单
        creative_form = adapter.get_creative_form()
        assert creative_form["form_id"] == "creative_form"
        assert len(creative_form["fields"]) >= 5
        field_names = [f["field"] for f in creative_form["fields"]]
        assert "input_value" in field_names
        assert "workflow" in field_names
        print(f"  ✅ 创意表单: {len(creative_form['fields'])} 个字段")

        # 测试数据模型
        models = adapter.get_data_models()
        assert len(models) == 4
        model_tables = [m["table"] for m in models]
        assert "kickart_products" in model_tables
        assert "kickart_creatives" in model_tables
        assert "kickart_storyboards" in model_tables
        assert "kickart_videos" in model_tables
        print(f"  ✅ 数据模型: {len(models)} 个表")

        # 测试流程定义
        workflow = adapter.get_workflow_definition()
        assert workflow["workflow_id"] == "kickart_creative_workflow"
        assert len(workflow["nodes"]) >= 7
        node_types = [n["node_type"] for n in workflow["nodes"]]
        assert "start" in node_types
        assert "task" in node_types
        assert "decision" in node_types
        assert "end" in node_types
        print(f"  ✅ 流程定义: {len(workflow['nodes'])} 个节点")

        # 测试页面
        pages = adapter.get_pages()
        assert len(pages) == 4
        page_types = [p["type"] for p in pages]
        assert "dashboard" in page_types
        assert "form" in page_types
        assert "detail" in page_types
        assert "list" in page_types
        print(f"  ✅ 页面定义: {len(pages)} 个页面")

        # 测试 API 注册
        apis = adapter.get_api_registry()
        assert len(apis) >= 6
        api_paths = [a["path"] for a in apis]
        assert "/orchestrate" in api_paths
        assert "/orchestrate/sync" in api_paths
        print(f"  ✅ API 注册: {len(apis)} 个端点")

        # 测试完整配置导出
        config = adapter.export_full_config()
        assert "manifest" in config
        assert "forms" in config
        assert "data_models" in config
        assert "workflows" in config
        assert "pages" in config
        assert "api_registry" in config

        config_file = Path(work_dir) / "jnpf_config.json"
        assert config_file.exists(), "配置文件应已保存"
        print(f"  ✅ 配置导出: {config_file}")

    return True


def test_compound_instructions():
    """测试 2: 复利系统指令集"""
    print("\n" + "=" * 60)
    print("📦 测试 2: 复利系统指令集")
    print("=" * 60)

    from instruction_set import CompoundInstructionEngine, INSTRUCTION_TEMPLATES

    with tempfile.TemporaryDirectory(prefix="v3_compound_") as work_dir:
        engine = CompoundInstructionEngine(registry_path=work_dir)

        # 测试指令清单
        instructions = engine.list_instructions()
        assert len(instructions) >= 8
        inst_names = [i["instruction"] for i in instructions]
        assert "generate.creative" in inst_names
        assert "generate.storyboard" in inst_names
        assert "generate.video" in inst_names
        assert "clone.kickart" in inst_names
        assert "compose.workflow" in inst_names
        assert "integrate.jnpf" in inst_names
        print(f"  ✅ 指令清单: {len(instructions)} 条指令")

        # 测试单条指令执行
        result = engine.execute("generate.creative", {
            "product_info": {
                "title": "Summer Dress",
                "description": "优雅夏季连衣裙",
                "category": "apparel",
            },
            "num_scenes": 4,
        })
        assert result["success"], f"创意生成失败: {result.get('error')}"
        assert "creative" in result
        assert "asset_path" in result
        print(f"  ✅ 单条指令执行: generate.creative → {result['creative']['creative_id']}")

        # 测试资产累积
        assets = engine.list_assets()
        assert len(assets) >= 1
        print(f"  ✅ 资产累积: {len(assets)} 个资产")

        # 测试资产复用
        if assets:
            asset_id = assets[0]["asset_id"]
            reuse_result = engine.reuse_asset(asset_id)
            assert reuse_result["success"]
            assert reuse_result["reuse_count"] == 1
            print(f"  ✅ 资产复用: {asset_id} (复用 {reuse_result['reuse_count']} 次)")

        # 测试指令链执行
        chain_result = engine.execute_chain("compose.workflow", {
            "input_value": "优雅夏季连衣裙",
            "product_info": {
                "title": "Summer Dress",
                "description": "优雅夏季连衣裙",
                "category": "apparel",
            },
        })
        assert chain_result["success"], f"指令链失败"
        assert len(chain_result["steps"]) >= 2
        print(f"  ✅ 指令链执行: {len(chain_result['steps'])} 步")

        # 验证资产注册表持久化
        registry_file = Path(work_dir) / "assets.json"
        assert registry_file.exists(), "资产注册表应已保存"
        print(f"  ✅ 注册表持久化: {registry_file}")

    return True


def test_tenant_management():
    """测试 3: 多租户支持"""
    print("\n" + "=" * 60)
    print("🏢 测试 3: 多租户支持")
    print("=" * 60)

    from manager import TenantManager, PLAN_QUOTAS

    with tempfile.TemporaryDirectory(prefix="v3_tenant_") as work_dir:
        manager = TenantManager(storage_path=work_dir)

        # 测试创建租户
        tenant = manager.create_tenant("测试公司A", "free")
        assert tenant.tenant_id.startswith("tenant_")
        assert tenant.api_key.startswith("kk_")
        assert tenant.plan == "free"
        assert "daily_videos" in tenant.quota
        print(f"  ✅ 创建租户: {tenant.name} ({tenant.plan})")
        print(f"     API Key: {tenant.api_key[:20]}...")

        # 测试创建不同套餐
        pro_tenant = manager.create_tenant("Pro公司B", "pro")
        ent_tenant = manager.create_tenant("企业C", "enterprise")
        assert pro_tenant.quota["daily_videos"] > tenant.quota["daily_videos"]
        assert ent_tenant.quota["daily_videos"] > pro_tenant.quota["daily_videos"]
        print(f"  ✅ 套餐配额: free={tenant.quota['daily_videos']}, "
              f"pro={pro_tenant.quota['daily_videos']}, "
              f"enterprise={ent_tenant.quota['daily_videos']}")

        # 测试 API Key 鉴权
        authenticated = manager.authenticate(tenant.api_key)
        assert authenticated is not None
        assert authenticated.tenant_id == tenant.tenant_id
        print(f"  ✅ API Key 鉴权: 成功")

        # 测试无效 API Key
        invalid = manager.authenticate("kk_invalid")
        assert invalid is None
        print(f"  ✅ 无效 Key 拒绝: 成功")

        # 测试配额检查
        quota = manager.check_quota(tenant.tenant_id, "video")
        assert quota["allowed"] is True
        assert quota["limit"] == 3  # free 套餐
        print(f"  ✅ 配额检查: video {quota['current']}/{quota['limit']}")

        # 测试用量记录
        manager.record_usage(tenant.tenant_id, "video")
        manager.record_usage(tenant.tenant_id, "video")
        quota_after = manager.check_quota(tenant.tenant_id, "video")
        assert quota_after["current"] == 2
        print(f"  ✅ 用量记录: video {quota_after['current']}/{quota_after['limit']}")

        # 测试 Agent 访问控制
        assert manager.check_agent_access(tenant.tenant_id, "product_parser") is True
        assert manager.check_agent_access(tenant.tenant_id, "video_gen") is False  # free 不含
        assert manager.check_agent_access(pro_tenant.tenant_id, "video_gen") is True
        print(f"  ✅ Agent 访问控制: free 无 video_gen, pro 有 video_gen")

        # 测试资源隔离
        workspace = manager.get_tenant_workspace(tenant.tenant_id)
        output_dir = manager.get_tenant_output_dir(tenant.tenant_id)
        assert tenant.tenant_id in workspace
        assert tenant.tenant_id in output_dir
        assert os.path.exists(workspace)
        assert os.path.exists(output_dir)
        print(f"  ✅ 资源隔离: {tenant.tenant_id} 专属目录")

        # 测试租户列表
        tenants = manager.list_tenants()
        assert len(tenants) == 3
        print(f"  ✅ 租户列表: {len(tenants)} 个租户")

        # 测试持久化
        tenants_file = Path(work_dir) / "tenants.json"
        assert tenants_file.exists(), "租户数据应已保存"
        print(f"  ✅ 持久化: {tenants_file}")

    return True


def test_monitoring():
    """测试 4: 监控告警"""
    print("\n" + "=" * 60)
    print("📊 测试 4: 监控告警")
    print("=" * 60)

    from monitor import MonitoringSystem, AlertLevel, AlertStatus

    with tempfile.TemporaryDirectory(prefix="v3_monitor_") as work_dir:
        monitor = MonitoringSystem(storage_path=work_dir)

        # 测试默认规则
        rules = monitor.list_rules()
        assert len(rules) >= 6
        rule_names = [r["name"] for r in rules]
        assert "agent_success_rate_low" in rule_names
        assert "e2e_latency_high" in rule_names
        print(f"  ✅ 默认规则: {len(rules)} 条")

        # 测试指标采集
        monitor.record_metric("daily_videos", 8)
        monitor.record_metric("agent_success_rate", 0.98)
        monitor.record_metric("e2e_latency", 250)

        latest = monitor.get_metric_latest("daily_videos")
        assert latest == 8
        print(f"  ✅ 指标采集: daily_videos = {latest}")

        # 测试平均值
        monitor.record_metric("daily_videos", 12)
        avg = monitor.get_metric_avg("daily_videos")
        assert avg == 10  # (8+12)/2
        print(f"  ✅ 指标平均: daily_videos avg = {avg}")

        # 测试告警触发（低成功率）
        monitor.record_metric("agent_success_rate", 0.70)  # 低于 0.80 critical
        alerts = monitor.evaluate_rules()
        critical_alerts = [a for a in alerts if a.level == AlertLevel.CRITICAL]
        assert len(critical_alerts) >= 1
        active = monitor.get_active_alerts()
        assert len(active) >= 1
        print(f"  ✅ 告警触发: {len(alerts)} 个新告警, {len(active)} 个活跃")

        # 测试告警恢复
        monitor.record_metric("agent_success_rate", 0.99)  # 恢复正常
        monitor.evaluate_rules()
        active_after = monitor.get_active_alerts()
        assert len(active_after) < len(active)
        print(f"  ✅ 告警恢复: 活跃 {len(active)} → {len(active_after)}")

        # 测试告警历史
        history = monitor.get_alert_history()
        assert len(history) >= 1
        print(f"  ✅ 告警历史: {len(history)} 条")

        # 测试健康检查
        health = monitor.health_check()
        assert "status" in health
        assert "checks" in health
        assert "api_server" in health["checks"]
        assert "ffmpeg" in health["checks"]
        print(f"  ✅ 健康检查: {health['status']}")
        for check_name, check in health["checks"].items():
            status = "✅" if check["healthy"] else "❌"
            print(f"     {status} {check_name}: {check['message'][:40]}")

        # 测试仪表盘
        dashboard = monitor.get_dashboard()
        assert "health" in dashboard
        assert "metrics" in dashboard
        assert "active_alerts" in dashboard
        print(f"  ✅ 仪表盘: {len(dashboard['metrics'])} 个指标, {len(dashboard['active_alerts'])} 个告警")

    return True


def test_platform_integration():
    """测试 5: 平台集成（JNPF + 复利 + 租户 + 监控）"""
    print("\n" + "=" * 60)
    print("🌐 测试 5: 平台集成")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="v3_integration_") as work_dir:
        work_dir = Path(work_dir)

        # 1. 创建租户
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "tenant"))
        from manager import TenantManager
        tenant_mgr = TenantManager(storage_path=str(work_dir / "tenants"))
        tenant = tenant_mgr.create_tenant("集成测试公司", "pro")

        # 2. 初始化监控
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "monitoring"))
        from monitor import MonitoringSystem
        monitor = MonitoringSystem(storage_path=str(work_dir / "monitoring"))

        # 3. 通过复利指令集执行创作
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "compound"))
        from instruction_set import CompoundInstructionEngine
        engine = CompoundInstructionEngine(
            registry_path=str(work_dir / "tenants" / tenant.tenant_id / "assets")
        )

        # 4. JNPF 适配层
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "jnpf"))
        from adapter import JNPFAdapter
        adapter = JNPFAdapter(output_dir=str(work_dir / "tenants" / tenant.tenant_id / "jnpf"))

        # 执行流程
        # a. 导出 JNPF 配置
        jnpf_config = adapter.export_full_config()
        assert jnpf_config["manifest"]["app_id"] == "kickart-clone"
        print(f"  ✅ JNPF 配置导出")

        # b. 执行复利指令
        result = engine.execute("generate.creative", {
            "product_info": {
                "title": "Integration Test Product",
                "description": "集成测试商品",
                "category": "generic",
            },
            "num_scenes": 4,
        })
        assert result["success"]
        print(f"  ✅ 复利指令执行: generate.creative")

        # c. 记录监控指标
        monitor.record_metric("daily_videos", 1)
        monitor.record_metric("agent_success_rate", 1.0)
        monitor.record_metric("e2e_latency", 30)
        print(f"  ✅ 监控指标记录")

        # d. 检查租户配额
        quota = tenant_mgr.check_quota(tenant.tenant_id, "video")
        assert quota["allowed"]
        print(f"  ✅ 租户配额检查: video {quota['current']}/{quota['limit']}")

        # e. 健康检查
        health = monitor.health_check()
        print(f"  ✅ 平台健康: {health['status']}")

        # f. 仪表盘汇总
        dashboard = monitor.get_dashboard()
        assert dashboard["metrics"]["daily_videos"] == 1
        assert dashboard["metrics"]["agent_success_rate"] == 1.0
        print(f"  ✅ 仪表盘汇总: {dashboard['metrics']['daily_videos']} 视频, "
              f"成功率 {dashboard['metrics']['agent_success_rate']}")

    print(f"\n  🎉 平台集成测试通过！")
    print(f"     JNPF6.2 + 复利指令集 + 多租户 + 监控告警 协同工作正常")
    return True


def main():
    print("\n" + "=" * 60)
    print("🚀 V3 端到端测试：平台化")
    print("=" * 60)

    tests = [
        ("JNPF6.2 适配层", test_jnpf_adapter),
        ("复利系统指令集", test_compound_instructions),
        ("多租户支持", test_tenant_management),
        ("监控告警", test_monitoring),
        ("平台集成", test_platform_integration),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed, None))
        except Exception as e:
            results.append((name, False, str(e)))
            import traceback
            traceback.print_exc()

    # 汇总
    print("\n" + "=" * 60)
    print("📊 测试汇总")
    print("=" * 60)

    passed = sum(1 for _, p, _ in results if p)
    total = len(results)

    for name, p, err in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"  {status} - {name}")
        if not p and err:
            print(f"           错误: {err[:80]}")

    print(f"\n  总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！V3 平台化阶段就绪。")
        print("\n📋 平台化能力总结:")
        print("   - JNPF6.2 适配: 表单/数据模型/流程/页面/API 注册")
        print("   - 复利系统指令集: 8 条指令 + 指令链 + 资产累积")
        print("   - 多租户: 3 级套餐 + API Key 鉴权 + 资源隔离")
        print("   - 监控告警: 指标采集 + 6 条规则 + 健康检查 + 仪表盘")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit(main())
