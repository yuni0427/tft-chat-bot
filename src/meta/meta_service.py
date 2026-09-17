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


# ---------------------------------------------------------------------------
# チャンピオン識別子の正規化・照合ユーティリティ
# ---------------------------------------------------------------------------

# プレフィックス除去パターン（優先順: 長いものから）
_CHAMP_PREFIX_RE = re.compile(
    r"^(?:DA_18_|TFT18_|Set18_|DA_18|DA_)",
    flags=re.IGNORECASE,
)
# 語尾の "18" などセット番号を除去するパターン
_CHAMP_SUFFIX_RE = re.compile(r"18$", flags=re.IGNORECASE)

# 表記ゆれを吸収する正規化（全角＝→除去、スペース除去、小文字化）
def _normalize_str(s: str) -> str:
    return s.lower().replace(" ", "").replace("＝", "").replace("=", "").replace("'", "").replace("'", "")


def _build_champion_id_map(patch: str | None = None) -> dict[str, str]:
    """champions.json を読み込み、各種キーから正規化済み日本語名へのマッピングを返す。

    登録されるキー（すべて _normalize_str 済み）:
      - 日本語名そのまま  (例: "コグ＝マウ" → "こぐまう")
      - api_name フル     (例: "da_18_kogmaw" → "こぐまう")
      - api_name のプレフィックス・サフィックス除去後  (例: "kogmaw" → "こぐまう")

    patch が None の場合は最新パッチを使用する。
    ファイルが存在しない場合は空辞書を返す（フォールバック可能）。
    """
    patch = patch or get_current_patch()
    champ_file = _patch_dir(patch) / "champions.json"
    if not champ_file.exists():
        # 最新パッチで再試行
        latest = get_latest_available_patch()
        champ_file = _patch_dir(latest) / "champions.json"
    if not champ_file.exists():
        return {}

    try:
        champs: dict = json.loads(champ_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    id_map: dict[str, str] = {}
    for name_ja, data in champs.items():
        norm_ja = _normalize_str(name_ja)
        # 日本語名 → 日本語名
        id_map[norm_ja] = norm_ja

        api_name: str = data.get("api_name", "") or data.get("apiName", "")
        if not api_name:
            continue

        # api_name フル（小文字）→ 日本語名
        id_map[_normalize_str(api_name)] = norm_ja

        # プレフィックス・サフィックス除去後 → 日本語名
        short = _CHAMP_PREFIX_RE.sub("", api_name)
        short = _CHAMP_SUFFIX_RE.sub("", short)
        id_map[_normalize_str(short)] = norm_ja

    return id_map


def _unit_raw_to_token(raw: str, id_map: dict[str, str]) -> str | None:
    """生の識別子文字列（日本語名・英語ID・apiName 問わず）を正規化済みトークンに変換する。

    変換優先順:
      1. id_map に完全一致（正規化後）
      2. プレフィックス/サフィックスを除去してから id_map を参照
      3. どちらも失敗した場合は正規化済み文字列をそのまま返す
         （日本語名はこのケースに該当し、照合時に役立つ）
    """
    if not raw:
        return None

    norm = _normalize_str(raw)

    # 1. 正規化後に完全一致
    if norm in id_map:
        return id_map[norm]

    # 2. プレフィックス・サフィックスを除去して再試行
    short = _CHAMP_PREFIX_RE.sub("", raw)
    short = _CHAMP_SUFFIX_RE.sub("", short)
    norm_short = _normalize_str(short)
    if norm_short in id_map:
        return id_map[norm_short]

    # 3. id_map の全 api_name に対して部分スキャン（DA_Gromp18_AP のような複合形式に対応）
    for key, token in id_map.items():
        if norm_short and norm_short in key:
            return token

    # 4. フォールバック: 正規化文字列をそのまま使う（日本語名はここに落ちる）
    return norm if norm else None


def _extract_unit_tokens(comp: dict, id_map: dict[str, str]) -> set[str]:
    """構成データから正規化済みユニットトークン集合を抽出する。

    対応する入力形式:
      - TFTAcademy 形式: finalComp: [{'apiName': 'DA_18_Ahri', ...}, ...]
      - Riot 統計形式:   key_units: ['コグ＝マウ', 'Sentinel18', ...]
    """
    tokens: set[str] = set()

    # TFTAcademy 形式（finalComp）
    for u in comp.get("finalComp", []):
        raw = u.get("apiName", "") if isinstance(u, dict) else str(u)
        tok = _unit_raw_to_token(raw, id_map)
        if tok:
            tokens.add(tok)

    # Riot 統計形式（key_units）
    for u in comp.get("key_units", []):
        raw = str(u.get("character_id", "") or u.get("name", "")) if isinstance(u, dict) else str(u)
        tok = _unit_raw_to_token(raw, id_map)
        if tok:
            tokens.add(tok)

    return tokens


def _match_score(tokens_a: set[str], tokens_b: set[str]) -> tuple[int, float]:
    """2つのトークン集合の一致スコアを返す。

    Returns:
        (共通ユニット数, Jaccard 係数)
    """
    if not tokens_a or not tokens_b:
        return 0, 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    jaccard = intersection / union if union > 0 else 0.0
    return intersection, jaccard


# ---------------------------------------------------------------------------
# マージ処理
# ---------------------------------------------------------------------------

def _merge_meta_data(static_data: dict, cache_data: dict) -> dict:
    """Riot 実戦統計（cache）と TFTAcademy ガイド（static）を駒照合でマージする。

    マージ方針:
      - cache_comps の各構成について、key_units から抽出したトークン集合と
        static_comps の finalComp トークン集合を比較し、
        共通ユニット数 >= MIN_OVERLAP かつ Jaccard >= MIN_JACCARD を満たす
        最良マッチを特定する。
      - マッチ成功時は TFTAcademy のリッチ情報（metaTitle, style, finalComp 等）を注入。
      - static にしか存在しない構成は末尾に追加（理論値構成の欠落を防ぐ）。
    """
    MIN_OVERLAP = 3    # 共通ユニット数の最低ライン
    MIN_JACCARD = 0.20  # Jaccard 係数の最低ライン（20% 以上の一致率）

    merged: dict = {
        "patch": cache_data.get("patch", static_data.get("patch")),
        "updated_at": cache_data.get("updated_at", static_data.get("updated_at")),
        "source": "riot_api_aggregate+static_supplement",
        "champion_item_builds": {},
        "comp_recommendations": [],
    }

    # --- チャンピオンビルドのマージ（既存ロジック維持）---
    static_builds = static_data.get("champion_item_builds", {})
    cache_builds = cache_data.get("champion_item_builds", {})
    for champ in set(static_builds) | set(cache_builds):
        cached = cache_builds.get(champ)
        curated = static_builds.get(champ)
        if cached and curated:
            merged_build = dict(cached)
            for f in ("anti_synergy_warnings", "debuff_roles", "core_items"):
                if not merged_build.get(f):
                    merged_build[f] = curated.get(f, [])
            merged["champion_item_builds"][champ] = merged_build
        else:
            merged["champion_item_builds"][champ] = cached or curated

    # --- 構成データの駒照合マージ ---
    patch = cache_data.get("patch") or static_data.get("patch")
    id_map = _build_champion_id_map(patch)

    static_comps: list[dict] = static_data.get("comp_recommendations", [])
    cache_comps: list[dict] = cache_data.get("comp_recommendations", [])

    # static_comps 側のトークン集合を事前計算（ O(N*M) の内ループを軽減）
    static_tokens: list[set[str]] = [
        _extract_unit_tokens(c, id_map) for c in static_comps
    ]

    used_static_indices: set[int] = set()

    for cached in cache_comps:
        cached_comp = dict(cached)
        cached_tokens = _extract_unit_tokens(cached_comp, id_map)

        best_idx = -1
        best_overlap = 0
        best_jaccard = 0.0

        for idx, s_tokens in enumerate(static_tokens):
            overlap, jaccard = _match_score(cached_tokens, s_tokens)
            # 共通ユニット数が同数の場合は Jaccard が高い方を優先
            if overlap >= MIN_OVERLAP and jaccard >= MIN_JACCARD:
                if overlap > best_overlap or (overlap == best_overlap and jaccard > best_jaccard):
                    best_overlap = overlap
                    best_jaccard = jaccard
                    best_idx = idx

        if best_idx >= 0:
            best_match = static_comps[best_idx]
            used_static_indices.add(best_idx)
            # TFTAcademy のリッチメタ情報を実戦統計オブジェクトに注入
            cached_comp["metaTitle"]    = best_match.get("metaTitle") or best_match.get("title")
            cached_comp["style"]        = best_match.get("style", "Standard")
            cached_comp["compSlug"]     = best_match.get("compSlug")
            cached_comp["augmentsTip"]  = best_match.get("augmentsTip")
            cached_comp["mainChampion"] = best_match.get("mainChampion")
            cached_comp["finalComp"]    = best_match.get("finalComp")
            cached_comp["_match_overlap"]  = best_overlap   # デバッグ用（本番でも無害）
            cached_comp["_match_jaccard"]  = round(best_jaccard, 3)

        merged["comp_recommendations"].append(cached_comp)

    # TFTAcademy 側にしかない構成（統計未集計の理論値構成）を末尾に追加
    for idx, curated in enumerate(static_comps):
        if idx not in used_static_indices:
            merged["comp_recommendations"].append(curated)

    return merged


def get_item_build(champion: str, patch: str | None = None) -> dict | None:
    """チャンピオン名でアイテムビルド統計を返す。

    champion は日本語名・英語内部ID どちらでも受け付ける。
    英語IDが渡された場合は _unit_raw_to_token で日本語名に正規化してから検索する。
    （meta_cache の champion_item_builds キーは日本語名だが、
    一部英語キーのまま格納されているケースにも対応する）
    """
    data = load_meta_data(patch)
    builds: dict = data.get("champion_item_builds", {})

    # 1. 直接一致
    if champion in builds:
        return builds[champion]

    # 2. 英語IDが渡された場合: 日本語名に正規化して再検索
    id_map = _build_champion_id_map(patch)
    ja_name = _unit_raw_to_token(champion, id_map)
    if ja_name and ja_name != champion and ja_name in builds:
        return builds[ja_name]

    # 3. 逆方向: builds に英語キーが残っている場合に日本語名で引けるようにする
    #    （ElderDragon, Sentinel18 等が英語キーのまま格納されているケース）
    norm_champ = _normalize_str(champion)
    for key in builds:
        norm_key = _normalize_str(key)
        # 正規化後一致
        if norm_key == norm_champ:
            return builds[key]
        # 英語キーを日本語に変換して一致確認
        key_ja = _unit_raw_to_token(key, id_map)
        if key_ja and _normalize_str(key_ja) == norm_champ:
            return builds[key]

    return None


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
    # 剣 / BF
    "剣": "bf",
    "けん": "bf",
    "ソード": "bf",
    "bf": "bf",
    "bfソード": "bf",
    "sword": "bf",
    # 棒 / ロッド
    "杖": "rod",
    "棒": "rod",
    "ロッド": "rod",
    "ap棒": "rod",
    "無駄にでかいロッド": "rod",
    "無駄に大きいロッド": "rod",
    # 弓
    "弓": "bow",
    "ゆみ": "bow",
    "ボウ": "bow",
    "リカーブボウ": "bow",
    "リカーブ": "bow",
    # 涙
    "涙": "tear",
    "なみだ": "tear",
    "ティアー": "tear",
    "女神の涙": "tear",
    # 鎖 / ベスト
    "鎖": "vest",
    "鎧": "vest",
    "ベスト": "vest",
    "アーマー": "vest",
    "チェインベスト": "vest",
    # マント / クローク
    "マント": "cloak",
    "クローク": "cloak",
    "貝": "cloak",
    "ネガトロンクローク": "cloak",
    # ベルト
    "ベルト": "belt",
    "ジャイアントベルト": "belt",
    # 手袋 / グローブ
    "手袋": "glove",
    "グローブ": "glove",
    "グローヴ": "glove",
    "クリティカル手袋": "glove",
    "スパーリンググローブ": "glove",
    # ヘラ・フライパン
    "ヘラ": "spatula",
    "へら": "spatula",
    "スパーチュラ": "spatula",
    "フライパン": "pan",
    "パン": "pan",
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
    """手持ち素材と紋章から最適な構成をスコアリングして返す。

    完成品が作れない素材1〜2個の場合でも、メインキャリーの BiS レシピ素材と
    合致していれば救済スコア（+6点）を加算して候補に残す。

    スコアリング優先度:
        紋章合致（+30）> キャリー素材合致（+6/素材）> クラフト完成品（+15 BiS等）> Tier基礎点
    """
    from src.meta.tft_translator import translate_term_for_patch

    matched: list[dict] = []
    inventory_tokens: list[str] = [
        normalize_item_token(it)
        for it in items
        if normalize_item_token(it) is not None
    ]
    emblems_lower = [em.lower() for em in emblems]

    for comp in guides:
        # [A] 非公開・無効 Tier の早期除外
        if not comp.get("isPublic"):
            continue
        tier = (comp.get("tier") or "").upper()
        if tier not in ["S", "A", "B", "C", "X"]:
            continue

        # [B] main_carry / main_tank の確定
        #     以降すべての処理でこれらを参照するため、最初に確定させる
        main_champ_raw: str = (comp.get("mainChampion") or {}).get("apiName", "")
        main_carry: str = translate_term_for_patch(main_champ_raw, target_patch)

        main_tank: str | None = None
        for unit in comp.get("finalComp", []):
            u_raw = unit.get("apiName", "")
            if u_raw != main_champ_raw and unit.get("items"):
                main_tank = translate_term_for_patch(u_raw, target_patch)
                break

        # [C] スコア・状態変数の初期化
        #     _try_craft 内の nonlocal score はここで score = 0 が済んでいるため有効
        score: int = 0
        reasons: list[str] = []
        user_inv: Counter = Counter(inventory_tokens)

        # [D] 内部ヘルパー: BIS/代用アイテムプール取得
        #     main_carry / main_tank が確定済みなのでここに配置できる
        def _get_target_pool(unit_name: str, comp_ref: dict) -> tuple[list[str], list[str]]:
            bis_items: list[str] = []
            alt_items: list[str] = []
            for u in comp_ref.get("finalComp", []):
                raw = u.get("apiName", "")
                if translate_term_for_patch(raw, target_patch) == unit_name:
                    bis_items = [
                        to_japanese_item_name(it)
                        for it in u.get("items", [])
                        if it
                    ]
            build_data = get_item_build(unit_name, target_patch)
            if build_data:
                for b in (build_data.get("bis_standard_build") or {}).get("items", []):
                    t = to_japanese_item_name(b)
                    if t and t not in bis_items:
                        bis_items.append(t)
                for sub in build_data.get("substitutes") or []:
                    s = to_japanese_item_name(sub.get("item", ""))
                    if s and s not in bis_items and s not in alt_items:
                        alt_items.append(s)
            return bis_items, alt_items

        # [E] アイテムプールの取得
        carry_bis, carry_alts = _get_target_pool(main_carry, comp)
        tank_bis, tank_alts = (
            _get_target_pool(main_tank, comp) if main_tank else ([], [])
        )

        # [F] 内部ヘルパー: クラフトシミュレーション
        #     nonlocal score → [C] で score = 0 済みのため SyntaxError は起きない
        planned_carry: list[str] = []
        planned_tank: list[str] = []

        def _try_craft(target_list: list[str], is_bis: bool, is_carry: bool) -> None:
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
                    label = f"{to_japanese_item_name(it)} ({'BiS' if is_bis else '代用'})"
                    (planned_carry if is_carry else planned_tank).append(label)

        # [G] クラフトシミュレーション実行
        _try_craft(carry_bis,  is_bis=True,  is_carry=True)
        _try_craft(tank_bis,   is_bis=True,  is_carry=False)
        _try_craft(carry_alts, is_bis=False, is_carry=True)
        _try_craft(tank_alts,  is_bis=False, is_carry=False)

        # [H] キャリー素材適合スコア（クラフト不可時の救済）
        #     carry_bis + carry_alts のレシピ素材に手持ち素材が含まれていれば +6点
        #     同一完成品アイテムへの重複加点は1回のみ
        has_component_match = False
        seen_item_reasons: set[str] = set()
        for inv_tok in inventory_tokens:
            for target_it in (carry_bis + carry_alts):
                if target_it in seen_item_reasons:
                    continue
                recipe_toks = _get_item_recipe(target_it)  # ["bf", "tear"] 等のトークンリスト
                if inv_tok in recipe_toks:
                    score += 6
                    has_component_match = True
                    seen_item_reasons.add(target_it)
                    reasons.append(f"【キャリー素材活用】{inv_tok} -> {target_it}")
                    break  # 同一素材トークンで複数アイテムへの重複加点を防ぐ

        # [I] 紋章判定
        comp_title = (comp.get("metaTitle") or comp.get("title", "")).lower()
        aug_tip    = (comp.get("augmentsTip") or "").lower()
        has_emblem_match = False
        for emblem in emblems_lower:
            clean_em = emblem.replace("の紋章", "").replace("紋章", "").strip()
            if clean_em and (clean_em in comp_title or clean_em in aug_tip):
                score += 30
                reasons.append(f"【紋章合致】{emblem}")
                has_emblem_match = True

        # Tier X は紋章合致がある場合のみ有効
        if tier == "X" and not has_emblem_match:
            continue

        # [J] Tier 基礎点
        tier_base = {"S": 10, "A": 6, "B": 3, "C": 0, "X": 12}
        score += tier_base.get(tier, 0)

        # [K] plan_summary の構築と候補追加
        plan_summary: list[str] = []
        if planned_carry:
            plan_summary.append(f"{main_carry}: {' + '.join(planned_carry)}")
        if planned_tank and main_tank:
            plan_summary.append(f"{main_tank}: {' + '.join(planned_tank)}")
        if plan_summary:
            reasons.insert(0, f"作成計画: {' / '.join(plan_summary)}")

        # クラフト完成品あり、キャリー素材合致あり、または紋章合致ありのいずれかで採用
        if score > 0 and (plan_summary or has_component_match or has_emblem_match):
            matched.append({
                "comp": comp,
                "score": score,
                "reasons": reasons,
                "main_carry": main_carry,
                "main_tank": main_tank or "メインタンク",
            })

    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched[:3]