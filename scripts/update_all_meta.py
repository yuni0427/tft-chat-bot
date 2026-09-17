import argparse
import os
from pathlib import Path
import subprocess
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.meta.champion_extractor import sync_champion_data
from src.meta import meta_service


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
        default=None,
        help="対象パッチバージョン (省略時は current_patch.txt を使用)",
    )
    parser.add_argument(
        "--start-time",
        type=int,
        default=None,
        help="試合取得の開始時刻（Unixエポック秒、省略時は current_patch.txt から自動取得）",
    )
    args = parser.parse_args()

    # 1. current_patch.txt からパッチ名と開始時刻を取得（コマンド引数があればそちらを優先）
    default_patch, default_start = meta_service.get_current_patch_info()
    patch_version = args.patch or default_patch
    start_time = args.start_time or default_start

    output_dir = project_root / f"data/patch_{patch_version}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🚀 メタデータ同期パイプラインを開始 (Target Patch: {patch_version})")
    if start_time:
        print(f"⏱️ 集計開始時刻フィルタ: {start_time} 以降の試合に限定")

    # Step 0.5: チャンピオン & シナジー (CDragon) の同期
    print("\n--- [Step 0.5] チャンピオン & シナジーデータの抽出・同期 ---")
    sync_champion_data(patch_version, output_dir)

    # Step 1: Riot API 収集 & meta_cache.json 生成
    if args.skip_riot:
        print("\n⚡ [Step 1] --skip-riot が指定されたため、Riot API の収集をスキップします。")
    else:
        print("\n--- [Step 1] Riot API からの上位帯マッチデータ収集 & 集計 ---")
        cmd = [
            sys.executable,
            str(project_root / "scripts" / "build_meta_stats.py"),
            "--patch",
            patch_version,
        ]
        if start_time:
            cmd.extend(["--start-time", str(start_time)])

        res = subprocess.run(cmd, check=False)
        if res.returncode != 0:
            print("⚠️ Riot API からの集計でエラーが発生しました。")

    # Step 2: 構成ガイド・メタ情報の確認
    print("\n--- [Step 2] 構成ガイド・メタ情報の確認 ---")

    # Step 3: RAG ベクトル DB の再構築
    print("\n--- [Step 3] RAG ベクトル DB の再構築 ---")
    vector_script = project_root / "scripts" / "build_vector_db.py"
    if vector_script.exists():
        subprocess.run([sys.executable, str(vector_script)], check=False)

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