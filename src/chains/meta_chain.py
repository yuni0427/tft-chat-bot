"""
最新メタ・アイテム・構成に関する質問への回答チェーン。
"""
import json
from pydantic import BaseModel, Field

from src.llm.factory import get_chat_model
from src.meta import meta_service
from src.meta.tft_translator import load_tft_translations, translate_term
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
4. 【参照元リンク】紹介・参照したTFTAcademyの構成がある場合、回答の末尾に「--- \n 📚 **参照元ガイド:**」として Markdown リンク形式（例: [構成名 - TFTAcademy](URL)）を必ず明記してください。
5. 【言語対応】ユーザーが英語で質問した場合は英語で回答し、日本語で質問した場合は日本語で回答してください。
"""


def _format_academy_data(raw_data: dict | list) -> str:
    """TFTAcademyの実データ構造からプロンプト用の軽量テキスト（URL情報付き）にフォーマット"""
    if not raw_data:
        return "利用可能なTFTAcademyデータはありません。"

    guides = raw_data.get("guides", []) if isinstance(raw_data, dict) else raw_data
    if not guides:
        return "利用可能なTFTAcademyデータはありません。"

    trans_map = load_tft_translations()

    grouped_comps: dict[str, list[dict]] = {}
    for comp in guides:
        if isinstance(comp, dict):
            tier = comp.get("tier", "Other").upper()
            grouped_comps.setdefault(tier, []).append(comp)

    tier_order = ["S", "A", "B", "C", "OTHER"]
    sorted_tiers = sorted(grouped_comps.keys(), key=lambda x: tier_order.index(x) if x in tier_order else 99)

    formatted = []
    for tier in sorted_tiers:
        formatted.append(f"【Tier {tier}】")
        for comp in grouped_comps[tier]:
            title = comp.get("metaTitle") or comp.get("title", "構成名")
            style = comp.get("style", "Standard")

            # TFTAcademy の構成詳細URLを生成 (slug または titleベース)
            slug = comp.get("slug") or title.lower().replace(" ", "-").replace("'", "")
            guide_url = f"https://tftacademy.com/tierlist/comps/{slug}"

            main_champ_info = comp.get("mainChampion", {})
            main_champ_raw = main_champ_info.get("apiName", "") if isinstance(main_champ_info, dict) else ""
            main_champ = translate_term(main_champ_raw, trans_map)

            items = []
            for board_unit in comp.get("finalComp", []):
                if board_unit.get("apiName") == main_champ_raw:
                    items = [translate_term(it, trans_map) for it in board_unit.get("items", [])]
                    break
            items_str = ", ".join(items) if items else "状況に応じて配分"

            comp_line = (
                f"  - {title} (スタイル: {style}) | キャリー: {main_champ} | "
                f"コアアイテム: {items_str} | ガイドURL: {guide_url}"
            )

            aug_tip = comp.get("augmentsTip")
            if aug_tip:
                comp_line += f" | コツ: {aug_tip}"

            formatted.append(comp_line)

    return "\n".join(formatted)


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

    content = response.content
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        return "".join(text_parts).strip()

    return str(content).strip()


def handle_meta(query: str, meta_subtype: str | None, patch: str | None = None) -> dict:
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