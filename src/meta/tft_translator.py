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

    # 1. 複数単語フレーズを先行置換（大文字小文字を無視）
    for en, ja in _COMMON_TERMS.items():
        result = re.sub(re.escape(en), ja, result, flags=re.IGNORECASE)

    # 2. 単語単位で translate_term を適用
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
    load_tft_translations.cache_clear()
