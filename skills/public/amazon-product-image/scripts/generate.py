import argparse
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
from PIL import Image


class StableDiffusionBatchGenerator:
    """Stable Diffusion 批量图片生成器 - 支持文生图和图生图"""

    def __init__(
        self,
        sd_url: str = "http://127.0.0.1:7860",
        output_dir: str = "/mnt/user-data/outputs",
        num_parallel: int = 2,
    ):
        self.sd_url = sd_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.num_parallel = min(num_parallel, 4)

    def _check_sd_status(self) -> bool:
        """检查 Stable Diffusion WebUI 是否运行"""
        try:
            response = requests.get(f"{self.sd_url}/sdapi/v1/progress", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _load_scene_template(self, scene_file: str) -> dict:
        """加载场景模板"""
        template_path = Path(scene_file)
        if not template_path.exists():
            template_path = Path(f"/mnt/skills/public/amazon-product-image/templates/{scene_file}.json")

        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _build_prompt(
        self,
        product_description: str,
        scene_config: dict,
        custom_prompt: Optional[str] = None,
        custom_negative: Optional[str] = None,
        include_arms: bool = False,
    ) -> tuple[str, str]:
        """构建生成提示词"""
        positive_prompt = custom_prompt or scene_config.get("default_prompt_template", "")
        negative_prompt = custom_negative or scene_config.get("default_negative_prompt", "")

        if "{product_description}" in positive_prompt:
            positive_prompt = positive_prompt.replace("{product_description}", product_description)
        elif product_description and product_description not in positive_prompt:
            positive_prompt = f"{product_description}, {positive_prompt}"

        if include_arms:
            positive_prompt = f"{positive_prompt}, full body view, both arms visible, two arms showing, arms away from body, natural arm position"
            negative_prompt = f"{negative_prompt}, one arm hidden, single arm, missing arm, arm behind back, arm cut off"

        return positive_prompt, negative_prompt

    def _get_default_settings(self, scene_config: dict) -> dict:
        """获取默认生成参数"""
        return scene_config.get("recommended_settings", {
            "steps": 30,
            "cfg_scale": 7,
            "sampler_name": "DPM++ 2M Karras",
            "width": 1024,
            "height": 1280,
        })

    def _image_to_base64(self, image_path: str) -> str:
        """将图片转换为 base64"""
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            print(f"Error encoding image {image_path}: {e}")
            return ""

    def generate_single(
        self,
        prompt: str,
        negative_prompt: str,
        output_filename: str,
        width: int = 1024,
        height: int = 1280,
        steps: int = 30,
        cfg_scale: float = 7.0,
        sampler: str = "DPM++ 2M Karras",
        seed: int = -1,
        enable_hr: bool = False,
        hr_scale: float = 1.5,
        hr_steps: int = 20,
        clip_skip: int = 1,
        lora_name: Optional[str] = None,
        lora_weight: float = 0.8,
        reference_image: Optional[str] = None,
        denoising_strength: float = 0.75,
        controlnet_enabled: bool = False,
        controlnet_model: str = "openpose",
        controlnet_weight: float = 1.0,
    ) -> dict:
        """生成单张图片（支持文生图和图生图）"""
        import io

        if not self._check_sd_status():
            return {"success": False, "error": "Stable Diffusion WebUI 未运行，请先启动"}

        is_img2img = reference_image is not None and os.path.exists(reference_image)

        if is_img2img:
            base64_img = self._image_to_base64(reference_image)
            if not base64_img:
                return {"success": False, "error": "无法读取参考图片"}

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "sampler_name": sampler,
            "seed": seed if seed != -1 else int(time.time()) % 2147483647,
            "clip_skip": clip_skip,
        }

        if lora_name:
            payload["prompt"] = f"<lora:{lora_name}:{lora_weight}> {prompt}"

        if enable_hr:
            payload.update({
                "enable_hr": True,
                "hr_scale": hr_scale,
                "hr_second_pass_steps": hr_steps,
                "denoising_strength": 0.4 if not is_img2img else denoising_strength,
            })

        if is_img2img:
            payload.update({
                "init_images": [base64_img],
                "denoising_strength": denoising_strength,
            })

        if controlnet_enabled and is_img2img:
            payload["alwayson_scripts"] = {
                "controlnet": {
                    "args": [
                        {
                            "input_image": base64_img,
                            "module": controlnet_model,
                            "model": f"control_{controlnet_model}_sd15 [fef5e48e]",
                            "weight": controlnet_weight,
                            "resize_mode": "Crop and Resize",
                            "lowvram": False,
                        }
                    ]
                }
            }

        output_path = self.output_dir / output_filename

        try:
            endpoint = f"{self.sd_url}/sdapi/v1/img2img" if is_img2img else f"{self.sd_url}/sdapi/v1/txt2img"
            response = requests.post(
                endpoint,
                json=payload,
                timeout=300,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("images"):
                image_data = result["images"][0]
                image = Image.open(io.BytesIO(base64.b64decode(image_data)))
                image.save(output_path, quality=95)

                return {
                    "success": True,
                    "output_path": str(output_path),
                    "seed": result.get("parameters", {}).get("seed", "unknown"),
                    "info": result.get("info", ""),
                }
            else:
                return {"success": False, "error": "未生成图片"}

        except requests.exceptions.Timeout:
            return {"success": False, "error": "请求超时，SD WebUI 响应过慢"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"API 请求失败: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"生成失败: {str(e)}"}

    def batch_generate(
        self,
        product_description: str,
        scenes: list[str],
        product_id: str,
        num_variants: int = 2,
        custom_prompts: Optional[dict] = None,
        custom_negatives: Optional[dict] = None,
        reference_image: Optional[str] = None,
        denoising_strength: float = 0.75,
        controlnet_enabled: bool = False,
        include_arms: bool = False,
        **generation_kwargs,
    ) -> dict:
        """批量生成多场景多变体图片"""
        if not self._check_sd_status():
            return {
                "success": False,
                "error": "Stable Diffusion WebUI 未运行",
                "results": [],
            }

        results = []
        tasks = []

        for scene in scenes:
            scene_config = self._load_scene_template(scene)
            prompt, negative = self._build_prompt(
                product_description,
                scene_config,
                custom_prompts.get(scene) if custom_prompts else None,
                custom_negatives.get(scene) if custom_negatives else None,
                include_arms=include_arms,
            )
            settings = self._get_default_settings(scene_config)
            settings.update(generation_kwargs)

            for variant in range(num_variants):
                filename = f"{product_id}_{scene}_{variant + 1}.png"
                tasks.append({
                    "prompt": prompt,
                    "negative_prompt": negative,
                    "output_filename": filename,
                    "seed": -1,
                    "reference_image": reference_image,
                    "denoising_strength": denoising_strength,
                    "controlnet_enabled": controlnet_enabled,
                    **settings,
                })

        def generate_task(task: dict) -> dict:
            return self.generate_single(**task)

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {executor.submit(generate_task, task): task for task in tasks}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({"success": False, "error": str(e)})

        success_count = sum(1 for r in results if r.get("success", False))
        return {
            "success": True,
            "total": len(results),
            "success_count": success_count,
            "failed_count": len(results) - success_count,
            "results": results,
        }


def validate_image(image_path: str) -> bool:
    """验证图片是否有效"""
    try:
        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            img.load()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import io

    parser = argparse.ArgumentParser(description="亚马逊服装图片批量生成工具")
    parser.add_argument("--product-description", required=True, help="服装产品描述")
    parser.add_argument("--product-id", required=True, help="产品ID，用于文件命名")
    parser.add_argument("--scenes", nargs="+", default=["studio"], help="场景列表: studio, outdoor_urban, outdoor_cafe, minimal_abstract, nature_outdoor, lifestyle_home")
    parser.add_argument("--num-variants", type=int, default=2, help="每个场景生成变体数量")
    parser.add_argument("--sd-url", default="http://127.0.0.1:7860", help="Stable Diffusion WebUI 地址")
    parser.add_argument("--output-dir", default="/mnt/user-data/outputs", help="输出目录")
    parser.add_argument("--num-parallel", type=int, default=2, help="并行生成数量")
    parser.add_argument("--width", type=int, default=1024, help="图片宽度")
    parser.add_argument("--height", type=int, default=1280, help="图片高度")
    parser.add_argument("--steps", type=int, default=30, help="采样步数")
    parser.add_argument("--cfg-scale", type=float, default=7.0, help="CFG 引导强度")
    parser.add_argument("--sampler", default="DPM++ 2M Karras", help="采样器")
    parser.add_argument("--enable-hr", action="store_true", help="启用高清修复")
    parser.add_argument("--lora-name", help="使用的 LoRA 模型名称")
    parser.add_argument("--lora-weight", type=float, default=0.8, help="LoRA 权重")
    parser.add_argument("--custom-prompt", help="自定义正向提示词（覆盖场景模板）")
    parser.add_argument("--custom-negative", help="自定义负向提示词")
    
    parser.add_argument("--reference-image", help="参考图片路径（用于图生图）")
    parser.add_argument("--denoising-strength", type=float, default=0.75, help="去噪强度（图生图专用，0-1）")
    parser.add_argument("--controlnet", action="store_true", help="启用 ControlNet 保持姿势")
    parser.add_argument("--controlnet-model", default="openpose", help="ControlNet 模型类型")
    
    parser.add_argument("--include-arms", action="store_true", help="强制显示两个胳膊")

    args = parser.parse_args()

    generator = StableDiffusionBatchGenerator(
        sd_url=args.sd_url,
        output_dir=args.output_dir,
        num_parallel=args.num_parallel,
    )

    if args.custom_prompt:
        custom_prompts = {scene: args.custom_prompt for scene in args.scenes}
    else:
        custom_prompts = None

    if args.custom_negative:
        custom_negatives = {scene: args.custom_negative for scene in args.scenes}
    else:
        custom_negatives = None

    print(f"开始批量生成: {args.product_description}")
    print(f"场景: {args.scenes}")
    print(f"每场景变体数: {args.num_variants}")
    print(f"参考图片: {args.reference_image or '无'}")
    print(f"强制显示双臂: {'是' if args.include_arms else '否'}")
    print(f"预计生成: {len(args.scenes) * args.num_variants} 张图片")
    print("-" * 50)

    result = generator.batch_generate(
        product_description=args.product_description,
        scenes=args.scenes,
        product_id=args.product_id,
        num_variants=args.num_variants,
        custom_prompts=custom_prompts,
        custom_negatives=custom_negatives,
        reference_image=args.reference_image,
        denoising_strength=args.denoising_strength,
        controlnet_enabled=args.controlnet,
        include_arms=args.include_arms,
        width=args.width,
        height=args.height,
        steps=args.steps,
        cfg_scale=args.cfg_scale,
        sampler=args.sampler,
        enable_hr=args.enable_hr,
        lora_name=args.lora_name,
        lora_weight=args.lora_weight,
    )

    print("\n" + "=" * 50)
    print(f"生成完成!")
    
    if result.get("success"):
        print(f"成功: {result.get('success_count', 0)}/{result.get('total', 0)}")
        print(f"失败: {result.get('failed_count', 0)}")

        if result.get("results"):
            print("\n生成详情:")
            for idx, res in enumerate(result["results"], 1):
                status = "✓" if res.get("success") else "✗"
                if res.get("success"):
                    print(f"  {status} {Path(res['output_path']).name} (seed: {res.get('seed', 'N/A')})")
                else:
                    print(f"  {status} {res.get('error', '未知错误')}")
    else:
        print(f"错误: {result.get('error', '未知错误')}")