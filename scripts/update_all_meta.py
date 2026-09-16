"""
TFT メタデータ・ナレッジ完全自動同期スクリプト (毎日15:00 JST / 手動実行両用)
0. Riot Data Dragon から最新パッチ番号を取得し data/current_patch.txt を自動更新
1. Riot公式 日本語辞書の最新化 (CommunityDragon)
2. Riot API マッチ統計の収集 & 分析 (build_meta_stats.py)
3. TFTAcademy データのプリキャッシュ
4. RAG ベクトルDB (理論ノート) の再構築 (build_vector_db.py)
5. GitHub への自動コミット & プッシュ
"""
import json
import subprocess
import sys
from pathlib import Path
import requests


def log(msg: str):
    print(f"\n{'='*55}\n[SYNC] {msg}\n{'='*55}")


def sync_latest_patch() -> str:
    log("0/4: Riot Data Dragon から最新パッチ番号を検出中...")
    fallback_patch = "14.23"

    try:
        url = "https://ddragon.leagueoflegends.com/api/versions.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        versions = resp.json()

        if versions and isinstance(versions, list):
            full_ver = versions[0]
            parts = full_ver.split(".")
            latest_patch = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else full_ver

            patch_file = Path("data/current_patch.txt")
            patch_file.parent.mkdir(parents=True, exist_ok=True)
            patch_file.write_text(latest_patch, encoding="utf-8")

            print(f"最新パッチを検出・保存しました: {latest_patch} (Data Dragon: {full_ver})")
            return latest_patch
    except Exception as e:
        print(f"パッチ番号取得中に警告: {e}。ローカルの既存設定を維持します。")

    patch_file = Path("data/current_patch.txt")
    if patch_file.exists():
        return patch_file.read_text(encoding="utf-8").strip()
    return fallback_patch


def update_lexicon():
    log("1/4: Riot公式 最新日本語辞書の取得中...")
    url = "https://raw.communitydragon.org/pbe/cdragon/tft/ja_jp.json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        mapping = {}

        for it in data.get("items", []):
            a, n = it.get("apiName", ""), it.get("name", "")
            if a and n:
                al = a.lower()
                mapping[al] = n
                for p in ["da_18_", "da_", "tft_augment_", "tft18_augment_", "tft18_", "tft_"]:
                    if al.startswith(p):
                        mapping[al[len(p):]] = n

        for s in data.get("setData", []):
            for ch in s.get("champions", []):
                a, n = ch.get("apiName", ""), ch.get("name", "")
                if a and n:
                    al = a.lower()
                    mapping[al] = n
                    for p in ["da_18_", "da_", "tft18_", "tft_"]:
                        if al.startswith(p):
                            mapping[al[len(p):]] = n

            for tr in s.get("traits", []):
                a, n = tr.get("apiName", ""), tr.get("name", "")
                if a and n:
                    al = a.lower()
                    mapping[al] = n
                    for p in ["da_18_", "da_", "tft18_", "tft_"]:
                        if al.startswith(p):
                            mapping[al[len(p):]] = n

        out = Path("data/tft_lexicon_ja.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"辞書更新完了: {len(mapping)} 件登録")
    except Exception as e:
        print(f"辞書取得エラー: {e}（既存辞書がある場合は処理を継続します）")


def update_riot_stats(patch: str):
    log(f"2/4: Riot API 実戦統計データの収集・分析・集計を実行中 (パッチ: {patch})...")
    # build_meta_stats.py に検知したパッチ番号を明示的に渡して実行
    res = subprocess.run([sys.executable, "scripts/build_meta_stats.py", "--patch", patch])
    if res.returncode != 0:
        print("⚠️ Riot API 統計の更新で警告またはエラーが発生しました。")


def warmup_tftacademy():
    log("3/4: TFTAcademy データのプリキャッシュ中...")
    try:
        from src.meta.tftacademy_client import get_tftacademy_tierlist

        data = get_tftacademy_tierlist()
        guides = data.get("guides", []) if isinstance(data, dict) else data
        print(f"TFTAcademy プリキャッシュ完了: {len(guides)} 件の構成を取得")
    except Exception as e:
        print(f"TFTAcademy 取得エラー: {e}")


def rebuild_vector_db():
    log("4/4: RAG ベクトルDB (理論ノート) の再構築中...")
    res = subprocess.run([sys.executable, "scripts/build_vector_db.py"])
    if res.returncode != 0:
        print("⚠️ ベクトルDBの再構築でエラーが発生しました。")


def sync_to_github():
    log("GitHub への自動コミット & プッシュを実行中...")
    subprocess.run(["git", "add", "data/"])
    commit_res = subprocess.run(
        ["git", "commit", "-m", "chore: auto-sync daily meta stats & knowledge [skip ci]"],
        capture_output=True,
        text=True,
    )
    if commit_res.returncode == 0:
        push_res = subprocess.run(["git", "push"])
        if push_res.returncode == 0:
            print("🎉 すべてのデータ更新と GitHub/Streamlit へのデプロイが完了しました！")
        else:
            print("⚠️ GitHub へのプッシュに失敗しました。")
    else:
        print("ℹ️ データに変更がなかったため、プッシュをスキップしました。")


def main():
    current_patch = sync_latest_patch()
    update_lexicon()
    update_riot_stats(current_patch)
    warmup_tftacademy()
    rebuild_vector_db()
    sync_to_github()


if __name__ == "__main__":
    main()