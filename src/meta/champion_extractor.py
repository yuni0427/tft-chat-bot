import html
import json
from pathlib import Path
import re
import urllib.request


def clean_spell_text(text: str) -> str:
    """スキル・特性説明からHTMLタグ、CDragon内部変数(@...@)、特殊記号を除去"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"@[^@]+@", "", text)
    text = re.sub(r"\(%i:[^)]+\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sync_trait_data(
    target_set: dict, output_dir: Path
) -> tuple[Path, dict]:
    """現行最新セット (Set 18 / TFTSet18) の特性（シナジー）情報を抽出して保存"""
    target_file = output_dir / "traits.json"
    traits_dict = {}

    for trait in target_set.get("traits", []):
        api_name = trait.get("apiName", "")
        name = trait.get("name")

        # Set 18 特性判定 (apiName に '18' を含む、または明示的な名前が存在)
        if not name or "18" not in api_name:
            continue

        raw_desc = trait.get("desc", "")
        clean_desc = clean_spell_text(raw_desc)

        # ブレークポイントごとの効果を取得
        effects_list = []
        for eff in trait.get("effects", []):
            min_units = eff.get("minUnits")
            if min_units is not None:
                effects_list.append(
                    {
                        "min_units": min_units,
                        "style": eff.get("style", 0),
                    }
                )

        # 昇順ソート
        effects_list.sort(key=lambda x: x["min_units"])

        traits_dict[name] = {
            "name": name,
            "api_name": api_name,
            "description": clean_desc,
            "breakpoints": [e["min_units"] for e in effects_list],
            "effects": effects_list,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(traits_dict, f, ensure_ascii=False, indent=2)

    print(
        f"✅ 特性抽出完了: Set 18 のシナジー {len(traits_dict)} 種類を保存しました。"
    )
    return target_file, traits_dict


def sync_champion_data(patch_version: str, output_dir: Path) -> Path:
    """現行最新セット (Set 18 / TFTSet18) のチャンピオンおよび特性情報を抽出して保存"""
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

    # 1. 特性（シナジー）を抽出・保存
    sync_trait_data(target_set, output_dir)

    # 2. チャンピオンを抽出・保存
    champions = {}
    debuff_keywords = {
        "負傷": "負傷(重症)",
        "重症": "重症",
        "炎上": "炎上",
        "細断": "細断",
        "分解": "分解",
        "スタン": "スタン",
        "マナリーヴ": "マナリーヴ",
    }

    for champ in target_set.get("champions", []):
        api_name = champ.get("apiName", "")
        name = champ.get("name")
        cost = champ.get("cost", 0)
        traits = champ.get("traits", [])

        if "18" not in api_name:
            continue
        if not name or cost not in [1, 2, 3, 4, 5]:
            continue
        if "(" in name or "（" in name:
            continue
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
        f"✅ チャンピオン抽出完了: Set 18 のチャンピオン {len(champions)} 体を保存しました。"
    )
    return target_file