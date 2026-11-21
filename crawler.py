import json
import os
import re
import time
import requests
from datetime import datetime, timezone

UNIVERSE_ID = "10563114921"
DATA_FILE = "game_data.json"
WIKI_API = "https://stealanegg.fandom.com/api.php"
HEADERS = {"User-Agent": "EggVaultBot/1.0 (https://github.com/ahne119/eggvault-gg)"}


def fetch_roblox_live_stats():
    url = f"https://games.roblox.com/v1/games?universeIds={UNIVERSE_ID}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        game_info = res.json()["data"][0]
        return {
            "name": game_info.get("name", "Steal An Egg"),
            "playing": game_info.get("playing", 0),
            "visits": game_info.get("visits", 0),
            "favorites": game_info.get("favoritedCount", 0),
            "updated": game_info.get("updated", ""),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
    except Exception as e:
        print(f"[경고] Roblox Games API 호출 실패: {e}")
        return None


def fetch_roblox_game_icon():
    url = (
        f"https://thumbnails.roblox.com/v1/games/icons"
        f"?universeIds={UNIVERSE_ID}&returnPolicy=PlaceHolder&size=512x512&format=Png&isCircular=false"
    )
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json().get("data", [])
        if data and data[0].get("state") == "Completed":
            return data[0].get("imageUrl", "")
    except Exception as e:
        print(f"[경고] Roblox Thumbnails API 호출 실패: {e}")
    return ""


def parse_income(income_str):
    if not income_str:
        return 0.0
    s = income_str.upper().replace("$", "").replace("/S", "").replace(",", "").strip()
    multipliers = [
        ("SX", 1e21),
        ("QI", 1e18),
        ("QA", 1e15),
        ("Q", 1e15),
        ("T", 1e12),
        ("B", 1e9),
        ("M", 1e6),
        ("K", 1e3),
    ]
    for suffix, mult in multipliers:
        if s.endswith(suffix):
            try:
                return float(s[: -len(suffix)].strip()) * mult
            except ValueError:
                return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_balanced_block(text, open_idx):
    """중괄호 { ... } 짝을 맞춰 문자열 안전하게 블록 추출"""
    depth = 0
    in_str = None
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[open_idx + 1 : i], i
        i += 1
    return "", open_idx


def fetch_wiki_pets_module():
    """Fandom Wiki의 Module:Pets/Data Lua 모듈에서 전체 펫 데이터 파싱"""
    params = {
        "action": "query",
        "titles": "Module:Pets/Data",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
    }
    try:
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        res.raise_for_status()
        pages = res.json()["query"]["pages"]
        page = next(iter(pages.values()))
        rev = page["revisions"][0]
        lua_text = rev.get("slots", {}).get("main", {}).get("*") or rev.get("*", "")
    except Exception as e:
        print(f"[경고] Module:Pets/Data 호출 실패: {e}")
        return []

    # Lua 주석 제거
    lua_text = re.sub(r"--\[\[.*?\]\]", "", lua_text, flags=re.S)
    lua_text = re.sub(r"^\s*--.*$", "", lua_text, flags=re.M)

    ret_match = re.search(r"return\s*\{", lua_text)
    if not ret_match:
        print("[경고] Lua return 블록을 찾지 못했습니다.")
        return []

    root_block, _ = extract_balanced_block(lua_text, ret_match.end() - 1)
    key_pattern = re.compile(r'(?:\["([^"]+)"\]|([A-Za-z0-9_]+))\s*=\s*\{')

    pets = []
    pos = 0
    pet_id = 1

    while pos < len(root_block):
        m_rarity = key_pattern.search(root_block, pos)
        if not m_rarity:
            break
        rarity = (m_rarity.group(1) or m_rarity.group(2)).strip()
        rarity_block, end_idx = extract_balanced_block(root_block, m_rarity.end() - 1)
        pos = end_idx + 1

        p_pos = 0
        while p_pos < len(rarity_block):
            m_pet = key_pattern.search(rarity_block, p_pos)
            if not m_pet:
                break
            pet_name = (m_pet.group(1) or m_pet.group(2)).strip()
            pet_block, p_end = extract_balanced_block(rarity_block, m_pet.end() - 1)
            p_pos = p_end + 1

            biome_m = re.search(r'biome\s*=\s*"([^"]*)"', pet_block)
            image_m = re.search(r'image\s*=\s*"([^"]*)"', pet_block)
            income_m = re.search(r'income\s*=\s*"([^"]*)"', pet_block)

            income_str = income_m.group(1).strip() if income_m else "$0/s"
            income_num = parse_income(income_str)

            pets.append({
                "id": pet_id,
                "name": pet_name,
                "rarity": rarity,
                "biome": biome_m.group(1).strip() if biome_m else "Unknown",
                "image_file": image_m.group(1).strip() if image_m else "",
                "image_url": "",
                "income_str": income_str,
                "baseIncome": income_num,
            })
            pet_id += 1

    return pets


def resolve_wiki_image_urls(pets):
    """MediaWiki API로 파일명(Chicken.png 등)에 해당하는 실제 썸네일 URL 일괄 조회"""
    filenames = sorted({p["image_file"] for p in pets if p["image_file"]})
    if not filenames:
        return pets

    url_map = {}
    batch_size = 45
    for i in range(0, len(filenames), batch_size):
        chunk = filenames[i : i + batch_size]
        titles = "|".join(f"File:{fn}" for fn in chunk)
        params = {
            "action": "query",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 180,
            "format": "json",
        }
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
            res.raise_for_status()
            data = res.json().get("query", {})

            # MediaWiki 정규화 매핑 처리 (공백/언더바 등)
            norm_map = {n["to"]: n["from"] for n in data.get("normalized", [])}
            pages = data.get("pages", {})
            for page in pages.values():
                title = page.get("title", "")
                orig_title = norm_map.get(title, title)
                clean_name = orig_title.replace("File:", "", 1)
                info = page.get("imageinfo", [])
                if info:
                    thumb = info[0].get("thumburl") or info[0].get("url", "")
                    if thumb:
                        url_map[clean_name] = thumb
                        url_map[title.replace("File:", "", 1)] = thumb
        except Exception as e:
            print(f"[경고] 이미지 배치 조회 실패 ({i}): {e}")
        time.sleep(0.25)

    for p in pets:
        fn = p["image_file"]
        p["image_url"] = url_map.get(fn) or url_map.get(fn.replace("_", " "), "")

    return pets


def load_existing_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def main():
    print("🚀 Steal An Egg v3 크롤링 시작...")
    existing = load_existing_data()

    live_stats = fetch_roblox_live_stats()
    time.sleep(0.3)
    icon_url = fetch_roblox_game_icon()
    time.sleep(0.3)

    history = existing.get("history", [])
    if live_stats:
        live_stats["icon_url"] = icon_url or existing.get("stats", {}).get("icon_url", "")
        history.append({"time": live_stats["fetched_at"], "playing": live_stats["playing"]})
        history = history[-48:]
    else:
        live_stats = existing.get("stats", {
            "name": "Steal An Egg",
            "playing": 880000,
            "visits": 11650000000,
            "icon_url": icon_url,
            "fetched_at": "Offline Fallback",
        })

    # 위키 데이터는 6시간마다 한 번씩만 갱신 (이미 있고 6시간 안 지났으면 재사용)
    pets = existing.get("pets", [])
    pets_updated_ts = existing.get("pets_updated_ts", 0)
    now_ts = int(time.time())

    if not pets or (now_ts - pets_updated_ts) >= 21600:
        print("📚 Fandom Wiki (Module:Pets/Data) 파싱 중...")
        new_pets = fetch_wiki_pets_module()
        if new_pets:
            print(f"🖼️ {len(new_pets)}개 펫의 이미지 URL 매칭 중...")
            pets = resolve_wiki_image_urls(new_pets)
            pets_updated_ts = now_ts
        else:
            print("⚠️ 위키 파싱 실패로 기존 데이터를 유지합니다.")
    else:
        print(f"♻️ 위키 펫 데이터 캐시 사용 ({len(pets)}종)")

    output = {
        "stats": live_stats,
        "history": history,
        "pets_updated_ts": pets_updated_ts,
        "pets_count": len(pets),
        "pets": pets,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    img_ok = sum(1 for p in pets if p.get("image_url"))
    print(f"✅ 완료! 동접자: {live_stats['playing']:,}명 | 수집된 펫: {len(pets)}종 (이미지 {img_ok}개 확보)")


if __name__ == "__main__":
    main()