import html
import json
from pathlib import Path
import re
import urllib.request


def clean_spell_text(text: str) -> str:
    """スキル説明からHTMLタグ、CDragon内部変数(@...@)、特殊記号を除去"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"@[^@]+@", "", text)
    text = re.sub(r"\(%i:[^)]+\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sync_champion_data(patch_version: str, output_dir: Path) -> Path:
    """apiName に '18' を含むユニットを抽出して保存"""
    target_file = output_dir / "champions.json"

    url = "https://raw.communitydragon.org/latest/cdragon/tft/ja_jp.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(req, timeout=20) as resp:
        raw_data = json.loads(resp.read().decode("utf-8"))

    # mutator が 'TFTSet18' のデータブロックを特定
    target_set = None
    for s in raw_data.get("setData", []):
        if s.get("mutator") == "TFTSet18":
            target_set = s
            break

    if not target_set:
        print("⚠️ TFTSet18 のデータブロックが見つかりませんでした。")
        return target_file

    champions = {}
    debuff_keywords = {
        "細断": "細断",
        "分解": "分解",
        "重症": "重症",
        "炎上": "炎上",
        "スタン": "スタン",
        "マナリーヴ": "マナリーヴ",
    }

    for champ in target_set.get("champions", []):
        api_name = champ.get("apiName", "")
        name = champ.get("name")
        cost = champ.get("cost", 0)
        traits = champ.get("traits", [])

        # 1. 内部ID (apiName) に '18' が含まれていること
        if "18" not in api_name:
            continue

        # 2. プレイアブル駒の基本条件（名前あり、コスト1〜5）
        if not name or cost not in [1, 2, 3, 4, 5]:
            continue

        # 3. スキン違い（括弧付きの名前）を除外し、ベース駒のみにする
        if "(" in name or "（" in name:
            continue

        # 既に登録済みの場合は重複スキップ
        if name in champions:
            continue

        ability = champ.get("ability", {})
        raw_desc = ability.get("desc", "")
        clean_desc = clean_spell_text(raw_desc)

        utilities = [kw for kw in debuff_keywords if kw in raw_desc]
        stats = champ.get("stats", {})

        champions[name] = {
            "name": name,
            "api_name": api_name,
            "cost": cost,
            "traits": traits,
            "stats": {
                "hp": stats.get("hp"),
                "mana": f"{stats.get('initialMana', 0)}/{stats.get('mana', 0)}",
                "armor": stats.get("armor"),
                "mr": stats.get("magicResist"),
                "range": stats.get("range"),
            },
            "ability": {
                "name": ability.get("name", ""),
                "description": clean_desc,
            },
            "utilities": utilities,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(champions, f, ensure_ascii=False, indent=2)

    print(
        f"✅ 抽出完了: Set 18 のチャンピオン {len(champions)} 体を保存しました。"
    )
    return target_file