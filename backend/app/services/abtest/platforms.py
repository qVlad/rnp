"""Маппинг appType (WB Adv API) → каноническая платформа устройства.

Используется в `apply_platform_snapshot` для дробления adv-метрики на
IOS / ANDROID / WEB / OTHER.

Источник кодов: поле `appType` в `/adv/v3/fullstats` → каждый объект в
`days[].apps[]`. WB документирует следующее (наблюдаемые значения):
    64 → iOS
    32 → Android
     1 → сайт (Web)
прочее → OTHER (резерв на будущее, обычно появляется при WB-side change)
"""
from __future__ import annotations

PLATFORM_IOS = "IOS"
PLATFORM_ANDROID = "ANDROID"
PLATFORM_WEB = "WEB"
PLATFORM_OTHER = "OTHER"

ALL_PLATFORMS = (PLATFORM_IOS, PLATFORM_ANDROID, PLATFORM_WEB, PLATFORM_OTHER)

AD_PLATFORM_LABELS: dict[str, str] = {
    PLATFORM_IOS: "iOS",
    PLATFORM_ANDROID: "Android",
    PLATFORM_WEB: "Сайт",
    PLATFORM_OTHER: "Прочее",
}


def app_type_to_platform(app_type: int) -> str:
    if app_type == 64:
        return PLATFORM_IOS
    if app_type == 32:
        return PLATFORM_ANDROID
    if app_type == 1:
        return PLATFORM_WEB
    return PLATFORM_OTHER
