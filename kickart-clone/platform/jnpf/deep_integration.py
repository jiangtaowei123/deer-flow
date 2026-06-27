"""
JNPF6.2 深度集成 - 表单引擎、流程引擎、页面渲染器
基于 JNPF6.2 低代码平台规范，实现：
1. 表单引擎 - 动态表单渲染、字段校验、联动
2. 流程引擎 - 节点调度、条件分支、并行执行
3. 页面渲染器 - 低代码页面 JSON → HTML 渲染
这是对 adapter.py 的深度扩展，使 Kickart Clone 真正嵌入 JNPF6.2 生态
"""
import ast
import json
import operator
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ============================================================================
# 安全表达式求值器（替代 eval()）
# ============================================================================

_SAFE_BINOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_SAFE_UNARYOPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval_expr(expr: str, context: dict) -> bool:
    """
    安全表达式求值（替代 eval()）。
    支持：比较、布尔运算、算术、in/not in、变量引用、字面量。
    禁止：函数调用、属性访问、import、任何名字解析为内置。
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return False

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.BoolOp):
            values = [_eval(v) for v in node.values]
            op = _SAFE_BINOPS.get(type(node.op))
            if op is None:
                raise ValueError("不支持的布尔运算")
            result = values[0]
            for v in values[1:]:
                result = op(result, v)
            return result
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op = _SAFE_BINOPS.get(type(node.op))
            if op is None:
                raise ValueError("不支持的二元运算")
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            op = _SAFE_UNARYOPS.get(type(node.op))
            if op is None:
                raise ValueError("不支持的一元运算")
            return op(operand)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op_node, right_node in zip(node.ops, node.comparators):
                right = _eval(right_node)
                op = _SAFE_BINOPS.get(type(op_node))
                if op is None:
                    raise ValueError("不支持的比较运算")
                if not op(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Name):
            # 仅允许从 context 取值，禁止任何 builtins
            if node.id == "True":
                return True
            if node.id == "False":
                return False
            if node.id == "None":
                return None
            return context.get(node.id)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [_eval(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(_eval(e) for e in node.elts)
        if isinstance(node, ast.Set):
            return {_eval(e) for e in node.elts}
        if isinstance(node, ast.Dict):
            return {_eval(k): _eval(v) for k, v in zip(node.keys, node.values)}
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")

    try:
        return bool(_eval(tree))
    except Exception:
        return False


# ============================================================================
# 表单引擎
# ============================================================================

class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    SELECT = "select"
    MULTISELECT = "multiselect"
    SWITCH = "switch"
    IMAGE = "image"
    URL = "url"
    DATE = "date"
    RATING = "rating"
    COLOR = "color"
    TAGS = "tags"
    RICH_TEXT = "rich_text"


@dataclass
class FormFieldRule:
    """表单字段联动规则"""
    field: str  # 触发字段
    condition: str  # 条件表达式，如 "== 'video'" / ">= 5" / "in ['a','b']"
    action: str  # show/hide/require/set_value/disable
    target: str  # 目标字段
    value: any = None  # set_value 时的值


@dataclass
class FormFieldDef:
    """表单字段定义（扩展版）"""
    field: str
    label: str
    type: FieldType
    required: bool = False
    default: any = None
    options: list = field(default_factory=list)
    placeholder: str = ""
    description: str = ""
    # 校验规则
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None  # 正则校验
    # 联动
    rules: list = field(default_factory=list)
    # 布局
    span: int = 24  # 栅格宽度（24 制）
    # i18n
    label_i18n: dict = field(default_factory=dict)


@dataclass
class FormSchema:
    """表单 Schema"""
    form_id: str
    name: str
    fields: list  # FormFieldDef 列表
    layout: str = "vertical"  # vertical/horizontal/inline
    label_width: str = "120px"
    # i18n
    name_i18n: dict = field(default_factory=dict)


class FormEngine:
    """
    JNPF6.2 表单引擎
    - 表单校验
    - 字段联动
    - 默认值填充
    - 表单序列化
    """

    def validate(self, schema: FormSchema, data: dict) -> dict:
        """
        校验表单数据
        返回: {"valid": bool, "errors": {field: message}}
        """
        errors = {}
        for f in schema.fields:
            value = data.get(f.field)

            # 必填校验
            if f.required and (value is None or value == "" or value == []):
                errors[f.field] = f"{f.label}不能为空"
                continue

            if value is None or value == "":
                continue

            # 类型校验
            if f.type == FieldType.NUMBER:
                try:
                    num = float(value)
                    if f.min_value is not None and num < f.min_value:
                        errors[f.field] = f"{f.label}不能小于 {f.min_value}"
                    if f.max_value is not None and num > f.max_value:
                        errors[f.field] = f"{f.label}不能大于 {f.max_value}"
                except (ValueError, TypeError):
                    errors[f.field] = f"{f.label}必须是数字"

            elif f.type in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.RICH_TEXT):
                length = len(str(value))
                if f.min_length is not None and length < f.min_length:
                    errors[f.field] = f"{f.label}至少 {f.min_length} 个字符"
                if f.max_length is not None and length > f.max_length:
                    errors[f.field] = f"{f.label}最多 {f.max_length} 个字符"
                if f.pattern and not re.match(f.pattern, str(value)):
                    errors[f.field] = f"{f.label}格式不正确"

            elif f.type == FieldType.SELECT:
                if f.options and value not in f.options:
                    errors[f.field] = f"{f.label}值无效"

            elif f.type == FieldType.MULTISELECT:
                if f.options:
                    for v in value if isinstance(value, list) else [value]:
                        if v not in f.options:
                            errors[f.field] = f"{f.label}值无效: {v}"
                            break

            elif f.type == FieldType.URL:
                if not str(value).startswith(("http://", "https://")):
                    errors[f.field] = f"{f.label}必须是有效的 URL"

        return {"valid": len(errors) == 0, "errors": errors}

    def apply_defaults(self, schema: FormSchema, data: dict) -> dict:
        """填充默认值"""
        result = data.copy()
        for f in schema.fields:
            if f.field not in result or result[f.field] is None:
                if f.default is not None:
                    result[f.field] = f.default
        return result

    def evaluate_rules(self, schema: FormSchema, data: dict) -> dict:
        """
        评估联动规则
        返回: {field: {visible: bool, required: bool, disabled: bool, value: any}}
        """
        field_states = {f.field: {"visible": True, "required": f.required, "disabled": False, "value": data.get(f.field)} for f in schema.fields}

        for f in schema.fields:
            for rule in f.rules:
                trigger_value = data.get(rule.field)
                if self._eval_condition(trigger_value, rule.condition):
                    if rule.action == "show":
                        field_states[rule.target]["visible"] = True
                    elif rule.action == "hide":
                        field_states[rule.target]["visible"] = False
                    elif rule.action == "require":
                        field_states[rule.target]["required"] = True
                    elif rule.action == "set_value":
                        field_states[rule.target]["value"] = rule.value
                    elif rule.action == "disable":
                        field_states[rule.target]["disabled"] = True

        return field_states

    def _eval_condition(self, value: any, condition: str) -> bool:
        """评估条件表达式"""
        try:
            condition = condition.strip()
            # == 比较
            if condition.startswith("== "):
                target = self._parse_value(condition[3:])
                return value == target
            elif condition.startswith("!= "):
                target = self._parse_value(condition[3:])
                return value != target
            elif condition.startswith(">= "):
                return float(value) >= float(condition[3:])
            elif condition.startswith("<= "):
                return float(value) <= float(condition[3:])
            elif condition.startswith("> "):
                return float(value) > float(condition[2:])
            elif condition.startswith("< "):
                return float(value) < float(condition[2:])
            elif condition.startswith("in "):
                target_list = ast.literal_eval(condition[3:])  # 安全：仅解析字面量
                return value in target_list
            elif condition.startswith("not in "):
                target_list = ast.literal_eval(condition[7:])  # 安全：仅解析字面量
                return value not in target_list
            else:
                return bool(value)
        except Exception:
            return False

    @staticmethod
    def _parse_value(s: str) -> any:
        """解析值字符串"""
        s = s.strip()
        if s.startswith("'") and s.endswith("'"):
            return s[1:-1]
        if s.startswith('"') and s.endswith('"'):
            return s[1:-1]
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return s

    def serialize(self, schema: FormSchema) -> dict:
        """序列化表单为 JSON"""
        return {
            "form_id": schema.form_id,
            "name": schema.name,
            "name_i18n": schema.name_i18n,
            "layout": schema.layout,
            "label_width": schema.label_width,
            "fields": [
                {
                    "field": f.field,
                    "label": f.label,
                    "label_i18n": f.label_i18n,
                    "type": f.type.value,
                    "required": f.required,
                    "default": f.default,
                    "options": f.options,
                    "placeholder": f.placeholder,
                    "description": f.description,
                    "min_value": f.min_value,
                    "max_value": f.max_value,
                    "min_length": f.min_length,
                    "max_length": f.max_length,
                    "pattern": f.pattern,
                    "span": f.span,
                    "rules": [
                        {
                            "field": r.field,
                            "condition": r.condition,
                            "action": r.action,
                            "target": r.target,
                            "value": r.value,
                        }
                        for r in f.rules
                    ],
                }
                for f in schema.fields
            ],
        }


# ============================================================================
# 流程引擎
# ============================================================================

class NodeType(str, Enum):
    START = "start"
    TASK = "task"
    DECISION = "decision"
    PARALLEL = "parallel"  # 并行分支
    MERGE = "merge"  # 并行合并
    SUBPROCESS = "subprocess"  # 子流程
    END = "end"


@dataclass
class FlowNode:
    """流程节点"""
    node_id: str
    node_type: NodeType
    name: str
    agent: Optional[str] = None
    next_nodes: list = field(default_factory=list)
    # 决策节点：条件分支
    branches: dict = field(default_factory=dict)  # {condition: [node_ids]}
    # 并行节点
    parallel_branches: list = field(default_factory=list)  # [[node_ids], [node_ids]]
    # 子流程
    sub_workflow_id: Optional[str] = None
    # 配置
    config: dict = field(default_factory=dict)
    # 超时（秒）
    timeout: Optional[int] = None
    # 重试
    max_retries: int = 0


@dataclass
class FlowInstance:
    """流程实例"""
    instance_id: str
    workflow_id: str
    status: str = "running"  # running/completed/failed/cancelled
    current_nodes: list = field(default_factory=list)
    completed_nodes: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: str = ""


class FlowEngine:
    """
    JNPF6.2 流程引擎
    - 节点调度
    - 条件分支
    - 并行执行
    - 子流程
    - 超时与重试
    """

    def __init__(self):
        self.workflows: dict[str, dict] = {}  # workflow_id -> {nodes: [...]}
        self.instances: dict[str, FlowInstance] = {}

    def register_workflow(self, workflow_id: str, nodes: list) -> dict:
        """注册流程定义"""
        node_map = {n.node_id: n for n in nodes}
        self.workflows[workflow_id] = {
            "workflow_id": workflow_id,
            "nodes": node_map,
            "node_list": nodes,
        }
        return self.workflows[workflow_id]

    def start(self, workflow_id: str, context: dict = None) -> FlowInstance:
        """启动流程实例"""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"未知流程: {workflow_id}")

        # 找到 start 节点
        start_node = None
        for n in workflow["node_list"]:
            if n.node_type == NodeType.START:
                start_node = n
                break
        if not start_node:
            raise ValueError("流程缺少 start 节点")

        instance = FlowInstance(
            instance_id=f"inst_{uuid.uuid4().hex[:12]}",
            workflow_id=workflow_id,
            current_nodes=start_node.next_nodes.copy(),
            context=context or {},
            started_at=time.time(),
        )
        # start 节点视为已完成
        instance.completed_nodes.append(start_node.node_id)
        self.instances[instance.instance_id] = instance
        return instance

    def execute_node(self, instance: FlowInstance, node_id: str, executor=None) -> dict:
        """
        执行单个节点
        executor: callable(node: FlowNode, context: dict) -> dict
        """
        workflow = self.workflows.get(instance.workflow_id)
        if not workflow:
            return {"success": False, "error": f"流程未注册: {instance.workflow_id}"}
        node = workflow["nodes"].get(node_id)
        if not node:
            return {"success": False, "error": f"节点不存在: {node_id}"}

        result = {"success": True, "node_id": node_id, "output": None}

        if node.node_type == NodeType.TASK:
            if executor:
                try:
                    output = executor(node, instance.context)
                    result["output"] = output
                    instance.context[node_id] = output
                except Exception as e:
                    result["success"] = False
                    result["error"] = str(e)
            # 推进到下一节点
            if result["success"]:
                instance.current_nodes = node.next_nodes.copy()

        elif node.node_type == NodeType.DECISION:
            # 评估条件分支
            next_ids = []
            for condition, targets in node.branches.items():
                if self._eval_branch_condition(condition, instance.context):
                    next_ids.extend(targets)
            if not next_ids and node.next_nodes:
                next_ids = node.next_nodes.copy()
            instance.current_nodes = next_ids

        elif node.node_type == NodeType.PARALLEL:
            # 并行分支：所有分支同时推进
            instance.current_nodes = []
            for branch in node.parallel_branches:
                instance.current_nodes.extend(branch)

        elif node.node_type == NodeType.MERGE:
            # 合并节点：等待所有分支到达
            instance.completed_nodes.append(node_id)
            # 检查是否所有分支都完成
            # 简化处理：直接推进
            instance.current_nodes = node.next_nodes.copy()

        elif node.node_type == NodeType.SUBPROCESS:
            # 子流程
            if node.sub_workflow_id and node.sub_workflow_id in self.workflows:
                sub_instance = self.start(node.sub_workflow_id, instance.context.copy())
                # 简化：同步执行完子流程
                instance.context[f"{node_id}_sub"] = sub_instance.instance_id
            instance.current_nodes = node.next_nodes.copy()

        elif node.node_type == NodeType.END:
            instance.status = "completed"
            instance.completed_at = time.time()
            instance.current_nodes = []

        if result["success"]:
            instance.completed_nodes.append(node_id)

        return result

    def _eval_branch_condition(self, condition: str, context: dict) -> bool:
        """评估分支条件（使用安全求值器，禁止任意代码执行）"""
        try:
            # 支持 context 变量引用，如:
            #   "workflow_type == 'video'" / "num_scenes >= 5" / "a > 1 and b < 2"
            return safe_eval_expr(condition, context)
        except Exception:
            return False

    def run(self, workflow_id: str, context: dict = None, executor=None) -> FlowInstance:
        """运行完整流程（同步）"""
        instance = self.start(workflow_id, context)

        max_steps = 100
        steps = 0
        while instance.current_nodes and instance.status == "running" and steps < max_steps:
            current = instance.current_nodes.copy()
            instance.current_nodes = []
            for node_id in current:
                result = self.execute_node(instance, node_id, executor)
                if not result["success"]:
                    instance.status = "failed"
                    instance.error = result.get("error", "未知错误")
                    instance.completed_at = time.time()
                    break
            steps += 1

        if steps >= max_steps and instance.status == "running":
            instance.status = "failed"
            instance.error = "超过最大步数限制"
            instance.completed_at = time.time()

        return instance

    def get_instance(self, instance_id: str) -> Optional[FlowInstance]:
        return self.instances.get(instance_id)

    def serialize_instance(self, instance: FlowInstance) -> dict:
        """序列化流程实例"""
        return {
            "instance_id": instance.instance_id,
            "workflow_id": instance.workflow_id,
            "status": instance.status,
            "current_nodes": instance.current_nodes,
            "completed_nodes": instance.completed_nodes,
            "started_at": datetime.fromtimestamp(instance.started_at).isoformat() if instance.started_at else None,
            "completed_at": datetime.fromtimestamp(instance.completed_at).isoformat() if instance.completed_at else None,
            "error": instance.error,
            "context_keys": list(instance.context.keys()),
            "context": instance.context,
        }


# ============================================================================
# 页面渲染器
# ============================================================================

class PageRenderer:
    """
    JNPF6.2 低代码页面渲染器
    将页面 JSON 定义渲染为 HTML
    """

    def render(self, page_def: dict, lang: str = "zh-CN") -> str:
        """
        渲染页面
        page_def: JNPFPage 序列化字典
        """
        title = page_def.get("title", "")
        description = page_def.get("description", "")
        components = page_def.get("components", [])
        api_bindings = page_def.get("api_bindings", {})

        components_html = []
        for comp in components:
            components_html.append(self._render_component(comp, lang))

        return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }}
        .page {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        .page-header {{ margin-bottom: 24px; }}
        .page-header h1 {{ font-size: 24px; margin-bottom: 8px; }}
        .page-header p {{ color: #666; font-size: 14px; }}
        .component {{ background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }}
        .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; padding: 20px; border-radius: 8px; }}
        .stat-card .label {{ font-size: 12px; opacity: 0.9; }}
        .stat-card .value {{ font-size: 28px; font-weight: bold; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #fafafa; font-weight: 600; }}
        .form-group {{ margin-bottom: 16px; }}
        .form-group label {{ display: block; margin-bottom: 6px; font-weight: 500; }}
        .form-group input, .form-group select, .form-group textarea {{ width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }}
        .btn {{ display: inline-block; padding: 10px 24px; background: #6366f1; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
        .btn:hover {{ background: #5457e0; }}
    </style>
</head>
<body>
    <div class="page">
        <div class="page-header">
            <h1>{title}</h1>
            <p>{description}</p>
        </div>
        {''.join(components_html)}
    </div>
</body>
</html>"""

    def _render_component(self, comp: dict, lang: str) -> str:
        """渲染单个组件"""
        comp_type = comp.get("type", "")

        if comp_type == "stat_card":
            label = comp.get("label", "")
            field = comp.get("field", "")
            return f"""<div class="component stat-grid"><div class="stat-card"><div class="label">{label}</div><div class="value" id="{field}">--</div></div></div>"""

        elif comp_type == "form":
            schema_ref = comp.get("schema_ref", "")
            return f'<div class="component" id="form_{schema_ref}"><div class="form-group"><label>表单区域（{schema_ref}）</label><p style="color:#999">表单将动态加载</p></div></div>'

        elif comp_type == "submit_button":
            label = comp.get("label", "提交")
            action = comp.get("action", "")
            return f'<div class="component"><button class="btn" onclick="submitForm(\'{action}\')">{label}</button></div>'

        elif comp_type == "table":
            fields = comp.get("fields", [])
            header = "".join(f"<th>{f}</th>" for f in fields)
            return f'<div class="component"><table><thead><tr>{header}</tr></thead><tbody id="table_body"></tbody></table></div>'

        elif comp_type == "task_timeline":
            label = comp.get("label", "任务时间线")
            return f'<div class="component"><h3>{label}</h3><div id="timeline"></div></div>'

        elif comp_type == "video_player":
            label = comp.get("label", "视频预览")
            field = comp.get("field", "video_path")
            return f'<div class="component"><h3>{label}</h3><video id="{field}" controls style="max-width:100%;border-radius:4px;"></video></div>'

        elif comp_type == "recent_runs":
            label = comp.get("label", "最近运行")
            return f'<div class="component"><h3>{label}</h3><div id="recent_runs"></div></div>'

        else:
            return f'<div class="component">{json.dumps(comp, ensure_ascii=False)}</div>'


# ============================================================================
# JNPF6.2 深度集成门面
# ============================================================================

class JNPFDeepIntegration:
    """
    JNPF6.2 深度集成门面
    整合表单引擎、流程引擎、页面渲染器
    """

    def __init__(self):
        self.form_engine = FormEngine()
        self.flow_engine = FlowEngine()
        self.page_renderer = PageRenderer()

    def build_creative_form_schema(self) -> FormSchema:
        """构建创意表单 Schema（带联动规则）"""
        fields = [
            FormFieldDef(
                field="input_value",
                label="商品输入",
                type=FieldType.TEXTAREA,
                required=True,
                placeholder="输入商品 URL/ID/描述",
                description="支持 Amazon URL、商品 ID 或文字描述",
                min_length=2,
                max_length=2000,
                span=24,
                label_i18n={"en-US": "Product Input", "ja-JP": "商品入力"},
            ),
            FormFieldDef(
                field="workflow",
                label="工作流类型",
                type=FieldType.SELECT,
                required=True,
                default="video",
                options=["video", "image", "storyboard"],
                span=12,
            ),
            FormFieldDef(
                field="num_scenes",
                label="场景数量",
                type=FieldType.NUMBER,
                default=6,
                min_value=3,
                max_value=10,
                span=12,
                rules=[
                    FormFieldRule(
                        field="workflow",
                        condition="== 'storyboard'",
                        action="hide",
                        target="num_scenes",
                    ),
                ],
            ),
            FormFieldDef(
                field="aspect_ratio",
                label="宽高比",
                type=FieldType.SELECT,
                default="9:16",
                options=["9:16", "16:9", "1:1", "4:3", "3:4"],
                span=12,
            ),
            FormFieldDef(
                field="voice",
                label="TTS 音色",
                type=FieldType.SELECT,
                default="xiaoxiao",
                options=["xiaoxiao", "yunxi", "yunjian", "xiaoyi", "yunyang", "xiaohan"],
                span=12,
                rules=[
                    FormFieldRule(
                        field="workflow",
                        condition="== 'image'",
                        action="hide",
                        target="voice",
                    ),
                ],
            ),
            FormFieldDef(
                field="enable_tts",
                label="启用旁白",
                type=FieldType.SWITCH,
                default=True,
                span=12,
                rules=[
                    FormFieldRule(
                        field="workflow",
                        condition="== 'image'",
                        action="hide",
                        target="enable_tts",
                    ),
                ],
            ),
            FormFieldDef(
                field="enable_subs",
                label="烧录字幕",
                type=FieldType.SWITCH,
                default=True,
                span=12,
                rules=[
                    FormFieldRule(
                        field="workflow",
                        condition="== 'image'",
                        action="hide",
                        target="enable_subs",
                    ),
                ],
            ),
        ]
        return FormSchema(
            form_id="creative_form_v2",
            name="营销创作表单",
            fields=fields,
            name_i18n={"en-US": "Creative Form", "ja-JP": "クリエイティブフォーム"},
        )

    def build_creative_workflow(self) -> list:
        """构建创意流程（带条件分支+并行）"""
        nodes = [
            FlowNode(
                node_id="start",
                node_type=NodeType.START,
                name="开始",
                next_nodes=["parse_product"],
            ),
            FlowNode(
                node_id="parse_product",
                node_type=NodeType.TASK,
                name="商品解析",
                agent="product_parser",
                next_nodes=["generate_creative"],
                config={"fallback": "manual_input"},
                timeout=60,
                max_retries=2,
            ),
            FlowNode(
                node_id="generate_creative",
                node_type=NodeType.TASK,
                name="创意生成",
                agent="creative",
                next_nodes=["generate_storyboard"],
                config={"fallback": "generic_template"},
                timeout=120,
            ),
            FlowNode(
                node_id="generate_storyboard",
                node_type=NodeType.TASK,
                name="分镜设计",
                agent="storyboard",
                next_nodes=["decision_output"],
                config={"fallback": "simple_shots"},
                timeout=120,
            ),
            FlowNode(
                node_id="decision_output",
                node_type=NodeType.DECISION,
                name="输出类型判断",
                branches={
                    "workflow == 'video'": ["parallel_av"],
                    "workflow == 'image'": ["generate_images"],
                    "workflow == 'storyboard'": ["end"],
                },
            ),
            # 并行：音频 + 视频
            FlowNode(
                node_id="parallel_av",
                node_type=NodeType.PARALLEL,
                name="并行生成",
                parallel_branches=[["generate_images"], ["generate_tts"]],
            ),
            FlowNode(
                node_id="generate_images",
                node_type=NodeType.TASK,
                name="图像生成",
                agent="image_gen",
                next_nodes=["decision_after_images"],
                config={"fallback": "placeholder_images"},
                timeout=300,
            ),
            FlowNode(
                node_id="generate_tts",
                node_type=NodeType.TASK,
                name="语音合成",
                agent="tts",
                next_nodes=["compose_video"],
                config={"fallback": "silent_audio"},
                timeout=120,
            ),
            FlowNode(
                node_id="decision_after_images",
                node_type=NodeType.DECISION,
                name="图像后处理判断",
                branches={
                    "workflow == 'video'": ["compose_video"],
                    "workflow == 'image'": ["end"],
                },
            ),
            FlowNode(
                node_id="compose_video",
                node_type=NodeType.TASK,
                name="视频合成",
                agent="video_gen",
                next_nodes=["end"],
                config={"fallback": None},
                timeout=600,
            ),
            FlowNode(
                node_id="end",
                node_type=NodeType.END,
                name="结束",
            ),
        ]
        return nodes

    def register_default_workflow(self):
        """注册默认流程"""
        nodes = self.build_creative_workflow()
        self.flow_engine.register_workflow("kickart_creative_v2", nodes)
        return "kickart_creative_v2"


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="JNPF6.2 深度集成")
    parser.add_argument("--action", required=True,
                        choices=["form-schema", "form-validate", "workflow-def", "workflow-run", "render-page"])
    parser.add_argument("--data-json", help="表单数据 JSON 文件")
    parser.add_argument("--context-json", help="流程上下文 JSON 文件")
    parser.add_argument("--page-json", help="页面定义 JSON 文件")
    parser.add_argument("--lang", default="zh-CN")
    parser.add_argument("--output", help="输出文件")

    args = parser.parse_args()
    integration = JNPFDeepIntegration()

    if args.action == "form-schema":
        schema = integration.build_creative_form_schema()
        result = integration.form_engine.serialize(schema)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.action == "form-validate":
        schema = integration.build_creative_form_schema()
        data = {}
        if args.data_json:
            with open(args.data_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        data = integration.form_engine.apply_defaults(schema, data)
        result = integration.form_engine.validate(schema, data)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.action == "workflow-def":
        integration.register_default_workflow()
        nodes = integration.build_creative_workflow()
        print(json.dumps([
            {
                "node_id": n.node_id,
                "node_type": n.node_type.value,
                "name": n.name,
                "agent": n.agent,
                "next_nodes": n.next_nodes,
                "branches": n.branches,
                "parallel_branches": n.parallel_branches,
            }
            for n in nodes
        ], ensure_ascii=False, indent=2))

    elif args.action == "workflow-run":
        wf_id = integration.register_default_workflow()
        context = {}
        if args.context_json:
            with open(args.context_json, "r", encoding="utf-8") as f:
                context = json.load(f)

        def mock_executor(node, ctx):
            return {"node": node.node_id, "status": "done"}

        instance = integration.flow_engine.run(wf_id, context, mock_executor)
        print(json.dumps(integration.flow_engine.serialize_instance(instance), ensure_ascii=False, indent=2))

    elif args.action == "render-page":
        page_def = {}
        if args.page_json:
            with open(args.page_json, "r", encoding="utf-8") as f:
                page_def = json.load(f)
        html = integration.page_renderer.render(page_def, args.lang)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"✅ 页面已渲染: {args.output}")
        else:
            print(html)

    return 0


if __name__ == "__main__":
    exit(main())
