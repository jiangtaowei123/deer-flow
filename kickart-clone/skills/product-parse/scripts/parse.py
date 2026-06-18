"""
商品解析脚本 - 从 URL/图片/ID 提取结构化商品信息
"""
import argparse
import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image


class ProductParser:
    """商品解析器"""

    def __init__(self, output_dir: str = "/mnt/user-data/workspace"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })

    def parse(self, input_value: str) -> dict:
        """自动判断输入类型并解析"""
        if input_value.startswith("http"):
            return self._parse_url(input_value)
        elif os.path.exists(input_value):
            return self._parse_image(input_value)
        else:
            return self._parse_id(input_value)

    def _parse_url(self, url: str) -> dict:
        """从 URL 解析商品信息"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if "amazon" in domain:
            return self._parse_amazon(url)
        elif "shopify" in domain or "myshopify" in domain:
            return self._parse_shopify(url)
        elif "taobao" in domain or "tmall" in domain:
            return self._parse_taobao(url)
        elif "jd.com" in domain:
            return self._parse_jd(url)
        else:
            return self._parse_generic(url)

    def _parse_amazon(self, url: str) -> dict:
        """解析亚马逊商品"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            html = response.text

            asin = self._extract_asin(url)
            title = self._extract_meta(html, "title")
            description = self._extract_meta(html, "description")
            image = self._extract_og_image(html)

            return {
                "product_id": asin,
                "platform": "amazon",
                "url": url,
                "title": title,
                "category": self._extract_category(html),
                "description": description,
                "key_features": self._extract_features(html),
                "brand": self._extract_brand(html),
                "price_range": self._extract_price(html),
                "main_image_url": image,
                "gallery_urls": [],
                "selling_points": [],
                "target_audience": "general",
            }
        except Exception as e:
            return {"error": f"Amazon parse failed: {str(e)}"}

    def _parse_shopify(self, url: str) -> dict:
        """解析 Shopify 商品"""
        try:
            product_url = url.rstrip("/") + ".json"
            response = self.session.get(product_url, timeout=15)
            response.raise_for_status()
            data = response.json().get("product", {})

            return {
                "product_id": str(data.get("id", "")),
                "platform": "shopify",
                "url": url,
                "title": data.get("title", ""),
                "category": "general",
                "description": data.get("body_html", ""),
                "key_features": [],
                "brand": data.get("vendor", ""),
                "price_range": self._extract_shopify_price(data),
                "main_image_url": data.get("image", {}).get("src", ""),
                "gallery_urls": [img["src"] for img in data.get("images", [])],
                "selling_points": [],
                "target_audience": "general",
            }
        except Exception as e:
            return {"error": f"Shopify parse failed: {str(e)}"}

    def _parse_taobao(self, url: str) -> dict:
        """解析淘宝商品（基础版）"""
        return {
            "product_id": self._extract_id_from_url(url, "id"),
            "platform": "taobao",
            "url": url,
            "title": "需手动补充",
            "category": "general",
            "description": "",
            "key_features": [],
            "brand": "",
            "price_range": "",
            "main_image_url": "",
            "gallery_urls": [],
            "selling_points": [],
            "target_audience": "general",
            "note": "淘宝需要登录态，建议上传图片解析"
        }

    def _parse_jd(self, url: str) -> dict:
        """解析京东商品（基础版）"""
        return {
            "product_id": self._extract_id_from_url(url, "product"),
            "platform": "jd",
            "url": url,
            "title": "需手动补充",
            "category": "general",
            "description": "",
            "key_features": [],
            "brand": "",
            "price_range": "",
            "main_image_url": "",
            "gallery_urls": [],
            "selling_points": [],
            "target_audience": "general",
            "note": "京东需要登录态，建议上传图片解析"
        }

    def _parse_generic(self, url: str) -> dict:
        """通用 OG 标签解析"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            html = response.text

            return {
                "product_id": "",
                "platform": "generic",
                "url": url,
                "title": self._extract_meta(html, "og:title") or self._extract_meta(html, "title"),
                "category": "general",
                "description": self._extract_meta(html, "og:description") or self._extract_meta(html, "description"),
                "key_features": [],
                "brand": self._extract_meta(html, "og:site_name"),
                "price_range": "",
                "main_image_url": self._extract_og_image(html),
                "gallery_urls": [],
                "selling_points": [],
                "target_audience": "general",
            }
        except Exception as e:
            return {"error": f"Generic parse failed: {str(e)}"}

    def _parse_image(self, image_path: str) -> dict:
        """从图片解析商品（需 VLM 支持）"""
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                format_name = img.format
        except Exception as e:
            return {"error": f"Image open failed: {str(e)}"}

        return {
            "product_id": "",
            "platform": "image",
            "image_path": image_path,
            "title": "需 VLM 识别",
            "category": "需 VLM 识别",
            "description": "需 VLM 识别",
            "key_features": [],
            "brand": "",
            "price_range": "",
            "main_image_url": "",
            "gallery_urls": [image_path],
            "selling_points": [],
            "target_audience": "general",
            "image_info": {"width": width, "height": height, "format": format_name},
            "note": "请使用 VLM (GPT-4V/Gemini) 进一步识别商品属性"
        }

    def _parse_id(self, product_id: str) -> dict:
        """从商品ID解析（需指定平台）"""
        return {
            "product_id": product_id,
            "platform": "unknown",
            "title": "需指定平台并补充URL",
            "note": "请提供完整URL或上传图片以获得更好效果"
        }

    def _extract_asin(self, url: str) -> str:
        match = re.search(r"/dp/([A-Z0-9]{10})", url)
        if match:
            return match.group(1)
        match = re.search(r"/product/([A-Z0-9]{10})", url)
        if match:
            return match.group(1)
        return ""

    def _extract_id_from_url(self, url: str, param: str) -> str:
        match = re.search(rf"{param}=([^&]+)", url)
        return match.group(1) if match else ""

    def _extract_meta(self, html: str, name: str) -> str:
        patterns = [
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(name)}["\']',
            rf'<{name}[^>]*>([^<]+)</{name}>',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_og_image(self, html: str) -> str:
        return self._extract_meta(html, "og:image")

    def _extract_category(self, html: str) -> str:
        match = re.search(r'"category"\s*:\s*"([^"]+)"', html)
        return match.group(1) if match else "general"

    def _extract_features(self, html: str) -> list:
        features = []
        for match in re.finditer(r'<span[^>]*class="[^"]*a-list-item[^"]*"[^>]*>([^<]+)</span>', html):
            text = match.group(1).strip()
            if text and len(text) > 5:
                features.append(text)
        return features[:10]

    def _extract_brand(self, html: str) -> str:
        match = re.search(r'"brand"\s*:\s*"([^"]+)"', html)
        return match.group(1) if match else ""

    def _extract_price(self, html: str) -> str:
        match = re.search(r'"price"\s*:\s*([\d.]+)', html)
        return f"${match.group(1)}" if match else ""

    def _extract_shopify_price(self, data: dict) -> str:
        variants = data.get("variants", [])
        if not variants:
            return ""
        prices = [float(v.get("price", 0)) for v in variants if v.get("price")]
        if not prices:
            return ""
        if len(prices) == 1:
            return f"${prices[0]}"
        return f"${min(prices)} - ${max(prices)}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="商品信息解析工具")
    parser.add_argument("--input", required=True, help="商品URL/图片路径/商品ID")
    parser.add_argument("--output", default="/mnt/user-data/workspace/product-info.json", help="输出JSON路径")

    args = parser.parse_args()

    product_parser = ProductParser()
    result = product_parser.parse(args.input)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"解析完成: {args.output}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
