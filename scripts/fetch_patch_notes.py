import sys
from pathlib import Path
import requests

def fetch_tftips_patch_notes(patch_version: str, output_dir: Path) -> bool:
    url = f"https://tftips.app/patches/{patch_version}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        from bs4 import BeautifulSoup

        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"⚠️ パッチノートが見つかりませんでした (Status: {res.status_code}): {url}")
            return False
            
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 本文メインエリアを抽出（tftipsのDOM構造に合わせてセレクタ調整）
        main_content = soup.find("main") or soup.find("article") or soup.body
        text_content = main_content.get_text(separator="\n", strip=True)
        
        md_file = output_dir / "patch_notes.md"
        md_file.write_text(f"# Patch {patch_version} Notes (tftips.app)\n\nURL: {url}\n\n" + text_content, encoding="utf-8")
        print(f"✅ パッチノートを保存しました: {md_file}")
        return True
    except Exception as e:
        print(f"⚠️ パッチノートの取得に失敗: {e}")
        return False