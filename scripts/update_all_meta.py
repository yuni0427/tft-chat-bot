"""TFT メタデータ・ナレッジ自動同期スクリプト (毎日15:00 JST / 手動実行両用)
0. Riot Data Dragon から最新パッチ番号を取得し data/current_patch.txt を自動更新
0.5. 新パッチ時のみ各チャンピオンの基礎データ・デバフ(重症/分解/細断)を更新
1. Riot API マッチ統計の収集 & 分析 (build_meta_stats.py)
2. TFTAcademy データのプリキャッシュ
3. RAG ベクトルDB (理論ノート) の再構築 (build_vector_db.py)
4. GitHub への自動コミット & プッシュ
"""

from pathlib import Path
import subprocess
import sys

# プロジェクトルート (scripts の1つ上の階層) を最優先で sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
            latest_patch = (
                f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else full_ver
            )

            patch_file = Path("data/current_patch.txt")
            patch_file.parent.mkdir(parents=True, exist_ok=True)
            patch_file.write_text(latest_patch, encoding="utf-8")

            print(
                f"最新パッチを検出・保存しました: {latest_patch} (Data Dragon: {full_ver})"
            )
            return latest_patch
    except Exception as e:
        print(
            f"パッチ番号取得中に警告: {e}。ローカルの既存設定を維持します。"
        )

    patch_file = Path("data/current_patch.txt")
    if patch_file.exists():
        return patch_file.read_text(encoding="utf-8").strip()
    return fallback_patch


def sync_champions_if_new_patch(patch: str, force: bool = False):
    """パッチ更新時（またはファイル未生成時 / 強制実行時）のみチャンピオン基礎情報・デバフを同期"""
    log(
        f"0.5/4: チャンピオン基礎データ & ユーティリティ(重症/分解/細断) チェック (パッチ: {patch})..."
    )

    patch_dir = Path("data") / f"patch_{patch}"
    target_file = patch_dir / "champions.json"

    if target_file.exists() and not force:
        print(
            f"ℹ️ パッチ {patch} のチャンピオンデータは既に存在するためスキップします。"
        )
        return

    try:
        from src.meta.champion_extractor import sync_champion_data

        print(
            f"⚡ チャンピオンデータを CDragon から抽出中: {target_file} ..."
        )
        sync_champion_data(patch_version=patch, output_dir=patch_dir)
        print("✅ チャンピオンデータの生成・保存が完了しました。")
    except Exception as e:
        print(f"⚠️ チャンピオンデータ同期中にエラーが発生しました: {e}")


def update_riot_stats(patch: str):
    log(
        f"1/4: Riot API 実戦統計データの収集・分析・集計を実行中 (パッチ: {patch})..."
    )
    res = subprocess.run(
        [sys.executable, "scripts/build_meta_stats.py", "--patch", patch]
    )
    if res.returncode != 0:
        print("⚠️ Riot API 統計の更新で警告またはエラーが発生しました。")


def warmup_tftacademy():
    log("2/4: TFTAcademy データのプリキャッシュ中...")
    try:
        from src.meta.tftacademy_client import get_tftacademy_tierlist

        data = get_tftacademy_tierlist()
        guides = data.get("guides", []) if isinstance(data, dict) else data
        print(f"TFTAcademy プリキャッシュ完了: {len(guides)} 件の構成を取得")
    except Exception as e:
        print(f"TFTAcademy 取得エラー: {e}")


def rebuild_vector_db():
    log("3/4: RAG ベクトルDB (理論ノート) の再構築中...")
    res = subprocess.run([sys.executable, "scripts/build_vector_db.py"])
    if res.returncode != 0:
        print("⚠️ ベクトルDBの再構築でエラーが発生しました。")


def sync_to_github():
    log("4/4: GitHub への自動コミット & プッシュを実行中...")
    subprocess.run(["git", "add", "data/"])
    commit_res = subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "chore: auto-sync daily meta stats & knowledge [skip ci]",
        ],
        capture_output=True,
        text=True,
    )
    if commit_res.returncode == 0:
        push_res = subprocess.run(["git", "push"])
        if push_res.returncode == 0:
            print(
                "🎉 すべてのデータ更新と GitHub/Streamlit へのデプロイが完了しました！"
            )
        else:
            print("⚠️ GitHub へのプッシュに失敗しました。")
    else:
        print(
            "ℹ️ データに変更がなかったため、プッシュをスキップしました。"
        )


def main():
    force_champ = "--force-champions" in sys.argv

    current_patch = sync_latest_patch()
    sync_champions_if_new_patch(current_patch, force=force_champ)
    update_riot_stats(current_patch)
    warmup_tftacademy()
    rebuild_vector_db()
    sync_to_github()


if __name__ == "__main__":
    main()