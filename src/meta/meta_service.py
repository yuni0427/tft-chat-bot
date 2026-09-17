"""
メタデータ提供の統合レイヤー。

- パッチ別ディレクトリ(data/patch_xx/)を参照し、data/current_patch.txt
  （またはStreamlitサイドバーでの選択）に応じて参照先を動的に切り替える。
- Riot API集計結果(meta_cache.json)または静的サンプル(meta_snapshot.json)の
  いずれか一方しか存在しない場合でも自動フォールバックして正常動作する。
- 両方存在する場合は、統計（量的データ）と質的知識（静的データ）をマージして提供する。
"""
import json
import re
from pathlib import Path

import config
from src.meta import static_provider


def _parse_patch_version(patch_str: str) -> tuple:
    """
    パッチ文字列をタプルに変換して比較する。
    順序: 18.2 < 18.2b < 18.2c < 18.3
    """
    clean = patch_str.strip().lstrip("\ufeff")
    m = re.match(r"^(\d+)\.(\d+)([a-zA-Z]*)$", clean)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2))
        sub = m.group(3).lower()
        return (major, minor, sub)
    
    # 16.18.2b 等の形式に対するフォールバック
    parts = [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", clean)]
    return tuple(parts)


def get_latest_available_patch() -> str:
    """data/ 内の patch_* から最も新しいバージョンを自動選定"""
    patches = list_available_patches()
    if not patches:
        return config.DEFAULT_PATCH
    return max(patches, key=_parse_patch_version)


def get_current_patch_info() -> tuple[str, int | None]:
    """
    current_patch.txt から (パッチ名, 開始時刻エポック秒) を取得。
    未指定・空・ファイル無しの場合は自動で最新パッチへフォールバック。
    """
    p = Path(config.CURRENT_PATCH_FILE)
    if p.exists():
        # BOM (\ufeff) を除去して安全にパース
        text = p.read_text(encoding="utf-8").strip().lstrip("\ufeff")
        if text:
            parts = [x.strip() for x in text.split(",")]
            patch = parts[0]
            start_time = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            return patch, start_time

    # 何も書かれていない場合は存在する最新パッチを採用
    return get_latest_available_patch(), None


def get_current_patch() -> str:
    """パッチ名文字列のみを返す（既存の呼び出しとの完全互換）"""
    patch, _ = get_current_patch_info()
    return patch


def set_current_patch(patch: str) -> None:
    p = Path(config.CURRENT_PATCH_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(patch, encoding="utf-8")


def set_current_patch(patch: str) -> None:
    p = Path(config.CURRENT_PATCH_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(patch, encoding="utf-8")


def list_available_patches() -> list[str]:
    data_dir = Path(config.DATA_DIR)
    if not data_dir.exists():
        return []
    return sorted(d.name.replace("patch_", "") for d in data_dir.glob("patch_*") if d.is_dir())


def _patch_dir(patch: str) -> Path:
    return Path(config.DATA_DIR) / f"patch_{patch}"


def load_meta_data(patch: str | None = None) -> dict:
    """静的データ（質的知識）とRiot API集計キャッシュ（量的統計）を柔軟に読み込んで返す。
    どちらか片方しか存在しない場合でもエラーにせずフォールバックする。
    """
    patch = patch or get_current_patch()
    d = _patch_dir(patch)

    snapshot_path = d / "meta_snapshot.json"
    cache_path = d / "meta_cache.json"

    # 1. どちらも存在しない場合はエラー
    if not snapshot_path.exists() and not cache_path.exists():
        raise FileNotFoundError(
            f"パッチ {patch} のデータが見つかりません（{d} に meta_cache.json または meta_snapshot.json が必要です）。"
            " data/current_patch.txt またはサイドバーの選択を確認してください。"
        )

    # 2. snapshot がなく cache のみ存在する場合（新パッチAPI収集直後）
    if not snapshot_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"キャッシュファイル {cache_path} の読み込みに失敗しました: {e}")

    # 3. snapshot の読み込み
    static_data = static_provider.load_snapshot(snapshot_path)

    # 4. cache がなく snapshot のみ存在する場合（静的データのみの環境）
    if not cache_path.exists():
        return static_data

    # 5. 両方存在する場合はマージ
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        return _merge_meta_data(static_data, cache_data)
    except Exception:
        # キャッシュが破損している場合は静的データのみで継続
        return static_data


def _merge_meta_data(static_data: dict, cache_data: dict) -> dict:
    merged = {
        "patch": cache_data.get("patch", static_data.get("patch")),
        "updated_at": cache_data.get("updated_at", static_data.get("updated_at")),
        "source": "riot_api_aggregate+static_supplement",
        "champion_item_builds": {},
        "comp_recommendations": [],
    }

    static_builds = static_data.get("champion_item_builds", {})
    cache_builds = cache_data.get("champion_item_builds", {})
    for champ in set(static_builds) | set(cache_builds):
        cached = cache_builds.get(champ)
        curated = static_builds.get(champ)
        if cached and curated:
            merged_build = dict(cached)
            if not merged_build.get("anti_synergy_warnings"):
                merged_build["anti_synergy_warnings"] = curated.get("anti_synergy_warnings", [])
            if not merged_build.get("debuff_roles"):
                merged_build["debuff_roles"] = curated.get("debuff_roles", [])
            if not merged_build.get("core_items"):
                merged_build["core_items"] = curated.get("core_items", [])
            merged["champion_item_builds"][champ] = merged_build
        else:
            merged["champion_item_builds"][champ] = cached or curated

    static_comps = {c["comp_name"]: c for c in static_data.get("comp_recommendations", [])}
    cache_comps = {c["comp_name"]: c for c in cache_data.get("comp_recommendations", [])}
    for name in set(static_comps) | set(cache_comps):
        cached = cache_comps.get(name)
        curated = static_comps.get(name)
        if cached and curated:
            merged_comp = dict(cached)
            for field in ("emblem_holder", "item_synergy_reason", "trigger_items", "trigger_emblems"):
                if not merged_comp.get(field):
                    merged_comp[field] = curated.get(field)
            merged["comp_recommendations"].append(merged_comp)
        else:
            merged["comp_recommendations"].append(cached or curated)

    return merged


def get_item_build(champion: str, patch: str | None = None) -> dict | None:
    data = load_meta_data(patch)
    return data.get("champion_item_builds", {}).get(champion)


def list_champions_with_build(patch: str | None = None) -> list[str]:
    data = load_meta_data(patch)
    return sorted(data.get("champion_item_builds", {}).keys())


def get_comp_recommendations(patch: str | None = None) -> list[dict]:
    data = load_meta_data(patch)
    return data.get("comp_recommendations", [])


def search_comps_by_assets(
    held_items: list[str], held_emblems: list[str], patch: str | None = None
) -> list[dict]:
    """手持ちのアイテム/紋章から、それらをトリガーとする構成を逆引きする。"""
    comps = get_comp_recommendations(patch)
    held = set(held_items) | set(held_emblems)
    matches = []
    for c in comps:
        triggers = set(c.get("trigger_items") or []) | set(c.get("trigger_emblems") or [])
        if triggers & held:
            matches.append(c)
    tier_order = {"S": 0, "A": 1, "B": 2}
    matches.sort(key=lambda c: (tier_order.get(c.get("tier", "B"), 9), c.get("avg_place", 8.0)))
    return matches


def get_one_example_snippet(patch: str | None = None) -> str:
    """理論回答に添える「現パッチ例」の短い一文を返す。"""
    try:
        comps = get_comp_recommendations(patch)
    except FileNotFoundError:
        return ""
    if not comps:
        return ""
    top = sorted(comps, key=lambda c: c.get("avg_place", 8.0))[0]
    top4_rate_pct = int(top.get("top4_rate", 0) * 100)
    return (
        f"{top.get('comp_name', '注目の構成')}（Tier{top.get('tier', 'A')}、"
        f"平均順位{top.get('avg_place', '-')}、Top4率{top4_rate_pct}%）"
    )