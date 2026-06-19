"""
V6 企业级集成与生态深化 - 端到端测试
测试覆盖：
1. SSO 单点登录与权限矩阵
2. Webhook 事件订阅系统
3. JNPF6.2 深度集成（表单引擎+流程引擎+页面渲染）
4. 复利系统指令集扩展（模板继承+版本管理+组合编排）
5. 国际化 i18n 多语言
6. CI/CD 配置验证
7. 生态集成验证
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 添加项目根到 path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_sso():
    """测试 SSO 单点登录与权限矩阵"""
    print("\n" + "=" * 60)
    print("测试 1: SSO 单点登录与权限矩阵")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 动态导入（避免 platform 命名冲突）
        sso_path = PROJECT_ROOT / "platform" / "auth"
        sys.path.insert(0, str(sso_path))
        from sso import SSOManager, Permission, ROLE_PERMISSIONS, SSOTenantConfig

        mgr = SSOManager(storage_path=tmpdir, jwt_secret="test_secret_12345")

        # 1. 创建用户
        user = mgr.create_user("testuser", "test@example.com", "tenant_001", "creator")
        assert user.user_id.startswith("user_")
        assert user.role == "creator"
        print(f"  ✅ 用户创建: {user.username} ({user.role})")

        # 2. 创建会话
        session = mgr.create_session(user, ip_address="127.0.0.1")
        assert session.token
        assert session.refresh_token
        assert session.expires_at > time.time()
        print(f"  ✅ 会话创建: {session.session_id}")

        # 3. 验证令牌
        payload = mgr.verify_token(session.token)
        assert payload is not None
        assert payload["sub"] == user.user_id
        assert payload["role"] == "creator"
        print(f"  ✅ 令牌验证: {payload['username']}")

        # 4. 权限检查
        assert mgr.check_permission(user, Permission.CREATE_VIDEO) is True
        assert mgr.check_permission(user, Permission.MANAGE_TENANT) is False
        assert mgr.check_permission_by_token(session.token, Permission.CREATE_IMAGE) is True
        assert mgr.check_permission_by_token(session.token, Permission.SYSTEM_ADMIN) is False
        print(f"  ✅ 权限矩阵: creator 可创作，不可管理")

        # 5. 刷新令牌
        new_session = mgr.refresh_token(session.refresh_token)
        assert new_session is not None
        assert new_session.token != session.token
        print(f"  ✅ 令牌刷新成功")

        # 6. 角色升级
        mgr.update_user_role(user.user_id, "admin")
        user = mgr.get_user(user.user_id)
        assert user.role == "admin"
        assert mgr.check_permission(user, Permission.SYSTEM_ADMIN) is True
        print(f"  ✅ 角色升级: admin 拥有全部权限 ({len(ROLE_PERMISSIONS['admin'])} 项)")

        # 7. SSO 配置
        sso_config = SSOTenantConfig(
            tenant_id="tenant_001",
            provider="oidc",
            client_id="test_client",
            client_secret="test_secret",
            authorize_url="https://idp.example.com/authorize",
            token_url="https://idp.example.com/token",
            userinfo_url="https://idp.example.com/userinfo",
            redirect_uri="https://kickart.example.com/callback",
        )
        mgr.set_sso_config(sso_config)
        auth_url = mgr.build_authorize_url("tenant_001", "random_state")
        assert "client_id=test_client" in auth_url
        assert "response_type=code" in auth_url
        print(f"  ✅ SSO 授权 URL 生成")

        # 8. SSO 回调处理
        session = mgr.handle_sso_callback(
            "tenant_001",
            "fake_code",
            {"sub": "sso_123", "email": "sso_user@example.com", "name": "SSO用户"},
        )
        assert session is not None
        sso_user = mgr.find_user_by_sso("oidc", "sso_123")
        assert sso_user is not None
        assert sso_user.email == "sso_user@example.com"
        print(f"  ✅ SSO 回调: 自动创建用户 {sso_user.username}")

        # 9. 撤销会话
        assert mgr.revoke_session(session.session_id) is True
        print(f"  ✅ 会话撤销")

    print("  🎉 SSO 全部测试通过")


def test_webhook():
    """测试 Webhook 事件订阅系统"""
    print("\n" + "=" * 60)
    print("测试 2: Webhook 事件订阅系统")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        webhook_path = PROJECT_ROOT / "platform" / "webhook"
        sys.path.insert(0, str(webhook_path))
        from manager import WebhookManager, EventType

        mgr = WebhookManager(storage_path=tmpdir)

        # 1. 创建订阅
        sub = mgr.subscribe(
            tenant_id="tenant_001",
            url="http://localhost:19999/webhook",
            events=["workflow.completed", "workflow.failed"],
        )
        assert sub.subscription_id.startswith("sub_")
        assert sub.secret
        assert "workflow.completed" in sub.events
        print(f"  ✅ 订阅创建: {sub.subscription_id}")

        # 2. 通配符订阅
        sub2 = mgr.subscribe(
            tenant_id="tenant_001",
            url="http://localhost:19998/webhook",
            events=["*"],
        )
        assert "*" in sub2.events
        print(f"  ✅ 通配符订阅创建")

        # 3. 发布事件（会尝试投递，但 URL 不可达，进入死信）
        delivery_ids = mgr.publish(
            EventType.WORKFLOW_COMPLETED.value,
            {"run_id": "run_123", "video_path": "/tmp/video.mp4"},
            tenant_id="tenant_001",
        )
        # 两个订阅都匹配
        assert len(delivery_ids) == 2
        print(f"  ✅ 事件发布: 投递 {len(delivery_ids)} 个订阅")

        # 4. 检查投递状态（URL 不可达，应为 dead）
        time.sleep(0.1)  # 等待投递完成
        for did in delivery_ids:
            delivery = mgr.get_delivery(did)
            assert delivery is not None
            assert delivery["status"] in ("dead", "success", "pending")
        print(f"  ✅ 投递记录查询")

        # 5. 死信列表
        dead_letters = mgr.list_dead_letters()
        assert len(dead_letters) > 0
        print(f"  ✅ 死信队列: {len(dead_letters)} 条")

        # 6. 签名验证
        import hmac
        import hashlib
        payload = b'{"event":"test"}'
        secret = sub.secret
        signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert WebhookManager.verify_signature(payload, signature, secret) is True
        assert WebhookManager.verify_signature(payload, "sha256=wrong", secret) is False
        print(f"  ✅ 签名验证")

        # 7. 取消订阅
        assert mgr.unsubscribe(sub.subscription_id) is True
        assert mgr.unsubscribe(sub.subscription_id) is False
        print(f"  ✅ 取消订阅")

        # 8. 列出订阅
        subs = mgr.list_subscriptions("tenant_001")
        assert len(subs) == 1  # sub2 还在
        print(f"  ✅ 剩余订阅: {len(subs)} 个")

    print("  🎉 Webhook 全部测试通过")


def test_jnpf_deep_integration():
    """测试 JNPF6.2 深度集成"""
    print("\n" + "=" * 60)
    print("测试 3: JNPF6.2 深度集成（表单引擎+流程引擎+页面渲染）")
    print("=" * 60)

    jnpf_path = PROJECT_ROOT / "platform" / "jnpf"
    sys.path.insert(0, str(jnpf_path))
    from deep_integration import (
        JNPFDeepIntegration, FormEngine, FlowEngine, PageRenderer,
        FieldType, NodeType, FormFieldDef, FormFieldRule, FormSchema,
        FlowNode,
    )

    integration = JNPFDeepIntegration()

    # ============ 表单引擎 ============
    print("  --- 表单引擎 ---")

    # 1. 构建表单 Schema
    schema = integration.build_creative_form_schema()
    assert schema.form_id == "creative_form_v2"
    assert len(schema.fields) == 7
    print(f"  ✅ 表单 Schema: {len(schema.fields)} 个字段")

    # 2. 默认值填充
    data = integration.form_engine.apply_defaults(schema, {})
    assert data["workflow"] == "video"
    assert data["num_scenes"] == 6
    print(f"  ✅ 默认值填充: workflow={data['workflow']}, num_scenes={data['num_scenes']}")

    # 3. 表单校验 - 通过
    data = integration.form_engine.apply_defaults(schema, {"input_value": "https://amazon.com/dp/B0TEST"})
    result = integration.form_engine.validate(schema, data)
    assert result["valid"] is True
    print(f"  ✅ 表单校验通过")

    # 4. 表单校验 - 失败（缺少必填）
    result = integration.form_engine.validate(schema, {"workflow": "video"})
    assert result["valid"] is False
    assert "input_value" in result["errors"]
    print(f"  ✅ 表单校验失败检测: {result['errors']}")

    # 5. 联动规则评估
    states = integration.form_engine.evaluate_rules(schema, {"workflow": "image"})
    assert states["voice"]["visible"] is False
    assert states["enable_tts"]["visible"] is False
    print(f"  ✅ 联动规则: image 模式隐藏 voice/enable_tts")

    states = integration.form_engine.evaluate_rules(schema, {"workflow": "video"})
    assert states["voice"]["visible"] is True
    print(f"  ✅ 联动规则: video 模式显示 voice")

    # 6. 序列化
    serialized = integration.form_engine.serialize(schema)
    assert serialized["form_id"] == "creative_form_v2"
    assert len(serialized["fields"]) == 7
    print(f"  ✅ 表单序列化")

    # ============ 流程引擎 ============
    print("  --- 流程引擎 ---")

    # 7. 注册流程
    wf_id = integration.register_default_workflow()
    assert wf_id == "kickart_creative_v2"
    workflow = integration.flow_engine.workflows[wf_id]
    assert len(workflow["nodes"]) == 11
    print(f"  ✅ 流程注册: {len(workflow['nodes'])} 个节点")

    # 8. 运行流程 - video 模式
    def mock_executor(node, ctx):
        return {"node": node.node_id, "agent": node.agent, "status": "done"}

    instance = integration.flow_engine.run(wf_id, {"workflow": "video"}, mock_executor)
    assert instance.status == "completed"
    assert "start" in instance.completed_nodes
    assert "end" in instance.completed_nodes
    print(f"  ✅ 流程执行 (video): {instance.status}, 完成 {len(instance.completed_nodes)} 节点")

    # 9. 运行流程 - image 模式（走不同分支）
    instance = integration.flow_engine.run(wf_id, {"workflow": "image"}, mock_executor)
    assert instance.status == "completed"
    assert "generate_images" in instance.completed_nodes
    assert "compose_video" not in instance.completed_nodes
    print(f"  ✅ 流程执行 (image): 走 image 分支")

    # 10. 运行流程 - storyboard 模式
    instance = integration.flow_engine.run(wf_id, {"workflow": "storyboard"}, mock_executor)
    assert instance.status == "completed"
    assert "generate_storyboard" in instance.completed_nodes
    assert "generate_images" not in instance.completed_nodes
    print(f"  ✅ 流程执行 (storyboard): 直接结束")

    # ============ 页面渲染 ============
    print("  --- 页面渲染 ---")

    # 11. 渲染页面
    page_def = {
        "page_id": "dashboard",
        "name": "工作台",
        "type": "dashboard",
        "title": "Kickart 营销创作工作台",
        "description": "一站式营销素材/视频创作平台",
        "components": [
            {"type": "stat_card", "field": "daily_videos", "label": "日成片数"},
            {"type": "stat_card", "field": "daily_assets", "label": "日素材数"},
            {"type": "table", "fields": ["run_id", "status", "created_at"]},
            {"type": "submit_button", "label": "开始创作", "action": "POST /orchestrate"},
        ],
        "api_bindings": {"list": "GET /orchestrate"},
    }
    html = integration.page_renderer.render(page_def, "zh-CN")
    assert "<!DOCTYPE html>" in html
    assert "Kickart 营销创作工作台" in html
    assert "日成片数" in html
    assert "stat-card" in html
    print(f"  ✅ 页面渲染: {len(html)} 字符 HTML")

    print("  🎉 JNPF 深度集成全部测试通过")


def test_compound_extension():
    """测试复利系统指令集扩展"""
    print("\n" + "=" * 60)
    print("测试 4: 复利系统指令集扩展（模板继承+版本管理+组合编排）")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        compound_path = PROJECT_ROOT / "platform" / "compound"
        sys.path.insert(0, str(compound_path))
        from extension import (
            CompoundSystemExtension, AssetTemplateManager,
            AssetVersionManager, CompositionEngine,
            AssetRelation, EXTENDED_TEMPLATES,
        )

        ext = CompoundSystemExtension(base_storage=tmpdir)

        # ============ 模板管理 ============
        print("  --- 模板管理 ---")

        # 1. 创建模板
        tpl = ext.template_mgr.create_template(
            name="测试创意模板",
            description="测试用模板",
            asset_type="template",
            template_content={
                "id": "creative_{uuid}",
                "theme": "{theme}",
                "audience": "{audience}",
                "scenes": [],
            },
            params_schema={
                "theme": {"type": "string", "required": True},
                "audience": {"type": "string", "default": "general"},
            },
        )
        assert tpl.template_id.startswith("tpl_")
        print(f"  ✅ 模板创建: {tpl.name}")

        # 2. 实例化模板
        instance = ext.template_mgr.instantiate(tpl.template_id, {"theme": "夏日清凉"})
        assert instance["content"]["theme"] == "夏日清凉"
        assert instance["content"]["audience"] == "general"  # 默认值
        print(f"  ✅ 模板实例化: theme={instance['content']['theme']}")

        # 3. 模板继承
        child = ext.template_mgr.inherit(
            tpl.template_id,
            "子模板-冬季温暖",
            {"template_content": {"theme": "冬季温暖"}},  # 这个会被合并
            description="继承测试",
        )
        # 注意：inherit 的 overrides 是合并到 template_content
        assert child.parent_template == tpl.template_id
        print(f"  ✅ 模板继承: {child.name} ← {tpl.name}")

        # 4. 使用计数
        assert tpl.use_count == 1  # 实例化过一次
        print(f"  ✅ 使用计数: {tpl.use_count}")

        # ============ 版本管理 ============
        print("  --- 版本管理 ---")

        # 5. 创建版本
        v1 = ext.version_mgr.create_version("asset_001", "1.0.0", "/tmp/asset_v1.json", "初始版本")
        v2 = ext.version_mgr.create_version("asset_001", "1.1.0", "/tmp/asset_v1_1.json", "新增场景")
        v3 = ext.version_mgr.create_version("asset_001", "2.0.0", "/tmp/asset_v2.json", "重大更新")
        assert v1.version_id.startswith("ver_")
        print(f"  ✅ 版本创建: 3 个版本")

        # 6. 版本历史
        versions = ext.version_mgr.get_versions("asset_001")
        assert len(versions) == 3
        assert versions[-1]["version"] == "2.0.0"
        print(f"  ✅ 版本历史: {len(versions)} 个版本")

        # 7. 最新版本
        latest = ext.version_mgr.get_latest_version("asset_001")
        assert latest.version == "2.0.0"
        print(f"  ✅ 最新版本: v{latest.version}")

        # 8. 资产关系
        ext.version_mgr.add_relation("asset_002", AssetRelation.DEPENDS_ON, "asset_001")
        ext.version_mgr.add_relation("asset_003", AssetRelation.INHERITS, "asset_001")
        relations = ext.version_mgr.get_relations("asset_001")
        assert len(relations) == 2
        dependents = ext.version_mgr.get_dependents("asset_001")
        assert "asset_002" in dependents
        print(f"  ✅ 资产关系: {len(relations)} 条，依赖者: {dependents}")

        # ============ 组合编排 ============
        print("  --- 组合编排 ---")

        # 9. 管道执行（无 instruction_engine，使用 mock）
        pipeline = [
            {
                "instruction": "generate.creative",
                "params": {"product_info": {"title": "测试商品"}},
                "output_key": "creative",
            },
            {
                "instruction": "generate.storyboard",
                "params": {},
                "input_mapping": {"creative": "creative.creative"},
                "output_key": "storyboard",
            },
        ]
        result = ext.composition_engine.execute_pipeline(pipeline)
        assert result["success"] is True
        assert len(result["results"]) == 2
        print(f"  ✅ 管道执行: {len(result['results'])} 步成功")

        # 10. 并行执行
        instructions = [
            {"instruction": "generate.creative", "params": {"product_info": {"title": "A"}}, "name": "creative_a"},
            {"instruction": "generate.creative", "params": {"product_info": {"title": "B"}}, "name": "creative_b"},
            {"instruction": "generate.creative", "params": {"product_info": {"title": "C"}}, "name": "creative_c"},
        ]
        result = ext.composition_engine.execute_parallel(instructions)
        assert result["success"] is True
        assert result["total"] == 3
        print(f"  ✅ 并行执行: {result['total']} 个指令")

        # 11. DAG 执行
        nodes_def = [
            {"node_id": "n1", "instruction": "generate.creative", "params": {"product_info": {"title": "X"}}, "output_name": "creative"},
            {"node_id": "n2", "instruction": "generate.images", "params": {}, "output_name": "images"},
            {"node_id": "n3", "instruction": "generate.video", "params": {}, "input_mapping": {"creative": "creative.creative", "images": "images.images_dir"}, "output_name": "video"},
        ]
        edges_def = [
            {"from": "n1", "to": "n2"},
            {"from": "n1", "to": "n3"},
            {"from": "n2", "to": "n3"},
        ]
        dag = ext.composition_engine.build_dag("test_dag", nodes_def, edges_def)
        result = ext.composition_engine.execute_dag(dag)
        assert result["success"] is True
        assert result["node_count"] == 3
        print(f"  ✅ DAG 执行: {result['node_count']} 个节点")

        # 12. 扩展指令模板验证
        assert "template.create" in EXTENDED_TEMPLATES
        assert "template.instantiate" in EXTENDED_TEMPLATES
        assert "template.inherit" in EXTENDED_TEMPLATES
        assert "asset.reuse" in EXTENDED_TEMPLATES
        assert "asset.version" in EXTENDED_TEMPLATES
        assert "asset.derive" in EXTENDED_TEMPLATES
        assert "compose.dag" in EXTENDED_TEMPLATES
        assert "compose.parallel" in EXTENDED_TEMPLATES
        assert "compose.pipeline" in EXTENDED_TEMPLATES
        print(f"  ✅ 扩展指令模板: {len(EXTENDED_TEMPLATES)} 条")

    print("  🎉 复利系统扩展全部测试通过")


def test_i18n():
    """测试国际化 i18n"""
    print("\n" + "=" * 60)
    print("测试 5: 国际化 i18n 多语言")
    print("=" * 60)

    i18n_path = PROJECT_ROOT / "platform" / "i18n"
    sys.path.insert(0, str(i18n_path))
    from translator import Translator, Language

    tr = Translator()

    # 1. 支持的语言
    langs = tr.get_supported_languages()
    assert len(langs) == 3
    codes = [l["code"] for l in langs]
    assert Language.ZH_CN in codes
    assert Language.EN_US in codes
    assert Language.JA_JP in codes
    print(f"  ✅ 支持语言: {[l['native'] for l in langs]}")

    # 2. 中文翻译
    tr.set_language(Language.ZH_CN)
    assert tr.t("common.success") == "成功"
    assert tr.t("nav.dashboard") == "工作台"
    assert tr.t("workflow.video") == "完整视频"
    print(f"  ✅ 中文: {tr.t('nav.dashboard')} / {tr.t('workflow.video')}")

    # 3. 英文翻译
    tr.set_language(Language.EN_US)
    assert tr.t("common.success") == "Success"
    assert tr.t("nav.dashboard") == "Dashboard"
    assert tr.t("workflow.video") == "Full Video"
    print(f"  ✅ 英文: {tr.t('nav.dashboard')} / {tr.t('workflow.video')}")

    # 4. 日文翻译
    tr.set_language(Language.JA_JP)
    assert tr.t("common.success") == "成功"
    assert tr.t("nav.dashboard") == "ダッシュボード"
    print(f"  ✅ 日文: {tr.t('nav.dashboard')} / {tr.t('workflow.video')}")

    # 5. 参数插值
    tr.set_language(Language.ZH_CN)
    result = tr.t("common.welcome", name="张三")
    assert "张三" in result
    print(f"  ✅ 参数插值: {result}")

    # 6. 错误信息插值
    result = tr.t("error.quota_exceeded", resource="视频", current=10, limit=5)
    assert "视频" in result
    assert "10" in result
    assert "5" in result
    print(f"  ✅ 错误插值: {result}")

    # 7. 回退到默认语言
    tr.set_language(Language.JA_JP)
    tr.add_translation("test.key", Language.ZH_CN, "测试")
    # 日文没有，回退到中文
    result = tr.t("test.key")
    assert result == "测试"
    print(f"  ✅ 语言回退: {result}")

    # 8. 导出翻译
    tr.set_language(Language.EN_US)
    exported = tr.export_translations(Language.EN_US)
    assert "common.success" in exported
    assert exported["common.success"] == "Success"
    print(f"  ✅ 导出翻译: {len(exported)} 个键")

    # 9. 翻译键列表
    keys = tr.list_keys()
    assert len(keys) > 30
    print(f"  ✅ 翻译键: {len(keys)} 个")

    print("  🎉 i18n 全部测试通过")


def test_cicd_config():
    """测试 CI/CD 配置"""
    print("\n" + "=" * 60)
    print("测试 6: CI/CD pipeline 配置")
    print("=" * 60)

    # 1. GitHub Actions 配置存在
    ci_yml = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_yml.exists(), "ci.yml 不存在"
    content = ci_yml.read_text(encoding="utf-8")
    assert "name: CI/CD Pipeline" in content
    assert "lint:" in content
    assert "test:" in content
    assert "security:" in content
    assert "build:" in content
    assert "deploy:" in content
    print(f"  ✅ GitHub Actions: 5 个 job（lint/test/security/build/deploy）")

    # 2. CI 脚本存在
    ci_sh = PROJECT_ROOT / "scripts" / "ci.sh"
    assert ci_sh.exists(), "ci.sh 不存在"
    assert os.access(ci_sh, os.X_OK), "ci.sh 不可执行"
    script_content = ci_sh.read_text(encoding="utf-8")
    assert "run_lint" in script_content
    assert "run_test" in script_content
    assert "run_security" in script_content
    assert "run_build" in script_content
    print(f"  ✅ CI 脚本: 可执行，含 4 个阶段")

    # 3. 矩阵测试配置
    assert "matrix:" in content
    assert "3.10" in content
    assert "3.11" in content
    assert "3.12" in content
    print(f"  ✅ 矩阵测试: Python 3.10/3.11/3.12")

    # 4. Docker 构建配置
    assert "docker/build-push-action" in content
    assert "cache-from" in content
    assert "cache-to" in content
    print(f"  ✅ Docker 构建: 含缓存")

    # 5. 安全扫描
    assert "bandit" in content
    assert "safety" in content
    print(f"  ✅ 安全扫描: bandit + safety")

    # 6. 测试覆盖所有版本
    for version in ["test_workflow.py", "test_v1_workflow.py", "test_v2_workflow.py",
                    "test_v3_workflow.py", "test_v4_workflow.py", "test_v5_workflow.py",
                    "test_v6_workflow.py"]:
        assert version in content, f"CI 未包含 {version}"
    print(f"  ✅ 测试覆盖: MVP ~ V6 全部版本")

    print("  🎉 CI/CD 配置全部测试通过")


def test_ecosystem_integration():
    """测试生态集成验证"""
    print("\n" + "=" * 60)
    print("测试 7: 生态集成验证（JNPF + 复利 + SSO + Webhook + i18n 联动）")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 验证各模块可独立导入
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "auth"))
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "webhook"))
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "jnpf"))
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "compound"))
        sys.path.insert(0, str(PROJECT_ROOT / "platform" / "i18n"))

        from sso import SSOManager, Permission
        from manager import WebhookManager, EventType
        from deep_integration import JNPFDeepIntegration
        from extension import CompoundSystemExtension
        from translator import Translator, Language

        print(f"  ✅ 所有 V6 模块导入成功")

        # 1. SSO + JNPF 联动：权限控制表单访问
        sso_mgr = SSOManager(storage_path=f"{tmpdir}/sso", jwt_secret="eco_secret")
        user = sso_mgr.create_user("ecouser", "eco@example.com", "tenant_eco", "creator")
        session = sso_mgr.create_session(user)

        integration = JNPFDeepIntegration()
        schema = integration.build_creative_form_schema()

        # creator 有权创建视频
        can_create = sso_mgr.check_permission_by_token(session.token, Permission.CREATE_VIDEO)
        assert can_create is True
        print(f"  ✅ SSO + JNPF: creator 可访问创作表单")

        # 2. JNPF + 复利系统：流程执行产生资产
        ext = CompoundSystemExtension(base_storage=f"{tmpdir}/compound")
        wf_id = integration.register_default_workflow()

        def executor(node, ctx):
            # 每个节点执行后累积资产
            ext.version_mgr.create_version(
                f"asset_{node.node_id}",
                "1.0.0",
                f"/tmp/{node.node_id}.json",
                f"节点 {node.name} 产出",
            )
            return {"node": node.node_id, "status": "done"}

        instance = integration.flow_engine.run(wf_id, {"workflow": "video"}, executor)
        assert instance.status == "completed"

        # 验证资产累积
        assets = ext.version_mgr.get_versions("asset_parse_product")
        assert len(assets) == 1
        print(f"  ✅ JNPF + 复利: 流程执行累积 {len(instance.completed_nodes)} 个资产版本")

        # 3. Webhook + JNPF：流程完成触发事件
        webhook_mgr = WebhookManager(storage_path=f"{tmpdir}/webhooks")
        webhook_mgr.subscribe("tenant_eco", "http://localhost:19997/wh", ["workflow.completed"])

        delivery_ids = webhook_mgr.publish(
            EventType.WORKFLOW_COMPLETED.value,
            {
                "instance_id": instance.instance_id,
                "workflow_id": wf_id,
                "completed_nodes": instance.completed_nodes,
            },
            tenant_id="tenant_eco",
        )
        assert len(delivery_ids) == 1
        print(f"  ✅ Webhook + JNPF: 流程完成事件已发布")

        # 4. i18n + JNPF：多语言表单
        tr = Translator()
        tr.set_language(Language.EN_US)
        en_name = schema.name_i18n.get(Language.EN_US, schema.name)
        assert en_name == "Creative Form"
        print(f"  ✅ i18n + JNPF: 表单多语言（{en_name}）")

        # 5. 复利系统 + 模板：模板化资产生成
        tpl = ext.template_mgr.create_template(
            name="生态测试模板",
            description="生态集成测试",
            asset_type="template",
            template_content={"id": "{id}", "name": "{name}"},
            params_schema={
                "id": {"type": "string", "required": True},
                "name": {"type": "string", "required": True},
            },
        )
        inst = ext.template_mgr.instantiate(tpl.template_id, {"id": "eco_001", "name": "生态资产"})
        assert inst["content"]["id"] == "eco_001"
        print(f"  ✅ 复利 + 模板: 资产模板化生成")

        # 6. 全链路验证
        print(f"\n  📊 全链路验证:")
        print(f"     SSO 用户: {user.username} ({user.role})")
        print(f"     JNPF 流程: {instance.workflow_id} → {instance.status}")
        print(f"     完成节点: {len(instance.completed_nodes)}")
        print(f"     累积资产: {len(ext.version_mgr.versions)} 个")
        print(f"     Webhook 事件: {len(delivery_ids)} 个投递")
        print(f"     i18n 语言: {tr.get_language()}")

    print("  🎉 生态集成全部测试通过")


def main():
    """运行所有 V6 测试"""
    print("=" * 60)
    print("V6 企业级集成与生态深化 - 端到端测试")
    print("=" * 60)

    tests = [
        ("SSO 单点登录", test_sso),
        ("Webhook 事件订阅", test_webhook),
        ("JNPF 深度集成", test_jnpf_deep_integration),
        ("复利系统扩展", test_compound_extension),
        ("国际化 i18n", test_i18n),
        ("CI/CD 配置", test_cicd_config),
        ("生态集成", test_ecosystem_integration),
    ]

    passed = 0
    failed = 0
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"V6 测试结果: ✅ {passed} 通过, ❌ {failed} 失败")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
