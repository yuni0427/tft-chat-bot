"""最新メタ・アイテム・構成に関する質問への回答チェーン。

- item_build: 特定チャンピオンのアイテムビルド解説（Riot統計 + TFTAcademyプロ推奨 + ガイドリンク）
- comp_from_item_or_emblem: 手持ちアイテム/紋章からの構成逆引き
- general: 基礎知識・ゲームデータ(ベクトルDB) ＋ Riot統計 ＋ TFTAcademy
を統合した実践的回答
"""

import json
from pydantic import BaseModel, Field

from src.llm.factory import get_chat_model
from src.meta import meta_service
from src.meta.tft_translator import load_tft_translations, translate_term
from src.meta.tftacademy_client import get_tftacademy_tierlist
from src.rag.retriever import retrieve
from src.schemas.comp_recommendation import CompRecommendation


class _ChampionExtraction(BaseModel):
    champion: str = Field(
        ...,
        description="質問が対象としているチャンピオン名（候補リストの中から1つ）",
    )


class _HeldAssets(BaseModel):
    items: list[str] = Field(
        default_factory=list, description="手持ちの通常アイテム名"
    )
    emblems: list[str] = Field(
        default_factory=list, description="手持ちの紋章名"
    )


_GENERAL_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)のハイレベルな専属コーチ兼トップアナリストです。
プレイヤーの質問に対し、【基礎知識・チャンピオン/特性データ】および【実戦統計・プロデータ】を根拠として論理的かつ正確に回答してください。

【重要：デバフ（負傷/重傷・燃焼/炎上・細断など）およびチャンピオンの回答ルール】
1. **「自前効果」と「アイテム適性」を絶対に混同しないでください。**
   - 「自前スキルや特性で付与できるチャンピオン」を聞かれた場合は、**アイテムなしでスキル文章や特性効果自体にデバフ付与が明記されている駒・シナジーのみ**を挙げてください。
   - 「アイテムを持たせることで広範囲に撒ける駒（適任者）」を、自前で持っているかのように説明することは厳禁です。言及する場合は「スキル自体にはないが、アイテム（モレロノミコン等）を持たせるキャリアとして優秀」と明確にセクションを分けてください。
2. データ内に該当する自前持ちユニットが少ない場合は、「スキル単体で標準搭載している駒はごく一部に限られるため、基本はアイテム（レッドバフ、モレロノミコン、サンファイア）や特性（インフェルノ等）で補うのが現環境のセオリー」と客観的な事実を伝えてください。
3. チャンピオンのコスト、スキル、特性、デバフ効果は、必ず【基礎知識・チャンピオン/特性データ】の記述のみを根拠とし、捏造や過去セットの記憶での補完を禁じます。
4. 【重要】「ナレッジベース」「提供されたコンテキスト」「データ内には〜」といったシステム内部の用語は一切使わないでください。「基本セオリーでは」「現行パッチのデータ上は」「基礎知識として」のように自然なコーチングの言葉遣いを用いてください。
5. 【構成ごとのリンクとチームコードの出力ルール】
   構成を具体的に推奨する場合は、解説セクションの「すぐ直下」にTFTAcademy詳細リンクとチームコードを以下のフォーマットで記載してください:
   - 📖 **詳細ガイド:** [構成名 - TFTAcademy](URL)

6. 【言語対応】ユーザーが英語で質問した場合は英語で回答し、日本語で質問した場合は日本語で回答してください。
"""

_ITEM_BUILD_SYSTEM_PROMPT = """あなたはTFTの最新メタに精通したトップアナリストです。
特定のチャンピオンに関するアイテムビルドの質問に対し、以下の2つのデータを照合して解説してください。
1. 「Riot公式 実戦マッチ統計」: 各アイテムの平均順位、Top4率、サンプル数
2. 「TFTAcademy 最新プロ推奨」: プロティアリストで推奨されているコアアイテム、採用されている構成、立ち回りのコツ

【出力構成】
- **推奨コアアイテム（三種の神器 / BIS）**: 統計・プロ推奨の両面から最もおすすめの3スロット
- **代替・状況別アイテム**: 寿司や素材の偏りに応じた柔軟な代替候補
- **プロのアドバイス & 採用構成**: TFTAcademyでの立ち回り方針や相性の良いシナジー
- **該当構成ガイド**: 参照元リンク（Markdown形式）

【言語対応】ユーザーの質問言語（日本語または英語）に合わせて回答してください。
"""


def _get_academy_champ_context(champ_name: str, raw_data: dict | list) -> str:
    """TFTAcademyデータから特定チャンピオンの推奨アイテムや構成情報を検索"""
    if not raw_data:
        return "TFTAcademyに該当データなし"

    guides = (
        raw_data.get("guides", [])
        if isinstance(raw_data, dict)
        else raw_data
    )
    trans_map = load_tft_translations()
    champ_lower = champ_name.lower()

    found_info = []
    for comp in guides:
        title = comp.get("metaTitle") or comp.get("title", "構成名")
        slug = comp.get("compSlug")
        guide_url = (
            f"https://tftacademy.com/tierlist/comps/{slug}"
            if slug
            else "https://tftacademy.com/tierlist/comps"
        )

        for unit in comp.get("finalComp", []):
            raw_api = unit.get("apiName", "")
            unit_ja = translate_term(raw_api, trans_map)
            clean_unit = raw_api.split("_")[-1].lower()

            if (
                champ_lower in raw_api.lower()
                or champ_lower in clean_unit
                or champ_lower in unit_ja.lower()
            ):
                items = [
                    translate_term(it, trans_map)
                    for it in unit.get("items", [])
                ]
                items_str = ", ".join(items) if items else "状況に応じて配分"
                tips = comp.get("augmentsTip", "")

                info = (
                    f"- 採用構成: 【Tier {comp.get('tier', 'A')}】{title}\n"
                    f"  推奨アイテム: {items_str}\n"
                    f"  ガイドURL: {guide_url}"
                )
                if tips:
                    info += f"\n  プロTips: {tips}"
                found_info.append(info)

    if not found_info:
        return "TFTAcademyの主要構成には現在メインキャリーとして掲載されていません（フレックス・サブ枠など）。"

    return "\n\n".join(found_info)


def _format_academy_data(raw_data: dict | list) -> str:
    """TFTAcademyの実データ構造からプロンプト用の軽量テキスト（URLとチームコード付き）にフォーマット"""
    if not raw_data:
        return "利用可能なTFTAcademyデータはありません。"

    guides = (
        raw_data.get("guides", [])
        if isinstance(raw_data, dict)
        else raw_data
    )
    if not guides:
        return "利用可能なTFTAcademyデータはありません。"

    trans_map = load_tft_translations()

    grouped_comps: dict[str, list[dict]] = {}
    for comp in guides:
        if isinstance(comp, dict):
            tier = comp.get("tier", "Other").upper()
            grouped_comps.setdefault(tier, []).append(comp)

    tier_order = ["S", "A", "B", "C", "OTHER"]
    sorted_tiers = sorted(
        grouped_comps.keys(),
        key=lambda x: tier_order.index(x) if x in tier_order else 99,
    )

    formatted = []
    for tier in sorted_tiers:
        formatted.append(f"【Tier {tier}】")
        for comp in grouped_comps[tier]:
            title = comp.get("metaTitle") or comp.get("title", "構成名")
            style = comp.get("style", "Standard")

            slug = comp.get("compSlug")
            guide_url = (
                f"https://tftacademy.com/tierlist/comps/{slug}"
                if slug
                else "https://tftacademy.com/tierlist/comps"
            )


            main_champ_info = comp.get("mainChampion", {})
            main_champ_raw = (
                main_champ_info.get("apiName", "")
                if isinstance(main_champ_info, dict)
                else ""
            )
            main_champ = translate_term(main_champ_raw, trans_map)

            items = []
            final_units = []
            for board_unit in comp.get("finalComp", []):
                u_raw = board_unit.get("apiName", "")
                final_units.append(translate_term(u_raw, trans_map))
                if u_raw == main_champ_raw:
                    items = [
                        translate_term(it, trans_map)
                        for it in board_unit.get("items", [])
                    ]

            items_str = ", ".join(items) if items else "状況に応じて配分"
            units_str = ", ".join(final_units) if final_units else "指定なし"

            comp_line = (
                f"  - 構成名: {title} (スタイル: {style})\n"
                f"    メインキャリー: {main_champ} | コアアイテム: {items_str}\n"
                f"    最終盤面ユニット: {units_str}\n"
                f"    ガイドURL: {guide_url}\n"
            )

            aug_tip = comp.get("augmentsTip")
            if aug_tip:
                comp_line += f"\n    コツ: {aug_tip}"

            formatted.append(comp_line)

    return "\n\n".join(formatted)


def handle_item_build(query: str, patch: str | None = None) -> str:
    """特定チャンピオンのアイテムビルドを Riot統計 + TFTAcademy の両方から回答"""
    champions = meta_service.list_champions_with_build(patch)
    if not champions:
        return "アイテム統計データが見つかりませんでした。"

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

    # 1. Riot 実戦マッチ統計
    build = meta_service.get_item_build(champion, patch)
    riot_stats_text = ""
    if build:
        trans_map = load_tft_translations()
        items_stats = []
        for it in build.get("top_items", []):
            it_name = translate_term(it.get("item_name", ""), trans_map)
            items_stats.append(
                f"- {it_name}: 平均順位 {it.get('avg_place', '-')} / Top4率 {int(it.get('top4_rate', 0)*100)}% (サンプル{it.get('sample_size', 0)}件)"
            )
        riot_stats_text = "\n".join(items_stats)
    else:
        riot_stats_text = "Riot統計データなし"

    # 2. TFTAcademy プロ推奨ガイド
    academy_raw = get_tftacademy_tierlist()
    academy_context = _get_academy_champ_context(champion, academy_raw)

    llm = get_chat_model(temperature=0.3)
    user_prompt = (
        f"対象チャンピオン: {champion}\n\n"
        f"【Riot公式 アイテム統計】\n{riot_stats_text}\n\n"
        f"【TFTAcademy プロティアリスト推奨】\n{academy_context}\n\n"
        f"質問: {query}"
    )

    messages = [
        {"role": "system", "content": _ITEM_BUILD_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    response = llm.invoke(messages)

    content = response.content
    if isinstance(content, list):
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "".join(text_parts).strip()

    return str(content).strip()


def handle_comp_lookup(
    query: str, patch: str | None = None
) -> list[CompRecommendation]:
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
    matches = meta_service.search_comps_by_assets(
        extracted.items, extracted.emblems, patch
    )
    return [CompRecommendation.model_validate(m) for m in matches]


def handle_general_meta(query: str, patch: str | None = None) -> str:
    # 1. ベクトルDBから基礎知識・チャンピオン・特性データを検索 (retrieve関数を使用)
    try:
        retrieved_docs = retrieve(query, k=5)
        knowledge_context = "\n\n".join(
            [
                doc.get("content") or doc.get("page_content") or str(doc)
                for doc in retrieved_docs
                if isinstance(doc, dict)
            ]
        )
    except Exception:
        knowledge_context = "基礎知識データの取得をスキップしました。"

    # 2. Riot実戦統計
    comps = meta_service.get_comp_recommendations(patch)
    comps_text = "\n".join(
        f"- {c['comp_name']} (Tier{c['tier']}, 平均順位{c['avg_place']}, "
        f"Top4率{int(c['top4_rate'] * 100)}%, サンプル{c['sample_size']}件/{c['confidence_level']})"
        for c in comps
    )

    # 3. TFTAcademy プロティア表
    academy_raw = get_tftacademy_tierlist()
    academy_text = _format_academy_data(academy_raw)

    llm = get_chat_model(temperature=0.3)
    user_prompt = (
        f"【基礎知識・チャンピオン/特性データ】\n{knowledge_context}\n\n"
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
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "".join(text_parts).strip()

    return str(content).strip()


def handle_meta(
    query: str, meta_subtype: str | None, patch: str | None = None
) -> dict:
    if meta_subtype == "item_build":
        advice_text = handle_item_build(query, patch)
        return {"type": "text", "data": advice_text}

    if meta_subtype == "comp_from_item_or_emblem":
        comps = handle_comp_lookup(query, patch)
        if not comps:
            return {
                "type": "text",
                "data": "手持ちのアイテム/紋章に合致する構成が見つかりませんでした。",
            }
        return {"type": "comp_list", "data": comps}

    return {"type": "text", "data": handle_general_meta(query, patch)}