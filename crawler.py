import json
import os
import time
import requests
from datetime import datetime, timezone

UNIVERSE_ID = "10563114921"
DATA_FILE = "game_data.json"

def fetch_roblox_live_stats():
    url = f"https://games.roblox.com/v1/games?universeIds={UNIVERSE_ID}"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        game_info = res.json()["data"][0]
        return {
            "name": game_info.get("name", "Steal An Egg"),
            "playing": game_info.get("playing", 0),
            "visits": game_info.get("visits", 0),
            "favorites": game_info.get("favoritedCount", 0),
            "updated": game_info.get("updated", ""),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }
    except Exception as e:
        print(f"[경고] Roblox Games API 호출 실패: {e}")
        return None

def fetch_roblox_game_icon():
    """Roblox 공식 Thumbnails API에서 고화질 게임 아이콘 URL 수집"""
    url = (
        f"https://thumbnails.roblox.com/v1/games/icons"
        f"?universeIds={UNIVERSE_ID}&returnPolicy=PlaceHolder&size=512x512&format=Png&isCircular=false"
    )
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json().get("data", [])
        if data and data[0].get("state") == "Completed":
            return data[0].get("imageUrl", "")
    except Exception as e:
        print(f"[경고] Roblox Thumbnails API 호출 실패: {e}")
    return ""

def fetch_wiki_category(category_name):
    """Fandom MediaWiki API로 카테고리별 항목 수집"""
    wiki_api = "https://stealanegg.fandom.com/api.php"
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category_name}",
        "cmlimit": 100,
        "format": "json"
    }
    try:
        res = requests.get(wiki_api, params=params, timeout=10)
        res.raise_for_status()
        members = res.json().get("query", {}).get("categorymembers", [])
        return [m["title"] for m in members if not m["title"].startswith("Category:")]
    except Exception as e:
        print(f"[경고] Wiki({category_name}) 수집 실패: {e}")
        return []

def load_existing_history():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("history", [])
        except Exception:
            pass
    return []

def main():
    print("🚀 Steal An Egg v2 크롤링 시작...")
    live_stats = fetch_roblox_live_stats()
    time.sleep(0.3)
    icon_url = fetch_roblox_game_icon()
    time.sleep(0.3)
    wiki_eggs = fetch_wiki_category("Eggs")
    time.sleep(0.3)
    wiki_pets = fetch_wiki_category("Pets")

    history = load_existing_history()

    if live_stats:
        live_stats["icon_url"] = icon_url
        # 최근 48개(30분 주기 기준 24시간) 스냅샷만 유지
        history.append({
            "time": live_stats["fetched_at"],
            "playing": live_stats["playing"]
        })
        history = history[-48:]
    else:
        live_stats = {
            "name": "Steal An Egg",
            "playing": 880000,
            "visits": 11650000000,
            "favorites": 10150000,
            "icon_url": icon_url,
            "fetched_at": "Offline Fallback"
        }

    output = {
        "stats": live_stats,
        "history": history,
        "wiki_eggs_discovered": wiki_eggs,
        "wiki_pets_discovered": wiki_pets
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 완료! 동접자: {live_stats['playing']:,}명 | 히스토리: {len(history)}건 | 위키 알 {len(wiki_eggs)}개 / 펫 {len(wiki_pets)}개")

if __name__ == "__main__":
    main()