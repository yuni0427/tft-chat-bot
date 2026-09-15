"""
アプリ全体の設定値を集約するモジュール。
.env および Streamlit Secrets を読み込み、各コンポーネントが共通で参照する定数を提供する。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# ローカル用の .env 読み込み
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def get_secret(key: str, default: str = "") -> str:
    """Streamlit Secrets -> 環境変数 (.env) -> デフォルト値 の順で設定値を取得する"""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# ==== LLM ====
LLM_PROVIDER = get_secret("LLM_PROVIDER", "gemini").lower()

OPENAI_API_KEY = get_secret("OPENAI_API_KEY", "")
OPENAI_MODEL = get_secret("OPENAI_MODEL", "gpt-4o-mini")

GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY", "")
GEMINI_MODEL = get_secret("GEMINI_MODEL", "gemini-2.0-flash")

# ==== Riot Games API ====
RIOT_API_KEY = get_secret("RIOT_API_KEY", "")

# デフォルトリージョン（単体実行用）
RIOT_PLATFORM_REGION = get_secret("RIOT_PLATFORM_REGION", "jp1")
RIOT_REGIONAL_ROUTE = get_secret("RIOT_REGIONAL_ROUTE", "asia")

# 収集パラメータ（各地域の上位N名 × 直近N試合）
META_COLLECT_TOP_N = int(get_secret("META_COLLECT_TOP_N", "20"))
META_COLLECT_MATCHES_PER_PLAYER = int(get_secret("META_COLLECT_MATCHES_PER_PLAYER", "5"))

# ==== グローバル収集（全16地域・チャレンジャー限定）の設定 ====
GLOBAL_REGIONS = [
    # --- アジア (ASIA) ---
    {"platform": "jp1", "host": "jp1.api.riotgames.com", "route": "asia"},
    {"platform": "kr", "host": "kr.api.riotgames.com", "route": "asia"},
    # --- アメリカ (AMERICAS) ---
    {"platform": "na1", "host": "na1.api.riotgames.com", "route": "americas"},
    {"platform": "br1", "host": "br1.api.riotgames.com", "route": "americas"},
    {"platform": "la1", "host": "la1.api.riotgames.com", "route": "americas"},
    {"platform": "la2", "host": "la2.api.riotgames.com", "route": "americas"},
    # --- ヨーロッパ (EUROPE) ---
    {"platform": "euw1", "host": "euw1.api.riotgames.com", "route": "europe"},
    {"platform": "eun1", "host": "eun1.api.riotgames.com", "route": "europe"},
    {"platform": "tr1", "host": "tr1.api.riotgames.com", "route": "europe"},
    {"platform": "ru", "host": "ru.api.riotgames.com", "route": "europe"},
    # --- 東南アジア / オセアニア (SEA) ---
    {"platform": "oc1", "host": "oc1.api.riotgames.com", "route": "sea"},
    {"platform": "ph2", "host": "ph2.api.riotgames.com", "route": "sea"},
    {"platform": "sg2", "host": "sg2.api.riotgames.com", "route": "sea"},
    {"platform": "th2", "host": "th2.api.riotgames.com", "route": "sea"},
    {"platform": "tw2", "host": "tw2.api.riotgames.com", "route": "sea"},
    {"platform": "vn2", "host": "vn2.api.riotgames.com", "route": "sea"},
]

# 取得階層をチャレンジャーのみに固定
TARGET_TIERS = ["challenger"]

# ==== RAG ====
EMBEDDING_MODEL_NAME = get_secret("EMBEDDING_MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2")
KNOWLEDGE_BASE_DIR = str(BASE_DIR / "knowledge_base")
CHROMA_PERSIST_DIR = str(BASE_DIR / "chroma_db")
CHROMA_COLLECTION_NAME = "tft_knowledge"

# ==== データ（メタ統計） ====
DATA_DIR = str(BASE_DIR / "data")
CURRENT_PATCH_FILE = str(BASE_DIR / "data" / "current_patch.txt")
DEFAULT_PATCH = "18.2"

# ==== 統計の信頼性フィルタリング ====
# 総試合数に対する出現率の閾値
CONFIDENCE_RATE_HIGH = 0.010    # 1.0% 以上: 信頼度 HIGH
CONFIDENCE_RATE_MEDIUM = 0.003  # 0.3% 以上: 信頼度 MEDIUM
CONFIDENCE_RATE_LOW = 0.001     # 0.1% 以上: 信頼度 LOW

# 最低採用ライン（総試合数に対する比率）
MIN_SAMPLE_RATE = CONFIDENCE_RATE_LOW

# 試合数が極端に少ない場合の足切り下限値
MIN_SAMPLE_FLOOR = 3

# （既存互換用フォールバック）
MIN_SAMPLE_SIZE = MIN_SAMPLE_FLOOR
CONFIDENCE_HIGH_MIN = 1000
CONFIDENCE_MEDIUM_MIN = 300
CONFIDENCE_LOW_MIN = MIN_SAMPLE_FLOOR

# 通常アイテムBiS選定: 試行回数が上位何%以内か
TOP_SAMPLE_PERCENTILE = 0.10

# 特殊シナジー枠として紹介するために必要な平均順位の改善マージン
SPECIAL_SYNERGY_MARGIN = 0.10

# 特殊アイテム判定キーワード
SPECIAL_ITEM_KEYWORDS = ["Emblem", "Artifact", "HeirloomEmblem"]

# ==== Data Dragon ====
DDRAGON_LOCALE = get_secret("DDRAGON_LOCALE", "ja_JP")
DDRAGON_VERSION_OVERRIDE = get_secret("DDRAGON_VERSION_OVERRIDE", "")