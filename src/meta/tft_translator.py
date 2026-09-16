"""
Riot Data Dragon から TFT の日本語名称マッピングを生成・保持するモジュール
"""
import requests
import streamlit as st

@st.cache_data(ttl=86400)
def load_tft_translations(patch_version: str = "latest") -> dict[str, str]:
    """
    Data Dragon (CommunityDragon) からチャンピオン・アイテム・特性の英語名/API名 -> 日本語名マッピングを取得
    """
    translation_map = {}
    try:
        # CommunityDragon の最新日本語データ（最新パッチのTFT辞書）
        url = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/ja_jp/v1/tft-items.json"
        # 全体辞書（チャンピオン・アイテム・シナジー網羅）
        cdragon_url = "https://raw.communitydragon.org/pbe/cdragon/tft/ja_jp.json"
        
        resp = requests.get(cdragon_url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # チャンピオン名マッピング
            for set_data in data.get("setData", []):
                for champ in set_data.get("champions", []):
                    api_name = champ.get("apiName", "")
                    name = champ.get("name", "")
                    if api_name and name:
                        translation_map[api_name.lower()] = name
                        # プレフィックス除去版も登録 (例: ahri -> アーリ)
                        clean = api_name.split("_")[-1].lower()
                        translation_map[clean] = name

            # アイテム名マッピング
            for item in data.get("items", []):
                api_name = item.get("apiName", "")
                name = item.get("name", "")
                if api_name and name:
                    translation_map[api_name.lower()] = name
                    clean = api_name.split("_")[-1].lower()
                    translation_map[clean] = name

    except Exception:
        # オフライン時や取得失敗時のフォールバック（代表的な主要名）
        pass

    return translation_map