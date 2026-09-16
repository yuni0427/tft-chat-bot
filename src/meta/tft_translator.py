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