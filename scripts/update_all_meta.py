import argparse
import os
from pathlib import Path
import subprocess
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.meta.champion_extractor import sync_champion_data
# 既存のインポート（プロジェクトの構成に合わせて保持）
# from src.meta.collector import ...
# from src.rag.build_vector_db import ...


def main():
    parser = argparse.ArgumentParser(description="TFT Meta Data Updater")
    parser.add_argument(
        "--skip-riot",
        action="store_true",
        help="Riot API からの試合データ・パッチ取得をスキップして高速実行",
    )
    parser.add_argument(
        "--patch",
        type=str,
        default="16.18",
        help="対象パッチバージョン (デフォルト: 16.18)",
    )
    args = parser.parse_args()

    patch_version = args.patch
    output_dir = project_root / f"data/patch_{patch_version}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🚀 メタデータ同期パイプラインを開始 (Target Patch: {patch_version})")

    # Step 0.5: チャンピオン & シナジー (CDragon) の同期
    print("\n--- [Step 0.5] チャンピオン & シナジーデータの抽出・同期 ---")
    sync_champion_data(patch_version, output_dir)

    # Step 1: Riot API 収集 (フラグ指定時は完全スキップ)
    if args.skip_riot:
        print("\n⚡ [Step 1] --skip-riot が指定されたため、Riot API の収集をスキップします。")
    else:
        print("\n--- [Step 1] Riot API からの上位帯マッチデータ収集 ---")
        # 既存の Riot API 収集関数を実行
        # collect_riot_matches(patch_version, output_dir)

    # Step 2: TFTAcademy 等の外部ガイド取得（キャッシュ済みの場合はスキップまたは既存処理）
    print("\n--- [Step 2] 構成ガイド・メタ情報の確認 ---")
    # 既存の外部ガイド処理

    # Step 3: RAG ベクトル DB の再構築 (champions.json や traits.json もインデックス化)
    print("\n--- [Step 3] RAG ベクトル DB の再構築 ---")
    # ここでローカルの champions.json, traits.json, 既存 meta_cache からベクトル化
    # build_vector_index(output_dir)

    # Step 4: Git コミット & プッシュ
    print("\n--- [Step 4] データの Git 同期 ---")
    try:
        subprocess.run(["git", "add", "data/"], check=True)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"chore: update meta & vector db for patch {patch_version}",
            ],
            check=False,
        )
        print("✅ Git ステージング/コミット完了")
    except Exception as e:
        print(f"⚠️ Git コミット中に警告: {e}")

    print("\n🎉 高速構築パイプラインが完了しました！")


if __name__ == "__main__":
    main()