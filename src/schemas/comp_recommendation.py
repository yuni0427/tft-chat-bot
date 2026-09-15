from typing import Literal, Optional

from pydantic import BaseModel, Field


class CompRecommendation(BaseModel):
    """構成（コンプ）の統計に基づく推薦情報。"""

    comp_name: str
    tier: Literal["S", "A", "B"]
    avg_place: float
    top4_rate: float
    sample_size: int
    confidence_level: Literal["HIGH", "MEDIUM", "LOW"]
    emblem_holder: Optional[str] = None
    key_units: list[str]
    item_synergy_reason: str

    # --- アイテム/紋章からの構成逆引き機能用の拡張フィールド ---
    # 手持ちのアイテム/紋章がこのリストに含まれる場合、逆引き検索でヒットする。
    trigger_items: list[str] = Field(default_factory=list)
    trigger_emblems: list[str] = Field(default_factory=list)
