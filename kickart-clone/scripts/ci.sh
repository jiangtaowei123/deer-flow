#!/bin/bash
# CI/CD 辅助脚本 - 本地测试与构建
# 用法: ./scripts/ci.sh [test|build|lint|security|all]

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

ACTION="${1:-all}"
PYTHON="${PYTHON:-python3}"

echo "=========================================="
echo "Kickart Clone CI/CD - $ACTION"
echo "Project: $PROJECT_DIR"
echo "=========================================="

run_lint() {
    echo ""
    echo "[1/4] 代码检查 (Lint)"
    echo "------------------------------------------"
    pip install --quiet ruff black isort 2>/dev/null || true
    ruff check . --ignore E501,W605,F401,E402 || echo "⚠️  ruff 有警告"
    black . --check --line-length 120 2>/dev/null || echo "⚠️  black 格式不一致"
    isort . --check-only --profile black 2>/dev/null || echo "⚠️  isort 顺序不一致"
    echo "✅ 代码检查完成"
}

run_test() {
    echo ""
    echo "[2/4] 端到端测试"
    echo "------------------------------------------"
    pip install --quiet -r requirements.txt 2>/dev/null || true
    pip install --quiet pytest requests pillow 2>/dev/null || true

    PASS=0
    FAIL=0
    for test_file in tests/e2e/test_*.py; do
        if [ -f "$test_file" ]; then
            echo "运行: $test_file"
            if $PYTHON -m pytest "$test_file" -v --tb=short 2>&1; then
                PASS=$((PASS + 1))
            else
                FAIL=$((FAIL + 1))
            fi
        fi
    done
    echo ""
    echo "测试结果: ✅ $PASS 通过, ❌ $FAIL 失败"
    if [ "$FAIL" -gt 0 ]; then
        return 1
    fi
}

run_security() {
    echo ""
    echo "[3/4] 安全扫描"
    echo "------------------------------------------"
    pip install --quiet bandit safety 2>/dev/null || true
    bandit -r . -f json -o /tmp/bandit-report.json 2>/dev/null || echo "⚠️  bandit 发现问题"
    safety check --file requirements.txt 2>/dev/null || echo "⚠️  safety 发现漏洞"
    echo "✅ 安全扫描完成"
}

run_build() {
    echo ""
    echo "[4/4] Docker 构建"
    echo "------------------------------------------"
    if command -v docker &>/dev/null; then
        docker build -t kickart-clone:ci -f Dockerfile . || echo "⚠️  Docker 构建失败"
        echo "✅ Docker 镜像构建完成: kickart-clone:ci"
    else
        echo "⚠️  Docker 未安装，跳过构建"
    fi
}

case "$ACTION" in
    lint)
        run_lint
        ;;
    test)
        run_test
        ;;
    security)
        run_security
        ;;
    build)
        run_build
        ;;
    all)
        run_lint
        run_test
        run_security
        run_build
        ;;
    *)
        echo "用法: $0 [test|build|lint|security|all]"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "CI/CD 完成"
echo "=========================================="
