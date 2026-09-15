from typing import Literal, Optional

from pydantic import BaseModel


class CoreItem(BaseModel):
    """必須コアアイテム（外せない理由付き）。"""

    name: str
    reason: str


class Substitute(BaseModel):
    """代用アイテムと、BiSからの統計変化（Delta Place）。"""

    item: str
    delta_avg_place: float  # BiSからの平均順位悪化量（例: +0.18）
    condition: Optional[str] = None


class AntiSynergyWarning(BaseModel):
    items: list[str]
    reason: str


class DebuffRole(BaseModel):
    debuff_type: Literal["分解", "細断", "重傷"]
    carrier: Literal["本人", "前衛", "サブキャリー", "スキル内蔵"]
    note: str


class ItemSetStats(BaseModel):
    """あるアイテム組み合わせの統計情報（信頼度フィルタ済み）。"""

    items: list[str]
    sample_size: int
    confidence_level: Literal["HIGH", "MEDIUM", "LOW"]
    avg_place: float
    win_rate: float
    special_note: Optional[str] = None


class ItemBuildAdvice(BaseModel):
    champion: str
    core_items: list[CoreItem]
    bis_standard_build: ItemSetStats
    substitutes: list[Substitute]
    special_synergy_builds: list[ItemSetStats]
    anti_synergy_warnings: list[AntiSynergyWarning]
    debuff_roles: list[DebuffRole]
