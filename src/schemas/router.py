from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClarificationOption(BaseModel):
    """曖昧な質問に対して提示する聞き返しの選択肢。"""

    label: str = Field(..., description="ユーザーに表示する選択肢の文言")
    route_to: Literal["theory", "meta_item", "meta_comp"] = Field(
        ..., description="選択後に直接遷移するチェーン"
    )
    prefill_query: str = Field(
        ..., description="選択後にそのままチェーンへ渡す具体的な質問文"
    )


class IntentClassification(BaseModel):
    """ユーザー入力を3分岐（曖昧/理論/メタ）に分類する構造化出力。"""

    category: Literal["ambiguous", "theory", "meta"]
    meta_subtype: Optional[
        Literal["item_build", "comp_from_item_or_emblem", "general"]
    ] = None
    clarification_message: Optional[str] = Field(
        default=None, description="ambiguousの場合に表示する聞き返し文"
    )
    clarification_options: Optional[list[ClarificationOption]] = Field(
        default=None, description="ambiguousの場合に提示する2択の選択肢"
    )
