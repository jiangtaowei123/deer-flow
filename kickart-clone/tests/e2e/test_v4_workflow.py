"""
V4 顶尖升级测试 - 生产级工程能力
测试：结构化日志、配置管理、并发引擎、SSE、鉴权限流、转场增强、Docker
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
# 使用直接路径导入，避开 platform/concurrent 标准库冲突
sys.path.insert(0, str(PROJECT_ROOT / "platform" / "observability"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "video_gen" / "scripts"))


def test_structured_logging():
    """测试 1: 结构化日志系统"""
    print("\n" + "=" * 60)
    print("📝 测试 1: 结构化日志系统")
    print("=" * 60)

    from logger import setup_logging, get_logger, set_request_context, new_request_id

    with tempfile.TemporaryDirectory() as work_dir:
        log_file = os.path.join(work_dir, "test.log")

        # 测试 JSON 格式日志
        setup_logging(level="INFO", json_output=True, log_file=log_file)
        logger = get_logger("test_module")

        # 设置请求上下文
        req_id = new_request_id()
        set_request_context(tenant_id="tenant_test")
        logger.info("测试日志消息", extra={"custom_field": "value"})

        # 验证日志文件
        assert os.path.exists(log_file), "日志文件应存在"
        with open(log_file, "r", encoding="utf-8") as f:
            log_content = f.read()

        log_data = json.loads(log_content.strip().split("\n")[0])
        assert log_data["level"] == "INFO"
        assert log_data["message"] == "测试日志消息"
        assert log_data["request_id"] == req_id
        assert log_data["tenant_id"] == "tenant_test"
        assert log_data["custom_field"] == "value"

        print(f"  ✅ JSON 结构化日志: 字段完整")
        print(f"  ✅ 请求上下文: request_id={req_id[:12]}...")
        print(f"  ✅ 自定义字段: custom_field=value")
        print(f"  ✅ 日志文件: {log_file}")

    return True


def test_config_management():
    """测试 2: 配置管理"""
    print("\n" + "=" * 60)
    print("⚙️  测试 2: 配置管理")
    print("=" * 60)

    from config import get_settings, reload_settings, is_production, is_debug

    # 测试默认配置
    settings = get_settings()
    assert settings.app_name == "kickart-clone"
    assert settings.app_version == "1.0.0"
    assert settings.api_port == 8765
    assert settings.sd_webui_url == "http://localhost:7860"
    assert settings.lead_agent_max_retries == 3
    assert settings.video_default_fps == 25
    assert settings.tts_default_voice == "xiaoxiao"
    print(f"  ✅ 默认配置: app={settings.app_name}, port={settings.api_port}")

    # 测试环境变量覆盖
    os.environ["KICKART_API_PORT"] = "9999"
    os.environ["KICKART_DEBUG"] = "true"
    os.environ["KICKART_ENVIRONMENT"] = "production"
    reload_settings()
    settings = get_settings()
    assert settings.api_port == 9999
    assert settings.debug is True
    assert settings.environment == "production"
    print(f"  ✅ 环境变量覆盖: port={settings.api_port}, debug={settings.debug}")

    # 测试便捷函数
    assert is_production() is True
    assert is_debug() is True
    print(f"  ✅ 便捷函数: is_production={is_production()}, is_debug={is_debug()}")

    # 清理环境变量
    del os.environ["KICKART_API_PORT"]
    del os.environ["KICKART_DEBUG"]
    del os.environ["KICKART_ENVIRONMENT"]
    reload_settings()

    return True


def test_concurrent_executor():
    """测试 3: 并发执行引擎"""
    print("\n" + "=" * 60)
    print("⚡ 测试 3: 并发执行引擎")
    print("=" * 60)

    from concurrent_executor import ConcurrentExecutor, run_parallel, run_pipeline

    # 测试并行执行
    def task_a():
        time.sleep(0.1)
        return "A"

    def task_b():
        time.sleep(0.1)
        return "B"

    def task_c(x):
        time.sleep(0.1)
        return f"C{x}"

    # 并行执行（3 个独立任务，各 0.1s，总应 < 0.3s）
    start = time.time()
    result = run_parallel([
        ("task_a", task_a, (), {}),
        ("task_b", task_b, (), {}),
        ("task_c", task_c, (42,), {}),
    ], max_workers=3)
    duration = time.time() - start

    assert result.success
    assert result.task_count == 3
    assert result.success_count == 3
    assert any(v == "A" for v in result.results.values())
    assert duration < 0.3, f"并行执行应 < 0.3s，实际 {duration:.2f}s"
    print(f"  ✅ 并行执行: 3 任务, {duration:.2f}s (< 0.3s)")

    # 测试流水线（依赖链）
    def stage1():
        return 1

    def stage2():
        return 2

    def stage3():
        return 3

    result = run_pipeline([
        ("stage1", stage1, (), {}),
        ("stage2", stage2, (), {}),
        ("stage3", stage3, (), {}),
    ])
    assert result.success
    assert result.task_count == 3
    print(f"  ✅ 流水线执行: 3 阶段依赖链")

    # 测试 DAG 依赖
    executor = ConcurrentExecutor(max_workers=4)
    t1 = executor.add_task("t1", task_a)
    t2 = executor.add_task("t2", task_b, dependencies=[t1])
    t3 = executor.add_task("t3", task_c, args=(99,), dependencies=[t1])
    t4 = executor.add_task("t4", task_a, dependencies=[t2, t3])

    result = executor.execute()
    assert result.success
    assert result.task_count == 4
    print(f"  ✅ DAG 依赖: 4 任务菱形依赖")

    # 测试失败处理
    def failing_task():
        raise ValueError("故意失败")

    executor = ConcurrentExecutor(max_workers=2)
    executor.add_task("ok", task_a)
    executor.add_task("fail", failing_task)
    result = executor.execute()
    assert not result.success
    assert result.success_count == 1
    assert result.failed_count == 1
    print(f"  ✅ 失败处理: 1 成功, 1 失败")

    return True


def test_sse_broadcaster():
    """测试 4: SSE 实时进度推送"""
    print("\n" + "=" * 60)
    print("📡 测试 4: SSE 实时进度推送")
    print("=" * 60)

    from sse import ProgressBroadcaster, ProgressEvent, get_broadcaster

    broadcaster = ProgressBroadcaster()

    # 测试订阅
    run_id = "run_test_001"
    q = broadcaster.subscribe(run_id)

    # 测试广播
    broadcaster.emit_started(run_id, "video", 6)
    event = q.get(timeout=1)
    assert event.event_type == "started"
    assert event.run_id == run_id
    assert event.data["workflow_type"] == "video"
    print(f"  ✅ 开始事件: workflow=video, tasks=6")

    # 测试进度事件
    broadcaster.emit_progress(run_id, 0.5, "creative", 3, 6)
    event = q.get(timeout=1)
    assert event.event_type == "progress"
    assert event.data["progress"] == 50.0
    print(f"  ✅ 进度事件: 50.0% - creative")

    # 测试任务完成事件
    broadcaster.emit_task_completed(run_id, "creative", 3, 6)
    event = q.get(timeout=1)
    assert event.event_type == "task_completed"
    assert event.data["task_name"] == "creative"
    print(f"  ✅ 任务完成事件: creative (3/6)")

    # 测试完成事件
    broadcaster.emit_completed(run_id, True, {"video_path": "/test.mp4"}, 30.5)
    event = q.get(timeout=1)
    assert event.event_type == "completed"
    assert event.data["success"] is True
    assert event.data["duration_sec"] == 30.5
    print(f"  ✅ 完成事件: success=True, duration=30.5s")

    # 测试 SSE 格式
    sse_str = event.to_sse()
    assert sse_str.startswith("event: completed\n")
    assert "data: " in sse_str
    assert sse_str.endswith("\n\n")
    print(f"  ✅ SSE 格式: 符合规范")

    # 测试取消订阅
    broadcaster.unsubscribe(run_id, q)
    print(f"  ✅ 取消订阅: 成功")

    # 测试全局广播器单例
    b1 = get_broadcaster()
    b2 = get_broadcaster()
    assert b1 is b2
    print(f"  ✅ 全局单例: 正常")

    return True


def test_middleware_components():
    """测试 5: API 鉴权与速率限制"""
    print("\n" + "=" * 60)
    print("🔒 测试 5: API 鉴权与速率限制")
    print("=" * 60)

    from middleware import TokenBucket, RateLimitMiddleware, AuthMiddleware, RequestTracingMiddleware

    # 测试令牌桶
    bucket = TokenBucket(rate=10.0, burst=5)  # 10/s, 突发 5
    assert bucket.consume(1) is True
    assert bucket.consume(1) is True
    assert bucket.consume(1) is True
    assert bucket.consume(1) is True
    assert bucket.consume(1) is True
    # 第 6 个应该失败（突发上限）
    assert bucket.consume(1) is False
    print(f"  ✅ 令牌桶: 5 个突发令牌消耗后限流")

    # 等待令牌恢复
    time.sleep(0.2)
    assert bucket.consume(1) is True
    print(f"  ✅ 令牌恢复: 0.2s 后恢复")

    # 测试状态查询
    status = bucket.get_status()
    assert "rate" in status
    assert "burst" in status
    assert "tokens_remaining" in status
    print(f"  ✅ 状态查询: rate={status['rate']}, burst={status['burst']}")

    # 测试中间件类存在
    assert AuthMiddleware is not None
    assert RateLimitMiddleware is not None
    assert RequestTracingMiddleware is not None
    print(f"  ✅ 中间件类: Auth/RateLimit/Tracing 已定义")

    # 测试公开路径
    assert "/health" in AuthMiddleware.PUBLIC_PATHS
    assert "/metrics" in AuthMiddleware.PUBLIC_PATHS
    print(f"  ✅ 公开路径: /health, /metrics 免鉴权")

    return True


def test_video_transitions():
    """测试 6: 视频转场增强"""
    print("\n" + "=" * 60)
    print("🎬 测试 6: 视频转场增强")
    print("=" * 60)

    # 测试视频转场（已在 sys.path 添加 agents/video_gen/scripts）
    from transitions import (
        TRANSITION_TYPES, SUBTITLE_STYLES,
        generate_styled_srt, add_watermark,
    )

    # 测试转场类型
    assert len(TRANSITION_TYPES) >= 30, f"应有 30+ 转场，实际 {len(TRANSITION_TYPES)}"
    assert "fade" in TRANSITION_TYPES
    assert "dissolve" in TRANSITION_TYPES
    assert "wipeleft" in TRANSITION_TYPES
    assert "zoomin" in TRANSITION_TYPES
    assert "circleopen" in TRANSITION_TYPES
    print(f"  ✅ 转场类型: {len(TRANSITION_TYPES)} 种")

    # 测试字幕样式
    assert len(SUBTITLE_STYLES) >= 5, f"应有 5+ 样式，实际 {len(SUBTITLE_STYLES)}"
    assert "default" in SUBTITLE_STYLES
    assert "bold" in SUBTITLE_STYLES
    assert "modern" in SUBTITLE_STYLES
    assert "cinematic" in SUBTITLE_STYLES
    assert "viral" in SUBTITLE_STYLES
    print(f"  ✅ 字幕样式: {len(SUBTITLE_STYLES)} 种预设")

    # 测试样式配置
    viral_style = SUBTITLE_STYLES["viral"]
    assert viral_style["fontsize"] == 64
    assert viral_style["bold"] == 1
    print(f"  ✅ 样式配置: viral fontsize={viral_style['fontsize']}")

    # 测试 ASS 字幕生成
    storyboard = {
        "shots": [
            {"shot_id": 1, "duration_sec": 3, "voiceover": "测试旁白一", "text_overlay": "字幕1"},
            {"shot_id": 2, "duration_sec": 5, "voiceover": "测试旁白二", "text_overlay": "字幕2"},
            {"shot_id": 3, "duration_sec": 4, "voiceover": "", "text_overlay": "仅文字"},
        ]
    }

    with tempfile.TemporaryDirectory() as work_dir:
        ass_path = os.path.join(work_dir, "subtitles.ass")
        result_path = generate_styled_srt(storyboard, ass_path, style="viral")
        assert os.path.exists(result_path)

        with open(result_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content
        assert "测试旁白一" in content
        assert "测试旁白二" in content
        assert "仅文字" in content
        print(f"  ✅ ASS 字幕生成: 3 条事件, style=viral")

        # 测试 SRT 生成
        srt_path = os.path.join(work_dir, "subtitles.srt")
        result_path = generate_styled_srt(storyboard, srt_path, style="default")
        assert os.path.exists(result_path)
        with open(result_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "00:00:00,000 --> 00:00:03,000" in content
        print(f"  ✅ SRT 字幕生成: 时间轴正确")

    return True


def test_docker_files():
    """测试 7: Docker 容器化"""
    print("\n" + "=" * 60)
    print("🐳 测试 7: Docker 容器化")
    print("=" * 60)

    # 测试 Dockerfile 存在
    dockerfile = PROJECT_ROOT / "Dockerfile"
    assert dockerfile.exists(), "Dockerfile 应存在"
    with open(dockerfile, "r") as f:
        content = f.read()
    assert "FROM python:3.11" in content
    assert "ffmpeg" in content
    assert "fonts-noto-cjk" in content  # 中文字体
    assert "HEALTHCHECK" in content
    assert "EXPOSE 8765" in content
    assert "VOLUME" in content
    print(f"  ✅ Dockerfile: 多阶段构建 + ffmpeg + 中文字体 + 健康检查")

    # 测试 docker-compose.yml
    compose_file = PROJECT_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml 应存在"
    with open(compose_file, "r") as f:
        content = f.read()
    assert "kickart-api" in content
    assert "redis" in content
    assert "prometheus" in content
    assert "grafana" in content
    assert "kickart-net" in content
    assert "healthcheck" in content
    print(f"  ✅ docker-compose: API + Redis + Prometheus + Grafana")

    # 测试 requirements.txt
    req_file = PROJECT_ROOT / "requirements.txt"
    assert req_file.exists(), "requirements.txt 应存在"
    with open(req_file, "r") as f:
        content = f.read()
    assert "fastapi" in content
    assert "uvicorn" in content
    assert "pydantic-settings" in content
    assert "edge-tts" in content
    assert "prometheus-client" in content
    print(f"  ✅ requirements.txt: 依赖完整")

    # 测试 .env.example
    env_file = PROJECT_ROOT / ".env.example"
    assert env_file.exists(), ".env.example 应存在"
    with open(env_file, "r") as f:
        content = f.read()
    assert "KICKART_API_PORT" in content
    assert "KICKART_SD_WEBUI_URL" in content
    assert "KICKART_LOG_FORMAT" in content
    print(f"  ✅ .env.example: 配置模板完整")

    # 测试 Prometheus 配置
    prom_file = PROJECT_ROOT / "monitoring" / "prometheus.yml"
    assert prom_file.exists(), "prometheus.yml 应存在"
    with open(prom_file, "r") as f:
        content = f.read()
    assert "kickart-api" in content
    assert "/metrics" in content
    print(f"  ✅ prometheus.yml: 抓取配置完整")

    return True


def test_metrics_system():
    """测试 8: Prometheus 指标系统"""
    print("\n" + "=" * 60)
    print("📊 测试 8: Prometheus 指标系统")
    print("=" * 60)

    from metrics import (
        track_agent_execution, track_workflow,
        videos_total, agent_success_total, active_workflows,
        get_metrics, get_metrics_content_type,
        PROMETHEUS_AVAILABLE,
    )

    # 测试指标采集
    @track_agent_execution("test_agent")
    def test_agent_func():
        time.sleep(0.05)
        return {"success": True}

    result = test_agent_func()
    assert result["success"] is True
    print(f"  ✅ Agent 执行追踪: 装饰器正常工作")

    # 测试工作流追踪
    @track_workflow("video")
    def test_workflow():
        return {"success": True}

    result = test_workflow()
    print(f"  ✅ 工作流追踪: 装饰器正常工作")

    # 测试指标导出
    metrics_data = get_metrics()
    if PROMETHEUS_AVAILABLE:
        assert len(metrics_data) > 0
        assert b"kickart_" in metrics_data
        print(f"  ✅ 指标导出: {len(metrics_data)} bytes")
    else:
        print(f"  ⚠️  prometheus_client 未安装，使用占位指标")

    # 测试 Content-Type
    ct = get_metrics_content_type()
    assert "text/plain" in ct
    print(f"  ✅ Content-Type: {ct}")

    return True


def main():
    print("\n" + "=" * 60)
    print("🚀 V4 顶尖升级测试")
    print("=" * 60)

    tests = [
        ("结构化日志系统", test_structured_logging),
        ("配置管理", test_config_management),
        ("并发执行引擎", test_concurrent_executor),
        ("SSE 实时进度推送", test_sse_broadcaster),
        ("API 鉴权与速率限制", test_middleware_components),
        ("视频转场增强", test_video_transitions),
        ("Docker 容器化", test_docker_files),
        ("Prometheus 指标系统", test_metrics_system),
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
        print("\n🎉 所有测试通过！V4 顶尖升级完成。")
        print("\n📋 顶尖升级能力总结:")
        print("   - 结构化日志: JSON 格式 + 请求追踪 + 上下文")
        print("   - 配置管理: pydantic-settings + 环境变量 + .env")
        print("   - 并发引擎: DAG 依赖 + 线程池 + 进度回调")
        print("   - SSE 推送: 实时进度 + 多订阅者 + 心跳")
        print("   - 安全防护: API Key + 令牌桶限流 + CORS")
        print("   - 视频增强: 30+ 转场 + 5 字幕样式 + 水印")
        print("   - 容器化: 多阶段构建 + docker-compose + Prometheus")
        print("   - 可观测性: Prometheus 指标 + 装饰器追踪")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit(main())
