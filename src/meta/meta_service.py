"""
メタデータ提供の統合レイヤー。

- パッチ別ディレクトリ(data/patch_xx/)を参照し、data/current_patch.txt
  （またはStreamlitサイドバーでの選択）に応じて参照先を動的に切り替える。
- Riot API集計結果(meta_cache.json)または静的サンプル(meta_snapshot.json)の
  いずれか一方しか存在しない場合でも自動フォールバックして正常動作する。
- 両方存在する場合は、統計（量的データ）と質的知識（静的データ）をマージして提供する。
"""
import json
import re
from collections import Counter
from pathlib import Path

import config
from src.meta import static_provider


def _parse_patch_version(patch_str: str) -> tuple:
    """
    パッチ文字列をタプルに変換して比較する。
    順序: 18.2 < 18.2b < 18.2c < 18.3
    """
    clean = patch_str.strip().lstrip("\ufeff")
    m = re.match(r"^(\d+)\.(\d+)([a-zA-Z]*)$", clean)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2))
        sub = m.group(3).lower()
        return (major, minor, sub)
    
    # 16.18.2b 等の形式に対するフォールバック
    parts = [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", clean)]
    return tuple(parts)


def get_latest_available_patch() -> str:
    """data/ 内の patch_* から最も新しいバージョンを自動選定"""
    patches = list_available_patches()
    if not patches:
        return config.DEFAULT_PATCH
    return max(patches, key=_parse_patch_version)


def get_current_patch_info() -> tuple[str, int | None]:
    """
    current_patch.txt から (パッチ名, 開始時刻エポック秒) を取得。
    未指定・空・ファイル無しの場合は自動で最新パッチへフォールバック。
    """
    p = Path(config.CURRENT_PATCH_FILE)
    if p.exists():
        # BOM (\ufeff) を除去して安全にパース
        text = p.read_text(encoding="utf-8").strip().lstrip("\ufeff")
        if text:
            parts = [x.strip() for x in text.split(",")]
            patch = parts[0]
            start_time = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            return patch, start_time

    # 何も書かれていない場合は存在する最新パッチを採用
    return get_latest_available_patch(), None


def get_current_patch() -> str:
    """パッチ名文字列のみを返す（既存の呼び出しとの完全互換）"""
    patch, _ = get_current_patch_info()
    return patch


def set_current_patch(patch: str) -> None:
    p = Path(config.CURRENT_PATCH_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(patch, encoding="utf-8")


def list_available_patches() -> list[str]:
    data_dir = Path(config.DATA_DIR)
    if not data_dir.exists():
        return []
    return sorted(d.name.replace("patch_", "") for d in data_dir.glob("patch_*") if d.is_dir())


def _patch_dir(patch: str) -> Path:
    return Path(config.DATA_DIR) / f"patch_{patch}"


def load_meta_data(patch: str | None = None) -> dict:
    """静的データ（質的知識）とRiot API集計キャッシュ（量的統計）を柔軟に読み込んで返す。
    どちらか片方しか存在しない場合でもエラーにせずフォールバックする。
    """
    patch = patch or get_current_patch()
    d = _patch_dir(patch)

    snapshot_path = d / "meta_snapshot.json"
    cache_path = d / "meta_cache.json"

    # 1. どちらも存在しない場合はエラー
    if not snapshot_path.exists() and not cache_path.exists():
        raise FileNotFoundError(
            f"パッチ {patch} のデータが見つかりません（{d} に meta_cache.json または meta_snapshot.json が必要です）。"
            " data/current_patch.txt またはサイドバーの選択を確認してください。"
        )

    # 2. snapshot がなく cache のみ存在する場合（新パッチAPI収集直後）
    if not snapshot_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"キャッシュファイル {cache_path} の読み込みに失敗しました: {e}")

    # 3. snapshot の読み込み
    static_data = static_provider.load_snapshot(snapshot_path)

    # 4. cache がなく snapshot のみ存在する場合（静的データのみの環境）
    if not cache_path.exists():
        return static_data

    # 5. 両方存在する場合はマージ
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        return _merge_meta_data(static_data, cache_data)
    except Exception:
        # キャッシュが破損している場合は静的データのみで継続
        return static_data


def _merge_meta_data(static_data: dict, cache_data: dict) -> dict:
    merged = {
        "patch": cache_data.get("patch", static_data.get("patch")),
        "updated_at": cache_data.get("updated_at", static_data.get("updated_at")),
        "source": "riot_api_aggregate+static_supplement",
        "champion_item_builds": {},
        "comp_recommendations": [],
    }

    static_builds = static_data.get("champion_item_builds", {})
    cache_builds = cache_data.get("champion_item_builds", {})
    for champ in set(static_builds) | set(cache_builds):
        cached = cache_builds.get(champ)
        curated = static_builds.get(champ)
        if cached and curated:
            merged_build = dict(cached)
            if not merged_build.get("anti_synergy_warnings"):
                merged_build["anti_synergy_warnings"] = curated.get("anti_synergy_warnings", [])
            if not merged_build.get("debuff_roles"):
                merged_build["debuff_roles"] = curated.get("debuff_roles", [])
            if not merged_build.get("core_items"):
                merged_build["core_items"] = curated.get("core_items", [])
            merged["champion_item_builds"][champ] = merged_build
        else:
            merged["champion_item_builds"][champ] = cached or curated

    static_comps = {c["comp_name"]: c for c in static_data.get("comp_recommendations", [])}
    cache_comps = {c["comp_name"]: c for c in cache_data.get("comp_recommendations", [])}
    for name in set(static_comps) | set(cache_comps):
        cached = cache_comps.get(name)
        curated = static_comps.get(name)
        if cached and curated:
            merged_comp = dict(cached)
            for field in ("emblem_holder", "item_synergy_reason", "trigger_items", "trigger_emblems"):
                if not merged_comp.get(field):
                    merged_comp[field] = curated.get(field)
            merged["comp_recommendations"].append(merged_comp)
        else:
            merged["comp_recommendations"].append(cached or curated)

    return merged


def get_item_build(champion: str, patch: str | None = None) -> dict | None:
    data = load_meta_data(patch)
    return data.get("champion_item_builds", {}).get(champion)


def list_champions_with_build(patch: str | None = None) -> list[str]:
    data = load_meta_data(patch)
    return sorted(data.get("champion_item_builds", {}).keys())


def get_comp_recommendations(patch: str | None = None) -> list[dict]:
    data = load_meta_data(patch)
    return data.get("comp_recommendations", [])


def search_comps_by_assets(
    held_items: list[str], held_emblems: list[str], patch: str | None = None
) -> list[dict]:
    """手持ちのアイテム/紋章から、それらをトリガーとする構成を逆引きする。"""
    comps = get_comp_recommendations(patch)
    held = set(held_items) | set(held_emblems)
    matches = []
    for c in comps:
        triggers = set(c.get("trigger_items") or []) | set(c.get("trigger_emblems") or [])
        if triggers & held:
            matches.append(c)
    tier_order = {"S": 0, "A": 1, "B": 2}
    matches.sort(key=lambda c: (tier_order.get(c.get("tier", "B"), 9), c.get("avg_place", 8.0)))
    return matches


def get_one_example_snippet(patch: str | None = None) -> str:
    """理論回答に添える「現パッチ例」の短い一文を返す。"""
    try:
        comps = get_comp_recommendations(patch)
    except FileNotFoundError:
        return ""
    if not comps:
        return ""
    top = sorted(comps, key=lambda c: c.get("avg_place", 8.0))[0]
    top4_rate_pct = int(top.get("top4_rate", 0) * 100)
    return (
        f"{top.get('comp_name', '注目の構成')}（Tier{top.get('tier', 'A')}、"
        f"平均順位{top.get('avg_place', '-')}、Top4率{top4_rate_pct}%）"
    )


# -------------------------------------------------------------
# 素材アイテム分解・合成シミュレーション用定義
# -------------------------------------------------------------

COMPONENT_ALIASES = {
    "bf": "bf", "bfソード": "bf", "b.f.ソード": "bf", "ソード": "bf",
    "ロッド": "rod", "ムダニデカイロッド": "rod", "ムダニ デカイ ロッド": "rod", "ap": "rod",
    "弓": "bow", "リカーブボウ": "bow", "リカーブ ボウ": "bow", "as": "bow",
    "涙": "tear", "女神の涙": "tear", "マナ": "tear",
    "ベスト": "vest", "チェインベスト": "vest", "チェイン ベスト": "vest", "アーマー": "vest",
    "クローク": "cloak", "ネガトロンクローク": "cloak", "ネガトロン クローク": "cloak", "mr": "cloak",
    "ベルト": "belt", "ジャイアントベルト": "belt", "ジャイアント ベルト": "belt", "hp": "belt",
    "グローブ": "glove", "スパーリンググローブ": "glove", "スパーリング グローブ": "glove", "手袋": "glove",
    "へら": "spatula", "ヘラ": "spatula",
    "フライパン": "pan", "パン": "pan",
}

# 提示された39種の完成品アイテム合成レシピ（素材ペア）
# API名（DA_xxx）と日本語名の両方に対応するレシピ辞書
ITEM_RECIPES_EXACT = {
    # 日本語名
    "アークエンジェル スタッフ": ["rod", "tear"],
    "アイオニック スパーク": ["rod", "cloak"],
    "アダプティブ ヘルム": ["cloak", "tear"],
    "イーブンシュラウド": ["cloak", "belt"],
    "インフィニティ エッジ": ["bf", "glove"],
    "ヴォイド スタッフ": ["bow", "tear"],
    "ガーゴイル ストーンプレート": ["vest", "cloak"],
    "クイックシルバー": ["glove", "cloak"],
    "グインソー レイジブレード": ["bow", "rod"],
    "クラーケンの怒り": ["cloak", "bow"],
    "クラウンガード": ["rod", "vest"],
    "サンファイア ケープ": ["vest", "belt"],
    "ジャイアント スレイヤー": ["bf", "bow"],
    "ジュエル ガントレット": ["rod", "glove"],
    "ショウジンの矛": ["bf", "tear"],
    "ステラックの篭手": ["bf", "belt"],
    "ストライカー フレイル": ["belt", "glove"],
    "スピリット ビサージュ": ["tear", "belt"],
    "タクティシャンのケープ": ["spatula", "pan"],
    "タクティシャンの王冠": ["spatula", "spatula"],
    "タクティシャンの盾": ["pan", "pan"],
    "デスブレード": ["bf", "bf"],
    "ドラゴン クロウ": ["cloak", "cloak"],
    "ナイト エッジ": ["bf", "vest"],
    "ナッシャー トゥース": ["bow", "belt"],
    "ハンド オブ ジャスティス": ["tear", "glove"],
    "ブラッドサースター": ["bf", "cloak"],
    "ブランブル ベスト": ["vest", "vest"],
    "ブルーバフ": ["tear", "tear"],
    "プロテクターの誓い": ["tear", "vest"],
    "ヘクステック ガンブレード": ["bf", "rod"],
    "モレロノミコン": ["rod", "belt"],
    "ラスト ウィスパー": ["bow", "glove"],
    "ラバドン デスキャップ": ["rod", "rod"],
    "レッドバフ": ["bow", "bow"],
    "ワーモグ アーマー": ["belt", "belt"],
    "巨人の誓い": ["vest", "bow"],
    "盗賊のグローブ": ["glove", "glove"],
    "揺るがぬ心": ["vest", "glove"],
    
    # TFTAcademy / APIキー名（プレフィックス除去後の英名正規化）
    "archangelsstaff": ["rod", "tear"],
    "ionicspark": ["rod", "cloak"],
    "adaptivehelm": ["cloak", "tear"],
    "evenshroud": ["cloak", "belt"],
    "infinityedge": ["bf", "glove"],
    "voidstaff": ["bow", "tear"],
    "gargoylestoneplate": ["vest", "cloak"],
    "quicksilver": ["glove", "cloak"],
    "guinsoosrageblade": ["bow", "rod"],
    "krakensfury": ["cloak", "bow"],
    "crownguard": ["rod", "vest"],
    "sunfirecape": ["vest", "belt"],
    "giantslayer": ["bf", "bow"],
    "jeweledgauntlet": ["rod", "glove"],
    "spearofshojin": ["bf", "tear"],
    "steraksgage": ["bf", "belt"],
    "strikersflail": ["belt", "glove"],
    "spiritvisage": ["tear", "belt"],
    "tacticianscape": ["spatula", "pan"],
    "tacticianscrown": ["spatula", "spatula"],
    "tacticiansshield": ["pan", "pan"],
    "deathblade": ["bf", "bf"],
    "dragonsclaw": ["cloak", "cloak"],
    "nightedge": ["bf", "vest"],
    "nashorstooth": ["bow", "belt"],
    "handofjustice": ["tear", "glove"],
    "bloodthirster": ["bf", "cloak"],
    "bramblevest": ["vest", "vest"],
    "bluebuff": ["tear", "tear"],
    "protectorsvow": ["tear", "vest"],
    "hextechgunblade": ["bf", "rod"],
    "morellonomicon": ["rod", "belt"],
    "lastwhisper": ["bow", "glove"],
    "rabadonsdeathcap": ["rod", "rod"],
    "redbuff": ["bow", "bow"],
    "warmogsarmor": ["belt", "belt"],
    "titansresolve": ["vest", "bow"],
    "thiefsgloves": ["glove", "glove"],
    "unflinchingheart": ["vest", "glove"],
}

# 英キー（正規化後）から正式日本語名への変換マッピング
ITEM_EN_TO_JA = {
    "archangelsstaff": "アークエンジェル スタッフ",
    "ionicspark": "アイオニック スパーク",
    "adaptivehelm": "アダプティブ ヘルム",
    "evenshroud": "イーブンシュラウド",
    "infinityedge": "インフィニティ エッジ",
    "voidstaff": "ヴォイド スタッフ",
    "gargoylestoneplate": "ガーゴイル ストーンプレート",
    "quicksilver": "クイックシルバー",
    "guinsoosrageblade": "グインソー レイジブレード",
    "krakensfury": "クラーケンの怒り",
    "crownguard": "クラウンガード",
    "sunfirecape": "サンファイア ケープ",
    "giantslayer": "ジャイアント スレイヤー",
    "jeweledgauntlet": "ジュエル ガントレット",
    "spearofshojin": "ショウジンの矛",
    "steraksgage": "ステラックの篭手",
    "strikersflail": "ストライカー フレイル",
    "spiritvisage": "スピリット ビサージュ",
    "tacticianscape": "タクティシャンのケープ",
    "tacticianscrown": "タクティシャンの王冠",
    "tacticiansshield": "タクティシャンの盾",
    "deathblade": "デスブレード",
    "dragonsclaw": "ドラゴン クロウ",
    "nightedge": "ナイト エッジ",
    "nashorstooth": "ナッシャー トゥース",
    "handofjustice": "ハンド オブ ジャスティス",
    "bloodthirster": "ブラッドサースター",
    "bramblevest": "ブランブル ベスト",
    "bluebuff": "ブルーバフ",
    "protectorsvow": "プロテクターの誓い",
    "hextechgunblade": "ヘクステック ガンブレード",
    "morellonomicon": "モレロノミコン",
    "lastwhisper": "ラスト ウィスパー",
    "rabadonsdeathcap": "ラバドン デスキャップ",
    "redbuff": "レッドバフ",
    "warmogsarmor": "ワーモグ アーマー",
    "titansresolve": "巨人の誓い",
    "thiefsgloves": "盗賊のグローブ",
    "unflinchingheart": "揺るがぬ心",
}

# 素材トークンの日本語変換辞書
COMPONENT_TO_JA = {
    "bf": "BFソード", "rod": "ロッド", "bow": "リカーブボウ",
    "tear": "女神の涙", "vest": "ベスト", "cloak": "クローク",
    "belt": "ベルト", "glove": "グローブ", "spatula": "ヘラ", "pan": "フライパン"
}

def to_japanese_item_name(raw_name: str) -> str:
    """DA_xxx、キャメルケース英名、日本語名を問わず正式日本語名に正規化"""
    if not raw_name:
        return ""
    # 既に日本語名ならそのまま返す
    if raw_name in ITEM_EN_TO_JA.values():
        return raw_name
    cleaned = _clean_item_key(raw_name)
    return ITEM_EN_TO_JA.get(cleaned, raw_name)

def get_item_recipe_ja(name_or_api: str) -> list[str]:
    """素材名も日本語（BFソード、女神の涙など）にしてレシピを返す"""
    tokens = _get_item_recipe(name_or_api)
    return [COMPONENT_TO_JA.get(t, t) for t in tokens]

def _clean_item_key(raw_name: str) -> str:
    """DA_ プレフィックスなどを除去して辞書キー用に小文字化"""
    cleaned = raw_name.replace("DA_", "").replace("TFT_Item_", "").replace(" ", "").lower()
    return cleaned


def _get_item_recipe(name_or_api: str) -> list[str]:
    """日本語名でもDA_付きAPI名でもレシピ素材ペアを返す"""
    if name_or_api in ITEM_RECIPES_EXACT:
        return ITEM_RECIPES_EXACT[name_or_api]
    cleaned = _clean_item_key(name_or_api)
    return ITEM_RECIPES_EXACT.get(cleaned, [])


def normalize_item_token(token: str) -> str | None:
    cleaned = token.lower().replace(" ", "").replace(".", "")
    for k, v in COMPONENT_ALIASES.items():
        if k.replace(" ", "").replace(".", "") in cleaned:
            return v
    return None


def match_comps_by_component_inventory(
    items: list[str],
    emblems: list[str],
    guides: list[dict],
    target_patch: str,
    trans_map: dict,
) -> list[dict]:
    """手持ち素材と紋章から、BiS・代用アイテムの作成シミュレーションを行い最適な構成をスコアリング"""
    from src.meta.tft_translator import translate_term

    matched = []
    inventory_tokens = [
        normalize_item_token(it)
        for it in items
        if normalize_item_token(it) is not None
    ]
    emblems_lower = [em.lower() for em in emblems]

    for comp in guides:
        # 1. 非公開（メタ落ち・アーカイブ）を完全除外（旧 AP Fast 9 等を弾く）
        if not comp.get("isPublic"):
            continue

        tier = (comp.get("tier") or "").upper()
        # 2. 有効Tier（S, A, B, C, X）のみ対象
        if tier not in ["S", "A", "B", "C", "X"]:
            continue

        score = 0
        reasons = []
        user_inv = Counter(inventory_tokens)

        # 3. 紋章判定
        comp_title = (comp.get("metaTitle") or comp.get("title", "")).lower()
        aug_tip = (comp.get("augmentsTip") or "").lower()
        has_emblem_match = False
        for emblem in emblems_lower:
            clean_em = emblem.replace("の紋章", "").replace("紋章", "").strip()
            if clean_em in comp_title or clean_em in aug_tip:
                score += 30
                reasons.append(f"【紋章合致】{emblem}")
                has_emblem_match = True

        # Tier X（特殊条件枠）は紋章合致がある場合のみ有効化
        if tier == "X" and not has_emblem_match:
            continue

        # 基礎点（S > A > B > C）
        tier_base_points = {"S": 10, "A": 6, "B": 3, "C": 0, "X": 12}
        score += tier_base_points.get(tier, 0)

        # 4. キャリー・タンクの特定
        main_champ_raw = comp.get("mainChampion", {}).get("apiName", "")
        main_carry = translate_term(main_champ_raw, trans_map)
        main_tank = "メインタンク"
        for unit in comp.get("finalComp", []):
            u_raw = unit.get("apiName", "")
            if u_raw != main_champ_raw and unit.get("items"):
                main_tank = translate_term(u_raw, trans_map)
                break

        # 5. ItemBuildAdvice スキーマから BiS と代用リストを取得
        def _get_target_pool(unit_name: str, comp_ref: dict):
            bis_items, alt_items = [], []
            for u in comp_ref.get("finalComp", []):
                if translate_term(u.get("apiName", ""), trans_map) == unit_name:
                    bis_items = [
                        to_japanese_item_name(it)
                        for it in u.get("items", [])
                    ]

            build_data = get_item_build(unit_name, target_patch)
            if build_data:
                bis_std = build_data.get("bis_standard_build", {}).get("items", [])
                for b in bis_std:
                    t_name = to_japanese_item_name(b)
                    if t_name not in bis_items:
                        bis_items.append(t_name)
                for sub in build_data.get("substitutes", []):
                    sub_name = to_japanese_item_name(sub.get("item", ""))
                    if sub_name not in bis_items and sub_name not in alt_items:
                        alt_items.append(sub_name)
            return bis_items, alt_items

        carry_bis, carry_alts = _get_target_pool(main_carry, comp)
        tank_bis, tank_alts = (
            _get_target_pool(main_tank, comp)
            if main_tank != "メインタンク"
            else ([], [])
        )

        planned_carry, planned_tank = [], []

        # 6. 手持ち素材からアイテム作成シミュレーション
        def _try_craft(target_list: list[str], is_bis: bool, is_carry: bool):
            nonlocal score
            for it in target_list:
                recipe = _get_item_recipe(it)
                if len(recipe) != 2:
                    continue
                r1, r2 = recipe[0], recipe[1]
                can_craft = False
                if r1 == r2 and user_inv[r1] >= 2:
                    user_inv[r1] -= 2
                    can_craft = True
                elif r1 != r2 and user_inv[r1] >= 1 and user_inv[r2] >= 1:
                    user_inv[r1] -= 1
                    user_inv[r2] -= 1
                    can_craft = True

                if can_craft:
                    score += (15 if is_bis else 8) if is_carry else (10 if is_bis else 5)
                    it_display = to_japanese_item_name(it)
                    label = f"{it_display} (BiS)" if is_bis else f"{it_display} (代用)"
                    (planned_carry if is_carry else planned_tank).append(label)

        _try_craft(carry_bis, is_bis=True, is_carry=True)
        _try_craft(tank_bis, is_bis=True, is_carry=False)
        _try_craft(carry_alts, is_bis=False, is_carry=True)
        _try_craft(tank_alts, is_bis=False, is_carry=False)

        plan_summary = []
        if planned_carry:
            plan_summary.append(f"{main_carry}: {' + '.join(planned_carry)}")
        if planned_tank:
            plan_summary.append(f"{main_tank}: {' + '.join(planned_tank)}")

        if score > 0 and plan_summary:
            reasons.append(f"作成計画: {' / '.join(plan_summary)}")
            matched.append({
                "comp": comp,
                "score": score,
                "reasons": reasons,
                "main_carry": main_carry,
                "main_tank": main_tank,
            })

    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched[:3]