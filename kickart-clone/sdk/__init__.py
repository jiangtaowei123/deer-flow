"""
Kickart Python SDK 包入口
"""
from .client import KickartClient, KickartError, KickartAPIError, quick_create_video, quick_create_images

__version__ = "1.0.0"
__all__ = [
    "KickartClient",
    "KickartError",
    "KickartAPIError",
    "quick_create_video",
    "quick_create_images",
]
