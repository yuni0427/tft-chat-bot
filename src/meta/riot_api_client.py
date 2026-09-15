"""
Riot Games 公式APIの薄いクライアント。
地域ルーティング・レート制限（既定: 個人用キーの 20req/秒, 100req/2分）への
簡易対応を行う。APIキー未設定やリクエスト失敗時は RiotAPIError を上げ、
呼び出し側（match_collector / meta_service）でフォールバック処理を行う想定。

ルーティング規則:
  Platform Routing  (jp1.api.riotgames.com) : tft-league-v1, tft-summoner-v1
  Regional Routing  (asia.api.riotgames.com) : tft-match-v1, account-v1
"""
import threading
import time
from collections import deque
from typing import Optional

import requests

import config


class RiotAPIError(RuntimeError):
    pass


class _RateLimiter:
    """個人用APIキーの既定レート制限に対する簡易トークンバケット。

    limits: [(期間内の最大リクエスト数, 期間[秒]), ...]
    例: [(20, 1.0), (100, 120.0)]  → 20req/秒 かつ 100req/2分
    """

    def __init__(self, limits: list[tuple[int, float]]):
        self._limits = limits
        self._history = [deque() for _ in limits]
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_time = 0.0
            for (max_count, period), history in zip(self._limits, self._history):
                # 期間外のエントリを破棄
                while history and now - history[0] > period:
                    history.popleft()
                if len(history) >= max_count:
                    wait_time = max(wait_time, period - (now - history[0]) + 0.05)
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.monotonic()
            for history in self._history:
                history.append(now)


_rate_limiter = _RateLimiter([(20, 1.0), (100, 120.0)])


def _request(url: str, params: dict | None = None, max_retries: int = 3) -> dict | list:
    """レートリミット・リトライ付き GET リクエスト共通処理。"""
    if not config.RIOT_API_KEY:
        raise RiotAPIError("RIOT_API_KEY が設定されていません。")

    headers = {"X-Riot-Token": config.RIOT_API_KEY}
    last_error: Exception | None = None

    for attempt in range(max_retries):
        _rate_limiter.acquire()
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
            continue

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            # Retry-After ヘッダが無い場合は 2 秒待機
            retry_after = float(resp.headers.get("Retry-After", "2"))
            time.sleep(retry_after)
            continue
        if resp.status_code in (502, 503, 504):
            time.sleep(1.0 * (attempt + 1))
            continue

        raise RiotAPIError(
            f"Riot API エラー: {resp.status_code} {resp.text[:200]} ({url})"
        )

    raise RiotAPIError(
        f"Riot API へのリクエストが繰り返し失敗しました: {url} ({last_error})"
    )


# --------------------------------------------------------------------------
# tft-league-v1 (Platform Routing)
# --------------------------------------------------------------------------

def get_challenger_league() -> dict:
    """チャレンジャー帯の TFT ランクリストを取得する。

    レスポンス: {"tier": "CHALLENGER", "entries": [{"summonerId": ..., "puuid": ..., ...}, ...]}
    """
    url = (
        f"https://{config.RIOT_PLATFORM_REGION}.api.riotgames.com"
        "/tft/league/v1/challenger"
    )
    return _request(url)  # type: ignore[return-value]


def get_grandmaster_league() -> dict:
    """グランドマスター帯の TFT ランクリストを取得する。

    レスポンス形式は get_challenger_league() と同一。
    """
    url = (
        f"https://{config.RIOT_PLATFORM_REGION}.api.riotgames.com"
        "/tft/league/v1/grandmaster"
    )
    return _request(url)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# tft-summoner-v1 (Platform Routing)
# --------------------------------------------------------------------------

def get_summoner_by_id(summoner_id: str) -> dict:
    """summonerId から PUUID を含むサモナー情報を取得する。

    entries[].puuid が存在しない古いレスポンスへのフォールバック用。
    レスポンス: {"id": ..., "puuid": ..., "name": ..., ...}
    """
    url = (
        f"https://{config.RIOT_PLATFORM_REGION}.api.riotgames.com"
        f"/tft/summoner/v1/summoners/{summoner_id}"
    )
    return _request(url)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# tft-match-v1 (Regional Routing)
# --------------------------------------------------------------------------

def get_match_ids_by_puuid(
    puuid: str,
    count: int = 5,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> list[str]:
    """プレイヤーの直近試合 ID リストを取得する。

    Args:
        puuid:      対象プレイヤーの PUUID
        count:      取得する試合数（最大 200）
        start_time: 取得開始時刻（エポック秒）。パッチ開始日時を渡すことで
                    前パッチの試合を除外できる。
        end_time:   取得終了時刻（エポック秒）。省略時は現在まで。

    Returns:
        Match ID の文字列リスト（例: ["JP1_1234567890", ...]）
    """
    url = (
        f"https://{config.RIOT_REGIONAL_ROUTE}.api.riotgames.com"
        f"/tft/match/v1/matches/by-puuid/{puuid}/ids"
    )
    params: dict = {"count": count}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time

    return _request(url, params=params)  # type: ignore[return-value]


def get_match_detail(match_id: str) -> dict:
    """試合詳細（参加者8名の構成・アイテム・順位）を取得する。

    主要取得フィールド:
        info.participants[].placement       最終順位（1〜8）
        info.participants[].units[]         投入ユニット配列
          .character_id                     ユニット内部ID（例: TFT14_Ashe）
          .tier                             星の数（1〜3）
          .itemNames                        装備アイテム名リスト
        info.participants[].traits[]        発動シナジー配列
          .name                             シナジー内部ID
          .num_units                        所持ユニット数
          .tier_current                     発動ティア
    """
    url = (
        f"https://{config.RIOT_REGIONAL_ROUTE}.api.riotgames.com"
        f"/tft/match/v1/matches/{match_id}"
    )
    return _request(url)  # type: ignore[return-value]
