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
    
    from pathlib import Path
from bs4 import BeautifulSoup


def sync_patch_guides(patch_version: str, output_dir: Path) -> None:
    """
    Step 2 用統合処理:
    1. TFTAcademy から構成データを取得し meta_snapshot.json として保存
    2. tftips.app からパッチ差分を取得し patch_notes.md として保存
    """
    # 1. TFTAcademy のデータを取得 & 保存
    try:
        comps_data = get_tftacademy_tierlist()
        if comps_data:
            snapshot_file = output_dir / "meta_snapshot.json"
            formatted_snapshot = {
                "patch": patch_version,
                "source": "tftacademy",
                "comp_recommendations": comps_data if isinstance(comps_data, list) else comps_data.get("comps", []),
            }
            snapshot_file.write_text(json.dumps(formatted_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✅ TFTAcademy ガイドを保存: {snapshot_file}")
        else:
            print("⚠️ TFTAcademy データの取得をスキップ（空データまたは未取得）")
    except Exception as e:
        print(f"⚠️ TFTAcademy 取得エラー: {e}")

    # 2. tftips.app のパッチノートを取得 & 保存
    url = f"https://tftips.app/patches/{patch_version}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            main_elem = soup.find("main") or soup.find("article") or soup.body
            if main_elem:
                notes_md = output_dir / "patch_notes.md"
                notes_md.write_text(
                    f"# Patch {patch_version} Notes (tftips.app)\n\nURL: {url}\n\n"
                    + main_elem.get_text(separator="\n", strip=True),
                    encoding="utf-8",
                )
                print(f"✅ tftips パッチノートを保存: {notes_md}")
        else:
            print(f"⚠️ tftips パッチノートが見つかりませんでした (Status: {res.status_code}): {url}")
    except Exception as e:
        print(f"⚠️ tftips パッチノート取得エラー: {e}")