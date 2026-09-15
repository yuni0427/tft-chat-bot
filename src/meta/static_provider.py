"""
静的データの提供モジュール。

2つの役割を持つ:
  1. meta_snapshot.json の読み込み（質的知識ベース）
  2. Data Dragon CDN からの TFT 静的マスタデータ取得と、
     内部ID → 日本語表示名の変換テーブル構築

Data Dragon の取得結果はプロセスライフサイクル中にメモリキャッシュし、
同一バージョンに対するリクエストは繰り返し行わない。
"""
import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Data Dragon クライアント
# --------------------------------------------------------------------------

_DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
_VERSIONS_URL = f"{_DDRAGON_BASE}/api/versions.json"
_DEFAULT_LOCALE = "ja_JP"
_REQUEST_TIMEOUT = 10  # 秒


def _get(url: str) -> dict | list:
    """シンプルな HTTP GET ラッパー。失敗時は RuntimeError を送出する。"""
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Data Dragon へのリクエストが失敗しました: {url} ({exc})") from exc


@lru_cache(maxsize=1)
def get_latest_ddragon_version() -> str:
    """Data Dragon の最新バージョン文字列を取得する（例: '15.8.1'）。

    lru_cache により同一プロセス内では1度だけ取得する。
    """
    versions: list = _get(_VERSIONS_URL)  # type: ignore[assignment]
    if not versions:
        raise RuntimeError("Data Dragon バージョンリストが空でした。")
    return versions[0]


def _build_cdn_url(version: str, locale: str, resource: str) -> str:
    """CDN の URL を組み立てる。

    例: https://ddragon.leagueoflegends.com/cdn/15.8.1/data/ja_JP/tft-champion.json
    """
    return f"{_DDRAGON_BASE}/cdn/{version}/data/{locale}/{resource}"


def _fetch_tft_data(resource: str, version: Optional[str] = None, locale: str = _DEFAULT_LOCALE) -> dict:
    """指定リソースの TFT 静的データを取得して data フィールドを返す。"""
    version = version or get_latest_ddragon_version()
    url = _build_cdn_url(version, locale, resource)
    payload: dict = _get(url)  # type: ignore[assignment]
    # Data Dragon レスポンスは {"type":..., "version":..., "data": {...}} の形式
    return payload.get("data", payload)


# --------------------------------------------------------------------------
# 変換テーブル構築
# --------------------------------------------------------------------------

class DataDragonNameTable:
    """内部ID → 日本語表示名のルックアップテーブル。

    使用例:
        table = DataDragonNameTable.load()
        table.champion("TFT14_Ashe")      # → "アッシュ"
        table.item("TFT_Item_Rabadons...")  # → "ラバドン デスキャップ"
        table.trait("Set14_Sorcerer")     # → "ソーサラー"
        table.is_special_item("TFT_Item_Crest_...")  # → True（紋章/神器系）
    """

    def __init__(
        self,
        champion_map: dict[str, str],
        item_map: dict[str, str],
        trait_map: dict[str, str],
        special_item_ids: set[str],
    ) -> None:
        self._champion_map = champion_map
        self._item_map = item_map
        self._trait_map = trait_map
        self._special_item_ids = special_item_ids

    @classmethod
    def load(cls, version: Optional[str] = None, locale: str = _DEFAULT_LOCALE) -> "DataDragonNameTable":
        """Data Dragon から最新データを取得してテーブルを構築する。

        失敗時は空テーブルを返し、呼び出し元が内部IDのままフォールバックできるようにする。
        """
        try:
            return cls._build(version, locale)
        except Exception as exc:
            logger.warning("Data Dragon の取得に失敗しました（内部IDのままフォールバック）: %s", exc)
            return cls({}, {}, {}, set())

    @classmethod
    def _build(cls, version: Optional[str], locale: str) -> "DataDragonNameTable":
        version = version or get_latest_ddragon_version()

        # チャンピオン: key は "TFT14_Ashe" 形式の id フィールド
        champion_data = _fetch_tft_data("tft-champion.json", version, locale)
        champion_map: dict[str, str] = {}
        for entry in champion_data.values():
            champ_id: str = entry.get("id", "")
            name: str = entry.get("name", "")
            if champ_id and name:
                champion_map[champ_id] = name
                # "_" 以降の末尾トークンでも引けるようにエイリアスを追加
                # （match_collector._clean_name が末尾トークンを返すため）
                short = champ_id.split("_")[-1]
                champion_map.setdefault(short, name)

        # アイテム: key は "TFT_Item_..." 形式
        item_data = _fetch_tft_data("tft-item.json", version, locale)
        item_map: dict[str, str] = {}
        special_item_ids: set[str] = set()
        for entry in item_data.values():
            item_id: str = entry.get("id", "")
            if not item_id:
                # Data Dragon のアイテムは key が id を兼ねる場合もある
                continue
            name_ja: str = entry.get("name", "")
            if item_id and name_ja:
                item_map[item_id] = name_ja
                short = item_id.split("_")[-1]
                item_map.setdefault(short, name_ja)

            # 特殊アイテム判定:
            #   - "Emblem"（紋章）または "Artifact"（神器/アーティファクト）を
            #     ID や effectsMap に含むものを特殊枠として分類する
            is_special = (
                "Emblem" in item_id
                or "Artifact" in item_id
                or "HeirloomEmblem" in item_id
            )
            if is_special:
                special_item_ids.add(item_id)
                if item_id.split("_")[-1]:
                    special_item_ids.add(item_id.split("_")[-1])

        # 特性: key は "Set14_Sorcerer" 等
        trait_data = _fetch_tft_data("tft-trait.json", version, locale)
        trait_map: dict[str, str] = {}
        for entry in trait_data.values():
            trait_id: str = entry.get("id", "")
            name_ja: str = entry.get("name", "")
            if trait_id and name_ja:
                trait_map[trait_id] = name_ja
                short = trait_id.split("_")[-1]
                trait_map.setdefault(short, name_ja)

        return cls(champion_map, item_map, trait_map, special_item_ids)

    # ------------------------------------------------------------------
    # ルックアップメソッド
    # ------------------------------------------------------------------

    def champion(self, raw_id: str) -> str:
        """内部チャンピオンIDを日本語表示名に変換する。未知の場合は末尾トークンを返す。"""
        if not raw_id:
            return raw_id
        return (
            self._champion_map.get(raw_id)
            or self._champion_map.get(raw_id.split("_")[-1])
            or raw_id.split("_")[-1]
        )

    def item(self, raw_id: str) -> str:
        """内部アイテムIDを日本語表示名に変換する。未知の場合は末尾トークンを返す。"""
        if not raw_id:
            return raw_id
        return (
            self._item_map.get(raw_id)
            or self._item_map.get(raw_id.split("_")[-1])
            or raw_id.split("_")[-1]
        )

    def trait(self, raw_id: str) -> str:
        """内部特性IDを日本語表示名に変換する。未知の場合は末尾トークンを返す。"""
        if not raw_id:
            return raw_id
        return (
            self._trait_map.get(raw_id)
            or self._trait_map.get(raw_id.split("_")[-1])
            or raw_id.split("_")[-1]
        )

    def is_special_item(self, raw_id: str) -> bool:
        """内部IDがアーティファクト/紋章などの特殊アイテムかどうかを返す。"""
        if not raw_id:
            return False
        return (
            raw_id in self._special_item_ids
            or raw_id.split("_")[-1] in self._special_item_ids
        )

    @property
    def is_empty(self) -> bool:
        """テーブルが空（Data Dragon 未取得のフォールバック状態）かどうか。"""
        return not self._champion_map and not self._item_map


# --------------------------------------------------------------------------
# プロセスレベルのシングルトンキャッシュ
# --------------------------------------------------------------------------

_name_table_cache: Optional[DataDragonNameTable] = None
_name_table_version: Optional[str] = None


def get_name_table(version: Optional[str] = None, locale: str = _DEFAULT_LOCALE) -> DataDragonNameTable:
    """DataDragonNameTable のシングルトンを返す。

    version が変わった場合（パッチ更新時）のみ再取得する。
    """
    global _name_table_cache, _name_table_version
    target_version = version or get_latest_ddragon_version.__wrapped__()  # type: ignore[attr-defined]

    # バージョン未取得の場合は lru_cache 経由で取得
    try:
        target_version = version or get_latest_ddragon_version()
    except Exception:
        target_version = None

    if _name_table_cache is None or _name_table_version != target_version:
        _name_table_cache = DataDragonNameTable.load(version=target_version, locale=locale)
        _name_table_version = target_version

    return _name_table_cache


def invalidate_name_table_cache() -> None:
    """バージョン更新時などに手動でキャッシュを破棄する。"""
    global _name_table_cache, _name_table_version
    get_latest_ddragon_version.cache_clear()  # type: ignore[attr-defined]
    _name_table_cache = None
    _name_table_version = None


# --------------------------------------------------------------------------
# meta_snapshot.json ローダー（既存機能）
# --------------------------------------------------------------------------

def load_snapshot(path) -> dict:
    """静的サンプルデータ(meta_snapshot.json)を読み込む。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"メタデータファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
