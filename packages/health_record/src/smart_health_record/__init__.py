"""smart-health-record：健康狀態記錄函式庫。"""
from .masking import mask_text
from .recorder import NodeRecorder

__version__ = "0.1.0"

__all__ = ["NodeRecorder", "mask_text", "__version__"]
