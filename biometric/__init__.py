# -*- coding: utf-8 -*-
"""
biometric — طبقة عازلة لأجهزة البصمة.

بقية النظام لا تعرف نوع الجهاز ولا بروتوكوله. تتعامل مع واجهة واحدة:
«اتصل، اقرأ البصمات بعد هذا الوقت، اقطع». هذا يُبقي الجهاز قابلاً
للتبديل: إن ظهر جهاز ببروتوكول آخر، نكتب صنفاً جديداً يحقّق الواجهة
نفسها، بلا مساس بالسحب ولا المطابقة ولا اللوحة.

المدعوم الآن:
  • ZKDevice  — بروتوكول ZKTeco على المنفذ 4370 (أغلب الأجهزة الصينية)
  • MockDevice — محاكٍ للاختبار بلا عتاد

يُختار الصنف حسب الإعداد `protocol`.
"""
from .zk_device import ZKDevice
from .mock_device import MockDevice


def make_device(cfg: dict):
    """
    يبني كائن جهاز من إعداده.

    cfg: {"protocol": "zk"|"mock", "ip": ..., "port": 4370,
          "comm_key": 0, "device_id": "gate1"}
    """
    proto = (cfg.get("protocol") or "zk").lower()
    if proto == "mock":
        return MockDevice(cfg)
    return ZKDevice(cfg)


__all__ = ["ZKDevice", "MockDevice", "make_device"]
