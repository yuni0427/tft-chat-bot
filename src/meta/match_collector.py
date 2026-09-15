"""
Riot APIから上位プレイヤーの直近試合を収集し、集計(aggregator.py)に必要な
生データ（チャンピオン別アイテム構成・順位、構成トレイト・順位）に整形するモジュール。

変更履歴:
  - startTime/endTime によるパッチ絞り込みに対応
  - Challenger entries に puuid が無い場合に tft-summoner-v1 経由で取得する
    PUUID フォールバックを追加
  - Grandmaster 帯プレイヤーの収集に対応（collect_raw_matches の include_grandmaster 引数）
  - Data Dragon の変換テーブルを利用して内部IDを日本語表示名に変換する処理を追加
    （取得失敗時は従来の末尾トークンにフォールバック）

Riot API未設定・取得失敗時はここで RiotAPIError が伝播するため、
呼び出し側（scripts/build_meta_stats.py, meta_service.py）でフォールバックすること。
"""
import logging
from typing import Optional

import config
from src.meta import riot_api_client as riot
from src.meta.static_provider import get_name_table

logger = logging.getLogger(__name__)


def collect_raw_matches(
    top_n: int | None = None,
    matches_per_player: int | None = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    include_grandmaster: bool = True,
) -> list[dict]:
    """上位プレイヤーの直近試合の参加者情報を、ユニット単位にフラット化して返す。

    Args:
        top_n:               収集する上位プレイヤー数（Challenger 帯から優先取得）。
                             include_grandmaster=True の場合は不足分を Grandmaster 帯で補う。
        matches_per_player:  1プレイヤーあたりの収集試合数。
        start_time:          試合取得の開始時刻（エポック秒）。
                             パッチ適用日時を渡すことで前パッチの試合を除外できる。
        end_time:            試合取得の終了時刻（エポック秒）。省略時は現在まで。
        include_grandmaster: True の場合、Challenger だけで top_n に達しないときに
                             Grandmaster 帯のエントリで補完する。

    戻り値の各要素:
        {
            "champion": str,       # チャンピオン日本語名（Data Dragon 未取得時は内部ID末尾トークン）
            "items": list[str],    # 保有アイテム日本語名リスト
            "placement": int,      # その試合の順位（1-8）
            "comp_name": str,      # 主要トレイトから推定した構成名
            "units": list[str],    # その試合で使用された全ユニット名
        }
    """
    top_n = top_n or config.META_COLLECT_TOP_N
    matches_per_player = matches_per_player or config.META_COLLECT_MATCHES_PER_PLAYER

    # Data Dragon 変換テーブルを事前にロード（失敗時は空テーブルで内部IDフォールバック）
    name_table = get_name_table()
    if name_table.is_empty:
        logger.warning(
            "Data Dragon の変換テーブルが空です。チャンピオン名・アイテム名は"
            "内部ID末尾トークンのまま集計されます。"
        )

    # ---- 上位プレイヤーエントリの収集 ----------------------------------------
    entries = _collect_entries(top_n, include_grandmaster)

    # ---- 試合データの収集 -------------------------------------------------------
    seen_match_ids: set[str] = set()
    raw_records: list[dict] = []

    for entry in entries:
        puuid = _resolve_puuid(entry)
        if not puuid:
            logger.debug("PUUID を解決できなかったエントリをスキップします: %s", entry)
            continue

        try:
            match_ids = riot.get_match_ids_by_puuid(
                puuid,
                count=matches_per_player,
                start_time=start_time,
                end_time=end_time,
            )
        except riot.RiotAPIError as exc:
            logger.warning("Match ID 取得に失敗しました（puuid=%s）: %s", puuid[:8], exc)
            continue

        for match_id in match_ids:
            if match_id in seen_match_ids:
                # 同じ試合に複数の上位プレイヤーが同卓している場合の重複除外
                continue
            seen_match_ids.add(match_id)

            try:
                detail = riot.get_match_detail(match_id)
            except riot.RiotAPIError as exc:
                logger.warning("試合詳細取得に失敗しました（match_id=%s）: %s", match_id, exc)
                continue

            for participant in detail.get("info", {}).get("participants", []):
                records = _parse_participant(participant, name_table)
                raw_records.extend(records)

    logger.info(
        "収集完了: match_ids=%d件, unit_records=%d件",
        len(seen_match_ids),
        len(raw_records),
    )
    return raw_records


# --------------------------------------------------------------------------
# 内部ヘルパー
# --------------------------------------------------------------------------

def _collect_entries(top_n: int, include_grandmaster: bool) -> list[dict]:
    """Challenger（＋必要なら Grandmaster）から top_n 件のエントリを返す。

    各エントリは {"puuid": ..., "summonerId": ...} を含む dict。
    """
    league = riot.get_challenger_league()
    entries: list[dict] = league.get("entries", [])

    if include_grandmaster and len(entries) < top_n:
        try:
            gm_league = riot.get_grandmaster_league()
            entries += gm_league.get("entries", [])
        except riot.RiotAPIError as exc:
            logger.warning("Grandmaster リスト取得に失敗しました: %s", exc)

    return entries[:top_n]


def _resolve_puuid(entry: dict) -> str | None:
    """エントリから PUUID を取得する。

    tft-league-v1 のレスポンスには puuid が含まれている場合と含まれていない場合がある。
    含まれていない（または空文字の）場合は tft-summoner-v1 経由で取得を試みる。
    """
    puuid: str | None = entry.get("puuid") or None
    if puuid:
        return puuid

    summoner_id: str | None = entry.get("summonerId") or None
    if not summoner_id:
        return None

    try:
        summoner = riot.get_summoner_by_id(summoner_id)
        return summoner.get("puuid") or None
    except riot.RiotAPIError as exc:
        logger.warning(
            "tft-summoner-v1 での PUUID 取得に失敗しました（summonerId=%s）: %s",
            summoner_id,
            exc,
        )
        return None


def _parse_participant(participant: dict, name_table) -> list[dict]:
    """参加者1名分のデータをユニット単位レコードのリストに変換する。"""
    placement: int = participant.get("placement", 0)
    units: list[dict] = participant.get("units", [])
    traits: list[dict] = participant.get("traits", [])

    comp_name = _infer_comp_name(traits, name_table)
    unit_names = [
        name_table.champion(u.get("character_id", "")) for u in units
        if u.get("character_id")
    ]

    records = []
    for unit in units:
        raw_char_id: str = unit.get("character_id", "")
        if not raw_char_id:
            continue

        champion = name_table.champion(raw_char_id)

        # itemNames（新しいAPI形式）と items（旧形式）の両方に対応
        raw_items: list[str] = unit.get("itemNames") or unit.get("items") or []
        items = [name_table.item(i) for i in raw_items if i]

        records.append(
            {
                "champion": champion,
                "items": items,
                "placement": placement,
                "comp_name": comp_name,
                "units": unit_names,
            }
        )

    return records


def _infer_comp_name(traits: list[dict], name_table) -> str:
    """発動トレイトから構成名を推定する。

    tier_current が高い上位2トレイトを日本語名で結合する。
    num_units も考慮し、同 tier_current の場合は num_units が多い方を優先する。
    """
    active_traits = [t for t in traits if t.get("tier_current", 0) > 0]
    active_traits.sort(
        key=lambda t: (t.get("tier_current", 0), t.get("num_units", 0)),
        reverse=True,
    )
    top = active_traits[:2]
    if not top:
        return "不明な構成"
    return "+".join(name_table.trait(t.get("name", "")) for t in top)
