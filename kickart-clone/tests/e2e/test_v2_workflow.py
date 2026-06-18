"""
V2 端到端测试 - Agent 协同
测试 Lead Agent 编排器：任务规划、Agent 调度、失败降级、端到端编排
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "lead_agent" / "scripts"))

from orchestrator import (
    LeadAgentOrchestrator,
    WorkflowType,
    TaskStatus,
)


def test_workflow_planning():
    """测试 1: 工作流规划"""
    print("\n" + "=" * 60)
    print("📋 测试 1: 工作流规划")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="v2_test_") as work_dir:
        orchestrator = LeadAgentOrchestrator(output_dir=work_dir)

        # 测试视频工作流规划
        run = orchestrator.plan_workflow(
            input_value="https://amazon.com/dp/B0TEST",
            workflow_type=WorkflowType.VIDEO,
            num_scenes=6,
        )

        assert run.run_id.startswith("run_"), "run_id 格式错误"
        assert run.workflow_type == WorkflowType.VIDEO
        assert len(run.tasks) == 6, f"视频工作流应有 6 个任务，实际 {len(run.tasks)}"
        assert run.tasks[0].agent_name == "product_parser"
        assert run.tasks[1].agent_name == "creative"
        assert run.tasks[2].agent_name == "storyboard"
        assert run.tasks[3].agent_name == "image_gen"
        assert run.tasks[4].agent_name == "tts"
        assert run.tasks[5].agent_name == "video_gen"

        # 测试图片工作流
        run_img = orchestrator.plan_workflow(
            input_value="test product",
            workflow_type=WorkflowType.IMAGE,
        )
        assert len(run_img.tasks) == 4, f"图片工作流应有 4 个任务，实际 {len(run_img.tasks)}"

        # 测试分镜工作流
        run_sb = orchestrator.plan_workflow(
            input_value="test product",
            workflow_type=WorkflowType.STORYBOARD,
        )
        assert len(run_sb.tasks) == 3, f"分镜工作流应有 3 个任务，实际 {len(run_sb.tasks)}"

    print("  ✅ 视频工作流: 6 个任务（parse→creative→storyboard→image→tts→video）")
    print("  ✅ 图片工作流: 4 个任务（parse→creative→storyboard→image）")
    print("  ✅ 分镜工作流: 3 个任务（parse→creative→storyboard）")
    return True


def test_agent_registry():
    """测试 2: Agent 注册表与降级配置"""
    print("\n" + "=" * 60)
    print("🤖 测试 2: Agent 注册表与降级配置")
    print("=" * 60)

    registry = LeadAgentOrchestrator.AGENT_REGISTRY

    # 验证所有 Agent 已注册
    expected_agents = {"product_parser", "creative", "storyboard", "image_gen", "tts", "video_gen"}
    assert set(registry.keys()) == expected_agents, f"Agent 注册不匹配: {set(registry.keys())}"

    # 验证必需性配置
    assert registry["product_parser"]["required"] is True
    assert registry["creative"]["required"] is True
    assert registry["storyboard"]["required"] is True
    assert registry["image_gen"]["required"] is False  # 可降级为占位图
    assert registry["tts"]["required"] is False  # 可降级为静音
    assert registry["video_gen"]["required"] is True

    # 验证降级方案
    assert registry["product_parser"]["fallback"] == "manual_input"
    assert registry["creative"]["fallback"] == "generic_template"
    assert registry["storyboard"]["fallback"] == "simple_shots"
    assert registry["image_gen"]["fallback"] == "placeholder_images"
    assert registry["tts"]["fallback"] == "silence_audio"
    assert registry["video_gen"]["fallback"] is None  # 无降级

    print("  ✅ 6 个 Agent 全部注册")
    print("  ✅ 必需性配置正确（4 必需 + 2 可选）")
    print("  ✅ 降级方案配置正确（5 个有降级，1 个无降级）")
    return True


def test_e2e_video_workflow():
    """测试 3: 端到端视频工作流（含降级）"""
    print("\n" + "=" * 60)
    print("🎬 测试 3: 端到端视频工作流")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="v2_test_") as work_dir:
        orchestrator = LeadAgentOrchestrator(output_dir=work_dir)

        # 使用文字描述作为输入（避免网络请求）
        run = orchestrator.plan_workflow(
            input_value="优雅的夏季碎花连衣裙，适合多种场合穿着，轻盈面料，修身剪裁",
            workflow_type=WorkflowType.VIDEO,
            num_scenes=6,
        )

        # 执行工作流
        result = orchestrator.execute_workflow(run.run_id)

        # 验证整体成功
        assert result.status == TaskStatus.SUCCESS, f"工作流应成功，实际 {result.status}"
        assert result.final_outputs["success"] is True

        # 验证任务执行情况
        tasks = result.final_outputs["tasks_summary"]
        assert len(tasks) == 6

        # product_parser: 应降级（无网络）或成功
        parse_task = tasks[0]
        assert parse_task["agent"] == "product_parser"
        assert parse_task["status"] in ("success", "degraded"), \
            f"product_parser 应成功或降级，实际 {parse_task['status']}"

        # creative: 应成功
        assert tasks[1]["status"] == "success", f"creative 应成功，实际 {tasks[1]['status']}"

        # storyboard: 应成功
        assert tasks[2]["status"] == "success", f"storyboard 应成功，实际 {tasks[2]['status']}"

        # image_gen: 应降级（SD 未运行）
        assert tasks[3]["status"] == "degraded", f"image_gen 应降级，实际 {tasks[3]['status']}"

        # tts: 应降级（edge-tts 网络受限）或成功
        assert tasks[4]["status"] in ("success", "degraded"), \
            f"tts 应成功或降级，实际 {tasks[4]['status']}"

        # video_gen: 应成功
        assert tasks[5]["status"] == "success", f"video_gen 应成功，实际 {tasks[5]['status']}"

        # 验证最终产物
        artifacts = result.final_outputs["artifacts"]
        assert "creative" in artifacts, "缺少 creative 产物"
        assert "storyboard" in artifacts, "缺少 storyboard 产物"
        assert "video" in artifacts, "缺少 video 产物"

        video_info = artifacts["video"]
        assert video_info.get("success") is True, "视频应生成成功"
        assert os.path.exists(video_info.get("output_path", "")), "视频文件应存在"

        # 验证降级日志
        if result.degradation_log:
            print(f"  ✅ 降级记录: {len(result.degradation_log)} 条")
            for log in result.degradation_log:
                print(f"     - {log['agent']}: {log['fallback']} → {log.get('result', '')}")

        print(f"  ✅ 工作流状态: {result.status.value}")
        print(f"  ✅ 任务执行: {sum(1 for t in tasks if t['status'] == 'success')} 成功, "
              f"{sum(1 for t in tasks if t['status'] == 'degraded')} 降级")
        print(f"  ✅ 视频输出: {video_info['output_path']}")
        print(f"  ✅ 视频时长: {video_info['duration_sec']}s")
        print(f"  ✅ 总耗时: {result.final_outputs['total_duration_sec']}s")

    return True


def test_degradation_mechanism():
    """测试 4: 失败降级机制"""
    print("\n" + "=" * 60)
    print("🛡️  测试 4: 失败降级机制")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="v2_test_") as work_dir:
        orchestrator = LeadAgentOrchestrator(output_dir=work_dir)

        # 测试商品解析降级（无效 URL）
        run = orchestrator.plan_workflow(
            input_value="这是一个纯文字商品描述，没有URL",
            workflow_type=WorkflowType.STORYBOARD,  # 仅到分镜，快速测试
        )
        result = orchestrator.execute_workflow(run.run_id)

        # product_parser 应降级为 manual_input
        parse_task = result.final_outputs["tasks_summary"][0]
        assert parse_task["status"] in ("success", "degraded"), \
            f"product_parser 应成功或降级，实际 {parse_task['status']}"

        # 验证降级后上下文正确传递
        artifacts = result.final_outputs["artifacts"]
        assert "creative" in artifacts, "降级后 creative 应仍能执行"
        assert "storyboard" in artifacts, "降级后 storyboard 应仍能执行"

        print(f"  ✅ 商品解析降级: {parse_task['status']}")
        print(f"  ✅ 降级后 creative 仍执行: success")
        print(f"  ✅ 降级后 storyboard 仍执行: success")
        print(f"  ✅ 上下文正确传递")

    return True


def test_required_agent_failure():
    """测试 5: 必需 Agent 失败终止"""
    print("\n" + "=" * 60)
    print("⛔ 测试 5: 必需 Agent 失败终止")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="v2_test_") as work_dir:
        orchestrator = LeadAgentOrchestrator(output_dir=work_dir)

        # 模拟 video_gen 失败（无降级方案）
        run = orchestrator.plan_workflow(
            input_value="test product",
            workflow_type=WorkflowType.VIDEO,
        )

        # 手动破坏 video_gen（让它无法执行）
        original_dispatch = orchestrator._dispatch_agent
        call_count = {"video_gen": 0}

        def broken_dispatch(task, context):
            if task.agent_name == "video_gen":
                call_count["video_gen"] += 1
                return {"success": False, "error": "模拟 video_gen 失败"}
            return original_dispatch(task, context)

        orchestrator._dispatch_agent = broken_dispatch
        result = orchestrator.execute_workflow(run.run_id)

        # video_gen 是必需且无降级，应导致工作流失败
        assert result.status == TaskStatus.FAILED, f"工作流应失败，实际 {result.status}"
        assert result.final_outputs["success"] is False
        assert "video_gen" in result.final_outputs.get("error", "")

        # 前面的任务应已完成
        completed = result.final_outputs.get("completed_tasks", [])
        assert len(completed) > 0, "前置任务应已完成"

        print(f"  ✅ video_gen 失败后工作流正确终止")
        print(f"  ✅ 前置任务完成数: {len(completed)}")
        print(f"  ✅ 错误信息: {result.final_outputs['error'][:60]}")

    return True


def test_run_persistence():
    """测试 6: 运行记录持久化"""
    print("\n" + "=" * 60)
    print("💾 测试 6: 运行记录持久化")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="v2_test_") as work_dir:
        orchestrator = LeadAgentOrchestrator(output_dir=work_dir)

        run = orchestrator.plan_workflow(
            input_value="test product for persistence",
            workflow_type=WorkflowType.STORYBOARD,
        )
        result = orchestrator.execute_workflow(run.run_id)

        # 验证运行记录文件已保存
        run_file = Path(work_dir) / f"{run.run_id}.json"
        assert run_file.exists(), "运行记录文件应存在"

        with open(run_file, "r", encoding="utf-8") as f:
            saved = json.load(f)

        assert saved["run_id"] == run.run_id
        assert saved["success"] is True
        assert "artifacts" in saved
        assert "tasks_summary" in saved

        # 验证查询接口
        retrieved = orchestrator.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.run_id == run.run_id

        # 验证列表接口
        runs = orchestrator.list_runs()
        assert len(runs) >= 1

        print(f"  ✅ 运行记录已保存: {run_file}")
        print(f"  ✅ 查询接口正常: get_run()")
        print(f"  ✅ 列表接口正常: list_runs() 返回 {len(runs)} 条")

    return True


def main():
    print("\n" + "=" * 60)
    print("🚀 V2 端到端测试：Agent 协同")
    print("=" * 60)

    tests = [
        ("工作流规划", test_workflow_planning),
        ("Agent 注册表", test_agent_registry),
        ("端到端视频工作流", test_e2e_video_workflow),
        ("失败降级机制", test_degradation_mechanism),
        ("必需 Agent 失败终止", test_required_agent_failure),
        ("运行记录持久化", test_run_persistence),
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
        print("\n🎉 所有测试通过！V2 Agent 协同阶段就绪。")
        print("\n📋 Lead Agent 能力总结:")
        print("   - 自主规划：根据输入类型规划任务链")
        print("   - 多 Agent 调度：6 个专业 Agent 协同")
        print("   - 失败降级：5 种降级方案保证可用性")
        print("   - 必需性控制：必需失败终止，可选失败降级")
        print("   - 状态跟踪：完整任务状态机 + 持久化")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit(main())
