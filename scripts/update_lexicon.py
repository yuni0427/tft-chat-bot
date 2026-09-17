"""
新セット移行時専用: Riot公式 (CommunityDragon) 日本語辞書生成 & 同期スクリプト
新セット開始時や大規模パッチで辞書を更新したい場合に単発で実行します。
"""
import json
import subprocess
import sys
from pathlib import Path
import requests

CDRAGON_URL = "https://raw.communitydragon.org/pbe/cdragon/tft/ja_jp.json"
OUTPUT_PATH = Path("data/tft_lexicon_ja.json")

# 剥がす対象のプレフィックスパターン
PREFIXES = [
    "da_18_", "da_", "tft_augment_", "tft18_augment_", "tft18_", "tft_",
    "tft13_", "tft12_", "tft11_", "tft10_", "tft9_", "tft8_", "tft7_", "tft6_"
]


def update_lexicon():
    print(f"\n[1/2] CommunityDragon から最新日本語データをダウンロード中...\nURL: {CDRAGON_URL}")
    try:
        resp = requests.get(CDRAGON_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"❌ ダウンロードに失敗しました: {exc}")
        sys.exit(1)

    mapping: dict[str, str] = {}

    def _register(api_name: str, ja_name: str):
        if not api_name or not ja_name:
            return
        al = api_name.lower().strip()
        mapping[al] = ja_name.strip()

        # プレフィックスを剥がしたキーも登録
        for p in PREFIXES:
            if al.startswith(p):
                clean_key = al[len(p):]
                mapping[clean_key] = ja_name.strip()

    # 1. アイテム & オーグメント
    for it in data.get("items", []):
        _register(it.get("apiName", ""), it.get("name", ""))

    # 2. セットデータ（チャンピオン & 特性）
    for s in data.get("setData", []):
        for ch in s.get("champions", []):
            _register(ch.get("apiName", ""), ch.get("name", ""))
        for tr in s.get("traits", []):
            _register(tr.get("apiName", ""), tr.get("name", ""))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    print(f"✅ 辞書更新完了: {len(mapping)} 件のエントリを {OUTPUT_PATH} に保存しました。")


def sync_git():
    print("\n[2/2] GitHub へ辞書ファイルを同期中...")
    subprocess.run(["git", "add", str(OUTPUT_PATH)])
    commit_res = subprocess.run(
        ["git", "commit", "-m", "chore: update TFT Japanese lexicon for new set"],
        capture_output=True,
        text=True,
    )
    if commit_res.returncode == 0:
        push_res = subprocess.run(["git", "push"])
        if push_res.returncode == 0:
            print("🎉 新セット用辞書の反映とデプロイが完了しました！")
        else:
            print("⚠️ プッシュに失敗しました。リモート設定を確認してください。")
    else:
        print("ℹ️ 既存の辞書ファイルと差分がなかったため、プッシュをスキップしました。")


def main():
    update_lexicon()
    sync_git()


if __name__ == "__main__":
    main()