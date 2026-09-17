"""
ローカル保存した Riot 公式翻訳辞書 (data/tft_lexicon_ja.json) を参照するモジュール
"""
import json
from pathlib import Path
import streamlit as st

_LEXICON_PATH = Path("data/tft_lexicon_ja.json")


@st.cache_data
def load_tft_translations() -> dict[str, str]:
    """data/tft_lexicon_ja.json を読み込んで辞書を返す"""
    if not _LEXICON_PATH.exists():
        return {}
    try:
        with open(_LEXICON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def translate_term(term: str, translation_map: dict[str, str] | None = None) -> str:
    """apiName や英語名を公式日本語名に変換"""
    if not term:
        return "-"

    if translation_map is None:
        translation_map = load_tft_translations()

    # 1. 完全一致（小文字）
    key_full = term.lower()
    if key_full in translation_map:
        return translation_map[key_full]

    # 2. プレフィックスと語尾の数字（パッチ/セット番号）を除去して探索
    clean = term
    for prefix in ["DA_18_", "DA_", "TFT18_", "TFT_", "TFT_Augment_"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    if clean.endswith("18"):
        clean = clean[:-2]

    key_clean = clean.lower()
    if key_clean in translation_map:
        return translation_map[key_clean]

    # 辞書にない場合は整形後の文字列をフォールバックとして返す
    return clean

def preprocess_tft_text(text: str, translation_map: dict[str, str] | None = None) -> str:
    """複合英文から駒・特性・スタイルを安全に日本語置換"""
    if not text:
        return ""
    if translation_map is None:
        translation_map = load_tft_translations()

    # 汎用プレイスタイル・定番俗称の即時マッピング
    common_terms = {
        "fast 8": "ファスト8",
        "fast 9": "ファスト9",
        "reroll": "リロール",
        "flex": "フレックス",
        "elder dragon": "エルダードラゴン",
        "dragon": "ドラゴン",
    }

    result = text
    # 1. 2単語以上のフレーズを先行置換
    for en, ja in common_terms.items():
        import re
        result = re.sub(re.escape(en), ja, result, flags=re.IGNORECASE)

    # 2. 単語単位で辞書引き（translate_term を活用）
    words = result.split()
    translated = []
    for w in words:
        # すでに日本語になっているかチェック
        tr = translate_term(w, translation_map)
        # translate_term が変換できた場合（元の w と異なる、かつハイフン以外）
        if tr and tr != "-" and tr.lower() != w.lower():
            translated.append(tr)
        else:
            translated.append(w)

    return " ".join(translated)