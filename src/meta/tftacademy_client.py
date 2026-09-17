import json
import logging
from pathlib import Path
import re
import requests
import streamlit as st

logger = logging.getLogger(__name__)

TFTACADEMY_BASE_URL = "https://tftacademy.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def _fetch_from_web() -> dict:
    """TFTAcademy からWebスクレイピングで最新データを直接取得"""
    try:
        url = f"{TFTACADEMY_BASE_URL}/api/tierlist/comps"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json()

        page_res = requests.get(
            f"{TFTACADEMY_BASE_URL}/tierlist/comps", headers=HEADERS, timeout=10
        )
        if page_res.status_code == 200 and "__NEXT_DATA__" in page_res.text:
            raw_html = page_res.text
            json_str = (
                raw_html.split(
                    '<script id="__NEXT_DATA__" type="application/json">'
                )[1]
                .split("</script>")[0]
            )
            data = json.loads(json_str)
            return (
                data.get("props", {})
                .get("pageProps", {})
                .get("tierlist", {})
            )
    except Exception as e:
        logger.warning(f"Failed to fetch TFTAcademy live data: {e}")
    return {}


@st.cache_data(ttl=21600, show_spinner=False)
def _cached_tierlist() -> dict:
    return _fetch_from_web()


def get_tftacademy_tierlist(force_refresh: bool = False) -> dict:
    """
    CLI/バッチ・Streamlit双方から安全に呼び出せるエントリーポイント。
    force_refresh=True でキャッシュをバイパスして最新を取得。
    """
    if force_refresh:
        try:
            _cached_tierlist.clear()
        except Exception:
            pass
        return _fetch_from_web()

    try:
        return _cached_tierlist()
    except Exception:
        return _fetch_from_web()


def sync_patch_guides(patch_version: str, output_dir: Path) -> None:
    """
    Step 2 用統合処理:
    1. TFTAcademy から構成データを取得し meta_snapshot.json として保存
    2. tftips.app からパッチ差分を取得し patch_notes.md として保存
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. TFTAcademy のデータを取得 & 保存
    try:
        comps_data = get_tftacademy_tierlist(force_refresh=True)
        if comps_data:
            snapshot_file = output_dir / "meta_snapshot.json"
            
            # APIのキーは 'guides'（フォールバックで 'comps' やリスト全体）
            raw_comps = (
                comps_data
                if isinstance(comps_data, list)
                else comps_data.get("guides", comps_data.get("comps", []))
            )
            
            # ★ isPublic が True の公開現役構成のみを厳選（AP Fast 9 などの17件を上流で完全遮断）
            active_comps = [c for c in raw_comps if c.get("isPublic") is True]

            formatted_snapshot = {
                "patch": patch_version,
                "source": "tftacademy",
                "comp_recommendations": active_comps,
            }
            snapshot_file.write_text(
                json.dumps(formatted_snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"✅ TFTAcademy ガイドを保存（公開 {len(active_comps)}件 / 全 {len(raw_comps)}件）: {snapshot_file}")
        else:
            print("⚠️ TFTAcademy データの取得をスキップ（空データまたは未取得）")
    except Exception as e:
        print(f"⚠️ TFTAcademy 取得エラー: {e}")