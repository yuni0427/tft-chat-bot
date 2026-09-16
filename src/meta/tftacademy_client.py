import streamlit as st
import requests
import json
import logging

logger = logging.getLogger(__name__)

TFTACADEMY_BASE_URL = "https://tftacademy.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


@st.cache_data(ttl=21600)  # 6時間（21,600秒）ごとに自動再取得
def get_tftacademy_tierlist() -> dict:
    """
    TFTAcademy から最新の構成ティアリストを自動取得・パースして返す。
    取得失敗時はフォールバックの空辞書を返すためアプリが落ちない。
    """
    try:
        # Next.js の内部API / ビルドデータを自動ターゲット
        # ※ サイト構造変更にも耐えられるよう、まずはメインのコンプ一覧を叩く
        url = f"{TFTACADEMY_BASE_URL}/api/tierlist/comps"
        res = requests.get(url, headers=HEADERS, timeout=10)

        if res.status_code == 200:
            return res.json()

        # 代替: HTML/NextDataからのフォールバック取得
        page_res = requests.get(f"{TFTACADEMY_BASE_URL}/tierlist/comps", headers=HEADERS, timeout=10)
        if page_res.status_code == 200 and "__NEXT_DATA__" in page_res.text:
            raw_html = page_res.text
            json_str = raw_html.split('<script id="__NEXT_DATA__" type="application/json">')[1].split("</script>")[0]
            data = json.loads(json_str)
            # Next.js の pageProps から構成データを抽出
            comps = data.get("props", {}).get("pageProps", {}).get("tierlist", {})
            return comps

    except Exception as e:
        logger.warning(f"Failed to fetch TFTAcademy live data: {e}")

    return {}