"""
match_collector.py が収集した生データから、統計的信頼性フィルタを適用した
アイテムビルド・構成統計（meta_cache.json相当）を構築するモジュール。

適用するルール:
- 通常アイテムBiSは「試行回数が上位10%以内」かつ「最低100件以上」の
  母集団から選出する（上振れ・サンプル不足データの除外）。
- サンプル数に応じて信頼度ランク（HIGH/MEDIUM/LOW）を付与する。
- アーティファクト/紋章などの特殊アイテムは通常アイテムと母集団を分け、
  特殊枠数（1枠/2枠等）が一致するグループ内で集計する。
- 通常BiSを明確に上回る特殊シナジーがある場合のみ special_synergy_builds として紹介する。

なお、アンチシナジー警告・デバフ担当・構成の紋章推奨先などの「質的知識」は
統計から自動導出できないため、このモジュールでは空のまま返す。
これらは meta_service.py 側で静的知識データ(meta_snapshot.json)と
マージして補完する。
"""
from datetime import datetime, timezone

import config
from src.meta.static_provider import get_name_table

# テーブルを一度だけ取得してキャッシュ
_NAME_TABLE = None


def _get_cached_name_table():
    global _NAME_TABLE
    if _NAME_TABLE is None:
        _NAME_TABLE = get_name_table()
    return _NAME_TABLE


def is_special_item(name: str) -> bool:
    """アーティファクト/紋章など特殊アイテムかどうかを判定する。"""
    name_table = _get_cached_name_table()
    if not name_table.is_empty:
        return name_table.is_special_item(name)
    # フォールバック: 英語内部IDキーワードによる判定
    return any(keyword in name for keyword in config.SPECIAL_ITEM_KEYWORDS)


def confidence_level(sample_size: int) -> str | None:
    """サンプル数に応じた信頼度ランクを返す。最低件数未満は None（採用不可）。"""
    if sample_size >= config.CONFIDENCE_HIGH_MIN:
        return "HIGH"
    if sample_size >= config.CONFIDENCE_MEDIUM_MIN:
        return "MEDIUM"
    if sample_size >= config.CONFIDENCE_LOW_MIN:
        return "LOW"
    return None


def filter_reliable_item_sets(
    item_sets: list[dict],
    min_samples: int | None = None,
    top_percentile: float | None = None,
) -> list[dict]:
    """試行回数が「上位top_percentile以内」かつ「min_samples以上」のセットのみ残す。"""
    min_samples = config.MIN_SAMPLE_SIZE if min_samples is None else min_samples
    top_percentile = (
        config.TOP_SAMPLE_PERCENTILE if top_percentile is None else top_percentile
    )

    eligible = [s for s in item_sets if s["sample_size"] >= min_samples]
    if not eligible:
        return []

    sizes = sorted((s["sample_size"] for s in eligible), reverse=True)
    cutoff_index = max(0, int(len(sizes) * top_percentile) - 1)
    threshold = sizes[cutoff_index]
    return [s for s in eligible if s["sample_size"] >= threshold]


def _to_item_set_stats(items: tuple, placements: list[int]) -> dict:
    n = len(placements)
    avg_place = sum(placements) / n
    top4_rate = sum(1 for p in placements if p <= 4) / n
    return {
        "items": list(items),
        "sample_size": n,
        "avg_place": round(avg_place, 2),
        "win_rate": round(top4_rate, 2),  # TFT慣習に合わせ、Top4率をwin_rateとして扱う
    }


def _group_item_sets(records: list[dict]) -> tuple[list[dict], dict[int, list[dict]]]:
    """あるチャンピオンのレコード群を、通常アイテムセットと特殊アイテムセット
    （特殊枠数ごと）に分けて集計する。"""
    normal_groups: dict[tuple, list[int]] = {}
    special_groups: dict[tuple[int, tuple], list[int]] = {}

    for r in records:
        items = tuple(sorted(set(r["items"])))
        if not items:
            continue
        special_count = sum(1 for i in items if is_special_item(i))
        placement = r["placement"]
        if special_count == 0:
            normal_groups.setdefault(items, []).append(placement)
        else:
            special_groups.setdefault((special_count, items), []).append(placement)

    normal_sets = [
        _to_item_set_stats(items, placements) for items, placements in normal_groups.items()
    ]

    special_by_slot: dict[int, list[dict]] = {}
    for (special_count, items), placements in special_groups.items():
        stats = _to_item_set_stats(items, placements)
        special_by_slot.setdefault(special_count, []).append(stats)

    return normal_sets, special_by_slot


def _infer_core_items(bis: dict, reliable_normal: list[dict]) -> list[dict]:
    """信頼できる上位ビルドの大多数（試行回数加重で80%以上）に共通するアイテムをコア扱いにする。"""
    if not reliable_normal:
        return []
    total_weight = sum(s["sample_size"] for s in reliable_normal)
    if total_weight == 0:
        return []

    presence: dict[str, int] = {}
    for s in reliable_normal:
        for item in s["items"]:
            presence[item] = presence.get(item, 0) + s["sample_size"]

    core = []
    for item in bis["items"]:
        ratio = presence.get(item, 0) / total_weight
        if ratio >= 0.8:
            core.append(
                {
                    "name": item,
                    "reason": "信頼できる上位ビルドの大多数で共通して採用されているコアアイテム",
                }
            )
    return core


def _aggregate_item_builds(raw_records: list[dict]) -> dict:
    by_champion: dict[str, list[dict]] = {}
    for r in raw_records:
        by_champion.setdefault(r["champion"], []).append(r)

    result: dict[str, dict] = {}
    for champion, records in by_champion.items():
        normal_sets, special_by_slot = _group_item_sets(records)
        reliable_normal = filter_reliable_item_sets(normal_sets)
        if not reliable_normal:
            continue  # 信頼できるデータが無いチャンピオンはスキップ（静的データにフォールバック）

        reliable_normal.sort(key=lambda s: s["avg_place"])
        bis_raw = reliable_normal[0]
        bis = {
            **bis_raw,
            "confidence_level": confidence_level(bis_raw["sample_size"]),
            "special_note": None,
        }

        substitutes = []
        for s in reliable_normal[1:]:
            diff_items = [item for item in s["items"] if item not in bis["items"]]
            representative_item = diff_items[0] if diff_items else (s["items"][0] if s["items"] else "")
            substitutes.append(
                {
                    "item": representative_item,
                    "delta_avg_place": round(s["avg_place"] - bis["avg_place"], 2),
                    "condition": None,
                }
            )

        special_builds = []
        for slot_count, sets in special_by_slot.items():
            for s in sets:
                if s["sample_size"] < config.MIN_SAMPLE_SIZE:
                    continue
                if s["avg_place"] <= bis["avg_place"] - config.SPECIAL_SYNERGY_MARGIN:
                    special_builds.append(
                        {
                            **s,
                            "confidence_level": confidence_level(s["sample_size"]),
                            "special_note": f"特殊アイテム{slot_count}枠構成。通常BiSより平均順位が改善",
                        }
                    )
        special_builds.sort(key=lambda s: s["avg_place"])

        result[champion] = {
            "champion": champion,
            "core_items": _infer_core_items(bis, reliable_normal),
            "bis_standard_build": bis,
            "substitutes": substitutes,
            "special_synergy_builds": special_builds,
            # 統計から導出できない質的知識。meta_service.py で静的データから補完される。
            "anti_synergy_warnings": [],
            "debuff_roles": [],
        }
    return result


def _place_to_tier(avg_place: float) -> str:
    if avg_place <= 4.0:
        return "S"
    if avg_place <= 4.4:
        return "A"
    return "B"


def _aggregate_comp_recommendations(raw_records: list[dict]) -> list[dict]:
    # ユニット単位にフラット化されたraw_recordsから、試合単位のレコードへ復元する
    seen: set[tuple] = set()
    match_level_records = []
    for r in raw_records:
        key = (r["comp_name"], r["placement"], tuple(sorted(r["units"])))
        if key in seen:
            continue
        seen.add(key)
        match_level_records.append(r)

    by_comp: dict[str, list[dict]] = {}
    for r in match_level_records:
        by_comp.setdefault(r["comp_name"], []).append(r)

    recommendations = []
    for comp_name, records in by_comp.items():
        n = len(records)
        if n < config.MIN_SAMPLE_SIZE:
            continue
        placements = [r["placement"] for r in records]
        avg_place = round(sum(placements) / n, 2)
        top4_rate = round(sum(1 for p in placements if p <= 4) / n, 2)

        unit_counts: dict[str, int] = {}
        for r in records:
            for u in r["units"]:
                unit_counts[u] = unit_counts.get(u, 0) + 1
        key_units = [
            u for u, _ in sorted(unit_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]

        recommendations.append(
            {
                "comp_name": comp_name,
                "tier": _place_to_tier(avg_place),
                "avg_place": avg_place,
                "top4_rate": top4_rate,
                "sample_size": n,
                "confidence_level": confidence_level(n),
                "emblem_holder": None,
                "key_units": key_units,
                "item_synergy_reason": "統計集計によるTop4率・平均順位に基づく自動生成の推薦です。",
                "trigger_items": [],
                "trigger_emblems": [],
            }
        )
    recommendations.sort(key=lambda c: c["avg_place"])
    return recommendations


def build_meta_dataset(raw_records: list[dict], patch: str) -> dict:
    """match_collector.collect_raw_matches() の出力から meta_cache.json 相当のdictを構築する。"""
    return {
        "patch": patch,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "riot_api_aggregate",
        "champion_item_builds": _aggregate_item_builds(raw_records),
        "comp_recommendations": _aggregate_comp_recommendations(raw_records),
    }
