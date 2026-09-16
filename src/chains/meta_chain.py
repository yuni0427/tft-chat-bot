"""
最新メタ・アイテム・構成に関する質問への回答チェーン。

meta_subtype に応じて以下の3つに分岐する:
- item_build: 特定チャンピオンのアイテムビルド解説（構造化出力 -> カードUI）
- comp_from_item_or_emblem: 手持ちアイテム/紋章からの構成逆引き（構造化出力 -> カードUI）
- general: Riot統計 ＋ TFTAcademy最新プロ評価を統合したナラティブ回答
"""
import json
from pydantic import BaseModel, Field

from src.llm.factory import get_chat_model
from src.meta import meta_service
from src.meta.tftacademy_client import get_tftacademy_tierlist
from src.schemas.comp_recommendation import CompRecommendation
from src.schemas.item_build import ItemBuildAdvice


class _ChampionExtraction(BaseModel):
    champion: str = Field(..., description="質問が対象としているチャンピオン名（候補リストの中から1つ）")


class _HeldAssets(BaseModel):
    items: list[str] = Field(default_factory=list, description="手持ちの通常アイテム名")
    emblems: list[str] = Field(default_factory=list, description="手持ちの紋章名")


_GENERAL_SYSTEM_PROMPT = """あなたはTFTの最新メタに精通したトップアナリストです。
提供された「Riot公式 統計データ（勝率・平均順位）」と「TFTAcademy（トッププロ監修のティア表・進行ガイド）」の両面を照らし合わせて、ユーザーの質問に具体的かつ論理的に回答してください。

【回答方針】
1. Riot統計から客観的な実数値（平均順位、Top4率など）を引用してください。
2. TFTAcademyの評価（S/A Tier、メインキャリー、推奨進行スタイルなど）がある場合はプロ視点のアドバイスとして補強してください。
3. 提供されたデータにない根拠のない情報は断定せず、分かりやすく整理して伝えてください。
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


def _format_academy_data(raw_data: dict | list) -> str:
    """TFTAcademyのデータをプロンプト用の軽量テキストにフォーマット"""
    if not raw_data:
        return "利用可能なTFTAcademyデータはありません。"

    formatted = []
    if isinstance(raw_data, dict):
        for tier, comps in raw_data.items():
            formatted.append(f"【Tier {tier}】")
            if isinstance(comps, list):
                for comp in comps:
                    if isinstance(comp, dict):
                        name = comp.get("name", "Unknown")
                        playstyle = comp.get("playstyle", "")
                        carries = ", ".join(comp.get("carries", [])) if isinstance(comp.get("carries"), list) else comp.get("carries", "")
                        items = ", ".join(comp.get("items", [])) if isinstance(comp.get("items"), list) else comp.get("items", "")
                        formatted.append(f"  - {name} ({playstyle}) | キャリー: {carries} | 推奨アイテム: {items}")
    elif isinstance(raw_data, list):
        for item in raw_data:
            if isinstance(item, dict):
                tier = item.get("tier", "Unknown")
                formatted.append(f"【Tier {tier}】")
                for comp in item.get("comps", []):
                    if isinstance(comp, dict):
                        formatted.append(f"  - {comp.get('name', 'Unknown')} ({comp.get('playstyle', '')})")
    return "\n".join(formatted) if formatted else json.dumps(raw_data, ensure_ascii=False)


def handle_general_meta(query: str, patch: str | None = None) -> str:
    # 1. Riot API 統計データの取得
    comps = meta_service.get_comp_recommendations(patch)
    comps_text = "\n".join(
        f"- {c['comp_name']} (Tier{c['tier']}, 平均順位{c['avg_place']}, "
        f"Top4率{int(c['top4_rate'] * 100)}%, サンプル{c['sample_size']}件/{c['confidence_level']})"
        for c in comps
    )

    # 2. TFTAcademy プロティア表の取得
    academy_raw = get_tftacademy_tierlist()
    academy_text = _format_academy_data(academy_raw)

    llm = get_chat_model(temperature=0.3)
    user_prompt = (
        f"【Riot公式 実戦マッチ統計】\n{comps_text}\n\n"
        f"【TFTAcademy 最新プロティア表】\n{academy_text}\n\n"
        f"質問: {query}"
    )

    messages = [
        {"role": "system", "content": _GENERAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
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
