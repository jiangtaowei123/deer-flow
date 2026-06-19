"""
LLM 多提供商适配器
支持：DeepSeek / 智谱 GLM / 火山引擎 Ark / Stability AI
所有文本提供商均兼容 OpenAI Chat Completions 接口，差异仅在 base_url 和鉴权头
图片生成提供商使用各自原生接口
基于用户提供的 7 个 API Key 清单（脱敏）实现
"""
import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# 提供商元信息
# ============================================================================

@dataclass
class ProviderMeta:
    """提供商元信息"""
    provider_id: str       # 唯一标识
    name: str              # 显示名称
    provider_type: str     # text / image
    base_url: str          # API 基础 URL
    models: list           # 支持的模型列表
    default_model: str     # 默认模型
    key_env: str           # 环境变量名
    purpose: str = ""      # 用途描述


# 提供商注册表（基于用户提供的 Key 清单）
PROVIDER_REGISTRY = {
    # ============ DeepSeek（3 个 Key） ============
    "deepseek_jnpf": ProviderMeta(
        provider_id="deepseek_jnpf",
        name="DeepSeek #1 (JNPF团队)",
        provider_type="text",
        base_url="https://api.deepseek.com/v1",
        models=["deepseek-v4-flash", "deepseek-v4-pro"],
        default_model="deepseek-v4-flash",
        key_env="DEEPSEEK_KEY_JNPF",
        purpose="jnpf_team",
    ),
    "deepseek_ecommerce": ProviderMeta(
        provider_id="deepseek_ecommerce",
        name="DeepSeek #2 (跨境电商+Paperclip CN)",
        provider_type="text",
        base_url="https://api.deepseek.com/v1",
        models=["deepseek-v4-flash", "deepseek-v4-pro"],
        default_model="deepseek-v4-flash",
        key_env="DEEPSEEK_KEY_ECOMMERCE",
        purpose="cross_border_ecommerce",
    ),
    "deepseek_aigc": ProviderMeta(
        provider_id="deepseek_aigc",
        name="DeepSeek #3 (AIGC数字营销中台)",
        provider_type="text",
        base_url="https://api.deepseek.com/v1",
        models=["deepseek-v4-flash", "deepseek-v4-pro"],
        default_model="deepseek-v4-flash",
        key_env="DEEPSEEK_KEY_AIGC",
        purpose="aigc_marketing",
    ),

    # ============ 智谱 GLM ============
    "glm_ecommerce": ProviderMeta(
        provider_id="glm_ecommerce",
        name="智谱 GLM (跨境电商AI智能体)",
        provider_type="text",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=["glm-4.5", "glm-4.5-air", "glm-4.6", "glm-4.7", "glm-5", "glm-5-turbo", "glm-5.1"],
        default_model="glm-4.6",
        key_env="GLM_KEY_ECOMMERCE",
        purpose="cross_border_ecommerce",
    ),

    # ============ 火山引擎 Ark（2 个 Key） ============
    "ark_default": ProviderMeta(
        provider_id="ark_default",
        name="火山引擎 Ark #1 (AIGC中台默认-豆包)",
        provider_type="text",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        models=["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k", "doubao-seed-1-6", "deepseek-v3-241226"],
        default_model="doubao-pro-32k",
        key_env="ARK_KEY_DEFAULT",
        purpose="aigc_marketing",
    ),
    "ark_backup": ProviderMeta(
        provider_id="ark_backup",
        name="火山引擎 Ark #2 (AIGC中台备用)",
        provider_type="text",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        models=["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k", "doubao-seed-1-6", "deepseek-v3-241226"],
        default_model="doubao-pro-32k",
        key_env="ARK_KEY_BACKUP",
        purpose="aigc_marketing",
    ),

    # ============ Stability AI（图片生成） ============
    "stability_image": ProviderMeta(
        provider_id="stability_image",
        name="Stability AI (图片生成)",
        provider_type="image",
        base_url="https://api.stability.ai/v1",
        models=["stable-image-core", "stable-image-ultra", "sd3.5-large", "sd3.5-medium"],
        default_model="stable-image-core",
        key_env="STABILITY_KEY",
        purpose="image_generation",
    ),
}


# ============================================================================
# 用途 → 提供商映射
# ============================================================================

# 基于用户提供的 Key 用途列
PURPOSE_PROVIDERS = {
    "jnpf_team": ["deepseek_jnpf"],
    "cross_border_ecommerce": ["deepseek_ecommerce", "glm_ecommerce"],
    "aigc_marketing": ["deepseek_aigc", "ark_default", "ark_backup"],
    "image_generation": ["stability_image"],
    # 默认用途：AIGC 营销中台
    "default": ["deepseek_aigc", "ark_default", "ark_backup"],
}


# ============================================================================
# 文本生成提供商基类
# ============================================================================

class TextProvider:
    """文本生成提供商基类（OpenAI 兼容接口）"""

    def __init__(self, meta: ProviderMeta, api_key: str = None, model: str = None):
        self.meta = meta
        self.api_key = api_key or os.environ.get(meta.key_env, "")
        self.model = model or meta.default_model
        self._call_count = 0
        self._error_count = 0
        self._total_tokens = 0
        self._last_error = ""
        self._last_success_at: Optional[float] = None

    def is_available(self) -> bool:
        """是否可用（有 Key）"""
        return bool(self.api_key)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 2000,
        model: str = None,
    ) -> str:
        """
        生成文本
        所有兼容 OpenAI 的提供商共用此实现
        """
        import requests

        url = f"{self.meta.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # 统计
        self._call_count += 1
        usage = data.get("usage", {})
        self._total_tokens += usage.get("total_tokens", 0)
        self._last_success_at = time.time()

        return data["choices"][0]["message"]["content"]

    def record_error(self, error: str):
        """记录错误"""
        self._error_count += 1
        self._last_error = error

    def get_stats(self) -> dict:
        """获取统计"""
        return {
            "provider_id": self.meta.provider_id,
            "name": self.meta.name,
            "model": self.model,
            "available": self.is_available(),
            "call_count": self._call_count,
            "error_count": self._error_count,
            "total_tokens": self._total_tokens,
            "last_error": self._last_error,
            "last_success_at": self._last_success_at,
            "success_rate": round(
                self._call_count / (self._call_count + self._error_count), 3
            ) if (self._call_count + self._error_count) > 0 else 1.0,
        }


# ============================================================================
# 图片生成提供商
# ============================================================================

class ImageProvider:
    """图片生成提供商（Stability AI）"""

    def __init__(self, meta: ProviderMeta, api_key: str = None, model: str = None):
        self.meta = meta
        self.api_key = api_key or os.environ.get(meta.key_env, "")
        self.model = model or meta.default_model
        self._call_count = 0
        self._error_count = 0
        self._last_error = ""
        self._last_success_at: Optional[float] = None

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: int = 0,
        model: str = None,
    ) -> dict:
        """
        生成图片
        返回: {"image_base64": str, "seed": int, "finish_reason": str}
        """
        import requests

        # Stability AI 使用 multipart/form-data
        url = f"{self.meta.base_url}/stable-image/generate/core"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        files = {
            "prompt": (None, prompt),
            "negative_prompt": (None, negative_prompt),
            "width": (None, str(width)),
            "height": (None, str(height)),
            "seed": (None, str(seed)),
        }

        resp = requests.post(url, headers=headers, files=files, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        self._call_count += 1
        self._last_success_at = time.time()

        image_b64 = data.get("image", "")
        return {
            "image_base64": image_b64,
            "seed": data.get("seed", seed),
            "finish_reason": data.get("finish_reason", "SUCCESS"),
        }

    def generate_image_to_file(
        self,
        prompt: str,
        output_path: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: int = 0,
    ) -> str:
        """生成图片并保存到文件"""
        result = self.generate_image(prompt, negative_prompt, width, height, seed)
        image_data = base64.b64decode(result["image_base64"])
        with open(output_path, "wb") as f:
            f.write(image_data)
        return output_path

    def record_error(self, error: str):
        self._error_count += 1
        self._last_error = error

    def get_stats(self) -> dict:
        return {
            "provider_id": self.meta.provider_id,
            "name": self.meta.name,
            "model": self.model,
            "available": self.is_available(),
            "call_count": self._call_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "last_success_at": self._last_success_at,
        }


# ============================================================================
# 提供商工厂
# ============================================================================

def create_provider(provider_id: str, api_key: str = None, model: str = None):
    """
    创建提供商实例
    Args:
        provider_id: 提供商 ID（见 PROVIDER_REGISTRY）
        api_key: API Key（不传则从环境变量读取）
        model: 模型名（不传则用默认）
    """
    meta = PROVIDER_REGISTRY.get(provider_id)
    if not meta:
        raise ValueError(f"未知提供商: {provider_id}，可用: {list(PROVIDER_REGISTRY.keys())}")

    if meta.provider_type == "text":
        return TextProvider(meta, api_key=api_key, model=model)
    elif meta.provider_type == "image":
        return ImageProvider(meta, api_key=api_key, model=model)
    else:
        raise ValueError(f"未知提供商类型: {meta.provider_type}")


def list_providers(purpose: str = None, provider_type: str = None) -> list:
    """列出提供商"""
    result = []
    for pid, meta in PROVIDER_REGISTRY.items():
        if purpose and meta.purpose != purpose:
            continue
        if provider_type and meta.provider_type != provider_type:
            continue
        result.append({
            "provider_id": pid,
            "name": meta.name,
            "type": meta.provider_type,
            "purpose": meta.purpose,
            "models": meta.models,
            "default_model": meta.default_model,
            "key_env": meta.key_env,
            "key_configured": bool(os.environ.get(meta.key_env, "")),
        })
    return result


def get_purposes() -> list:
    """获取所有用途"""
    return [
        {"purpose": "jnpf_team", "name": "JNPF团队", "providers": PURPOSE_PROVIDERS["jnpf_team"]},
        {"purpose": "cross_border_ecommerce", "name": "跨境电商", "providers": PURPOSE_PROVIDERS["cross_border_ecommerce"]},
        {"purpose": "aigc_marketing", "name": "AIGC数字营销中台", "providers": PURPOSE_PROVIDERS["aigc_marketing"]},
        {"purpose": "image_generation", "name": "图片生成", "providers": PURPOSE_PROVIDERS["image_generation"]},
    ]


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LLM 多提供商适配器")
    parser.add_argument("--action", required=True,
                        choices=["list", "purposes", "test", "generate", "generate-image"])
    parser.add_argument("--provider", help="提供商 ID")
    parser.add_argument("--purpose", help="用途")
    parser.add_argument("--model", help="模型名")
    parser.add_argument("--prompt", help="用户提示词")
    parser.add_argument("--system-prompt", default="你是营销创意助手", help="系统提示词")
    parser.add_argument("--output", help="图片输出路径")

    args = parser.parse_args()

    if args.action == "list":
        print(json.dumps(list_providers(args.purpose), ensure_ascii=False, indent=2))

    elif args.action == "purposes":
        print(json.dumps(get_purposes(), ensure_ascii=False, indent=2))

    elif args.action == "test":
        if not args.provider:
            print("错误: 需要 --provider")
            return 1
        provider = create_provider(args.provider, model=args.model)
        print(f"提供商: {provider.meta.name}")
        print(f"可用: {provider.is_available()}")
        print(f"模型: {provider.model}")
        if provider.is_available():
            try:
                result = provider.generate(
                    system_prompt="回复'OK'即可",
                    user_prompt="测试连接",
                    max_tokens=10,
                )
                print(f"测试响应: {result[:100]}")
                print("✅ 连接正常")
            except Exception as e:
                print(f"❌ 连接失败: {e}")
                return 1

    elif args.action == "generate":
        if not args.provider or not args.prompt:
            print("错误: 需要 --provider --prompt")
            return 1
        provider = create_provider(args.provider, model=args.model)
        if not provider.is_available():
            print(f"❌ 提供商不可用（未配置 Key: {provider.meta.key_env}）")
            return 1
        result = provider.generate(
            system_prompt=args.system_prompt,
            user_prompt=args.prompt,
        )
        print(result)

    elif args.action == "generate-image":
        if not args.provider or not args.prompt or not args.output:
            print("错误: 需要 --provider --prompt --output")
            return 1
        provider = create_provider(args.provider, model=args.model)
        if not provider.is_available():
            print(f"❌ 提供商不可用（未配置 Key: {provider.meta.key_env}）")
            return 1
        provider.generate_image_to_file(args.prompt, args.output)
        print(f"✅ 图片已生成: {args.output}")

    return 0


if __name__ == "__main__":
    exit(main())
