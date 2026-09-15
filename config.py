"""
アプリ全体の設定値を集約するモジュール。
.env を読み込み、各コンポーネントが共通で参照する定数を提供する。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# ==== LLM ====
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# ==== Riot Games API ====
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")
RIOT_PLATFORM_REGION = os.getenv("RIOT_PLATFORM_REGION", "jp1")
RIOT_REGIONAL_ROUTE = os.getenv("RIOT_REGIONAL_ROUTE", "asia")
META_COLLECT_TOP_N = int(os.getenv("META_COLLECT_TOP_N", "20"))
META_COLLECT_MATCHES_PER_PLAYER = int(os.getenv("META_COLLECT_MATCHES_PER_PLAYER", "5"))

# ==== RAG ====
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2")
KNOWLEDGE_BASE_DIR = str(BASE_DIR / "knowledge_base")
CHROMA_PERSIST_DIR = str(BASE_DIR / "chroma_db")
CHROMA_COLLECTION_NAME = "tft_knowledge"

# ==== データ（メタ統計） ====
DATA_DIR = str(BASE_DIR / "data")
CURRENT_PATCH_FILE = str(BASE_DIR / "data" / "current_patch.txt")
DEFAULT_PATCH = "18.2"

# ==== 統計の信頼性フィルタリング ====
# 総試合数に対する出現率の閾値（10万試合時の想定比率）
# 100,000試合で 100件 = 0.001 (0.1%), 300件 = 0.003 (0.3%), 1000件 = 0.010 (1.0%)
CONFIDENCE_RATE_HIGH = 0.010    # 1.0% 以上: 信頼度 HIGH
CONFIDENCE_RATE_MEDIUM = 0.003  # 0.3% 以上: 信頼度 MEDIUM
CONFIDENCE_RATE_LOW = 0.001     # 0.1% 以上: 信頼度 LOW

# 最低採用ライン（総試合数に対する比率）
MIN_SAMPLE_RATE = CONFIDENCE_RATE_LOW

# 試合数が極端に少ない場合の足切り下限値（ガードレール）
MIN_SAMPLE_FLOOR = 1

# （既存互換用フォールバック）
# ※ 固定で参照された場合でも0件除外されないようガードレール下限値を代入
MIN_SAMPLE_SIZE = MIN_SAMPLE_FLOOR
CONFIDENCE_HIGH_MIN = 1000
CONFIDENCE_MEDIUM_MIN = 300
CONFIDENCE_LOW_MIN = MIN_SAMPLE_FLOOR

# 通常アイテムBiS選定: 試行回数が上位何%以内か
TOP_SAMPLE_PERCENTILE = 0.10

# 特殊シナジー枠として紹介するために必要な、通常BiSに対する平均順位の改善マージン
SPECIAL_SYNERGY_MARGIN = 0.10

# アーティファクト/紋章など特殊アイテムを判定するキーワード
SPECIAL_ITEM_KEYWORDS = ["Emblem", "Artifact", "HeirloomEmblem"]

# ==== Data Dragon ====
# Data Dragon CDN から取得するロケール。ja_JP で日本語名を取得する。
DDRAGON_LOCALE = os.getenv("DDRAGON_LOCALE", "ja_JP")
# バージョンを固定したい場合に指定する。空文字の場合は最新版を自動取得する。
DDRAGON_VERSION_OVERRIDE = os.getenv("DDRAGON_VERSION_OVERRIDE", "")
