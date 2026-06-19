"""
LLM 智能创意生成 - AI 驱动的个性化营销创意
V7 升级：接入多提供商智能路由层（DeepSeek/智谱GLM/火山Ark/Stability）
支持按用途路由、故障转移、多 Key 轮询、熔断保护
保留旧接口兼容（OpenAI/Anthropic/Local Provider）
自动回退到模板生成（保证可用性）
"""
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# 添加 creative 脚本路径（用于回退）
_CREATIVE_PATH = Path(__file__).parent.parent.parent / "agents" / "creative" / "scripts"
if str(_CREATIVE_PATH) not in sys.path:
    sys.path.insert(0, str(_CREATIVE_PATH))

# 添加 observability 路径
_OBS_PATH = Path(__file__).parent.parent.parent / "platform" / "observability"
if str(_OBS_PATH) not in sys.path:
    sys.path.insert(0, str(_OBS_PATH))

# 添加 llm 路由层路径
_LLM_PATH = Path(__file__).parent.parent.parent / "platform" / "llm"
if str(_LLM_PATH) not in sys.path:
    sys.path.insert(0, str(_LLM_PATH))

from logger import get_logger

logger = get_logger(__name__)


# ============ 旧版 LLM 提供商（保留兼容） ============

class LLMProvider:
    """LLM 提供商基类（旧版，保留兼容）"""

    def __init__(self, model: str, api_key: str = None, base_url: str = None):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, max_tokens: int = 2000) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    """OpenAI / 兼容 API（旧版，保留兼容）"""

    def __init__(self, model: str = "gpt-4o-mini", api_key: str = None, base_url: str = None):
        super().__init__(model, api_key or os.environ.get("OPENAI_API_KEY"), base_url or os.environ.get("OPENAI_BASE_URL"))

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, max_tokens: int = 2000) -> str:
        import requests
        url = (self.base_url or "https://api.openai.com/v1") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class AnthropicProvider(LLMProvider):
    """Anthropic Claude（旧版，保留兼容）"""

    def __init__(self, model: str = "claude-3-5-haiku-20241022", api_key: str = None):
        super().__init__(model, api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, max_tokens: int = 2000) -> str:
        import requests
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


class LocalLLMProvider(LLMProvider):
    """本地 LLM（如 Ollama / vLLM）"""

    def __init__(self, model: str = "qwen2.5:7b", base_url: str = None):
        super().__init__(model, base_url=base_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434"))

    def is_available(self) -> bool:
        try:
            import requests
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, max_tokens: int = 2000) -> str:
        import requests
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


# ============ V7 路由层适配器 ============

class RouterProvider(LLMProvider):
    """
    V7 路由层适配器
    将 LLMRouter 包装为旧版 LLMProvider 接口
    实现新旧接口兼容
    """

    def __init__(self, purpose: str = None, preferred_provider: str = None, model: str = None):
        from router import get_router
        self.router = get_router()
        self.purpose = purpose or os.environ.get("KICKART_LLM_DEFAULT_PURPOSE", "aigc_marketing")
        self.preferred_provider = preferred_provider
        self.model = model
        # 旧接口兼容字段
        self.api_key = "router_managed"
        self.base_url = "router_managed"

    def is_available(self) -> bool:
        """检查路由器是否有可用提供商"""
        status = self.router.get_router_status()
        return status["available_providers"] > 0

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, max_tokens: int = 2000) -> str:
        """通过路由层生成"""
        result = self.router.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            purpose=self.purpose,
            temperature=temperature,
            max_tokens=max_tokens,
            model=self.model,
            preferred_provider=self.preferred_provider,
        )
        if result.get("error"):
            raise RuntimeError(result["error"])
        # 更新 model 字段为实际使用的模型
        self.model = result.get("model", self.model)
        return result["text"]


# ============ 提示词工程 ============

SYSTEM_PROMPT = """你是顶尖的营销创意总监，擅长为电商商品创作短视频营销脚本。

你的创意原则：
1. 前3秒必须制造强烈钩子（提问/冲突/惊喜/痛点）
2. 痛点-解决方案结构：明确用户痛点，展示商品如何解决
3. 融入社会证明（用户评价/使用场景/数据）
4. 结尾有明确的行动召唤（CTA）
5. 每个场景的旁白口语化、有感染力

输出要求：严格的 JSON 格式，不要任何额外说明文字。"""


def build_user_prompt(product_info: dict, num_scenes: int = 6, style: str = "viral") -> str:
    """构建用户提示词"""
    style_guides = {
        "viral": "爆款病毒式：节奏快、情绪强、有反转",
        "elegant": "优雅品质：节奏舒缓、画面精致、强调质感",
        "professional": "专业测评：数据驱动、客观对比、理性说服",
        "emotional": "情感共鸣：故事化、代入感强、有温度",
        "energetic": "活力青春：动感、明快、有节奏感",
    }

    return f"""请为以下商品创作 {num_scenes} 个场景的短视频营销脚本。

商品信息：
- 标题：{product_info.get('title', '未知商品')}
- 类目：{product_info.get('category', '通用')}
- 描述：{product_info.get('description', '')}
- 卖点：{', '.join(product_info.get('selling_points', [])) or '待挖掘'}
- 目标人群：{product_info.get('target_audience', '通用人群')}

风格要求：{style_guides.get(style, style_guides['viral'])}

请输出以下 JSON 格式（不要 markdown 代码块）：
{{
  "creative_id": "auto",
  "theme": "创意主题（10字内）",
  "storyline": "故事线概述（30字内）",
  "target_audience": "精准目标人群",
  "tone": "调性关键词",
  "total_duration": {num_scenes * 5},
  "style": "{style}",
  "scenes": [
    {{
      "scene_id": 1,
      "title": "场景标题",
      "duration_sec": 5,
      "visual_description": "画面描述（镜头/场景/动作）",
      "voiceover": "旁白文案（口语化，有感染力）",
      "text_overlay": "画面文字（简短有力）",
      "hook_type": "钩子类型（question/conflict/surprise/pain_point/social_proof/cta）",
      "emotion": "情绪（curiosity/desire/trust/urgency/joy）"
    }}
  ]
}}"""


# ============ 智能创意生成器 ============

class IntelligentCreativeGenerator:
    """
    AI 智能创意生成器
    V7：优先使用路由层（多提供商），回退到旧版单提供商，最终回退到模板
    - 优先使用 LLM 路由层生成个性化创意
    - 路由层不可用时回退到旧版单提供商
    - 所有 LLM 不可用时回退到模板生成
    - 支持指定用途和偏好提供商
    """

    def __init__(self, provider: LLMProvider = None, purpose: str = None, preferred_provider: str = None):
        """
        Args:
            provider: 旧版提供商（兼容）
            purpose: V7 用途（jnpf_team/cross_border_ecommerce/aigc_marketing）
            preferred_provider: V7 偏好提供商 ID
        """
        self.provider = provider
        self.purpose = purpose
        self.preferred_provider = preferred_provider
        self._fallback_count = 0
        self._llm_count = 0
        self._router_used = False

    @classmethod
    def auto_select(cls, purpose: str = None, preferred_provider: str = None) -> "IntelligentCreativeGenerator":
        """
        自动选择可用的 LLM 提供商
        V7 优先级：路由层 → 旧版 OpenAI → 旧版 Anthropic → 本地 → 模板
        """
        # 1. 优先尝试 V7 路由层
        try:
            router_provider = RouterProvider(purpose=purpose, preferred_provider=preferred_provider)
            if router_provider.is_available():
                logger.info(f"V7 路由层可用（purpose={purpose or 'default'}）")
                return cls(provider=router_provider, purpose=purpose, preferred_provider=preferred_provider)
        except Exception as e:
            logger.debug(f"V7 路由层不可用: {e}")

        # 2. 回退到旧版提供商
        providers = [
            OpenAIProvider(),
            AnthropicProvider(),
            LocalLLMProvider(),
        ]
        for p in providers:
            if p.is_available():
                logger.info(f"LLM 提供商可用: {p.__class__.__name__} (model={p.model})")
                return cls(provider=p)
        logger.warning("无可用 LLM 提供商，将使用模板回退")
        return cls(provider=None)

    def generate(
        self,
        product_info: dict,
        num_scenes: int = 6,
        style: str = "viral",
        temperature: float = 0.8,
    ) -> dict:
        """
        生成创意脚本

        Args:
            product_info: 商品信息
            num_scenes: 场景数
            style: 风格（viral/elegant/professional/emotional/energetic）
            temperature: 创意度（0.0-1.0）

        Returns:
            创意脚本 JSON
        """
        if self.provider and self.provider.is_available():
            try:
                creative = self._generate_with_llm(product_info, num_scenes, style, temperature)
                self._llm_count += 1
                logger.info(f"LLM 创意生成成功: theme={creative.get('theme')}")
                return creative
            except Exception as e:
                logger.warning(f"LLM 生成失败，回退到模板: {e}")

        # 回退到模板生成
        creative = self._generate_with_template(product_info, num_scenes)
        self._fallback_count += 1
        logger.info(f"模板创意生成: theme={creative.get('theme')}")
        return creative

    def _generate_with_llm(
        self, product_info: dict, num_scenes: int, style: str, temperature: float
    ) -> dict:
        """使用 LLM 生成"""
        user_prompt = build_user_prompt(product_info, num_scenes, style)

        start = time.time()
        raw = self.provider.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=2000,
        )
        duration = time.time() - start
        logger.info(f"LLM 响应耗时: {duration:.2f}s, 长度: {len(raw)}")

        # 解析 JSON（容错处理）
        creative = self._parse_llm_output(raw)
        creative["creative_id"] = f"llm_{uuid.uuid4().hex[:8]}"
        creative["generated_by"] = "llm"
        creative["llm_model"] = self.provider.model
        creative["llm_duration_sec"] = round(duration, 2)
        creative["style"] = style
        # V7 路由层信息
        if isinstance(self.provider, RouterProvider):
            creative["router_used"] = True
            creative["purpose"] = self.provider.purpose
        return creative

    def _parse_llm_output(self, raw: str) -> dict:
        """解析 LLM 输出（容错）"""
        # 去除可能的 markdown 代码块
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            raise ValueError(f"无法解析 LLM 输出为 JSON: {raw[:200]}")

    def _generate_with_template(self, product_info: dict, num_scenes: int) -> dict:
        """模板回退生成"""
        from creative_gen import generate_creative
        creative = generate_creative(
            product_info=product_info,
            num_scenes=num_scenes,
        )
        creative["generated_by"] = "template"
        return creative

    def get_stats(self) -> dict:
        """获取生成统计"""
        total = self._llm_count + self._fallback_count
        return {
            "total": total,
            "llm_generated": self._llm_count,
            "template_fallback": self._fallback_count,
            "llm_ratio": round(self._llm_count / total, 2) if total > 0 else 0,
            "router_used": isinstance(self.provider, RouterProvider),
        }


# ============ 批量风格生成 ============

def generate_multi_style(
    product_info: dict,
    styles: list = None,
    num_scenes: int = 6,
    purpose: str = None,
) -> list[dict]:
    """
    为同一商品生成多种风格的创意（用于 A/B 测试）
    V7 支持指定用途路由

    Args:
        product_info: 商品信息
        styles: 风格列表
        num_scenes: 场景数
        purpose: V7 用途

    Returns:
        多个创意脚本列表
    """
    if styles is None:
        styles = ["viral", "elegant", "professional"]

    generator = IntelligentCreativeGenerator.auto_select(purpose=purpose)
    creatives = []
    for style in styles:
        creative = generator.generate(
            product_info=product_info,
            num_scenes=num_scenes,
            style=style,
        )
        creatives.append(creative)

    return creatives


# ============ CLI 入口 ============

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LLM 智能创意生成")
    parser.add_argument("--product-json", required=True, help="商品信息 JSON 文件")
    parser.add_argument("--output", default="creative_llm.json", help="输出文件")
    parser.add_argument("--num-scenes", type=int, default=6)
    parser.add_argument("--style", default="viral", choices=["viral", "elegant", "professional", "emotional", "energetic"])
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--multi-style", action="store_true", help="生成多风格（A/B 测试）")
    # V7 新增参数
    parser.add_argument("--purpose", default=None,
                        choices=["jnpf_team", "cross_border_ecommerce", "aigc_marketing", "default"],
                        help="V7 业务用途路由")
    parser.add_argument("--preferred-provider", default=None,
                        help="V7 偏好提供商 ID")

    args = parser.parse_args()

    with open(args.product_json, "r", encoding="utf-8") as f:
        product_info = json.load(f)

    if args.multi_style:
        creatives = generate_multi_style(product_info, num_scenes=args.num_scenes, purpose=args.purpose)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(creatives, f, ensure_ascii=False, indent=2)
        print(f"✅ 生成 {len(creatives)} 个风格创意: {args.output}")
    else:
        generator = IntelligentCreativeGenerator.auto_select(
            purpose=args.purpose,
            preferred_provider=args.preferred_provider,
        )
        creative = generator.generate(
            product_info=product_info,
            num_scenes=args.num_scenes,
            style=args.style,
            temperature=args.temperature,
        )
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(creative, f, ensure_ascii=False, indent=2)
        print(f"✅ 创意生成: {args.output}")
        print(f"   生成方式: {creative.get('generated_by')}")
        print(f"   主题: {creative.get('theme')}")
        print(f"   场景数: {len(creative.get('scenes', []))}")
        if creative.get("router_used"):
            print(f"   路由层: 已使用 (purpose={creative.get('purpose')})")
        stats = generator.get_stats()
        print(f"   统计: LLM {stats['llm_generated']}, 模板 {stats['template_fallback']}, 路由层 {stats['router_used']}")


if __name__ == "__main__":
    exit(main())
