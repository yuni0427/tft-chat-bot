"""
最新メタ・アイテム・構成に関する質問への回答チェーン。

meta_subtype に応じて以下の3つに分岐する:
- item_build: 特定チャンピオンのアイテムビルド解説（構造化出力 -> カードUI）
- comp_from_item_or_emblem: 手持ちアイテム/紋章からの構成逆引き（構造化出力 -> カードUI）
- general: Tier表など全体的なメタ傾向のナラティブ回答
"""
from pydantic import BaseModel, Field

from src.llm.factory import get_chat_model
from src.meta import meta_service
from src.schemas.comp_recommendation import CompRecommendation
from src.schemas.item_build import ItemBuildAdvice


class _ChampionExtraction(BaseModel):
    champion: str = Field(..., description="質問が対象としているチャンピオン名（候補リストの中から1つ）")


class _HeldAssets(BaseModel):
    items: list[str] = Field(default_factory=list, description="手持ちの通常アイテム名")
    emblems: list[str] = Field(default_factory=list, description="手持ちの紋章名")


_GENERAL_SYSTEM_PROMPT = """あなたはTFTの最新メタに詳しいアナリストです。
以下の構成統計データに基づいて、質問に対して簡潔に回答してください。
データに書かれていない情報を断定的に語らないよう注意してください。
"""


def handle_item_build(query: str, patch: str | None = None) -> ItemBuildAdvice | None:
    champions = meta_service.list_champions_with_build(patch)
    if not champions:
        return None

    champion = None
    for c in champions:
        if c in query:
            champion = c
            break

    if champion is None:
        llm = get_chat_model(temperature=0.0)
        extractor = llm.with_structured_output(_ChampionExtraction)
        extracted = extractor.invoke(
            [
                {
                    "role": "system",
                    "content": (
                        "以下のチャンピオン名の候補から、質問に最も合致する1名を選んでください。"
                        f" 候補: {', '.join(champions)}"
                    ),
                },
                {"role": "user", "content": query},
            ]
        )
        champion = extracted.champion

    build = meta_service.get_item_build(champion, patch)
    if not build:
        return None
    return ItemBuildAdvice.model_validate(build)


def handle_comp_lookup(query: str, patch: str | None = None) -> list[CompRecommendation]:
    llm = get_chat_model(temperature=0.0)
    extractor = llm.with_structured_output(_HeldAssets)
    extracted = extractor.invoke(
        [
            {
                "role": "system",
                "content": (
                    "ユーザーの発言から、手持ちの通常アイテム名(items)と紋章名(emblems)を"
                    "抽出してください。分からなければ空リストで構いません。"
                ),
            },
            {"role": "user", "content": query},
        ]
    )
    matches = meta_service.search_comps_by_assets(extracted.items, extracted.emblems, patch)
    return [CompRecommendation.model_validate(m) for m in matches]


def handle_general_meta(query: str, patch: str | None = None) -> str:
    comps = meta_service.get_comp_recommendations(patch)
    comps_text = "\n".join(
        f"- {c['comp_name']} (Tier{c['tier']}, 平均順位{c['avg_place']}, "
        f"Top4率{int(c['top4_rate'] * 100)}%, サンプル{c['sample_size']}件/{c['confidence_level']})"
        for c in comps
    )
    llm = get_chat_model(temperature=0.3)
    messages = [
        {"role": "system", "content": _GENERAL_SYSTEM_PROMPT},
        {"role": "user", "content": f"構成統計データ:\n{comps_text}\n\n質問: {query}"},
    ]
    response = llm.invoke(messages)
    return response.content


def handle_meta(query: str, meta_subtype: str | None, patch: str | None = None) -> dict:
    """戻り値: {"type": "item_build" | "comp_list" | "text", "data": ...}"""
    if meta_subtype == "item_build":
        advice = handle_item_build(query, patch)
        if advice is None:
            return {
                "type": "text",
                "data": "該当するアイテムビルドの統計データが見つかりませんでした。チャンピオン名を明示して再度質問してください。",
            }
        return {"type": "item_build", "data": advice}

    if meta_subtype == "comp_from_item_or_emblem":
        comps = handle_comp_lookup(query, patch)
        if not comps:
            return {
                "type": "text",
                "data": "手持ちのアイテム/紋章に合致する構成が見つかりませんでした。",
            }
        return {"type": "comp_list", "data": comps}

    return {"type": "text", "data": handle_general_meta(query, patch)}
