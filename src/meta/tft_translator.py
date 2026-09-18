"""
チャンピオン識別子・特性名・汎用 TFT 用語の日本語変換モジュール。

変換優先順:
  1. data/patch_xx/champions.json から動的に構築した api_name -> 日本語名マップ
     （tft_lexicon_ja.json が存在しなくても確実に動作する）
  2. data/tft_lexicon_ja.json が存在する場合は補完辞書として使用
  3. 上記いずれにもヒットしない場合はプレフィックス/サフィックス除去した文字列を返す

変更履歴:
  - tft_lexicon_ja.json 非依存化。champions.json を一次ソースに変更。
  - プレフィックス除去パターンを meta_service._CHAMP_PREFIX_RE と統一。
"""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# ---- プレフィックス/サフィックス正規化 ------------------------------------
_PREFIX_RE = re.compile(
    r"^(?:DA_18_|TFT18_|Set18_|DA_18|DA_)",
    flags=re.IGNORECASE,
)
_SUFFIX_RE = re.compile(r"18$", flags=re.IGNORECASE)

# ---- 汎用プレイスタイル用語の即時マッピング --------------------------------
_COMMON_TERMS: dict[str, str] = {
    "fast 8": "ファスト8",
    "fast 9": "ファスト9",
    "slow 8": "スロー8",
    "reroll": "リロール",
    "flex": "フレックス",
    "standard": "スタンダード",
    "elder dragon": "エルダードラゴン",
    "dragon": "ドラゴン",
    "4-cost": "4コスト",
    "5-cost": "5コスト",
    "3-cost": "3コスト",
    "2-cost": "2コスト",
    "1-cost": "1コスト",
    "master yi": "マスター・イー",
    "kha'zix": "カ＝ジックス",
    "khazix": "カ＝ジックス",
    "kog'maw": "コグ＝マウ",
    "flora fatalis": "フローラ・ファターリス",
    "sprykin": "スプライキン",
    "pebbles": "ペブルズ",
    "trait ladder": "特性ラダー",
    "unrivaled": "無双",
}


def _strip_prefix_suffix(raw: str) -> str:
    """DA_18_ / DA_ / 18 末尾 などを除去して英字コア部分だけにする。"""
    s = _PREFIX_RE.sub("", raw)
    s = _SUFFIX_RE.sub("", s)
    # _AP / _AD などのロールサフィックスも除去（Nidalee18_AP -> Nidalee）
    s = re.sub(r"_[A-Z]{1,3}$", "", s)
    return s


# ---- champions.json ベースの変換テーブル ----------------------------------

def _find_latest_champions_path() -> Path | None:
    """data/ から最新パッチの champions.json を探す。"""
    data_dir = Path("data")
    if not data_dir.exists():
        return None
    dirs = sorted(data_dir.glob("patch_*"), reverse=True)
    for d in dirs:
        p = d / "champions.json"
        if p.exists():
            return p
    return None


@lru_cache(maxsize=1)
def _build_champ_map() -> dict[str, str]:
    """champions.json から複数キー形式で引ける api_name -> 日本語名マップを構築。

    登録されるキー（すべて小文字）:
      - api_name フル       例: "da_18_ahri"       -> "アーリ"
      - プレフィックス除去後 例: "ahri"             -> "アーリ"
      - ロールサフィックス除去後 例: "nidalee"      -> "ニダリー"
      - 日本語名そのまま    例: "アーリ"            -> "アーリ"
    """
    champ_file = _find_latest_champions_path()
    if not champ_file:
        logger.warning("champions.json が見つかりません。translate_term はフォールバック動作します。")
        return {}

    try:
        data: dict = json.loads(champ_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("champions.json の読み込みに失敗: %s", exc)
        return {}

    mapping: dict[str, str] = {}
    for ja_name, entry in data.items():
        api: str = entry.get("api_name", "") or entry.get("apiName", "")
        if not api:
            continue

        # 日本語名 -> 日本語名（すでに日本語で渡された場合に対応）
        mapping[ja_name] = ja_name
        mapping[ja_name.lower()] = ja_name

        # api_name フル（小文字）
        mapping[api.lower()] = ja_name

        # プレフィックス除去後
        short = _strip_prefix_suffix(api)
        if short:
            mapping[short.lower()] = ja_name

        # さらに末尾の数字も除去（Amumu18 -> Amumu 等）
        short_no_num = re.sub(r"\d+$", "", short)
        if short_no_num and short_no_num != short:
            mapping[short_no_num.lower()] = ja_name

    return mapping


def _build_champ_map_for_patch(patch: str) -> dict[str, str]:
    """特定パッチの champions.json からマップを構築する（キャッシュなし版）。

    meta_service._build_champion_id_map との重複を避けるため、
    通常は _build_champ_map()（最新パッチ自動選択）を使う。
    """
    champ_file = Path("data") / f"patch_{patch}" / "champions.json"
    if not champ_file.exists():
        return _build_champ_map()

    try:
        data: dict = json.loads(champ_file.read_text(encoding="utf-8"))
    except Exception:
        return _build_champ_map()

    mapping: dict[str, str] = {}
    for ja_name, entry in data.items():
        api: str = entry.get("api_name", "") or entry.get("apiName", "")
        if not api:
            continue
        mapping[ja_name] = ja_name
        mapping[ja_name.lower()] = ja_name
        mapping[api.lower()] = ja_name
        short = _strip_prefix_suffix(api)
        if short:
            mapping[short.lower()] = ja_name
        short_no_num = re.sub(r"\d+$", "", short)
        if short_no_num and short_no_num != short:
            mapping[short_no_num.lower()] = ja_name
    return mapping


@lru_cache(maxsize=1)
def _build_trait_map() -> dict[str, str]:
    """最新パッチのtraits.jsonから英語api_nameを日本語特性名へ変換する。"""
    data_dir = Path("data")
    trait_files = sorted(data_dir.glob("patch_*/traits.json"), reverse=True)
    if not trait_files:
        return {}

    try:
        traits: dict = json.loads(trait_files[0].read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("traits.jsonの読み込みに失敗: %s", exc)
        return {}

    mapping: dict[str, str] = {}
    for name_ja, entry in traits.items():
        api_name = entry.get("api_name", "") or entry.get("apiName", "")
        if not api_name:
            continue
        mapping[name_ja.lower()] = name_ja
        mapping[api_name.lower()] = name_ja
        short = _strip_prefix_suffix(api_name)
        if short:
            mapping[short.lower()] = name_ja
    return mapping


# ---- 補完辞書（tft_lexicon_ja.json / フォールバック用） -------------------

@lru_cache(maxsize=1)
def load_tft_translations() -> dict[str, str]:
    """data/tft_lexicon_ja.json を読み込む。

    ファイルが存在しない場合は空辞書を返す（champions.json ベースでカバーされるため実害なし）。
    Streamlit の @st.cache_data デコレータは削除し、lru_cache に統一した。
    """
    lexicon_path = Path("data/tft_lexicon_ja.json")
    if not lexicon_path.exists():
        return {}
    try:
        with open(lexicon_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("tft_lexicon_ja.json の読み込みに失敗: %s", exc)
        return {}


# ---- メイン変換関数 -------------------------------------------------------

def translate_term(term: str, translation_map: dict[str, str] | None = None) -> str:
    """apiName や英語名を日本語名に変換する。

    変換優先順:
      1. champions.json ベースのマップ（最も信頼性が高い）
      2. translation_map（tft_lexicon_ja.json 等の補完辞書）
      3. プレフィックス/サフィックス除去した文字列（フォールバック）
    """
    if not term or term == "-":
        return term

    champ_map = _build_champ_map()

    # 1. champions.json マップで完全一致（正規化前）
    if term in champ_map:
        return champ_map[term]

    # 2. 小文字で完全一致
    key = term.lower()
    if key in champ_map:
        return champ_map[key]

    # 3. プレフィックス/サフィックス除去後で照合
    short = _strip_prefix_suffix(term)
    short_key = short.lower()
    if short_key in champ_map:
        return champ_map[short_key]

    # 4. 数字サフィックスも除去して再照合
    short_no_num = re.sub(r"\d+$", "", short)
    if short_no_num and short_no_num.lower() in champ_map:
        return champ_map[short_no_num.lower()]

    # 5. 補完辞書（tft_lexicon_ja.json）で照合
    if translation_map is None:
        translation_map = load_tft_translations()
    if translation_map:
        if key in translation_map:
            return translation_map[key]
        if short_key in translation_map:
            return translation_map[short_key]

    # 6. フォールバック: プレフィックス除去した英語文字列を返す
    return short if short else term


def translate_term_for_patch(term: str, patch: str) -> str:
    """特定パッチの champions.json を使って変換する。

    handle_single_comp_guide など、パッチを明示したい箇所で使用する。
    """
    if not term or term == "-":
        return term

    champ_map = _build_champ_map_for_patch(patch)

    for key in [term, term.lower(), _strip_prefix_suffix(term).lower()]:
        if key in champ_map:
            return champ_map[key]

    short = _strip_prefix_suffix(term)
    short_no_num = re.sub(r"\d+$", "", short)
    if short_no_num.lower() in champ_map:
        return champ_map[short_no_num.lower()]

    # 汎用マップにフォールバック
    return translate_term(term)


def preprocess_tft_text(text: str, translation_map: dict[str, str] | None = None) -> str:
    """複合英文から駒・特性・スタイル用語を日本語に置換する。"""
    if not text:
        return ""

    result = text

    # 1. traits.jsonの特性名を先に置換（Juggernaut / Summoner等）
    for en, ja in sorted(_build_trait_map().items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"(?<![A-Za-z]){re.escape(en)}(?![A-Za-z])", ja, result, flags=re.IGNORECASE)

    # 2. 複数単語フレーズを先行置換（大文字小文字を無視）
    for en, ja in _COMMON_TERMS.items():
        result = re.sub(re.escape(en), ja, result, flags=re.IGNORECASE)

    # 構成タイトルで使われるキャリー分類も日本語化する。
    result = re.sub(r"\bAP\b", "魔法型", result, flags=re.IGNORECASE)
    result = re.sub(r"\bAD\b", "物理型", result, flags=re.IGNORECASE)

    # 3. 単語単位でtranslate_termを適用
    words = result.split()
    translated = []
    for w in words:
        tr = translate_term(w, translation_map)
        # 変換できた（元の単語と異なる）場合だけ置換
        if tr and tr != w and tr.lower() != w.lower():
            translated.append(tr)
        else:
            translated.append(w)

    return " ".join(translated)


def invalidate_translation_cache() -> None:
    """パッチ更新時などにキャッシュを破棄する。"""
    _build_champ_map.cache_clear()
    _build_trait_map.cache_clear()
    load_tft_translations.cache_clear()


# ===========================================================================
# アイテム・チャンピオンの略称・俗称・表記揺れ対応
# ===========================================================================

def _alias_key(s: str) -> str:
    """エイリアス照合用のキー正規化: 小文字化 + スペース/中黒/ハイフン/全角除去"""
    return (
        s.lower()
        .replace(" ", "")
        .replace("　", "")
        .replace("・", "")
        .replace("-", "")
        .replace("ー", "ー")  # 長音符は保持（除去しない）
    )


# ---------------------------------------------------------------------------
# 完成アイテム エイリアス辞書
# キー: _alias_key() 適用後の文字列  値: 正式日本語名
# ---------------------------------------------------------------------------
ITEM_ALIASES: dict[str, str] = {
    # ショウジンの矛
    "ショウジン": "ショウジンの矛",
    "矛": "ショウジンの矛",
    "槍": "ショウジンの矛",
    "shojin": "ショウジンの矛",
    # ブルーバフ
    "青バフ": "ブルーバフ",
    "青バフ": "ブルーバフ",  # 全角スペースなし版
    "青": "ブルーバフ",
    "ブルー": "ブルーバフ",
    "blue": "ブルーバフ",
    "bluebuff": "ブルーバフ",
    # アークエンジェル スタッフ
    "アーク": "アークエンジェル スタッフ",
    "アクエン": "アークエンジェル スタッフ",
    "大天使": "アークエンジェル スタッフ",
    "AA": "アークエンジェル スタッフ",
    "aa": "アークエンジェル スタッフ",
    "archangel": "アークエンジェル スタッフ",
    "archangels": "アークエンジェル スタッフ",
    "archangelsstaff": "アークエンジェル スタッフ",
    # ヘクステック ガンブレード
    "ガンブレ": "ヘクステック ガンブレード",
    "銃剣": "ヘクステック ガンブレード",
    "gunblade": "ヘクステック ガンブレード",
    "hextechgunblade": "ヘクステック ガンブレード",
    # ラバドン デスキャップ
    "デスキャ": "ラバドン デスキャップ",
    "ラバドン": "ラバドン デスキャップ",
    "帽子": "ラバドン デスキャップ",
    "デキャップ": "ラバドン デスキャップ",
    "rabadon": "ラバドン デスキャップ",
    "cap": "ラバドン デスキャップ",
    "rabadons": "ラバドン デスキャップ",
    "rabadonsdeathcap": "ラバドン デスキャップ",
    # ジュエル ガントレット
    "JG": "ジュエル ガントレット",
    "jg": "ジュエル ガントレット",
    "ジュエル": "ジュエル ガントレット",
    "ガントレット": "ジュエル ガントレット",
    "ジュエガン": "ジュエル ガントレット",
    "jeweled": "ジュエル ガントレット",
    "jeweledgauntlet": "ジュエル ガントレット",
    # モレロノミコン
    "モレロ": "モレロノミコン",
    "鬼本": "モレロノミコン",
    "morello": "モレロノミコン",
    "morellonomicon": "モレロノミコン",
    # ナッシャー トゥース
    "ナッシャー": "ナッシャー トゥース",
    "牙": "ナッシャー トゥース",
    "nashor": "ナッシャー トゥース",
    "nashorstooth": "ナッシャー トゥース",
    # インフィニティ エッジ
    "IE": "インフィニティ エッジ",
    "ie": "インフィニティ エッジ",
    "無限": "インフィニティ エッジ",
    "infinity": "インフィニティ エッジ",
    "infinityedge": "インフィニティ エッジ",
    # ラスト ウィスパー
    "ラスウィス": "ラスト ウィスパー",
    "LW": "ラスト ウィスパー",
    "lw": "ラスト ウィスパー",
    "弓矢": "ラスト ウィスパー",
    "lastwhisper": "ラスト ウィスパー",
    # デスブレード
    "デスブレ": "デスブレード",
    "赤剣": "デスブレード",
    "DB": "デスブレード",
    "db": "デスブレード",
    "deathblade": "デスブレード",
    # グインソー レイジブレード
    "グインソー": "グインソー レイジブレード",
    "羊刀": "グインソー レイジブレード",
    "RB": "グインソー レイジブレード",
    "rb": "グインソー レイジブレード",
    "rageblade": "グインソー レイジブレード",
    "guinsoosrageblade": "グインソー レイジブレード",
    # ステラックの篭手
    "ステラック": "ステラックの篭手",
    "篭手": "ステラックの篭手",
    "sterak": "ステラックの篭手",
    "steraksgage": "ステラックの篭手",
    # クラウンガード
    "カニ爪": "クラウンガード",
    "crownguard": "クラウンガード",
    # 揺るがぬ心
    "心の鋼": "揺るがぬ心",
    "鋼の心": "揺るがぬ心",
    "心臓": "揺るがぬ心",
    "頑固": "揺るがぬ心",
    "heart": "揺るがぬ心",
    "unflinchingheart": "揺るがぬ心",
    # サンファイア ケープ
    "サンファイア": "サンファイア ケープ",
    "炎衣": "サンファイア ケープ",
    "sunfire": "サンファイア ケープ",
    "sunfirecape": "サンファイア ケープ",
    # ワーモグ アーマー
    "ワーモグ": "ワーモグ アーマー",
    "緑鎧": "ワーモグ アーマー",
    "warmog": "ワーモグ アーマー",
    "warmogsarmor": "ワーモグ アーマー",
    # ガーゴイル ストーンプレート
    "ガゴ": "ガーゴイル ストーンプレート",
    "石像": "ガーゴイル ストーンプレート",
    "ドッペル": "ガーゴイル ストーンプレート",
    "gargoyle": "ガーゴイル ストーンプレート",
    "gargoylestoneplate": "ガーゴイル ストーンプレート",
    # アイオニック スパーク
    "スパーク": "アイオニック スパーク",
    "アイスパ": "アイオニック スパーク",
    "イオン": "アイオニック スパーク",
    "電撃": "アイオニック スパーク",
    "spark": "アイオニック スパーク",
    "ionicspark": "アイオニック スパーク",
    # ドラゴン クロウ
    "ドラクロ": "ドラゴン クロウ",
    "竜牙": "ドラゴン クロウ",
    "Dクロー": "ドラゴン クロウ",
    "dクロー": "ドラゴン クロウ",
    "dclaw": "ドラゴン クロウ",
    "dragonsclaw": "ドラゴン クロウ",
    # ブランブル ベスト
    "ブランブル": "ブランブル ベスト",
    "棘": "ブランブル ベスト",
    "bramble": "ブランブル ベスト",
    "bramblevest": "ブランブル ベスト",
    # イーブンシュラウド
    "薄暮": "イーブンシュラウド",
    "shroud": "イーブンシュラウド",
    "evenshroud": "イーブンシュラウド",
}

# キーを正規化済み形式で再インデックス（ランタイム時に一度だけ実行）
_ITEM_ALIAS_NORMALIZED: dict[str, str] = {
    _alias_key(k): v for k, v in ITEM_ALIASES.items()
}


CHAMPION_ALIASES: dict[str, str] = {
    # ----------------------------------------------------
    # あ行
    # ----------------------------------------------------
    # アーリ
    "ahri": "アーリ",
    "アーリ": "アーリ",
    "狐": "アーリ",
    # アフェリオス
    "aphel": "アフェリオス",
    "aphelios": "アフェリオス",
    "アフェ": "アフェリオス",
    "銃": "アフェリオス",
    # アニー
    "annie": "アニー",
    "アニー": "アニー",
    "クマ": "アニー",
    # アンバサ
    "ambessa": "アンバサ",
    "アンバサ": "アンバサ",
    "ベッサ": "アンバサ",
    # ヴェル＝コズ
    "vel": "ヴェル＝コズ",
    "velkoz": "ヴェル＝コズ",
    "ヴェル": "ヴェル＝コズ",
    "ヴェルコズ": "ヴェル＝コズ",
    # エズリアル
    "ez": "エズリアル",
    "ezreal": "エズリアル",
    "エズ": "エズリアル",
    # エコー
    "ekko": "エコー",
    "エコー": "エコー",
    # エリス
    "elise": "エリス",
    "エリス": "エリス",
    "蜘蛛": "エリス",
    # エルダードラゴン
    "elder": "ElderDragon",
    "elderdragon": "ElderDragon",
    "エルダー": "ElderDragon",
    "エルダードラゴン": "ElderDragon",
    "ドラゴン": "ElderDragon",
    "竜": "ElderDragon",
    # オーン
    "ornn": "オーン",
    "オーン": "オーン",
    "鍛冶屋": "オーン",
    # ----------------------------------------------------
    # か行
    # ----------------------------------------------------
    # カ＝ジックス
    "khaz": "カ＝ジックス",
    "khazix": "カ＝ジックス",
    "カジ": "カ＝ジックス",
    "カジックス": "カ＝ジックス",
    # カシオペア
    "cas": "カシオペア",
    "cass": "カシオペア",
    "cassiopeia": "カシオペア",
    "カシ": "カシオペア",
    "カシピ": "カシオペア",
    # カタリナ
    "kat": "カタリナ",
    "katarina": "カタリナ",
    "カタ": "カタリナ",
    # ガリオ
    "galio": "ガリオ",
    "ガリオ": "ガリオ",
    "石像": "ガリオ",
    # ガングプランク
    "gangplank": "ガングプランク",
    "gp": "ガングプランク",
    "ガングプランク": "ガングプランク",
    "ジーピー": "ガングプランク",
    "樽": "ガングプランク",
    "船長": "ガングプランク",
    # グレイブス
    "graves": "グレイブス",
    "グブ": "グレイブス",
    "グレイブス": "グレイブス",
    # ケイトリン
    "cait": "ケイトリン",
    "caitlyn": "ケイトリン",
    "ケイト": "ケイトリン",
    "スナ": "ケイトリン",
    # コーキ
    "corki": "コーキ",
    "コーキ": "コーキ",
    "コルキ": "コーキ",
    # コグ＝マウ
    "kog": "コグ＝マウ",
    "kogmaw": "コグ＝マウ",
    "コグ": "コグ＝マウ",
    "コグマウ": "コグ＝マウ",
    # ----------------------------------------------------
    # さ行
    # ----------------------------------------------------
    # サイオン
    "sion": "サイオン",
    "サイオン": "サイオン",
    # サイラス
    "sylas": "サイラス",
    "サイラス": "サイラス",
    # ザック
    "zac": "ザック",
    "ザック": "ザック",
    "スライム": "ザック",
    # ジリアン
    "zilean": "ジリアン",
    "ジリアン": "ジリアン",
    "時計": "ジリアン",
    # ジャーヴァンIV
    "j4": "ジャーヴァンIV",
    "jarvan": "ジャーヴァンIV",
    "jarvaniv": "ジャーヴァンIV",
    "ジャーヴァン": "ジャーヴァンIV",
    "ジャーヴァン4世": "ジャーヴァンIV",
    "ジェー4": "ジャーヴァンIV",
    "ジェーフォー": "ジャーヴァンIV",
    "ジェーⅳ": "ジャーヴァンIV",
    "旗": "ジャーヴァンIV",
    # ジンクス
    "jinx": "ジンクス",
    "ジンクス": "ジンクス",
    "ロケット": "ジンクス",
    # スウェイン
    "swain": "スウェイン",
    "カラス": "スウェイン",
    "スウェイン": "スウェイン",
    # セト
    "sett": "セト",
    "セト": "セト",
    "ボス": "セト",
    # ソラカ
    "soraka": "ソラカ",
    "ソラカ": "ソラカ",
    "バナナ": "ソラカ",
    "救急車": "ソラカ",
    # ----------------------------------------------------
    # た行
    # ----------------------------------------------------
    # タム・ケンチ
    "kench": "タム・ケンチ",
    "tahm": "タム・ケンチ",
    "カエル": "タム・ケンチ",
    "ケンチ": "タム・ケンチ",
    "タムケン": "タム・ケンチ",
    "ナマズ": "タム・ケンチ",
    # チョ＝ガス
    "cho": "チョ＝ガス",
    "chogath": "チョ＝ガス",
    "チョ": "チョ＝ガス",
    "チョガス": "チョ＝ガス",
    # ツイステッド・フェイト
    "tf": "ツイステッド・フェイト",
    "twistedfate": "ツイステッド・フェイト",
    "カード": "ツイステッド・フェイト",
    "ツイステ": "ツイステッド・フェイト",
    "ツイステッドフェイト": "ツイステッド・フェイト",
    "ティーエフ": "ツイステッド・フェイト",
    "トランプ": "ツイステッド・フェイト",
    # トリスターナ
    "trist": "トリスターナ",
    "tristana": "トリスターナ",
    "トリス": "トリスターナ",
    "トリスタ": "トリスターナ",
    # トリンダメア
    "trynd": "トリンダメア",
    "tryndamere": "トリンダメア",
    "ダメア": "トリンダメア",
    "トリン": "トリンダメア",
    "兄貴": "トリンダメア",
    # ----------------------------------------------------
    # な行
    # ----------------------------------------------------
    # ナサス
    "nasus": "ナサス",
    "ナサス": "ナサス",
    "犬": "ナサス",
    # ヌヌ＆ウィランプ
    "nunu": "ヌヌ＆ウィランプ",
    "ヌヌ": "ヌヌ＆ウィランプ",
    # ノーチラス
    "naut": "ノーチラス",
    "nautilus": "ノーチラス",
    "イカリ": "ノーチラス",
    "ノーチ": "ノーチラス",
    "ノーチラス": "ノーチラス",
    "錨": "ノーチラス",
    # ----------------------------------------------------
    # は行
    # ----------------------------------------------------
    # ハイマーディンガー
    "heimer": "ハイマーディンガー",
    "heimerdinger": "ハイマーディンガー",
    "ハイマー": "ハイマーディンガー",
    "教授": "ハイマーディンガー",
    # フィドルスティックス
    "fiddle": "フィドルスティックス",
    "fiddlesticks": "フィドルスティックス",
    "かかし": "フィドルスティックス",
    "フィドル": "フィドルスティックス",
    # ブラッドミア
    "vlad": "ブラッドミア",
    "vladimir": "ブラッドミア",
    "ブラジ": "ブラッドミア",
    "ブラッド": "ブラッドミア",
    "吸血鬼": "ブラッドミア",
    # ブリッツクランク
    "blitz": "ブリッツクランク",
    "blitzcrank": "ブリッツクランク",
    "ブリッツ": "ブリッツクランク",
    "ロボ": "ブリッツクランク",
    # ヘカリム
    "heca": "ヘカリム",
    "hekarim": "ヘカリム",
    "ヘカリム": "ヘカリム",
    "馬": "ヘカリム",
    # ----------------------------------------------------
    # ま行
    # ----------------------------------------------------
    # マルザハール
    "malz": "マルザハール",
    "malzahar": "マルザハール",
    "マルザ": "マルザハール",
    "虫": "マルザハール",
    # ミス・フォーチュン
    "missfortune": "ミス・フォーチュン",
    "mf": "ミス・フォーチュン",
    "エムエフ": "ミス・フォーチュン",
    "ミス・フォーチュン": "ミス・フォーチュン",
    "ミスフォーチュン": "ミス・フォーチュン",
    # モルガナ
    "morg": "モルガナ",
    "morgana": "モルガナ",
    "モルガ": "モルガナ",
    # モルデカイザー
    "morde": "モルデカイザー",
    "モルデ": "モルデカイザー",
    "モルデカイザー": "モルデカイザー",
    "鉄": "モルデカイザー",
    # ----------------------------------------------------
    # や・ら・わ行
    # ----------------------------------------------------
    # ヤスオ
    "yasuo": "ヤスオ",
    "ハサキ": "ヤスオ",
    "ヤスオ": "ヤスオ",
    # ヨネ
    "yone": "ヨネ",
    "ヨネ": "ヨネ",
    # ルブラン
    "lb": "ルブラン",
    "leblanc": "ルブラン",
    "エルビー": "ルブラン",
    "ルブラン": "ルブラン",
    # レク＝サイ
    "rek": "レク＝サイ",
    "reksai": "レク＝サイ",
    "ゴキ": "レク＝サイ",
    "ゴキブリ": "レク＝サイ",
    "レクサイ": "レク＝サイ",
    "レクスサイ": "レク＝サイ",
    # ワーウィック
    "warwick": "ワーウィック",
    "ww": "ワーウィック",
    "ワラワラ": "ワーウィック",
    "ワーウィック": "ワーウィック",
    "狼": "ワーウィック",
}
# キーを正規化済み形式で再インデックス
_CHAMPION_ALIAS_NORMALIZED: dict[str, str] = {
    _alias_key(k): v for k, v in CHAMPION_ALIASES.items()
}


# ---------------------------------------------------------------------------
# 公開API
# ---------------------------------------------------------------------------

def normalize_item_alias(name: str) -> str:
    """略称・俗称・英語エイリアスから正式アイテム日本語名へ変換する。

    変換できない場合は入力文字列をそのまま返す。

    例:
        normalize_item_alias("ショウジン")  -> "ショウジンの矛"
        normalize_item_alias("青バフ")      -> "ブルーバフ"
        normalize_item_alias("ガーゴイル ストーンプレート")  -> "ガーゴイル ストーンプレート"（変換不要）
    """
    if not name:
        return name
    key = _alias_key(name)
    return _ITEM_ALIAS_NORMALIZED.get(key, name)


def normalize_champion_alias(name: str) -> str:
    """略称・俗称・英語エイリアスから正式チャンピオン日本語名へ変換する。

    変換できない場合は入力文字列をそのまま返す。

    例:
        normalize_champion_alias("コグ")    -> "コグ＝マウ"
        normalize_champion_alias("カシ")    -> "カシオペア"
        normalize_champion_alias("アーリ")  -> "アーリ"（変換不要）
    """
    if not name:
        return name
    key = _alias_key(name)
    return _CHAMPION_ALIAS_NORMALIZED.get(key, name)
