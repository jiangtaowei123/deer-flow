"""
国际化 i18n 多语言支持
支持：中/英/日三语、翻译键值管理、运行时切换、参数插值
基于 JNPF6.2 页面引擎的多语言扩展
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ============================================================================
# 支持的语言
# ============================================================================

class Language:
    ZH_CN = "zh-CN"
    EN_US = "en-US"
    JA_JP = "ja-JP"
    SUPPORTED = [ZH_CN, EN_US, JA_JP]
    DEFAULT = ZH_CN


# ============================================================================
# 翻译字典
# ============================================================================

TRANSLATIONS = {
    # ============ 通用 ============
    "common.app_name": {
        Language.ZH_CN: "Kickart 营销创作平台",
        Language.EN_US: "Kickart Marketing Creation Platform",
        Language.JA_JP: "Kickart マーケティング作成プラットフォーム",
    },
    "common.welcome": {
        Language.ZH_CN: "欢迎使用 {name}",
        Language.EN_US: "Welcome, {name}",
        Language.JA_JP: "ようこそ、{name}さん",
    },
    "common.loading": {
        Language.ZH_CN: "加载中...",
        Language.EN_US: "Loading...",
        Language.JA_JP: "読み込み中...",
    },
    "common.success": {
        Language.ZH_CN: "成功",
        Language.EN_US: "Success",
        Language.JA_JP: "成功",
    },
    "common.failed": {
        Language.ZH_CN: "失败",
        Language.EN_US: "Failed",
        Language.JA_JP: "失敗",
    },
    "common.cancel": {
        Language.ZH_CN: "取消",
        Language.EN_US: "Cancel",
        Language.JA_JP: "キャンセル",
    },
    "common.confirm": {
        Language.ZH_CN: "确认",
        Language.EN_US: "Confirm",
        Language.JA_JP: "確認",
    },
    "common.save": {
        Language.ZH_CN: "保存",
        Language.EN_US: "Save",
        Language.JA_JP: "保存",
    },
    "common.delete": {
        Language.ZH_CN: "删除",
        Language.EN_US: "Delete",
        Language.JA_JP: "削除",
    },

    # ============ 导航 ============
    "nav.dashboard": {
        Language.ZH_CN: "工作台",
        Language.EN_US: "Dashboard",
        Language.JA_JP: "ダッシュボード",
    },
    "nav.create": {
        Language.ZH_CN: "新建创作",
        Language.EN_US: "Create",
        Language.JA_JP: "新規作成",
    },
    "nav.runs": {
        Language.ZH_CN: "历史记录",
        Language.EN_US: "History",
        Language.JA_JP: "履歴",
    },
    "nav.scenes": {
        Language.ZH_CN: "场景模板",
        Language.EN_US: "Scene Templates",
        Language.JA_JP: "シーンテンプレート",
    },
    "nav.health": {
        Language.ZH_CN: "系统健康",
        Language.EN_US: "System Health",
        Language.JA_JP: "システムヘルス",
    },

    # ============ 创作表单 ============
    "form.input_value": {
        Language.ZH_CN: "商品输入",
        Language.EN_US: "Product Input",
        Language.JA_JP: "商品入力",
    },
    "form.input_value.placeholder": {
        Language.ZH_CN: "输入商品 URL/ID/描述",
        Language.EN_US: "Enter product URL/ID/description",
        Language.JA_JP: "商品URL/ID/説明を入力",
    },
    "form.workflow": {
        Language.ZH_CN: "工作流类型",
        Language.EN_US: "Workflow Type",
        Language.JA_JP: "ワークフロータイプ",
    },
    "form.num_scenes": {
        Language.ZH_CN: "场景数量",
        Language.EN_US: "Number of Scenes",
        Language.JA_JP: "シーン数",
    },
    "form.aspect_ratio": {
        Language.ZH_CN: "宽高比",
        Language.EN_US: "Aspect Ratio",
        Language.JA_JP: "アスペクト比",
    },
    "form.voice": {
        Language.ZH_CN: "TTS 音色",
        Language.EN_US: "TTS Voice",
        Language.JA_JP: "TTS音声",
    },
    "form.submit": {
        Language.ZH_CN: "开始创作",
        Language.EN_US: "Start Creating",
        Language.JA_JP: "作成開始",
    },

    # ============ 工作流类型 ============
    "workflow.video": {
        Language.ZH_CN: "完整视频",
        Language.EN_US: "Full Video",
        Language.JA_JP: "フル動画",
    },
    "workflow.image": {
        Language.ZH_CN: "仅图片",
        Language.EN_US: "Images Only",
        Language.JA_JP: "画像のみ",
    },
    "workflow.storyboard": {
        Language.ZH_CN: "仅分镜",
        Language.EN_US: "Storyboard Only",
        Language.JA_JP: "ストーリーボードのみ",
    },

    # ============ 状态 ============
    "status.pending": {
        Language.ZH_CN: "等待中",
        Language.EN_US: "Pending",
        Language.JA_JP: "待機中",
    },
    "status.running": {
        Language.ZH_CN: "执行中",
        Language.EN_US: "Running",
        Language.JA_JP: "実行中",
    },
    "status.completed": {
        Language.ZH_CN: "已完成",
        Language.EN_US: "Completed",
        Language.JA_JP: "完了",
    },
    "status.failed": {
        Language.ZH_CN: "失败",
        Language.EN_US: "Failed",
        Language.JA_JP: "失敗",
    },
    "status.degraded": {
        Language.ZH_CN: "已降级",
        Language.EN_US: "Degraded",
        Language.JA_JP: "ダウングレード",
    },

    # ============ Agent 名称 ============
    "agent.product_parser": {
        Language.ZH_CN: "商品解析",
        Language.EN_US: "Product Parser",
        Language.JA_JP: "商品解析",
    },
    "agent.creative": {
        Language.ZH_CN: "创意生成",
        Language.EN_US: "Creative",
        Language.JA_JP: "クリエイティブ",
    },
    "agent.storyboard": {
        Language.ZH_CN: "分镜设计",
        Language.EN_US: "Storyboard",
        Language.JA_JP: "ストーリーボード",
    },
    "agent.image_gen": {
        Language.ZH_CN: "图像生成",
        Language.EN_US: "Image Generation",
        Language.JA_JP: "画像生成",
    },
    "agent.tts": {
        Language.ZH_CN: "语音合成",
        Language.EN_US: "Text to Speech",
        Language.JA_JP: "音声合成",
    },
    "agent.video_gen": {
        Language.ZH_CN: "视频合成",
        Language.EN_US: "Video Composition",
        Language.JA_JP: "動画合成",
    },

    # ============ 错误信息 ============
    "error.quota_exceeded": {
        Language.ZH_CN: "配额已超限：{resource}（{current}/{limit}）",
        Language.EN_US: "Quota exceeded: {resource} ({current}/{limit})",
        Language.JA_JP: "クォータ超過: {resource} ({current}/{limit})",
    },
    "error.unauthorized": {
        Language.ZH_CN: "未授权，请登录",
        Language.EN_US: "Unauthorized, please login",
        Language.JA_JP: "認証が必要です",
    },
    "error.forbidden": {
        Language.ZH_CN: "无权限执行此操作",
        Language.EN_US: "Forbidden to perform this action",
        Language.JA_JP: "この操作を実行する権限がありません",
    },
    "error.not_found": {
        Language.ZH_CN: "资源不存在",
        Language.EN_US: "Resource not found",
        Language.JA_JP: "リソースが見つかりません",
    },
    "error.internal": {
        Language.ZH_CN: "服务器内部错误",
        Language.EN_US: "Internal server error",
        Language.JA_JP: "サーバー内部エラー",
    },

    # ============ 监控指标 ============
    "metric.daily_videos": {
        Language.ZH_CN: "日成片数",
        Language.EN_US: "Daily Videos",
        Language.JA_JP: "日次動画数",
    },
    "metric.daily_assets": {
        Language.ZH_CN: "日素材数",
        Language.EN_US: "Daily Assets",
        Language.JA_JP: "日次アセット数",
    },
    "metric.agent_success_rate": {
        Language.ZH_CN: "Agent 成功率",
        Language.EN_US: "Agent Success Rate",
        Language.JA_JP: "エージェント成功率",
    },
    "metric.e2e_latency": {
        Language.ZH_CN: "端到端耗时",
        Language.EN_US: "End-to-End Latency",
        Language.JA_JP: "エンドツーエンド遅延",
    },
}


# ============================================================================
# 翻译器
# ============================================================================

class Translator:
    """
    多语言翻译器
    - 键值查找
    - 参数插值
    - 语言切换
    - 回退到默认语言
    - 自定义翻译加载
    """

    def __init__(self, default_lang: str = Language.DEFAULT):
        self.default_lang = default_lang
        self.current_lang = default_lang
        self.translations: dict = TRANSLATIONS.copy()
        self.custom_translations: dict = {}

    def set_language(self, lang: str):
        """设置当前语言"""
        if lang not in Language.SUPPORTED:
            raise ValueError(f"不支持的语言: {lang}，支持: {Language.SUPPORTED}")
        self.current_lang = lang

    def get_language(self) -> str:
        return self.current_lang

    def t(self, key: str, **kwargs) -> str:
        """
        翻译
        支持参数插值: t("common.welcome", name="张三")
        """
        # 先查自定义翻译
        entry = self.custom_translations.get(key) or self.translations.get(key)
        if not entry:
            return key  # 找不到返回 key 本身

        # 当前语言 → 默认语言 → 第一个可用
        text = entry.get(self.current_lang) or entry.get(self.default_lang)
        if not text:
            text = next(iter(entry.values()), key)

        # 参数插值
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                pass

        return text

    def add_translation(self, key: str, lang: str, text: str):
        """添加自定义翻译"""
        if key not in self.custom_translations:
            self.custom_translations[key] = {}
        self.custom_translations[key][lang] = text

    def load_translations(self, file_path: str):
        """从 JSON 文件加载翻译"""
        path = Path(file_path)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, langs in data.items():
            for lang, text in langs.items():
                self.add_translation(key, lang, text)

    def export_translations(self, lang: Optional[str] = None) -> dict:
        """导出翻译（用于前端）"""
        result = {}
        for key, entry in {**self.translations, **self.custom_translations}.items():
            if lang:
                if lang in entry:
                    result[key] = entry[lang]
            else:
                result[key] = entry
        return result

    def list_keys(self) -> list:
        """列出所有翻译键"""
        return list({**self.translations, **self.custom_translations}.keys())

    def get_supported_languages(self) -> list:
        """获取支持的语言列表"""
        return [
            {"code": Language.ZH_CN, "name": "简体中文", "native": "简体中文"},
            {"code": Language.EN_US, "name": "English", "native": "English"},
            {"code": Language.JA_JP, "name": "日本語", "native": "日本語"},
        ]


# ============================================================================
# 全局单例
# ============================================================================

_translator: Optional[Translator] = None


def get_translator() -> Translator:
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def t(key: str, **kwargs) -> str:
    """便捷翻译函数"""
    return get_translator().t(key, **kwargs)


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="国际化 i18n")
    parser.add_argument("--action", required=True,
                        choices=["translate", "export", "keys", "languages", "set-lang"])
    parser.add_argument("--key", help="翻译键")
    parser.add_argument("--lang", default=Language.DEFAULT, choices=Language.SUPPORTED)
    parser.add_argument("--params", help="参数 JSON，如 {\"name\":\"张三\"}")

    args = parser.parse_args()
    tr = get_translator()

    if args.action == "translate":
        if not args.key:
            print("错误: 需要 --key")
            return 1
        tr.set_language(args.lang)
        params = {}
        if args.params:
            params = json.loads(args.params)
        print(tr.t(args.key, **params))
    elif args.action == "export":
        tr.set_language(args.lang)
        print(json.dumps(tr.export_translations(args.lang), ensure_ascii=False, indent=2))
    elif args.action == "keys":
        print(json.dumps(tr.list_keys(), ensure_ascii=False, indent=2))
    elif args.action == "languages":
        print(json.dumps(tr.get_supported_languages(), ensure_ascii=False, indent=2))
    elif args.action == "set-lang":
        tr.set_language(args.lang)
        print(f"✅ 语言已设置: {args.lang}")

    return 0


if __name__ == "__main__":
    exit(main())
