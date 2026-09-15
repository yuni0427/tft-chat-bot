"""
Riot Games公式APIから上位プレイヤーの直近試合を収集し、統計フィルタを適用した
アイテムビルド・構成統計を集計して data/patch_xx/meta_cache.json に保存するCLIスクリプト。

RIOT_API_KEY が .env に設定されている必要があります。
未設定・取得失敗時はエラーメッセージを表示して終了します（アプリ本体は
meta_snapshot.json への自動フォールバックにより問題なく動作し続けます）。

使い方:
    # 最新パッチで収集（startTime/endTime なし）
    python scripts/build_meta_stats.py

    # パッチを指定
    python scripts/build_meta_stats.py --patch 15.8

    # パッチ期間をエポック秒で絞り込む（前パッチの試合を除外できる）
    python scripts/build_meta_stats.py --start-time 1712880000 --end-time 1713484800

    # 収集量を調整
    python scripts/build_meta_stats.py --top-n 50 --matches-per-player 10

    # Grandmaster 帯を除外して Challenger のみ収集
    python scripts/build_meta_stats.py --no-grandmaster
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from src.meta import match_collector, meta_service  # noqa: E402
from src.meta.aggregator import build_meta_dataset  # noqa: E402
from src.meta.riot_api_client import RiotAPIError  # noqa: E402
from src.meta.static_provider import get_latest_ddragon_version  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Riot APIからTFTメタ統計を収集・集計して meta_cache.json に保存する"
    )
    parser.add_argument(
        "--patch",
        default=None,
        help="対象パッチ（省略時は data/current_patch.txt の値を使用）",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help=f"収集する上位プレイヤー数（デフォルト: {config.META_COLLECT_TOP_N}）",
    )
    parser.add_argument(
        "--matches-per-player",
        type=int,
        default=None,
        help=f"1プレイヤーあたりの収集試合数（デフォルト: {config.META_COLLECT_MATCHES_PER_PLAYER}）",
    )
    parser.add_argument(
        "--start-time",
        type=int,
        default=None,
        metavar="EPOCH_SEC",
        help=(
            "試合取得の開始時刻（Unixエポック秒）。"
            "パッチ適用日時を渡すと前パッチの試合を除外できる。"
            "例: 1712880000（2024-04-12 00:00 UTC）"
        ),
    )
    parser.add_argument(
        "--end-time",
        type=int,
        default=None,
        metavar="EPOCH_SEC",
        help=(
            "試合取得の終了時刻（Unixエポック秒）。"
            "省略時は現在まで取得する。"
        ),
    )
    parser.add_argument(
        "--no-grandmaster",
        action="store_true",
        default=False,
        help="Grandmaster 帯のプレイヤーを収集対象から除外する（Challenger のみ）",
    )
    args = parser.parse_args()

    # ---- API キーチェック -------------------------------------------------------
    if not config.RIOT_API_KEY:
        print("RIOT_API_KEY が .env に設定されていません。処理を中止します。")
        print("（アプリ本体は data/patch_xx/meta_snapshot.json のサンプルデータで動作します）")
        return

    # ---- パッチ決定 -------------------------------------------------------------
    patch = args.patch or meta_service.get_current_patch()

    # ---- Data Dragon バージョン表示（デバッグ用） --------------------------------
    try:
        ddragon_ver = get_latest_ddragon_version()
        logger.info("Data Dragon バージョン: %s（ロケール: %s）", ddragon_ver, config.DDRAGON_LOCALE)
    except Exception as exc:
        logger.warning("Data Dragon バージョン取得に失敗しました: %s", exc)

    # ---- 収集パラメータのサマリ表示 ---------------------------------------------
    logger.info("パッチ %s のメタ統計を収集します", patch)
    if args.start_time:
        logger.info("  startTime : %d（エポック秒）", args.start_time)
    if args.end_time:
        logger.info("  endTime   : %d（エポック秒）", args.end_time)
    logger.info(
        "  上位プレイヤー数: %d、1人あたり試合数: %d、Grandmaster含む: %s",
        args.top_n or config.META_COLLECT_TOP_N,
        args.matches_per_player or config.META_COLLECT_MATCHES_PER_PLAYER,
        not args.no_grandmaster,
    )

    # ---- データ収集 -------------------------------------------------------------
    try:
        raw_records = match_collector.collect_raw_matches(
            top_n=args.top_n,
            matches_per_player=args.matches_per_player,
            start_time=args.start_time,
            end_time=args.end_time,
            include_grandmaster=not args.no_grandmaster,
        )
    except RiotAPIError as exc:
        print(f"Riot APIからのデータ収集に失敗しました: {exc}")
        print("（アプリ本体は meta_snapshot.json のサンプルデータで動作を継続します）")
        return

    if not raw_records:
        print(
            "収集できたデータが0件でした。集計をスキップします。\n"
            "ヒント: --start-time / --end-time が厳しすぎるか、"
            "RIOT_API_KEY の権限を確認してください。"
        )
        return

    logger.info("%d件のユニット単位レコードを収集しました。集計中...", len(raw_records))

    # ---- 集計 & 保存 ------------------------------------------------------------
    dataset = build_meta_dataset(raw_records, patch)

    patch_dir = Path(config.DATA_DIR) / f"patch_{patch}"
    patch_dir.mkdir(parents=True, exist_ok=True)
    cache_path = patch_dir / "meta_cache.json"
    cache_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    n_champions = len(dataset["champion_item_builds"])
    n_comps = len(dataset["comp_recommendations"])
    print(f"完了しました: {cache_path}")
    print(f"  - 信頼できる統計が得られたチャンピオン数: {n_champions}")
    print(f"  - 構成レコメンド数: {n_comps}")


if __name__ == "__main__":
    main()
