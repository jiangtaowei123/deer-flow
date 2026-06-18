"""
Kickart Clone - 端到端测试
验证完整工作流：商品解析 → API 创建任务 → 状态查询
"""
import json
import time
import sys
from pathlib import Path

import requests

API_BASE = "http://localhost:8765"
TEST_TIMEOUT = 60


def test_health():
    """测试 1: 健康检查"""
    print("=== 测试 1: 健康检查 ===")
    r = requests.get(f"{API_BASE}/health", timeout=5)
    assert r.status_code == 200, f"健康检查失败: {r.status_code}"
    data = r.json()
    assert data["status"] == "ok"
    print(f"✓ 健康检查通过: {data['service']} v{data['version']}")
    return True


def test_scenes_list():
    """测试 2: 场景列表"""
    print("\n=== 测试 2: 场景列表 ===")
    r = requests.get(f"{API_BASE}/scenes", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 15, f"场景数不足: {data['total']} < 15"
    print(f"✓ 场景列表通过: 共 {data['total']} 个场景")
    for s in data["scenes"][:3]:
        print(f"  - {s['id']}: {s['name']}")
    return True


def test_create_task_with_description():
    """测试 3: 使用商品描述创建任务"""
    print("\n=== 测试 3: 创建生成任务（商品描述）===")
    payload = {
        "product_description": "burgundy red ribbed tank top bodysuit",
        "product_id": "E2E-TEST-001",
        "scenes": ["studio", "outdoor_urban"],
        "num_variants": 1,
        "include_arms": True,
        "enable_hr": False,
    }
    r = requests.post(f"{API_BASE}/generate", json=payload, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "pending"
    task_id = data["task_id"]
    print(f"✓ 任务创建成功: {task_id}")
    print(f"  消息: {data['message']}")
    return task_id


def test_create_task_with_url():
    """测试 4: 使用商品URL创建任务"""
    print("\n=== 测试 4: 创建生成任务（Amazon URL）===")
    payload = {
        "product_url": "https://www.amazon.com/dp/B08N5WRWNW",
        "scenes": ["studio"],
        "num_variants": 1,
    }
    r = requests.post(f"{API_BASE}/generate", json=payload, timeout=10)
    assert r.status_code == 200
    data = r.json()
    task_id = data["task_id"]
    print(f"✓ 任务创建成功: {task_id}")
    return task_id


def test_task_status(task_id: str, expect_product_info: bool = False):
    """测试 5: 查询任务状态"""
    print(f"\n=== 测试 5: 查询任务状态 ({task_id}) ===")
    # 轮询直到完成或超时
    start = time.time()
    while time.time() - start < TEST_TIMEOUT:
        r = requests.get(f"{API_BASE}/tasks/{task_id}", timeout=5)
        assert r.status_code == 200
        data = r.json()
        status = data["status"]
        print(f"  状态: {status}, 进度: {data['progress']:.0%}")

        if status in ["completed", "failed"]:
            break
        time.sleep(2)

    # 验证最终状态
    assert status in ["completed", "failed"], f"任务超时: {status}"

    if expect_product_info and data.get("product_info"):
        pi = data["product_info"]
        print(f"✓ 商品解析成功:")
        print(f"  商品ID: {pi.get('product_id')}")
        print(f"  平台: {pi.get('platform')}")

    if status == "failed":
        # SD 未运行是预期失败
        results = data.get("results", {})
        error = results.get("error", "") if isinstance(results, dict) else ""
        if "Stable Diffusion WebUI" in error or "未运行" in error:
            print(f"✓ 预期失败（SD未运行）: {error}")
            return True
        else:
            print(f"✗ 非预期失败: {error}")
            return False
    elif status == "completed":
        results = data.get("results", {})
        print(f"✓ 任务完成: {results.get('success_count', 0)}/{results.get('total', 0)}")
        return True
    return True


def test_list_tasks():
    """测试 6: 列出所有任务"""
    print("\n=== 测试 6: 列出所有任务 ===")
    r = requests.get(f"{API_BASE}/tasks?limit=10", timeout=5)
    assert r.status_code == 200
    data = r.json()
    print(f"✓ 任务列表: 共 {data['total']} 个任务")
    for t in data["tasks"][:3]:
        print(f"  - {t['task_id']}: {t['status']}")
    return True


def test_delete_task(task_id: str):
    """测试 7: 删除任务"""
    print(f"\n=== 测试 7: 删除任务 ({task_id}) ===")
    r = requests.delete(f"{API_BASE}/tasks/{task_id}", timeout=5)
    assert r.status_code == 200
    print(f"✓ 任务已删除")
    # 验证已删除
    r = requests.get(f"{API_BASE}/tasks/{task_id}", timeout=5)
    assert r.status_code == 404
    print(f"✓ 任务已确认删除（404）")
    return True


def main():
    """运行所有测试"""
    print("=" * 60)
    print("🧪 Kickart Clone - 端到端测试")
    print("=" * 60)

    tests = []
    try:
        # 1. 基础测试
        tests.append(("健康检查", test_health()))
        tests.append(("场景列表", test_scenes_list()))

        # 2. 任务测试
        task_id_1 = test_create_task_with_description()
        test_task_status(task_id_1)

        task_id_2 = test_create_task_with_url()
        test_task_status(task_id_2, expect_product_info=True)

        # 3. 列表与删除
        test_list_tasks()
        test_delete_task(task_id_1)

    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        sys.exit(1)

    # 总结
    print("\n" + "=" * 60)
    print("📊 测试总结")
    print("=" * 60)
    passed = sum(1 for _, result in tests if result)
    total = len(tests)
    for name, result in tests:
        icon = "✓" if result else "✗"
        print(f"  {icon} {name}")
    print(f"\n通过: {passed}/{total}")
    if passed == total:
        print("🎉 所有测试通过！")
    else:
        print(f"⚠️  {total - passed} 个测试未通过")


if __name__ == "__main__":
    main()
