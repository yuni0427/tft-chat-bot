"""最新メタ・アイテム・構成に関する質問への回答チェーン。

- item_build: 特定チャンピオンのアイテムビルド解説（Riot統計 + TFTAcademyプロ推奨 + ガイドリンク）
- comp_from_item_or_emblem: 手持ちアイテム/紋章からの構成逆引き
- comp_recommendation: おすすめ構成・メタ傾向（Riot実戦統計 × TFTAcademy比較）
- general: 単体チャンピオン仕様・デバフ効果・基礎知識（ベクトルDB参照）
"""

import json
from pathlib import Path
from pydantic import BaseModel, Field

import config
from src.llm.factory import get_chat_model
from src.meta import meta_service
from src.meta.tft_translator import (
    load_tft_translations,
    preprocess_tft_text,
    translate_term,
)
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


# 1. 構成メタ・おすすめ構成専用プロンプト（完全日本語化・統計比較）
_COMP_META_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の論理的で無駄のないトップアナリストです。
プレイヤーの質問に対し、【Riot公式 実戦マッチ統計】と【TFTAcademy 最新プロティア表】を照合し、各構成を明確に比較・評価して完全な日本語で回答してください。

【絶対前提】
- ユーザーはUI上で現在稼働中の最新パッチ（Patch {target_patch}）を選択しています。
- パッチの妥当性を疑ったり、「データが存在しない」「古い/未来のパッチである」と回答することは一切禁止します。
- あなた自身の古い事前学習知識（過去セットの駒や構成など）でパッチの存在を否定せず、提供された実データを唯一の事実として受け入れてください。

【最重要：完全日本語化ルール】
すべての出力を自然な日本語およびカタカナ表記で統一してください。英語タイトルの放置は禁止です。
- 提供データに英語のTipsやアドバイスが含まれる場合も、必ず自然で無駄のない日本語に要約・翻訳して提示してください。
- DA_xxx などの内部API名や生トークン（rod, tear 等）の混入は厳禁です。

【出力要件】
1. **各構成の提示と実戦スタッツ**
   - 構成ごとに【Riot公式 実戦マッチ統計】から「平均順位」「Top4率」「サンプル数」を明記してください。
   - 構成名およびスタイル名は必ず日本語表記（例: 【Tier A】インヴォーカー アーリ（スタイル: 4コスト ファスト8））としてください。
2. **スタッツに基づく構成比較・立ち位置の解説（必須）**
   - 単に並べるのではなく、「Top4率が高く安定してLPを盛れる構成」「到達時の平均順位は最上位だが進行事故のリスクもあるファスト9型」のように、強み・リスクの違いを明確に比較してください。
3. **コミット条件（※TFTAcademyに記載がある場合のみ）**
   - 提供された【TFTAcademy 最新プロティア表】のTipsやガイド情報内に明記されている場合のみ、アイテム素材の寄り、オーグメント/紋章、盤面の重なりを箇条書きで記載してください。
   - データ内に明確な言及がない場合は、無理に推測・創作せず省略してください。
4. **ガイドリンク**
   - 各構成の直下に以下のみを記載してください:
     - 📖 **詳細ガイド:** [構成名(日本語) - TFTAcademy](URL)

【トーン & マナー】
- 感情的な説教（「〜しましょう！」等）や精神論は禁止し、客観的な事実と判断ロジックのみを淡々と伝えてください。
- 「ナレッジベース」「コンテキスト」などの内部用語は使用禁止です。
"""

# 2. 単体駒・仕様・基礎知識専用プロンプト（余計なお節介を排除）
_GENERAL_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の論理的で無駄のない専属アナリストです。
プレイヤーの質問に対し、【基礎知識・チャンピオン/特性データ】に基づいて簡潔かつ正確に回答してください。

【回答の基本原則】
1. **質問のスコープを厳格に守る**
   - 特定の駒やデバフについて聞かれた場合は、その対象の情報のみを端的に回答してください。
   - ユーザーから明示的に求められない限り、余計な構成紹介や長々としたセオリー講釈は一切不要です。
2. **「自前効果」の正確な線引き**
   - 「自前でデバフを持つ駒」を聞かれた場合は、スキルや特性に効果が明記されている駒のみを挙げてください（アイテム適任者を混ぜない）。
3. **トーン & マナー**
   - 「〜しましょう！」といった感情的な説教調は禁止し、客観的な事実のみを淡々と伝えてください。
   - 「ナレッジベース」「コンテキスト」などの内部用語は使用禁止です。

【言語対応】ユーザーの言語（日本語/英語）に合わせて回答してください。
"""

# 3. アイテムビルド専用プロンプト
_ITEM_BUILD_SYSTEM_PROMPT = """あなたはTFTの最新メタに精通したトップアナリストです。
特定のチャンピオンに関するアイテムビルドの質問に対し、以下の2つのデータを照合して解説してください。
1. 「Riot公式 実戦マッチ統計」: 各アイテムの平均順位、Top4率、サンプル数、またはコアアイテム採用理由
2. 「TFTAcademy 最新プロ推奨」: プロティアリストで推奨されているコアアイテム、採用されている構成、立ち回りのコツ

【出力構成】
- **推奨コアアイテム（三種の神器 / BIS）**: 統計・プロ推奨の両面から最もおすすめの3スロット
- **代替・状況別アイテム**: 寿司や素材の偏りに応じた柔軟な代替候補
- **プロのアドバイス & 採用構成**: TFTAcademyでの立ち回り方針や相性の良いシナジー
- **該当構成ガイド**: 参照元リンク（Markdown形式）

【言語対応】ユーザーの質問言語（日本語または英語）に合わせて回答してください。
"""


# 4. 単一構成専用プロンプト
_SINGLE_COMP_GUIDE_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の論理的で無駄のないトップアナリストです。
特定の構成に関するやり方・プレイ方法の質問に対し、【TFTAcademy ガイド詳細】と【実戦マッチ統計】を照合して過不足なく解説してください。

【出力構成】
1. **構成概要 & 実戦スタッツ**
   - 構成名、プレイスタイル（Fast8、リロール等）、Riot統計がある場合は平均順位/Top4率を記載。
2. **メインキャリー & メインタンクの推奨アイテム（BIS）**
   - キャリーおよびタンクの推奨アイテムと採用理由を端的に解説。
3. **進行と立ち回りのコツ**
   - TFTAcademyに記載されている盤面進行やオーグメントのTipsを抜粋（データにない場合は無理に創作しない）。
4. **詳細ガイドリンク**
   - 📖 **詳細ガイド:** [構成名 - TFTAcademy](URL)
5. **セオリー案内（必須）**
   - 回答の末尾で「なお、この構成の基礎となる『{cost}コスト構成の一般的な進行セオリーやリロールタイミング』について詳しく確認しますか？」と一言添えてください。

【トーン & マナー】
- 感情的な精神論は排除し、客観的な事実と判断ロジックのみを淡々と述べてください。
- 「ナレッジベース」「コンテキスト」などの内部用語は使用禁止です。
"""

# 5. アイテム/紋章からの逆引き専用プロンプト（TFTAcademy主軸 × Riot統計裏付け）
_COMP_FROM_ASSETS_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の論理的で無駄のないトップアナリストです。
プレイヤーの手持ちアイテムや紋章に対し、【TFTAcademy 最新プロティア表】から向かうべき有力構成を提示し、【Riot公式 実戦マッチ統計】でその強さ（信憑性）を裏付けて回答してください。

【絶対前提】
- ユーザーはUI上で現在稼働中の最新パッチ（Patch {target_patch}）を選択しています。
- パッチの妥当性を疑ったり、「データが存在しない」「古い/未来のパッチである」と回答することは一切禁止します。
- 構成の型やアイテム適正は【TFTAcademy】を最高精度の正解基準とし、実戦スタッツ（平均順位・Top4率）をその信憑性の裏付けとして扱ってください。

【出力要件】
各候補構成（最大3つ）について、必ず以下の項目・形式で記載してください:
1. **構成名 & 実戦スタッツ**
   - 構成名 (Tier)、プレイスタイル (Fast8, リロール等)
   - 実戦スタッツ: 平均順位、Top4率、サンプル数（提供データにある場合）
2. **手持ち素材で作る推奨アイテム（必須）**
   - 提供された「今回作成するアイテム」を基に、手持ち素材を組み合わせて「何を作るか」を具体的に提示してください。
3. **完成形に向けた残りのスロット**
   - 提供された「目指すべき残りのスロット」に記載されているアイテムと素材のみをそのまま案内してください。
   - ※提供データに存在しないアイテム名や妥協候補、合成レシピを独自に推測・創作することは一切禁止します。
4. **詳細ガイドリンク**
   - 各構成の末尾に、提供されたガイドURLを用いて以下のみを記載してください:
     📖 **詳細ガイド:** [構成名 - TFTAcademy](URL)

【トーン & マナー】
- 感情的な精神論や説教調（「〜しましょう！」等）は排除し、客観的な事実と移行判断ロジックのみを淡々と伝えてください。
- 「コンテキスト」「プロンプト」などの内部用語は使用禁止です。
"""

def _find_target_comp(query: str, guides: list[dict]) -> dict | None:
    """ユーザーの入力に最も合致する構成をTFTAcademyデータから検索"""
    trans_map = load_tft_translations()
    query_lower = query.lower()

    # 1. 構成タイトルやslugでの部分一致
    for comp in guides:
        title = comp.get("metaTitle") or comp.get("title", "")
        slug = comp.get("compSlug", "")
        if (title and title.lower() in query_lower) or (slug and slug.replace("-", " ") in query_lower):
            return comp

    # 2. メインキャリー名での一致（日本語/英語）
    for comp in guides:
        main_champ_info = comp.get("mainChampion", {})
        raw_api = main_champ_info.get("apiName", "") if isinstance(main_champ_info, dict) else ""
        unit_ja = translate_term(raw_api, trans_map)
        unit_en = raw_api.split("_")[-1].lower()

        if (unit_ja and unit_ja.lower() in query_lower) or (unit_en and unit_en in query_lower):
            return comp

    return None


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
    """TFTAcademyの実データ構造からプロンプト用の軽量テキスト（URL付き）にフォーマット"""
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
            # ★ 非公開アーカイブ（メタ落ち）を確実に遮断
            if not comp.get("isPublic", True):
                continue
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
            raw_title = comp.get("metaTitle") or comp.get("title", "構成名")
            # ★ 辞書にある駒名・特性名を先行して日本語化
            title = preprocess_tft_text(raw_title, trans_map)

            raw_style = comp.get("style", "Standard")
            style = preprocess_tft_text(raw_style, trans_map)

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
                    # ★ アイテム専用の日本語変換を使用
                    items = [
                        meta_service.to_japanese_item_name(it)
                        for it in board_unit.get("items", [])
                    ]

            items_str = ", ".join(items) if items else "状況に応じて配分"
            units_str = ", ".join(final_units) if final_units else "指定なし"

            comp_line = (
                f"  - 構成名: {title} (スタイル: {style})\n"
                f"    メインキャリー: {main_champ} | コアアイテム: {items_str}\n"
                f"    最終盤面ユニット: {units_str}\n"
                f"    ガイドURL: {guide_url}"
            )

            aug_tip = comp.get("augmentsTip")
            if aug_tip:
                # ★ Tips内の駒名・特性名も先行日本語化
                comp_line += f"\n    コツ: {preprocess_tft_text(aug_tip, trans_map)}"

            formatted.append(comp_line)

    return "\n\n".join(formatted) if formatted else "利用可能な公開構成はありません。"


def handle_comp_meta(query: str, patch: str | None = None) -> str:
    """おすすめ構成・メタ質問専用（Riot実戦統計 × TFTAcademy比較）"""
    target_patch = patch or meta_service.get_current_patch()

    comps = meta_service.get_comp_recommendations(target_patch)
    trans_map = load_tft_translations()

    # KeyErrorを防ぐために .get() で安全に取得し、構成名を先行日本語化
    comps_text = (
        "\n".join(
            f"- {preprocess_tft_text(c.get('comp_name') or c.get('name') or c.get('title', '名称不明'), trans_map)} "
            f"(Tier{c.get('tier', '-')}, 平均順位{c.get('avg_place', '-')}, "
            f"Top4率{int(c.get('top4_rate', 0) * 100)}%, サンプル{c.get('sample_size', 0)}件/{c.get('confidence_level', '-')})"
            for c in comps
        )
        if comps
        else "実戦統計データ集計中（サンプル蓄積中）"
    )

    academy_raw = get_tftacademy_tierlist()
    academy_text = _format_academy_data(academy_raw)

    # パッチノート (tftips.app) が存在すれば自動で差し込む
    patch_notes_file = Path(config.DATA_DIR) / f"patch_{target_patch}" / "patch_notes.md"
    patch_notes_text = ""
    if patch_notes_file.exists():
        patch_notes_text = f"【Patch {target_patch} 差分・パッチノート】\n{patch_notes_file.read_text(encoding='utf-8')[:1500]}\n\n"

    system_prompt = _COMP_META_SYSTEM_PROMPT.replace("{target_patch}", str(target_patch))

    llm = get_chat_model(temperature=0.3)
    user_prompt = (
        f"【対象ゲーム内パッチ】: Patch {target_patch}\n\n"
        f"{patch_notes_text}"
        f"【Riot公式 実戦マッチ統計】\n{comps_text}\n\n"
        f"【TFTAcademy 最新プロティア表】\n{academy_text}\n\n"
        f"質問: {query}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = llm.invoke(messages)
    content = response.content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    return str(content).strip()


def handle_general_meta(query: str, patch: str | None = None) -> str:
    """単体駒・仕様・基礎知識専用（ベクトルDBのみを参照して端的に回答）"""
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

    llm = get_chat_model(temperature=0.1)
    user_prompt = (
        f"【基礎知識・チャンピオン/特性データ】\n{knowledge_context}\n\n"
        f"質問: {query}"
    )

    messages = [
        {"role": "system", "content": _GENERAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    response = llm.invoke(messages)
    content = response.content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    return str(content).strip()


def handle_item_build(query: str, patch: str | None = None) -> str:
    """特定チャンピオンのアイテムビルドを Riot統計 + TFTAcademy の両方から回答"""
    target_patch = patch or meta_service.get_current_patch()
    champions = meta_service.list_champions_with_build(target_patch)
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

    # 1. Riot 実戦マッチ統計 / アイテム推奨データ
    build = meta_service.get_item_build(champion, target_patch)
    riot_stats_text = ""
    if build:
        trans_map = load_tft_translations()
        items_stats = []

        # top_items 形式と core_items 形式の両方に対応
        item_list = build.get("top_items") or build.get("core_items") or []
        for it in item_list:
            raw_name = it.get("item_name") or it.get("name", "")
            it_name = translate_term(raw_name, trans_map)

            # 実戦スタッツ（平均順位等）がある場合は統計表記
            if "avg_place" in it:
                items_stats.append(
                    f"- {it_name}: 平均順位 {it.get('avg_place', '-')} / Top4率 {int(it.get('top4_rate', 0)*100)}% (サンプル{it.get('sample_size', 0)}件)"
                )
            # ビルド理由がある場合
            elif "reason" in it:
                items_stats.append(f"- {it_name}: {it.get('reason')}")
            else:
                items_stats.append(f"- {it_name}")

        # bis_standard_build（標準三種の神器セット）がある場合
        bis_info = build.get("bis_standard_build", {})
        if isinstance(bis_info, dict) and bis_info.get("items"):
            bis_items = [translate_term(name, trans_map) for name in bis_info["items"]]
            items_stats.append(f"\n【標準BISセット】: {' + '.join(bis_items)}")

        riot_stats_text = "\n".join(items_stats) if items_stats else "推奨アイテムデータなし"
    else:
        riot_stats_text = "Riot統計データなし"

    # 2. TFTAcademy プロ推奨ガイド
    academy_raw = get_tftacademy_tierlist()
    academy_context = _get_academy_champ_context(champion, academy_raw)

    llm = get_chat_model(temperature=0.3)
    user_prompt = (
        f"【対象ゲーム内パッチ】: Patch {target_patch}\n"
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
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    return str(content).strip()


def handle_comp_lookup(query: str, patch: str | None = None) -> str:
    """手持ちアイテム/紋章からTFTAcademy主軸で逆引きし、Riot実戦統計で裏付けして解説"""
    target_patch = patch or meta_service.get_current_patch()
    trans_map = load_tft_translations()

    # 1. 手持ちアセットの抽出
    llm_extract = get_chat_model(temperature=0.0)
    extractor = llm_extract.with_structured_output(_HeldAssets)
    extracted = extractor.invoke([
        {
            "role": "system",
            "content": (
                "ユーザーの発言から、手持ちの通常アイテム名(items)と紋章名(emblems)を抽出してください。"
                "例: 「BFと涙」-> items=['BF', '涙']"
            ),
        },
        {"role": "user", "content": query},
    ])

    if not extracted.items and not extracted.emblems:
        return "手持ちのアイテム素材や紋章が認識できませんでした。「BFと涙がある」「アンバサ紋章出た」のようにお伝えください。"

    # 2. TFTAcademyから適合構成をスコアリング
    academy_raw = get_tftacademy_tierlist()
    guides = (
        academy_raw.get("guides", [])
        if isinstance(academy_raw, dict)
        else academy_raw
    )

    matched_candidates = meta_service.match_comps_by_component_inventory(
        extracted.items,
        extracted.emblems,
        guides,
        target_patch,
        trans_map,
    )

    if not matched_candidates:
        return "提示されたアイテム素材/紋章を活用できる有力なTFTAcademy構成が見つかりませんでした。"

    # 3. Riot実戦統計による裏付け付与
    comps_stats = meta_service.get_comp_recommendations(target_patch)
    candidates_context = []

    for item in matched_candidates:
        comp = item["comp"]
        title = comp.get("metaTitle") or comp.get("title", "構成名")
        tier = comp.get("tier", "A")
        style = comp.get("style", "Standard")
        slug = comp.get("compSlug", "")
        guide_url = (
            f"https://tftacademy.com/tierlist/comps/{slug}"
            if slug
            else "https://tftacademy.com/tierlist/comps"
        )

        main_carry = item["main_carry"]

# 1. TFTAcademy推奨のキャリー完成形アイテム（日本語名で統一取得）
        carry_target_items = []
        for u in comp.get("finalComp", []):
            u_raw = u.get("apiName", "").replace("DA_", "")
            u_name = translate_term(u_raw, trans_map)
            # 部分一致も含めて確実にキャリー駒を捕捉
            if u_name == main_carry or u_raw.lower() in main_carry.lower() or main_carry.lower() in u_raw.lower():
                carry_target_items = [meta_service.to_japanese_item_name(it) for it in u.get("items", [])]
                break

        # 2. 今回作成するアイテム（日本語）
        planned_text = " / ".join(item.get("reasons", []))

        # 3. 今回作ったアイテムを除外し、「残りの枠」と「必要素材」を日本語で算出
        remaining_items_info = []
        for target_it in carry_target_items:
            # スペースを除去して重複チェック（「ショウジンの矛」の残り枠混入を防止）
            clean_target = target_it.replace(" ", "")
            clean_planned = planned_text.replace(" ", "")
            if clean_target and clean_target not in clean_planned:
                recipe_ja = meta_service.get_item_recipe_ja(target_it)
                recipe_str = f"（必要素材: {' + '.join(recipe_ja)}）" if recipe_ja else ""
                remaining_items_info.append(f"{target_it}{recipe_str}")

        remaining_desc = ", ".join(remaining_items_info) if remaining_items_info else "主要枠完成"

        # 3. Riot実戦スタッツの紐付け
        stat = next(
            (
                c
                for c in comps_stats
                if main_carry in c.get("comp_name", "")
                or title in c.get("comp_name", "")
            ),
            None,
        )
        stat_info = (
            f"平均順位: {stat['avg_place']} / Top4率: {int(stat['top4_rate']*100)}% (サンプル数: {stat['sample_size']}件)"
            if stat
            else "実戦統計: サンプル蓄積中"
        )

        # 4. コンテキストの構築（URL、スタッツ、残り枠をすべて明示）
        candidates_context.append(
            f"【Tier {tier}】{title} (スタイル: {style})\n"
            f"- メインキャリー: {main_carry}\n"
            f"- 実戦スタッツ裏付け: {stat_info}\n"
            f"- 手持ち素材で作るアイテム: {planned_text}\n"
            f"- 目指すべき残りの完成形スロット: {remaining_desc}\n"
            f"- ガイドURL: {guide_url}"
        )

    # 4. LLMで解説文を生成
    system_prompt = _COMP_FROM_ASSETS_SYSTEM_PROMPT.replace(
        "{target_patch}", str(target_patch)
    )
    user_prompt = (
        f"【対象ゲーム内パッチ】: Patch {target_patch}\n"
        f"手持ちアイテム素材: {', '.join(extracted.items) if extracted.items else 'なし'}\n"
        f"手持ち紋章: {', '.join(extracted.emblems) if extracted.emblems else 'なし'}\n\n"
        f"【TFTAcademy 適合構成候補 & 実戦統計裏付け】\n"
        + "\n\n".join(candidates_context)
        + f"\n\nユーザーの質問: {query}"
    )

    llm = get_chat_model(temperature=0.2)
    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])
    content = response.content
    if isinstance(content, list):
        return "".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    return str(content).strip()


def _build_item_context(carry: str, tank: str | None, patch: str, trans_map: dict) -> str:
    """キャリーとタンクのアイテムコンテキストを構築するヘルパー"""
    def _extract_build(unit_name: str) -> str:
        build = meta_service.get_item_build(unit_name, patch)
        if not build:
            return f"- {unit_name}: アイテムデータ集計中"
        
        lines = []
        item_list = build.get("top_items") or build.get("core_items") or []
        for it in item_list:
            raw_name = it.get("item_name") or it.get("name", "")
            it_name = translate_term(raw_name, trans_map)
            if "avg_place" in it:
                lines.append(f"  - {it_name} (平均順位 {it.get('avg_place')} / Top4率 {int(it.get('top4_rate', 0)*100)}%)")
            elif "reason" in it:
                lines.append(f"  - {it_name}: {it.get('reason')}")
            else:
                lines.append(f"  - {it_name}")

        bis_info = build.get("bis_standard_build", {})
        if isinstance(bis_info, dict) and bis_info.get("items"):
            bis_items = [translate_term(n, trans_map) for n in bis_info["items"]]
            lines.append(f"  【標準三種の神器】: {' + '.join(bis_items)}")

        return "\n".join(lines) if lines else f"- {unit_name}: 推奨データなし"

    context = f"【メインキャリー ({carry}) 推奨アイテム】\n{_extract_build(carry)}"
    if tank and tank != "メインタンク":
        context += f"\n\n【メインタンク ({tank}) 推奨アイテム】\n{_extract_build(tank)}"
    return context


def handle_single_comp_guide(query: str, patch: str | None = None) -> str:
    """単一構成のやり方・進行・アイテムを包括的に解説（TFTAcademy非掲載時は統計＋アイテム特化）"""
    target_patch = patch or meta_service.get_current_patch()
    trans_map = load_tft_translations()
    
    academy_raw = get_tftacademy_tierlist()
    guides = academy_raw.get("guides", []) if isinstance(academy_raw, dict) else academy_raw
    target_comp = _find_target_comp(query, guides)

    comps_stats = meta_service.get_comp_recommendations(target_patch)

    # -------------------------------------------------------------
    # パターンA: TFTAcademy に該当構成が存在する場合（フルガイド）
    # -------------------------------------------------------------
    if target_comp:
        raw_title = target_comp.get("metaTitle") or target_comp.get("title", "構成")
        comp_title = preprocess_tft_text(raw_title, trans_map)
        style = preprocess_tft_text(target_comp.get("style", "Standard"), trans_map)
        slug = target_comp.get("compSlug", "")
        guide_url = f"https://tftacademy.com/tierlist/comps/{slug}" if slug else "https://tftacademy.com/tierlist/comps"

        main_champ_raw = target_comp.get("mainChampion", {}).get("apiName", "")
        main_carry = translate_term(main_champ_raw, trans_map)

        # タンク特定
        main_tank = "メインタンク"
        for unit in target_comp.get("finalComp", []):
            u_raw = unit.get("apiName", "")
            if u_raw != main_champ_raw and unit.get("items"):
                main_tank = translate_term(u_raw, trans_map)
                break

        matched_stat = next((c for c in comps_stats if main_carry in c.get("comp_name", "") or comp_title in c.get("comp_name", "")), None)
        stat_text = (
            f"実戦統計: 平均順位 {matched_stat['avg_place']} / Top4率 {int(matched_stat['top4_rate']*100)}% (サンプル数: {matched_stat['sample_size']})"
            if matched_stat else "実戦統計: 集計中"
        )

        build_context = _build_item_context(main_carry, main_tank, target_patch, trans_map)
        tips = target_comp.get("augmentsTip", "")
        cost_label = style.split("-")[0] if "Cost" in style else "この"

        system_prompt = _SINGLE_COMP_GUIDE_SYSTEM_PROMPT.replace("{cost}", cost_label)

        user_prompt = (
            f"【対象ゲーム内パッチ】: Patch {target_patch}\n"
            f"【構成名】: {comp_title} (スタイル: {style})\n"
            f"{stat_text}\n\n"
            f"{build_context}\n\n"
            f"【TFTAcademy プロTips・進行】: {tips}\n"
            f"【ガイドURL】: {guide_url}\n"
            f"ユーザーの質問: {query}"
        )

        llm = get_chat_model(temperature=0.2)
        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        content = response.content
        if isinstance(content, list):
            return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text").strip()
        return str(content).strip()

    # -------------------------------------------------------------
    # パターンB: TFTAcademy にないが、Riot実戦統計には存在する場合
    # -------------------------------------------------------------
    matched_stat = None
    query_lower = query.lower()
    for c in comps_stats:
        c_name = c.get("comp_name", "").lower()
        if any(token in c_name for token in query_lower.replace("構成", "").split()):
            matched_stat = c
            break

    if matched_stat:
        comp_name = matched_stat.get("comp_name", "該当構成")
        stat_text = (
            f"【Riot実戦統計】\n"
            f"- 構成名: {comp_name} (Tier {matched_stat.get('tier', '-')})\n"
            f"- 平均順位: {matched_stat.get('avg_place', '-')} / Top4率: {int(matched_stat.get('top4_rate', 0)*100)}% "
            f"(サンプル数: {matched_stat.get('sample_size', 0)}件 / 信頼度: {matched_stat.get('confidence_level', '-')})\n"
        )

        parts = [p.strip() for p in comp_name.replace("構成", "").split("/") if p.strip()]
        main_carry = parts[0] if len(parts) > 0 else comp_name
        main_tank = parts[1] if len(parts) > 1 else None

        build_context = _build_item_context(main_carry, main_tank, target_patch, trans_map)

        fallback_prompt = (
            f"【対象ゲーム内パッチ】: Patch {target_patch}\n"
            f"{stat_text}\n"
            f"{build_context}\n\n"
            f"※注: この構成は現在TFTAcademyの個別ティアリストには未掲載のため、Riot実戦統計およびアイテムビルドデータを中心に提示しています。\n\n"
            f"ユーザーの質問: {query}"
        )

        fallback_system = """あなたはTFTのトップアナリストです。
TFTAcademyに個別ガイドがない構成について、実戦統計データとアイテムビルドのみを端的に解説してください。

【出力要件】
1. **実戦スタッツの提示**（平均順位、Top4率、サンプル数）
2. **メインキャリー・メインタンクの推奨アイテム（BIS）**
3. **セオリー案内**（回答の末尾で「なお、この構成の基礎となるキャリーを軸にした一般的な進行セオリーを確認しますか？」と一言添える）

【トーン】客観的かつ論理的に記載し、推測の嘘情報は書かないこと。
"""
        llm = get_chat_model(temperature=0.2)
        response = llm.invoke([
            {"role": "system", "content": fallback_system},
            {"role": "user", "content": fallback_prompt},
        ])
        content = response.content
        if isinstance(content, list):
            return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text").strip()
        return str(content).strip()

    # -------------------------------------------------------------
    # パターンC: どちらにも存在しない場合
    # -------------------------------------------------------------
    return handle_comp_meta(query, target_patch)
def handle_meta(query: str, meta_subtype: str, patch: str | None = None) -> dict:
    """Web UI / オーケストレーターからのリクエストを受け取り、適切なハンドラーに振り分けるエントリポイント"""
    target_patch = patch or meta_service.get_current_patch()

    if meta_subtype == "item_build":
        answer = handle_item_build(query, target_patch)
        source = "item_build"
    elif meta_subtype == "comp_from_item_or_emblem":
        answer = handle_comp_lookup(query, target_patch)
        source = "comp_lookup"
    elif meta_subtype == "comp_recommendation":
        answer = handle_comp_meta(query, target_patch)
        source = "comp_meta"
    elif meta_subtype == "single_comp_guide":
        answer = handle_single_comp_guide(query, target_patch)
        source = "single_comp_guide"
    else:
        answer = handle_general_meta(query, target_patch)
        source = "general_meta"

    return {
        "data": answer,
        "type": meta_subtype,  # ★ app.py 側の要求キー ('item_build' 等の判定に使用)
        "source": source,
        "patch": target_patch,
    }
