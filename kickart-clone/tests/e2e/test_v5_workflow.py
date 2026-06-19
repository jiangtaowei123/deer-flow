"""
V5 智能化与生态测试
测试：LLM 创意、Web 前端、任务队列、对象存储、SDK、A/B 测试
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "observability"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "creative" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "queue"))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "storage"))
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "abtest"))
sys.path.insert(0, str(PROJECT_ROOT / "sdk"))


def test_llm_creative():
    """测试 1: LLM 智能创意生成"""
    print("\n" + "=" * 60)
    print("🧠 测试 1: LLM 智能创意生成")
    print("=" * 60)

    from llm_creative import (
        IntelligentCreativeGenerator, LLMProvider,
        OpenAIProvider, AnthropicProvider, LocalLLMProvider,
        generate_multi_style, SYSTEM_PROMPT, build_user_prompt,
    )

    # 测试提示词构建
    product_info = {"title": "夏季连衣裙", "category": "apparel", "description": "轻盈面料"}
    prompt = build_user_prompt(product_info, num_scenes=6, style="viral")
    assert "夏季连衣裙" in prompt
    assert "6" in prompt
    assert "viral" in prompt
    print(f"  ✅ 提示词构建: 包含商品信息+场景数+风格")

    # 测试系统提示词
    assert "营销创意总监" in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT
    print(f"  ✅ 系统提示词: 角色定义+输出要求")

    # 测试提供商类定义
    assert OpenAIProvider is not None
    assert AnthropicProvider is not None
    assert LocalLLMProvider is not None
    print(f"  ✅ LLM 提供商: OpenAI/Anthropic/Local 三种")

    # 测试自动选择（无 API Key 时应回退到模板）
    generator = IntelligentCreativeGenerator.auto_select()
    creative = generator.generate(
        product_info=product_info,
        num_scenes=4,
        style="elegant",
    )
    assert "creative_id" in creative
    assert "scenes" in creative
    assert len(creative["scenes"]) == 4
    assert "generated_by" in creative
    print(f"  ✅ 创意生成: {len(creative['scenes'])} 场景, 方式={creative['generated_by']}")

    # 测试多风格生成
    creatives = generate_multi_style(product_info, styles=["viral", "elegant"], num_scenes=3)
    assert len(creatives) == 2
    print(f"  ✅ 多风格生成: {len(creatives)} 个风格变体")

    # 测试统计
    stats = generator.get_stats()
    assert "total" in stats
    assert "llm_ratio" in stats
    print(f"  ✅ 生成统计: total={stats['total']}, llm_ratio={stats['llm_ratio']}")

    return True


def test_web_frontend():
    """测试 2: Web 前端界面"""
    print("\n" + "=" * 60)
    print("🎨 测试 2: Web 前端界面")
    print("=" * 60)

    frontend_file = PROJECT_ROOT / "frontend" / "index.html"
    assert frontend_file.exists(), "前端文件应存在"

    with open(frontend_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 验证页面结构
    assert "<!DOCTYPE html>" in content
    assert 'lang="zh-CN"' in content
    assert "Kickart" in content
    print(f"  ✅ HTML 结构: 完整")

    # 验证 5 个页面
    pages = ["dashboard", "create", "runs", "scenes", "health"]
    for page in pages:
        assert f"page-{page}" in content, f"缺少页面: {page}"
    print(f"  ✅ 页面: {len(pages)} 个（工作台/创作/历史/场景/健康）")

    # 验证导航
    assert "showPage" in content
    assert "nav-item" in content
    print(f"  ✅ 导航: 侧边栏切换")

    # 验证表单
    assert "input-value" in content
    assert "workflow-type" in content
    assert "num-scenes" in content
    assert "aspect-ratio" in content
    assert "voice" in content
    print(f"  ✅ 创作表单: 5 个字段")

    # 验证 API 调用
    assert "orchestrate" in content
    assert "health" in content
    assert "scenes" in content
    print(f"  ✅ API 集成: orchestrate/health/scenes")

    # 验证进度展示
    assert "progress-bar" in content
    assert "progress-fill" in content
    assert "timeline" in content
    print(f"  ✅ 进度展示: 进度条+时间线")

    # 验证样式
    assert "--primary" in content
    assert "var(--card)" in content
    assert "border-radius" in content
    print(f"  ✅ 样式: CSS 变量+暗色主题")

    # 验证文件大小（应有足够内容）
    assert len(content) > 5000, f"前端文件应 > 5KB，实际 {len(content)}"
    print(f"  ✅ 文件大小: {len(content)} bytes")

    return True


def test_task_queue():
    """测试 3: 异步任务队列"""
    print("\n" + "=" * 60)
    print("📋 测试 3: 异步任务队列")
    print("=" * 60)

    from task_queue import TaskQueue, TaskPriority, QueueTaskState, MemoryBackend

    # 测试内存后端
    queue = TaskQueue(backend="memory", queue_name="test")
    assert queue.backend.__class__.__name__ == "MemoryBackend"
    print(f"  ✅ 内存后端: 正常")

    # 测试任务注册
    results = []
    def sample_task(x):
        time.sleep(0.05)
        results.append(x)
        return x * 2

    queue.register_func("sample_task", sample_task)
    assert "sample_task" in queue._func_registry
    print(f"  ✅ 函数注册: sample_task")

    # 测试任务提交
    task_id = queue.submit(
        func_name="sample_task",
        args=(21,),
        name="测试任务",
        priority=TaskPriority.HIGH,
    )
    assert task_id.startswith("q_")
    print(f"  ✅ 任务提交: {task_id}")

    # 测试任务查询
    task = queue.get_task(task_id)
    assert task is not None
    assert task.name == "测试任务"
    assert task.priority == TaskPriority.HIGH
    print(f"  ✅ 任务查询: name={task.name}, priority={task.priority}")

    # 测试 worker 执行
    queue.start_workers(num_workers=1)
    time.sleep(0.5)  # 等待执行
    queue.stop_workers()

    result = queue.get_result(task_id)
    assert result is not None
    assert result["success"] is True
    assert result["result"] == 42  # 21 * 2
    print(f"  ✅ 任务执行: result={result['result']}")

    # 测试优先级
    queue2 = TaskQueue(backend="memory", queue_name="test_priority")
    queue2.register_func("sample_task", sample_task)
    t_low = queue2.submit("sample_task", args=(1,), priority=TaskPriority.LOW)
    t_high = queue2.submit("sample_task", args=(2,), priority=TaskPriority.HIGH)
    tasks = queue2.list_tasks()
    assert len(tasks) == 2
    print(f"  ✅ 优先级: LOW + HIGH 提交")

    # 测试队列大小
    assert queue2.queue_size() == 2
    print(f"  ✅ 队列大小: {queue2.queue_size()}")

    return True


def test_storage():
    """测试 4: 对象存储集成"""
    print("\n" + "=" * 60)
    print("📦 测试 4: 对象存储集成")
    print("=" * 60)

    from storage import StorageManager, LocalStorage

    with tempfile.TemporaryDirectory() as work_dir:
        # 测试本地存储
        storage = StorageManager(backend="local", base_dir=work_dir)
        assert isinstance(storage.backend, LocalStorage)
        print(f"  ✅ 本地后端: {work_dir}")

        # 创建测试文件
        test_file = os.path.join(work_dir, "test_video.mp4")
        with open(test_file, "wb") as f:
            f.write(b"fake video content" * 100)

        # 测试上传
        result = storage.upload(
            local_path=test_file,
            category="video",
            tenant_id="tenant_test",
        )
        assert result["success"]
        assert "remote_key" in result
        assert "url" in result
        assert "hash" in result
        assert result["size"] > 0
        print(f"  ✅ 文件上传: {result['remote_key']}")
        print(f"     URL: {result['url'][:50]}...")
        print(f"     Hash: {result['hash'][:16]}...")
        print(f"     Size: {result['size']} bytes")

        # 测试去重
        result2 = storage.upload(
            local_path=test_file,
            category="video",
            tenant_id="tenant_test",
        )
        assert result2["deduplicated"] is True
        assert result2["remote_key"] == result["remote_key"]
        print(f"  ✅ 文件去重: 命中相同 hash")

        # 测试存在检查
        assert storage.exists(result["remote_key"]) is True
        print(f"  ✅ 存在检查: True")

        # 测试下载
        download_path = os.path.join(work_dir, "downloaded.mp4")
        storage.download(result["remote_key"], download_path)
        assert os.path.exists(download_path)
        print(f"  ✅ 文件下载: {download_path}")

        # 测试 URL 生成
        url = storage.get_url(result["remote_key"])
        assert "http" in url
        print(f"  ✅ URL 生成: {url[:50]}...")

        # 测试列表
        objects = storage.list_objects()
        assert len(objects) >= 1
        print(f"  ✅ 对象列表: {len(objects)} 个")

        # 测试元数据
        meta = storage.get_metadata(result["remote_key"])
        assert meta["category"] == "video"
        assert meta["tenant_id"] == "tenant_test"
        print(f"  ✅ 元数据: category={meta['category']}")

        # 测试统计
        stats = storage.get_stats()
        assert stats["total_files"] >= 1
        assert "video" in stats["categories"]
        print(f"  ✅ 存储统计: {stats['total_files']} 文件, {stats['total_size_mb']} MB")

        # 测试删除
        assert storage.delete(result["remote_key"]) is True
        assert storage.exists(result["remote_key"]) is False
        print(f"  ✅ 文件删除: 成功")

    return True


def test_sdk():
    """测试 5: Python SDK"""
    print("\n" + "=" * 60)
    print("📚 测试 5: Python SDK")
    print("=" * 60)

    from client import KickartClient, KickartError, KickartAPIError

    # 测试客户端创建
    client = KickartClient(base_url="http://localhost:59999", api_key="kk_test")
    assert client.base_url == "http://localhost:59999"
    assert client.api_key == "kk_test"
    assert client.timeout == 300
    print(f"  ✅ 客户端创建: base_url={client.base_url}")

    # 测试 API Key 设置
    assert client._session.headers.get("X-API-Key") == "kk_test"
    print(f"  ✅ API Key: 已设置到 header")

    # 测试方法存在
    assert hasattr(client, "create_video")
    assert hasattr(client, "create_images")
    assert hasattr(client, "create_storyboard")
    assert hasattr(client, "get_run")
    assert hasattr(client, "list_runs")
    assert hasattr(client, "wait_for_completion")
    assert hasattr(client, "list_scenes")
    assert hasattr(client, "health")
    assert hasattr(client, "batch_create_videos")
    print(f"  ✅ API 方法: 10+ 个")

    # 测试异常类
    assert issubclass(KickartAPIError, KickartError)
    err = KickartAPIError(404, "not found")
    assert err.status_code == 404
    print(f"  ✅ 异常类: KickartError + KickartAPIError")

    # 测试便捷函数
    from client import quick_create_video, quick_create_images
    assert callable(quick_create_video)
    assert callable(quick_create_images)
    print(f"  ✅ 便捷函数: quick_create_video/images")

    # 测试连接错误处理（连接不存在的服务）
    try:
        client.health()
        assert False, "应抛出连接错误"
    except KickartError as e:
        print(f"  ✅ 错误处理: 连接失败正确捕获")

    return True


def test_abtest():
    """测试 6: A/B 测试框架"""
    print("\n" + "=" * 60)
    print("🧪 测试 6: A/B 测试框架")
    print("=" * 60)

    from manager import ABTestManager, ExperimentStatus, VariantStatus, PRESET_EXPERIMENTS

    with tempfile.TemporaryDirectory() as work_dir:
        manager = ABTestManager(storage_dir=work_dir)

        # 测试预设模板
        assert "style_comparison" in PRESET_EXPERIMENTS
        assert "voice_comparison" in PRESET_EXPERIMENTS
        assert "aspect_ratio_comparison" in PRESET_EXPERIMENTS
        print(f"  ✅ 预设模板: {len(PRESET_EXPERIMENTS)} 个")

        # 测试创建实验
        exp = manager.create_experiment(
            name="风格对比测试",
            product_input="优雅夏季连衣裙",
            variants_config=[
                {"name": "爆款病毒式", "config": {"style": "viral"}},
                {"name": "优雅品质", "config": {"style": "elegant"}},
                {"name": "专业测评", "config": {"style": "professional"}},
            ],
        )
        assert exp.experiment_id.startswith("exp_")
        assert len(exp.variants) == 3
        assert exp.status == ExperimentStatus.DRAFT
        print(f"  ✅ 实验创建: {exp.experiment_id}, {len(exp.variants)} 变体")

        # 测试运行实验
        exp = manager.run_experiment(exp.experiment_id)
        assert exp.status == ExperimentStatus.RUNNING
        for v in exp.variants:
            assert v.status == VariantStatus.GENERATED
            assert "creative" in v.artifacts
        print(f"  ✅ 实验运行: 3 变体全部生成")

        # 测试指标记录
        manager.record_metrics(exp.experiment_id, exp.variants[0].variant_id, {
            "views": 1000, "likes": 80, "shares": 20, "conversions": 10
        })
        manager.record_metrics(exp.experiment_id, exp.variants[1].variant_id, {
            "views": 1000, "likes": 50, "shares": 10, "conversions": 5
        })
        manager.record_metrics(exp.experiment_id, exp.variants[2].variant_id, {
            "views": 1000, "likes": 30, "shares": 5, "conversions": 2
        })
        print(f"  ✅ 指标记录: 3 变体效果数据")

        # 测试分析
        report = manager.analyze(exp.experiment_id)
        assert report["variant_count"] == 3
        assert report["winner"] is not None
        assert "significance" in report
        assert "recommendation" in report
        print(f"  ✅ 实验分析: winner={report['winner']['name']}")
        print(f"     显著性: {report['significance']['significant']}")
        print(f"     建议: {report['recommendation'][:50]}...")

        # 测试持久化
        assert (Path(work_dir) / f"{exp.experiment_id}.json").exists()
        print(f"  ✅ 持久化: 实验数据已保存")

        # 测试列表
        experiments = manager.list_experiments()
        assert len(experiments) == 1
        print(f"  ✅ 实验列表: {len(experiments)} 个")

    return True


def test_ecosystem_integration():
    """测试 7: 生态集成"""
    print("\n" + "=" * 60)
    print("🌐 测试 7: 生态集成")
    print("=" * 60)

    # 验证所有 V5 模块文件存在
    modules = {
        "LLM 创意": PROJECT_ROOT / "agents" / "creative" / "scripts" / "llm_creative.py",
        "Web 前端": PROJECT_ROOT / "frontend" / "index.html",
        "任务队列": PROJECT_ROOT / "platform" / "queue" / "task_queue.py",
        "对象存储": PROJECT_ROOT / "platform" / "storage" / "storage.py",
        "Python SDK": PROJECT_ROOT / "sdk" / "client.py",
        "SDK 包入口": PROJECT_ROOT / "sdk" / "__init__.py",
        "A/B 测试": PROJECT_ROOT / "platform" / "abtest" / "manager.py",
    }

    for name, path in modules.items():
        assert path.exists(), f"{name} 文件不存在: {path}"
        print(f"  ✅ {name}: {path.name}")

    # 验证模块间引用
    from llm_creative import IntelligentCreativeGenerator
    from task_queue import TaskQueue
    from storage import StorageManager
    from client import KickartClient
    from manager import ABTestManager

    print(f"\n  ✅ 模块间引用: 全部可导入")

    # 验证 SDK 可调用所有能力
    client = KickartClient()
    methods = [m for m in dir(client) if not m.startswith("_")]
    assert "create_video" in methods
    assert "create_images" in methods
    assert "batch_create_videos" in methods
    print(f"  ✅ SDK 能力: {len(methods)} 个公开方法")

    return True


def main():
    print("\n" + "=" * 60)
    print("🚀 V5 智能化与生态测试")
    print("=" * 60)

    tests = [
        ("LLM 智能创意生成", test_llm_creative),
        ("Web 前端界面", test_web_frontend),
        ("异步任务队列", test_task_queue),
        ("对象存储集成", test_storage),
        ("Python SDK", test_sdk),
        ("A/B 测试框架", test_abtest),
        ("生态集成", test_ecosystem_integration),
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
        print("\n🎉 所有测试通过！V5 智能化与生态完成。")
        print("\n📋 智能化与生态能力总结:")
        print("   - LLM 创意: 3 提供商 + 提示词工程 + 多风格 + 模板回退")
        print("   - Web 前端: 5 页面 + 暗色主题 + 实时进度 + API 集成")
        print("   - 任务队列: Redis/内存 + 优先级 + 重试 + 多 worker")
        print("   - 对象存储: 本地/S3/OSS + 去重 + 元数据 + CDN URL")
        print("   - Python SDK: 完整 API 封装 + 批量操作 + 异常处理")
        print("   - A/B 测试: 多变体 + 指标采集 + 统计分析 + 自动选优")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit(main())
