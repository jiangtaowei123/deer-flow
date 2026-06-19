"""
复利系统指令集扩展 - 资产复用、模板继承、组合编排
基于复利理念：每次生成的资产都可累积、继承、复用、组合
这是对 instruction_set.py 的深度扩展，实现真正的"复利"效应
扩展能力：
1. 资产继承 - 子资产继承父资产的属性
2. 模板系统 - 可参数化的资产模板
3. 组合编排 - 多指令的 DAG 编排
4. 版本管理 - 资产版本演进
5. 依赖追踪 - 资产间依赖关系
"""
import copy
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ============================================================================
# 扩展数据模型
# ============================================================================

class AssetRelation(str, Enum):
    """资产关系类型"""
    INHERITS = "inherits"      # 继承
    DEPENDS_ON = "depends_on"  # 依赖
    COMPOSED_OF = "composed_of"  # 组合自
    DERIVED_FROM = "derived_from"  # 派生自
    REPLACES = "replaces"      # 替代


@dataclass
class AssetVersion:
    """资产版本"""
    version_id: str
    version: str  # semver: 1.0.0
    asset_id: str
    path: str
    changelog: str = ""
    created_at: Optional[float] = None
    created_by: str = "system"


@dataclass
class AssetTemplate:
    """资产模板（可参数化）"""
    template_id: str
    name: str
    description: str
    asset_type: str  # system/component/template/config/dataset
    # 模板参数 schema
    params_schema: dict = field(default_factory=dict)
    # 模板内容（含占位符 {param_name}）
    template_content: dict = field(default_factory=dict)
    # 继承的父模板
    parent_template: Optional[str] = None
    created_at: Optional[float] = None
    use_count: int = 0


@dataclass
class CompositionDAG:
    """组合编排 DAG"""
    dag_id: str
    name: str
    nodes: dict = field(default_factory=dict)  # node_id -> CompositionNode
    edges: list = field(default_factory=list)  # [(from, to), ...]
    created_at: Optional[float] = None


@dataclass
class CompositionNode:
    """组合节点"""
    node_id: str
    instruction: str  # 指令名
    params: dict = field(default_factory=dict)
    # 输入映射：从上游节点输出取值
    input_mapping: dict = field(default_factory=dict)  # {param: "node_id.output_key"}
    # 输出名称
    output_name: str = "output"
    status: str = "pending"  # pending/running/success/failed
    result: dict = field(default_factory=dict)


# ============================================================================
# 扩展的指令模板
# ============================================================================

EXTENDED_TEMPLATES = {
    # ============ 模板类指令 ============
    "template.create": {
        "type": "template",
        "target": "asset_template",
        "description": "创建可参数化的资产模板",
        "params_schema": {
            "name": {"type": "string", "required": True},
            "asset_type": {"type": "string", "required": True},
            "template_content": {"type": "dict", "required": True},
            "parent_template": {"type": "string", "required": False},
        },
        "produces": "template_asset",
    },
    "template.instantiate": {
        "type": "template",
        "target": "template_instance",
        "description": "从模板实例化资产",
        "params_schema": {
            "template_id": {"type": "string", "required": True},
            "params": {"type": "dict", "default": {}},
        },
        "produces": "instantiated_asset",
    },
    "template.inherit": {
        "type": "template",
        "target": "inherited_template",
        "description": "继承父模板创建子模板",
        "params_schema": {
            "parent_template_id": {"type": "string", "required": True},
            "child_name": {"type": "string", "required": True},
            "overrides": {"type": "dict", "default": {}},
        },
        "produces": "child_template",
    },

    # ============ 资产复用类指令 ============
    "asset.reuse": {
        "type": "reuse",
        "target": "reused_asset",
        "description": "复用已有资产（增加复用计数）",
        "params_schema": {
            "asset_id": {"type": "string", "required": True},
            "context": {"type": "dict", "default": {}},
        },
        "produces": "reuse_record",
    },
    "asset.version": {
        "type": "version",
        "target": "asset_version",
        "description": "创建资产新版本",
        "params_schema": {
            "asset_id": {"type": "string", "required": True},
            "version": {"type": "string", "required": True},
            "path": {"type": "string", "required": True},
            "changelog": {"type": "string", "default": ""},
        },
        "produces": "version_record",
    },
    "asset.derive": {
        "type": "derive",
        "target": "derived_asset",
        "description": "从已有资产派生新资产",
        "params_schema": {
            "source_asset_id": {"type": "string", "required": True},
            "modifications": {"type": "dict", "required": True},
            "new_name": {"type": "string", "required": True},
        },
        "produces": "derived_asset",
    },

    # ============ 组合编排类指令 ============
    "compose.dag": {
        "type": "compose_dag",
        "target": "dag_composition",
        "description": "DAG 组合编排多指令",
        "params_schema": {
            "dag_def": {"type": "dict", "required": True},
        },
        "produces": "dag_result",
    },
    "compose.parallel": {
        "type": "compose_parallel",
        "target": "parallel_composition",
        "description": "并行执行多指令",
        "params_schema": {
            "instructions": {"type": "list", "required": True},
        },
        "produces": "parallel_result",
    },
    "compose.pipeline": {
        "type": "compose_pipeline",
        "target": "pipeline_composition",
        "description": "管道式串联执行（上游输出→下游输入）",
        "params_schema": {
            "steps": {"type": "list", "required": True},
        },
        "produces": "pipeline_result",
    },
}


# ============================================================================
# 资产模板管理器
# ============================================================================

class AssetTemplateManager:
    """
    资产模板管理器
    - 模板 CRUD
    - 模板继承
    - 参数化实例化
    - 占位符替换
    """

    def __init__(self, storage_path: str = "/mnt/user-data/workspace/compound_templates"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.templates: dict[str, AssetTemplate] = {}
        self._load()

    def _load(self):
        """加载模板"""
        tpl_file = self.storage_path / "templates.json"
        if tpl_file.exists():
            with open(tpl_file, "r", encoding="utf-8") as f:
                for t_data in json.load(f).get("templates", []):
                    tpl = AssetTemplate(**t_data)
                    self.templates[tpl.template_id] = tpl

    def _save(self):
        """保存模板"""
        with open(self.storage_path / "templates.json", "w", encoding="utf-8") as f:
            json.dump({
                "templates": [
                    {
                        "template_id": t.template_id,
                        "name": t.name,
                        "description": t.description,
                        "asset_type": t.asset_type,
                        "params_schema": t.params_schema,
                        "template_content": t.template_content,
                        "parent_template": t.parent_template,
                        "created_at": t.created_at,
                        "use_count": t.use_count,
                    }
                    for t in self.templates.values()
                ],
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def create_template(
        self,
        name: str,
        description: str,
        asset_type: str,
        template_content: dict,
        params_schema: dict = None,
        parent_template: str = None,
    ) -> AssetTemplate:
        """创建模板"""
        # 如果有父模板，先继承
        if parent_template:
            parent = self.templates.get(parent_template)
            if parent:
                # 合并：父模板内容 + 子模板覆盖
                merged_content = copy.deepcopy(parent.template_content)
                merged_content = self._deep_merge(merged_content, template_content)
                template_content = merged_content
                merged_schema = copy.deepcopy(parent.params_schema)
                if params_schema:
                    merged_schema = self._deep_merge(merged_schema, params_schema)
                params_schema = merged_schema

        tpl = AssetTemplate(
            template_id=f"tpl_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            asset_type=asset_type,
            params_schema=params_schema or {},
            template_content=template_content,
            parent_template=parent_template,
            created_at=time.time(),
        )
        self.templates[tpl.template_id] = tpl
        self._save()
        return tpl

    def instantiate(self, template_id: str, params: dict = None) -> dict:
        """实例化模板（参数替换）"""
        tpl = self.templates.get(template_id)
        if not tpl:
            raise ValueError(f"模板不存在: {template_id}")

        params = params or {}
        # 校验必填参数
        for param_name, schema in tpl.params_schema.items():
            if schema.get("required") and param_name not in params:
                if "default" not in schema:
                    raise ValueError(f"缺少必填参数: {param_name}")
                params[param_name] = schema["default"]

        # 填充默认值
        for param_name, schema in tpl.params_schema.items():
            if param_name not in params and "default" in schema:
                params[param_name] = schema["default"]

        # 递归替换占位符
        content = copy.deepcopy(tpl.template_content)
        content = self._replace_placeholders(content, params)

        tpl.use_count += 1
        self._save()

        return {
            "template_id": template_id,
            "template_name": tpl.name,
            "params": params,
            "content": content,
            "instantiated_at": datetime.now().isoformat(),
        }

    def inherit(
        self,
        parent_template_id: str,
        child_name: str,
        overrides: dict,
        description: str = "",
    ) -> AssetTemplate:
        """继承父模板创建子模板"""
        parent = self.templates.get(parent_template_id)
        if not parent:
            raise ValueError(f"父模板不存在: {parent_template_id}")

        merged_content = self._deep_merge(copy.deepcopy(parent.template_content), overrides)

        child = AssetTemplate(
            template_id=f"tpl_{uuid.uuid4().hex[:12]}",
            name=child_name,
            description=description or f"继承自 {parent.name}",
            asset_type=parent.asset_type,
            params_schema=copy.deepcopy(parent.params_schema),
            template_content=merged_content,
            parent_template=parent_template_id,
            created_at=time.time(),
        )
        self.templates[child.template_id] = child
        self._save()
        return child

    def list_templates(self) -> list:
        return [
            {
                "template_id": t.template_id,
                "name": t.name,
                "description": t.description,
                "asset_type": t.asset_type,
                "parent_template": t.parent_template,
                "use_count": t.use_count,
                "params": list(t.params_schema.keys()),
                "created_at": datetime.fromtimestamp(t.created_at).isoformat() if t.created_at else None,
            }
            for t in self.templates.values()
        ]

    def get_template(self, template_id: str) -> Optional[AssetTemplate]:
        return self.templates.get(template_id)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并字典"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = AssetTemplateManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def _replace_placeholders(obj: any, params: dict) -> any:
        """递归替换占位符 {param_name}"""
        if isinstance(obj, str):
            try:
                return obj.format(**params)
            except (KeyError, IndexError, ValueError):
                return obj
        elif isinstance(obj, dict):
            return {k: AssetTemplateManager._replace_placeholders(v, params) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [AssetTemplateManager._replace_placeholders(item, params) for item in obj]
        return obj


# ============================================================================
# 资产版本管理器
# ============================================================================

class AssetVersionManager:
    """
    资产版本管理器
    - 版本创建
    - 版本历史
    - 版本回滚
    - 依赖追踪
    """

    def __init__(self, storage_path: str = "/mnt/user-data/workspace/compound_versions"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.versions: dict[str, list[AssetVersion]] = {}  # asset_id -> [versions]
        self.relations: list[dict] = []  # 资产关系
        self._load()

    def _load(self):
        ver_file = self.storage_path / "versions.json"
        if ver_file.exists():
            with open(ver_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for asset_id, vers in data.get("versions", {}).items():
                    self.versions[asset_id] = [AssetVersion(**v) for v in vers]
                self.relations = data.get("relations", [])

    def _save(self):
        with open(self.storage_path / "versions.json", "w", encoding="utf-8") as f:
            json.dump({
                "versions": {
                    aid: [
                        {
                            "version_id": v.version_id,
                            "version": v.version,
                            "asset_id": v.asset_id,
                            "path": v.path,
                            "changelog": v.changelog,
                            "created_at": v.created_at,
                            "created_by": v.created_by,
                        }
                        for v in vers
                    ]
                    for aid, vers in self.versions.items()
                },
                "relations": self.relations,
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def create_version(
        self,
        asset_id: str,
        version: str,
        path: str,
        changelog: str = "",
        created_by: str = "system",
    ) -> AssetVersion:
        """创建新版本"""
        ver = AssetVersion(
            version_id=f"ver_{uuid.uuid4().hex[:12]}",
            version=version,
            asset_id=asset_id,
            path=path,
            changelog=changelog,
            created_at=time.time(),
            created_by=created_by,
        )
        if asset_id not in self.versions:
            self.versions[asset_id] = []
        self.versions[asset_id].append(ver)
        self._save()
        return ver

    def get_versions(self, asset_id: str) -> list:
        """获取资产版本历史"""
        vers = self.versions.get(asset_id, [])
        return [
            {
                "version_id": v.version_id,
                "version": v.version,
                "path": v.path,
                "changelog": v.changelog,
                "created_at": datetime.fromtimestamp(v.created_at).isoformat() if v.created_at else None,
                "created_by": v.created_by,
            }
            for v in vers
        ]

    def get_latest_version(self, asset_id: str) -> Optional[AssetVersion]:
        """获取最新版本"""
        vers = self.versions.get(asset_id, [])
        return vers[-1] if vers else None

    def get_version(self, asset_id: str, version: str) -> Optional[AssetVersion]:
        """获取指定版本"""
        for v in self.versions.get(asset_id, []):
            if v.version == version:
                return v
        return None

    def add_relation(
        self,
        source_asset_id: str,
        relation: AssetRelation,
        target_asset_id: str,
        metadata: dict = None,
    ):
        """添加资产关系"""
        self.relations.append({
            "source": source_asset_id,
            "relation": relation.value,
            "target": target_asset_id,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
        })
        self._save()

    def get_relations(self, asset_id: str) -> list:
        """获取资产的所有关系"""
        return [
            r for r in self.relations
            if r["source"] == asset_id or r["target"] == asset_id
        ]

    def get_dependents(self, asset_id: str) -> list:
        """获取依赖此资产的所有资产"""
        return [r["source"] for r in self.relations if r["target"] == asset_id and r["relation"] == "depends_on"]


# ============================================================================
# 组合编排引擎
# ============================================================================

class CompositionEngine:
    """
    组合编排引擎
    - DAG 编排
    - 并行执行
    - 管道串联
    - 输入映射
    """

    def __init__(self, instruction_engine=None):
        """
        instruction_engine: CompoundInstructionEngine 实例（来自 instruction_set.py）
        """
        self.instruction_engine = instruction_engine

    def execute_dag(self, dag: CompositionDAG) -> dict:
        """
        执行 DAG
        拓扑排序后按序执行，无依赖的节点可并行
        """
        # 拓扑排序
        order = self._topological_sort(dag)
        if order is None:
            return {"success": False, "error": "DAG 存在循环依赖"}

        results = {}
        for node_id in order:
            node = dag.nodes[node_id]
            node.status = "running"

            # 解析输入映射
            resolved_params = self._resolve_inputs(node, results)

            # 合并参数
            final_params = {**node.params, **resolved_params}

            # 执行指令
            if self.instruction_engine:
                result = self.instruction_engine.execute(node.instruction, final_params)
            else:
                result = {"success": True, "mock": True, "instruction": node.instruction, "params": final_params}

            if not result.get("success"):
                node.status = "failed"
                node.result = result
                return {
                    "success": False,
                    "error": f"节点 {node_id} 执行失败",
                    "failed_node": node_id,
                    "results": results,
                }

            node.status = "success"
            node.result = result
            results[node.output_name] = result

        return {
            "success": True,
            "dag_id": dag.dag_id,
            "results": results,
            "node_count": len(dag.nodes),
        }

    def execute_parallel(self, instructions: list) -> dict:
        """并行执行多指令"""
        import concurrent.futures

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(instructions), 10)) as executor:
            futures = {}
            for item in instructions:
                inst = item.get("instruction")
                params = item.get("params", {})
                name = item.get("name", inst)
                if self.instruction_engine:
                    future = executor.submit(self.instruction_engine.execute, inst, params)
                else:
                    future = executor.submit(lambda i=inst, p=params: {"success": True, "mock": True, "instruction": i, "params": p})
                futures[future] = name

            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    results.append({"name": name, "result": result})
                except Exception as e:
                    results.append({"name": name, "result": {"success": False, "error": str(e)}})

        return {
            "success": all(r["result"].get("success") for r in results),
            "results": results,
            "total": len(results),
        }

    def execute_pipeline(self, steps: list) -> dict:
        """
        管道式串联执行
        steps: [{"instruction": "...", "params": {...}, "output_key": "..."}]
        上游的输出会作为下游的输入（通过 output_key 映射）
        """
        context = {}
        results = []

        for i, step in enumerate(steps):
            inst = step.get("instruction")
            params = {**step.get("params", {})}
            output_key = step.get("output_key", f"step_{i}")

            # 从上下文注入参数
            for param_name, ctx_key in step.get("input_mapping", {}).items():
                if ctx_key in context:
                    params[param_name] = context[ctx_key]

            if self.instruction_engine:
                result = self.instruction_engine.execute(inst, params)
            else:
                result = {"success": True, "mock": True, "instruction": inst, "params": params}

            results.append({"step": i, "instruction": inst, "result": result})

            if not result.get("success"):
                return {
                    "success": False,
                    "failed_step": i,
                    "results": results,
                }

            context[output_key] = result

        return {
            "success": True,
            "results": results,
            "final_output": results[-1]["result"] if results else None,
        }

    def build_dag(
        self,
        name: str,
        nodes_def: list,
        edges_def: list,
    ) -> CompositionDAG:
        """
        构建 DAG
        nodes_def: [{"node_id": "...", "instruction": "...", "params": {...}, "input_mapping": {...}, "output_name": "..."}]
        edges_def: [{"from": "...", "to": "..."}]
        """
        dag = CompositionDAG(
            dag_id=f"dag_{uuid.uuid4().hex[:12]}",
            name=name,
            nodes={},
            edges=[(e["from"], e["to"]) for e in edges_def],
            created_at=time.time(),
        )
        for nd in nodes_def:
            node = CompositionNode(
                node_id=nd["node_id"],
                instruction=nd["instruction"],
                params=nd.get("params", {}),
                input_mapping=nd.get("input_mapping", {}),
                output_name=nd.get("output_name", "output"),
            )
            dag.nodes[node.node_id] = node
        return dag

    def _topological_sort(self, dag: CompositionDAG) -> Optional[list]:
        """拓扑排序"""
        # 计算入度
        in_degree = {nid: 0 for nid in dag.nodes}
        adj = {nid: [] for nid in dag.nodes}
        for frm, to in dag.edges:
            adj[frm].append(to)
            in_degree[to] = in_degree.get(to, 0) + 1

        # Kahn 算法
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(dag.nodes):
            return None  # 存在环
        return order

    def _resolve_inputs(self, node: CompositionNode, results: dict) -> dict:
        """解析输入映射"""
        resolved = {}
        for param_name, mapping in node.input_mapping.items():
            # mapping 格式: "node_output_name.key1.key2"
            parts = mapping.split(".")
            if parts[0] in results:
                value = results[parts[0]]
                for key in parts[1:]:
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        break
                resolved[param_name] = value
        return resolved


# ============================================================================
# 复利系统扩展门面
# ============================================================================

class CompoundSystemExtension:
    """
    复利系统扩展门面
    整合模板管理、版本管理、组合编排
    """

    def __init__(self, base_storage: str = "/mnt/user-data/workspace/compound"):
        self.template_mgr = AssetTemplateManager(storage_path=f"{base_storage}/templates")
        self.version_mgr = AssetVersionManager(storage_path=f"{base_storage}/versions")
        self.composition_engine = CompositionEngine()

    def register_default_templates(self):
        """注册默认模板"""
        # 创意脚本模板
        self.template_mgr.create_template(
            name="营销创意脚本模板",
            description="标准营销创意脚本模板，可参数化",
            asset_type="template",
            template_content={
                "creative_id": "creative_{uuid}",
                "theme": "{theme}",
                "storyline": "{storyline}",
                "target_audience": "{target_audience}",
                "tone": "{tone}",
                "total_duration": "{duration}",
                "scenes": [],
            },
            params_schema={
                "theme": {"type": "string", "required": True},
                "storyline": {"type": "string", "required": True},
                "target_audience": {"type": "string", "default": "general"},
                "tone": {"type": "string", "default": "professional"},
                "duration": {"type": "int", "default": 30},
            },
        )

        # 分镜模板
        self.template_mgr.create_template(
            name="分镜列表模板",
            description="标准分镜列表模板",
            asset_type="template",
            template_content={
                "storyboard_id": "sb_{uuid}",
                "aspect_ratio": "{aspect_ratio}",
                "total_shots": "{num_shots}",
                "shots": [],
            },
            params_schema={
                "aspect_ratio": {"type": "string", "default": "9:16"},
                "num_shots": {"type": "int", "default": 6},
            },
        )

    def build_video_pipeline(self) -> list:
        """构建视频生成管道"""
        return [
            {
                "instruction": "generate.creative",
                "params": {"product_info": {"title": "商品", "description": "描述"}},
                "output_key": "creative",
            },
            {
                "instruction": "generate.storyboard",
                "params": {},
                "input_mapping": {"creative": "creative.creative"},
                "output_key": "storyboard",
            },
            {
                "instruction": "generate.images",
                "params": {},
                "input_mapping": {"storyboard": "storyboard.storyboard"},
                "output_key": "images",
            },
            {
                "instruction": "generate.video",
                "params": {},
                "input_mapping": {
                    "storyboard": "storyboard.storyboard",
                    "images_dir": "images.images_dir",
                },
                "output_key": "video",
            },
        ]


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="复利系统指令集扩展")
    parser.add_argument("--action", required=True,
                        choices=["template-create", "template-list", "template-instantiate",
                                 "template-inherit", "version-create", "version-list",
                                 "compose-pipeline", "compose-parallel", "compose-dag",
                                 "init-defaults"])
    parser.add_argument("--name")
    parser.add_argument("--description", default="")
    parser.add_argument("--asset-type", default="template")
    parser.add_argument("--content-json", help="模板内容 JSON 文件")
    parser.add_argument("--params-json", help="参数 JSON 文件")
    parser.add_argument("--template-id")
    parser.add_argument("--parent-template")
    parser.add_argument("--asset-id")
    parser.add_argument("--version")
    parser.add_argument("--path")
    parser.add_argument("--changelog", default="")
    parser.add_argument("--storage", default="/mnt/user-data/workspace/compound")

    args = parser.parse_args()
    ext = CompoundSystemExtension(base_storage=args.storage)

    if args.action == "init-defaults":
        ext.register_default_templates()
        print("✅ 默认模板已注册")
        print(json.dumps(ext.template_mgr.list_templates(), ensure_ascii=False, indent=2))

    elif args.action == "template-create":
        if not args.name or not args.content_json:
            print("错误: 需要 --name --content-json")
            return 1
        with open(args.content_json, "r", encoding="utf-8") as f:
            content = json.load(f)
        tpl = ext.template_mgr.create_template(
            name=args.name,
            description=args.description,
            asset_type=args.asset_type,
            template_content=content,
            parent_template=args.parent_template,
        )
        print(f"✅ 模板创建: {tpl.template_id}")

    elif args.action == "template-list":
        print(json.dumps(ext.template_mgr.list_templates(), ensure_ascii=False, indent=2))

    elif args.action == "template-instantiate":
        if not args.template_id:
            print("错误: 需要 --template-id")
            return 1
        params = {}
        if args.params_json:
            with open(args.params_json, "r", encoding="utf-8") as f:
                params = json.load(f)
        result = ext.template_mgr.instantiate(args.template_id, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.action == "template-inherit":
        if not args.parent_template or not args.name:
            print("错误: 需要 --parent-template --name")
            return 1
        overrides = {}
        if args.content_json:
            with open(args.content_json, "r", encoding="utf-8") as f:
                overrides = json.load(f)
        child = ext.template_mgr.inherit(args.parent_template, args.name, overrides, args.description)
        print(f"✅ 子模板创建: {child.template_id}（继承自 {args.parent_template}）")

    elif args.action == "version-create":
        if not all([args.asset_id, args.version, args.path]):
            print("错误: 需要 --asset-id --version --path")
            return 1
        ver = ext.version_mgr.create_version(args.asset_id, args.version, args.path, args.changelog)
        print(f"✅ 版本创建: {ver.version_id} (v{ver.version})")

    elif args.action == "version-list":
        if not args.asset_id:
            print("错误: 需要 --asset-id")
            return 1
        print(json.dumps(ext.version_mgr.get_versions(args.asset_id), ensure_ascii=False, indent=2))

    elif args.action == "compose-pipeline":
        pipeline = ext.build_video_pipeline()
        result = ext.composition_engine.execute_pipeline(pipeline)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif args.action == "compose-parallel":
        instructions = [
            {"instruction": "generate.creative", "params": {"product_info": {"title": "A"}}, "name": "creative_a"},
            {"instruction": "generate.creative", "params": {"product_info": {"title": "B"}}, "name": "creative_b"},
        ]
        result = ext.composition_engine.execute_parallel(instructions)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif args.action == "compose-dag":
        nodes_def = [
            {"node_id": "n1", "instruction": "generate.creative", "params": {"product_info": {"title": "X"}}, "output_name": "creative"},
            {"node_id": "n2", "instruction": "generate.storyboard", "input_mapping": {"creative": "creative.creative"}, "output_name": "storyboard"},
        ]
        edges_def = [
            {"from": "n1", "to": "n2"},
        ]
        dag = ext.composition_engine.build_dag("test_dag", nodes_def, edges_def)
        result = ext.composition_engine.execute_dag(dag)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    exit(main())
