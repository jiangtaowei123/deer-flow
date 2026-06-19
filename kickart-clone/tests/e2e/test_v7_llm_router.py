"""
V7 多提供商 LLM 路由层 - 端到端测试
测试覆盖：
1. 提供商注册表与元信息
2. 提供商实例化与可用性检查
3. 用途路由映射
4. 智能路由器（故障转移/轮询/熔断）
5. 用量统计
6. llm_creative.py 路由层接入
7. 配置文件完整性
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "llm"))


def test_provider_registry():
    """测试提供商注册表"""
    print("\n" + "=" * 60)
    print("测试 1: 提供商注册表与元信息")
    print("=" * 60)

    from providers import PROVIDER_REGISTRY, PURPOSE_PROVIDERS, list_providers, get_purposes

    # 1. 7 个提供商
    assert len(PROVIDER_REGISTRY) == 7, f"应有 7 个提供商，实际 {len(PROVIDER_REGISTRY)}"
    print(f"  ✅ 提供商总数: {len(PROVIDER_REGISTRY)}")

    # 2. 验证每个 Key 的用途
    assert PROVIDER_REGISTRY["deepseek_jnpf"].purpose == "jnpf_team"
    assert PROVIDER_REGISTRY["deepseek_ecommerce"].purpose == "cross_border_ecommerce"
    assert PROVIDER_REGISTRY["deepseek_aigc"].purpose == "aigc_marketing"
    assert PROVIDER_REGISTRY["glm_ecommerce"].purpose == "cross_border_ecommerce"
    assert PROVIDER_REGISTRY["ark_default"].purpose == "aigc_marketing"
    assert PROVIDER_REGISTRY["ark_backup"].purpose == "aigc_marketing"
    assert PROVIDER_REGISTRY["stability_image"].purpose == "image_generation"
    print(f"  ✅ 用途映射: 7 个 Key 全部正确")

    # 3. 模型清单
    assert "deepseek-v4-flash" in PROVIDER_REGISTRY["deepseek_jnpf"].models
    assert "glm-4.6" in PROVIDER_REGISTRY["glm_ecommerce"].models
    assert "doubao-pro-32k" in PROVIDER_REGISTRY["ark_default"].models
    print(f"  ✅ 模型清单: DeepSeek/GLM/Ark 模型齐全")

    # 4. 用途→提供商映射
    assert PURPOSE_PROVIDERS["jnpf_team"] == ["deepseek_jnpf"]
    assert "deepseek_ecommerce" in PURPOSE_PROVIDERS["cross_border_ecommerce"]
    assert "glm_ecommerce" in PURPOSE_PROVIDERS["cross_border_ecommerce"]
    assert len(PURPOSE_PROVIDERS["aigc_marketing"]) == 3  # deepseek_aigc + ark_default + ark_backup
    print(f"  ✅ 用途路由: jnpf(1) / ecommerce(2) / aigc(3) / image(1)")

    # 5. list_providers
    all_providers = list_providers()
    assert len(all_providers) == 7
    aigc_providers = list_providers(purpose="aigc_marketing")
    assert len(aigc_providers) == 3
    print(f"  ✅ list_providers: 全部 7 个，AIGC 3 个")

    # 6. get_purposes
    purposes = get_purposes()
    assert len(purposes) == 4
    purpose_names = [p["purpose"] for p in purposes]
    assert "jnpf_team" in purpose_names
    assert "image_generation" in purpose_names
    print(f"  ✅ get_purposes: {len(purposes)} 个用途")

    print("  🎉 提供商注册表测试通过")


def test_provider_instantiation():
    """测试提供商实例化"""
    print("\n" + "=" * 60)
    print("测试 2: 提供商实例化与可用性检查")
    print("=" * 60)

    from providers import create_provider, TextProvider, ImageProvider

    # 1. 创建文本提供商（无 Key）
    provider = create_provider("deepseek_jnpf")
    assert isinstance(provider, TextProvider)
    assert provider.meta.provider_id == "deepseek_jnpf"
    assert provider.model == "deepseek-v4-flash"  # 默认模型
    assert provider.is_available() is False  # 无 Key
    print(f"  ✅ DeepSeek 实例化: model={provider.model}, available={provider.is_available()}")

    # 2. 创建图片提供商
    img_provider = create_provider("stability_image")
    assert isinstance(img_provider, ImageProvider)
    assert img_provider.meta.provider_type == "image"
    print(f"  ✅ Stability 实例化: type=image")

    # 3. 传入 Key
    provider_with_key = create_provider("glm_ecommerce", api_key="test_key_123")
    assert provider_with_key.is_available() is True
    assert provider_with_key.api_key == "test_key_123"
    print(f"  ✅ 传入 Key: available={provider_with_key.is_available()}")

    # 4. 指定模型
    provider_model = create_provider("ark_default", api_key="test", model="doubao-pro-128k")
    assert provider_model.model == "doubao-pro-128k"
    print(f"  ✅ 指定模型: {provider_model.model}")

    # 5. 未知提供商
    try:
        create_provider("unknown_provider")
        assert False, "应抛出异常"
    except ValueError as e:
        assert "未知提供商" in str(e)
    print(f"  ✅ 未知提供商异常")

    # 6. 统计信息
    stats = provider_with_key.get_stats()
    assert stats["provider_id"] == "glm_ecommerce"
    assert stats["call_count"] == 0
    print(f"  ✅ 统计信息: {stats['name']}")

    print("  🎉 提供商实例化测试通过")


def test_router_routing():
    """测试智能路由器路由逻辑"""
    print("\n" + "=" * 60)
    print("测试 3: 智能路由器（故障转移/轮询/熔断）")
    print("=" * 60)

    from router import LLMRouter, RouteStrategy, CircuitBreaker
    from providers import PURPOSE_PROVIDERS

    # 使用显式 Key 创建路由器（不依赖环境变量）
    keys = {
        "deepseek_jnpf": "sk_test_jnpf",
        "deepseek_ecommerce": "sk_test_ecom",
        "deepseek_aigc": "sk_test_aigc",
        "glm_ecommerce": "glm_test",
        "ark_default": "ark_test_1",
        "ark_backup": "ark_test_2",
        "stability_image": "stab_test",
    }

    router = LLMRouter(strategy=RouteStrategy.FAILOVER, keys=keys)
    print(f"  ✅ 路由器创建: strategy=failover")

    # 1. 状态检查
    status = router.get_router_status()
    assert status["total_providers"] == 7
    assert status["available_providers"] == 7
    assert status["broken_providers"] == 0
    print(f"  ✅ 状态: {status['available_providers']}/{status['total_providers']} 可用")

    # 2. 可用提供商列表
    aigc_providers = router.get_available_providers(purpose="aigc_marketing")
    assert len(aigc_providers) == 3
    print(f"  ✅ AIGC 用途: {len(aigc_providers)} 个可用提供商")

    # 3. 候选选择（故障转移顺序）
    candidates = router._get_candidates("aigc_marketing")
    assert candidates[0] == "deepseek_aigc"  # 主
    assert "ark_default" in candidates
    assert "ark_backup" in candidates
    print(f"  ✅ 故障转移顺序: {candidates}")

    # 4. 偏好提供商
    candidates_pref = router._get_candidates("aigc_marketing", preferred="ark_default")
    assert candidates_pref[0] == "ark_default"
    print(f"  ✅ 偏好提供商: {candidates_pref[0]} 优先")

    # 5. 熔断器
    breaker = CircuitBreaker(failure_threshold=2, cooldown_sec=1)
    assert breaker.is_open("test") is False
    breaker.record_failure("test")
    assert breaker.is_open("test") is False  # 1 次不熔断
    breaker.record_failure("test")
    assert breaker.is_open("test") is True  # 2 次熔断
    breaker.record_success("test")
    assert breaker.is_open("test") is False  # 成功重置
    print(f"  ✅ 熔断器: 2 次失败熔断，成功重置")

    # 6. 轮询策略
    router_rr = LLMRouter(strategy=RouteStrategy.ROUND_ROBIN, keys=keys)
    ordered1 = router_rr._order_candidates(["a", "b", "c"], "test")
    ordered2 = router_rr._order_candidates(["a", "b", "c"], "test")
    assert ordered1[0] != ordered2[0]  # 轮询应该不同
    print(f"  ✅ 轮询策略: {ordered1[0]} → {ordered2[0]}")

    # 7. 最少使用策略
    router_lu = LLMRouter(strategy=RouteStrategy.LEAST_USED, keys=keys)
    ordered = router_lu._order_candidates(["a", "b", "c"], "test")
    assert len(ordered) == 3
    print(f"  ✅ 最少使用策略: {ordered}")

    print("  🎉 路由器路由逻辑测试通过")


def test_router_generate_mock():
    """测试路由器生成（mock 网络请求）"""
    print("\n" + "=" * 60)
    print("测试 4: 路由器生成（mock 网络）")
    print("=" * 60)

    from router import LLMRouter, RouteStrategy

    keys = {
        "deepseek_aigc": "sk_test",
        "ark_default": "ark_test",
        "ark_backup": "ark_test_2",
    }
    router = LLMRouter(strategy=RouteStrategy.FAILOVER, keys=keys)

    # 1. mock 成功生成
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "测试创意内容"}}],
        "usage": {"total_tokens": 50},
    }
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response):
        result = router.generate(
            system_prompt="测试系统",
            user_prompt="测试用户",
            purpose="aigc_marketing",
        )

    assert result["text"] == "测试创意内容"
    assert result["provider_id"] == "deepseek_aigc"  # 主提供商
    assert result["latency_ms"] >= 0
    print(f"  ✅ 成功生成: provider={result['provider_id']}, tokens={result['tokens']}")

    # 2. mock 故障转移（主失败，备用成功）
    call_count = [0]
    def mock_post_failover(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # 第一次（主）失败
            raise ConnectionError("主提供商不可用")
        # 第二次（备用）成功
        resp = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "备用生成内容"}}],
            "usage": {"total_tokens": 40},
        }
        resp.raise_for_status = MagicMock()
        return resp

    router2 = LLMRouter(strategy=RouteStrategy.FAILOVER, keys=keys)
    with patch("requests.post", side_effect=mock_post_failover):
        result = router2.generate(
            system_prompt="测试",
            user_prompt="测试",
            purpose="aigc_marketing",
        )

    assert result["text"] == "备用生成内容"
    assert result["provider_id"] != "deepseek_aigc"  # 不是主提供商
    print(f"  ✅ 故障转移: 主失败 → {result['provider_id']}")

    # 3. 全部失败
    router3 = LLMRouter(strategy=RouteStrategy.FAILOVER, keys=keys)
    with patch("requests.post", side_effect=ConnectionError("全部不可用")):
        result = router3.generate(
            system_prompt="测试",
            user_prompt="测试",
            purpose="aigc_marketing",
        )

    assert result["text"] == ""
    assert "所有提供商均失败" in result["error"]
    print(f"  ✅ 全部失败: {result['error'][:30]}...")

    # 4. 用量统计
    stats = router.get_usage_stats("provider_id")
    assert "deepseek_aigc" in stats
    assert stats["deepseek_aigc"]["total_calls"] >= 1
    print(f"  ✅ 用量统计: {stats['deepseek_aigc']['total_calls']} 次调用")

    # 5. 最近调用
    recent = router.get_recent_calls(5)
    assert len(recent) >= 1
    print(f"  ✅ 最近调用: {len(recent)} 条记录")

    print("  🎉 路由器生成测试通过")


def test_llm_creative_integration():
    """测试 llm_creative.py 路由层接入"""
    print("\n" + "=" * 60)
    print("测试 5: llm_creative.py 路由层接入")
    print("=" * 60)

    # 设置环境变量模拟 Key
    os.environ["DEEPSEEK_KEY_AIGC"] = "sk_test_aigc"
    os.environ["ARK_KEY_DEFAULT"] = "ark_test"

    # 添加必要路径（logger 在 observability 下）
    sys.path.insert(0, str(PROJECT_ROOT / "agents" / "creative" / "scripts"))
    sys.path.insert(0, str(PROJECT_ROOT / "platform" / "observability"))
    sys.path.insert(0, str(PROJECT_ROOT / "platform" / "llm"))

    # 重置路由器单例
    try:
        from router import reset_router
        reset_router()
    except ImportError:
        pass

    from llm_creative import (
        IntelligentCreativeGenerator, RouterProvider,
        OpenAIProvider, AnthropicProvider, LocalLLMProvider,
        LLMProvider,
    )

    # 1. RouterProvider 可用性
    rp = RouterProvider(purpose="aigc_marketing")
    assert rp.is_available() is True  # 有 Key
    print(f"  ✅ RouterProvider 可用: purpose={rp.purpose}")

    # 2. auto_select 优先路由层
    generator = IntelligentCreativeGenerator.auto_select(purpose="aigc_marketing")
    assert isinstance(generator.provider, RouterProvider)
    print(f"  ✅ auto_select: 优先路由层")

    # 3. 旧接口兼容（无 OPENAI_API_KEY 时不可用）
    openai = OpenAIProvider()
    assert openai.is_available() is False  # 无 Key
    print(f"  ✅ 旧接口兼容: OpenAIProvider 无 Key 不可用")

    # 4. mock 路由层生成
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"theme":"测试主题","scenes":[]}'}}],
        "usage": {"total_tokens": 30},
    }
    mock_response.raise_for_status = MagicMock()

    product_info = {"title": "测试商品", "description": "测试描述"}

    with patch("requests.post", return_value=mock_response):
        creative = generator.generate(product_info, num_scenes=3, style="viral")

    assert creative["generated_by"] == "llm"
    assert creative["router_used"] is True
    assert creative["purpose"] == "aigc_marketing"
    print(f"  ✅ 路由层生成: theme={creative.get('theme')}, router_used={creative['router_used']}")

    # 5. 统计
    stats = generator.get_stats()
    assert stats["llm_generated"] == 1
    assert stats["router_used"] is True
    print(f"  ✅ 统计: LLM={stats['llm_generated']}, router={stats['router_used']}")

    # 6. 模板回退（路由层失败时）
    # 清除 Key 使路由层不可用
    old_key = os.environ.pop("DEEPSEEK_KEY_AIGC", None)
    old_key2 = os.environ.pop("ARK_KEY_DEFAULT", None)

    from router import reset_router
    reset_router()

    generator_fallback = IntelligentCreativeGenerator.auto_select()
    creative_fallback = generator_fallback.generate(product_info, num_scenes=3)
    assert creative_fallback["generated_by"] == "template"
    print(f"  ✅ 模板回退: generated_by={creative_fallback['generated_by']}")

    # 恢复环境变量
    if old_key:
        os.environ["DEEPSEEK_KEY_AIGC"] = old_key
    if old_key2:
        os.environ["ARK_KEY_DEFAULT"] = old_key2

    print("  🎉 llm_creative 路由层接入测试通过")


def test_config_completeness():
    """测试配置文件完整性"""
    print("\n" + "=" * 60)
    print("测试 6: 配置文件完整性")
    print("=" * 60)

    # 1. .env.example 包含所有 Key
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DEEPSEEK_KEY_JNPF" in env_example
    assert "DEEPSEEK_KEY_ECOMMERCE" in env_example
    assert "DEEPSEEK_KEY_AIGC" in env_example
    assert "GLM_KEY_ECOMMERCE" in env_example
    assert "ARK_KEY_DEFAULT" in env_example
    assert "ARK_KEY_BACKUP" in env_example
    assert "STABILITY_KEY" in env_example
    print(f"  ✅ .env.example: 7 个 Key 全部配置")

    # 2. 路由策略配置
    assert "KICKART_LLM_STRATEGY" in env_example
    assert "KICKART_LLM_DEFAULT_PURPOSE" in env_example
    assert "KICKART_LLM_BREAKER_ENABLED" in env_example
    print(f"  ✅ .env.example: 路由策略配置齐全")

    # 3. config.py LLM 配置项
    config_content = (PROJECT_ROOT / "platform" / "observability" / "config.py").read_text(encoding="utf-8")
    assert "llm_strategy" in config_content
    assert "llm_default_purpose" in config_content
    assert "llm_breaker_enabled" in config_content
    assert "llm_breaker_threshold" in config_content
    assert "llm_default_temperature" in config_content
    print(f"  ✅ config.py: LLM 配置项齐全")

    # 4. Key 脱敏验证（.env.example 中的 Key 应该是脱敏的）
    # 检查不包含完整 Key 格式
    assert "sk-1bb...5947" in env_example  # 脱敏格式
    print(f"  ✅ Key 脱敏: .env.example 使用脱敏占位符")

    print("  🎉 配置文件完整性测试通过")


def test_purpose_isolation():
    """测试用途隔离"""
    print("\n" + "=" * 60)
    print("测试 7: 用途隔离验证")
    print("=" * 60)

    from router import LLMRouter
    from providers import PURPOSE_PROVIDERS

    keys = {
        "deepseek_jnpf": "sk_jnpf",
        "deepseek_ecommerce": "sk_ecom",
        "deepseek_aigc": "sk_aigc",
        "glm_ecommerce": "glm_key",
        "ark_default": "ark_1",
        "ark_backup": "ark_2",
        "stability_image": "stab_key",
    }
    router = LLMRouter(keys=keys)

    # 1. JNPF 团队用途只能用 deepseek_jnpf
    jnpf_candidates = router._get_candidates("jnpf_team")
    assert jnpf_candidates == ["deepseek_jnpf"]
    print(f"  ✅ JNPF 团队: 隔离到 {jnpf_candidates}")

    # 2. 跨境电商用途用 deepseek_ecommerce + glm_ecommerce
    ecom_candidates = router._get_candidates("cross_border_ecommerce")
    assert set(ecom_candidates) == {"deepseek_ecommerce", "glm_ecommerce"}
    print(f"  ✅ 跨境电商: 隔离到 {ecom_candidates}")

    # 3. AIGC 中台用 3 个 Key
    aigc_candidates = router._get_candidates("aigc_marketing")
    assert len(aigc_candidates) == 3
    print(f"  ✅ AIGC 中台: {len(aigc_candidates)} 个 Key")

    # 4. 图片生成隔离
    img_candidates = router._get_candidates("image_generation")
    assert img_candidates == ["stability_image"]
    print(f"  ✅ 图片生成: 隔离到 {img_candidates}")

    # 5. 默认用途 = AIGC
    default_candidates = router._get_candidates("default")
    assert len(default_candidates) == 3
    print(f"  ✅ 默认用途: 等同 AIGC 中台")

    print("  🎉 用途隔离测试通过")


def main():
    """运行所有 V7 测试"""
    print("=" * 60)
    print("V7 多提供商 LLM 路由层 - 端到端测试")
    print("=" * 60)

    tests = [
        ("提供商注册表", test_provider_registry),
        ("提供商实例化", test_provider_instantiation),
        ("路由器路由逻辑", test_router_routing),
        ("路由器生成(mock)", test_router_generate_mock),
        ("llm_creative 接入", test_llm_creative_integration),
        ("配置文件完整性", test_config_completeness),
        ("用途隔离", test_purpose_isolation),
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
    print(f"V7 测试结果: ✅ {passed} 通过, ❌ {failed} 失败")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
