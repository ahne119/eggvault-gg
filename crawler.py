import html
import json
import os
import re
import time
import urllib.parse
import requests
from datetime import datetime, timezone

UNIVERSE_ID = "10563114921"
SITE_URL = "https://ahne119.github.io/eggvault-gg"
GA_ID = "G-YPEB4EYT4F"
GA_SCRIPT = (
    f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>\n'
    '  <script>\n'
    '    window.dataLayer = window.dataLayer || [];\n'
    '    function gtag(){dataLayer.push(arguments);}\n'
    "    gtag('js', new Date());\n"
    f"    gtag('config', '{GA_ID}');\n"
    '  </script>'
) if GA_ID else ""
DATA_FILE = "game_data.json"
WIKI_API = "https://stealanegg.fandom.com/api.php"
HEADERS = {"User-Agent": "EggVaultBot/1.0 (https://github.com/ahne119/eggvault-gg)"}

MUTATIONS = [
    ("Normal", 1.0, "text-slate-200"),
    ("Silver", 1.2, "text-slate-300"),
    ("Bloom", 1.25, "text-emerald-300"),
    ("Golden", 2.5, "text-amber-300"),
    ("Spirit Bloom", 2.5, "text-teal-300"),
    ("Fractured", 2.75, "text-orange-300"),
    ("Scrambled", 2.75, "text-orange-300"),
    ("Parasite", 3.0, "text-purple-300"),
    ("Rainbow", 3.5, "text-pink-300"),
]


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
        ("SX", 1e21), ("QI", 1e18), ("QA", 1e15), ("Q", 1e15),
        ("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3),
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


def format_money(val):
    n = float(val or 0)
    units = [(1e18, "Qi"), (1e15, "Q"), (1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]
    for div, suffix in units:
        if n >= div:
            txt = f"{n / div:.2f}".rstrip("0").rstrip(".")
            return f"${txt}{suffix}/s"
    return f"${round(n):,}/s"


def extract_balanced_block(text, open_idx):
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

    lua_text = re.sub(r"--\[\[.*?\]\]", "", lua_text, flags=re.S)
    lua_text = re.sub(r"^\s*--.*$", "", lua_text, flags=re.M)

    ret_match = re.search(r"return\s*\{", lua_text)
    if not ret_match:
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
            "iiurlwidth": 220,
            "redirects": 1,
            "format": "json",
        }
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
            res.raise_for_status()
            data = res.json().get("query", {})
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


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return s or "pet"


def assign_slugs(pets):
    used = set()
    for p in pets:
        base = slugify(p["name"])
        slug = base
        idx = 2
        while slug in used:
            slug = f"{base}-{idx}"
            idx += 1
        used.add(slug)
        p["slug"] = slug
    return pets


def generate_seo_pages(pets):
    """각 펫마다 구글 검색 최적화 개별 HTML 페이지 생성"""
    os.makedirs("pets", exist_ok=True)
    written = 0

    for p in pets:
        name = p["name"]
        esc_name = html.escape(name, quote=True)
        esc_rarity = html.escape(p["rarity"], quote=True)
        esc_biome = html.escape(p["biome"], quote=True)
        base_inc = p["baseIncome"]
        esc_income = html.escape(p.get("income_str") or format_money(base_inc), quote=True)
        slug = p["slug"]
        page_url = f"{SITE_URL}/pets/{slug}.html"
        img_url = p.get("image_url", "")
        q_name = urllib.parse.quote(name)

        og_image_tag = f'<meta property="og:image" content="{html.escape(img_url, quote=True)}" />' if img_url else ""
        img_block = (
            f'<img src="{html.escape(img_url, quote=True)}" alt="{esc_name} Steal An Egg" referrerpolicy="no-referrer" '
            f'class="w-24 h-24 rounded-2xl object-contain bg-slate-800/80 p-2 border border-slate-700" />'
            if img_url
            else '<div class="w-24 h-24 rounded-2xl bg-slate-800 flex items-center justify-center text-4xl border border-slate-700">🥚</div>'
        )

        # 변이 + 무게(1kg, 2.5kg, 5kg) 표 생성
        mut_rows = []
        for m_name, mult, cls in MUTATIONS:
            v1 = html.escape(format_money(base_inc * mult * 1.0))
            v25 = html.escape(format_money(base_inc * mult * 2.5))
            v5 = html.escape(format_money(base_inc * mult * 5.0))
            mut_rows.append(
                f'<tr class="border-b border-slate-800/80 hover:bg-slate-800/40">'
                f'<td class="py-2.5 px-3 font-semibold {cls}">{m_name} ({mult}x)</td>'
                f'<td class="py-2.5 px-3 text-emerald-400 font-bold">{v1}</td>'
                f'<td class="py-2.5 px-3 text-slate-200">{v25}</td>'
                f'<td class="py-2.5 px-3 text-amber-300 font-semibold">{v5}</td>'
                f'</tr>'
            )

        # 같은 바이옴 또는 같은 등급의 연관 펫 최대 6개 내부 링크(SEO 핵심)
        related = [
            x for x in pets
            if x["slug"] != slug and (x["biome"] == p["biome"] or x["rarity"] == p["rarity"])
        ][:6]
        rel_cards = "".join(
            f'<a href="./{html.escape(r["slug"], quote=True)}.html" '
            f'class="glass rounded-xl p-3 hover:border-indigo-500/60 transition flex items-center justify-between gap-2">'
            f'<div class="min-w-0">'
            f'<p class="font-bold text-white text-sm truncate">{html.escape(r["name"])}</p>'
            f'<p class="text-[11px] text-slate-400 truncate">{html.escape(r["rarity"])} • {html.escape(r["biome"])}</p>'
            f'</div>'
            f'<span class="text-xs font-bold text-emerald-400 shrink-0">{html.escape(r.get("income_str") or format_money(r["baseIncome"]))}</span>'
            f'</a>'
            for r in related
        )

        golden_inc = html.escape(format_money(base_inc * 2.5))
        rainbow_inc = html.escape(format_money(base_inc * 3.5))

        page_html = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc_name} Value, Stats &amp; Trades — Steal An Egg | EggVault.gg</title>
  <meta name="description" content="{esc_name} in Steal An Egg: {esc_rarity} rarity pet from {esc_biome} biome with {esc_income} base income. Check Golden ({golden_inc}), Rainbow ({rainbow_inc}) values and live P2P trades." />
  <link rel="canonical" href="{page_url}" />
  <meta property="og:type" content="article" />
  <meta property="og:title" content="{esc_name} Value &amp; Mutation Stats — Steal An Egg" />
  <meta property="og:description" content="{esc_rarity} pet from {esc_biome} • Base Income: {esc_income} • Rainbow (3.5x): {rainbow_inc}" />
  <meta property="og:url" content="{page_url}" />
  {og_image_tag}
  <meta name="theme-color" content="#f59e0b" />
  {GA_SCRIPT}
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{ background-color: #0b0f19; color: #e2e8f0; font-family: 'Inter', system-ui, -apple-system, sans-serif; }}
    .glass {{ background: rgba(17, 24, 39, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }}
  </style>
</head>
<body class="min-h-screen flex flex-col">
  <header class="glass sticky top-0 z-40">
    <div class="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="../index.html" class="flex items-center gap-2 font-extrabold text-white">
        <span>🥚</span><span>EggVault<span class="text-amber-400">.gg</span></span>
      </a>
      <nav class="flex items-center gap-3 text-xs font-semibold">
        <a href="../index.html" class="text-slate-300 hover:text-white">📚 Pet Wiki</a>
        <a href="../index.html?tab=calculator&pet={q_name}" class="text-slate-300 hover:text-white">⚖️ WFL Calc</a>
        <a href="../index.html?tab=trades&search={q_name}" class="px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500">🤝 Find Trades</a>
      </nav>
    </div>
  </header>

  <main class="max-w-4xl mx-auto w-full px-4 py-8 space-y-8 flex-1">
    <div class="text-xs text-slate-400">
      <a href="../index.html" class="hover:text-white">Home</a> &rsaquo;
      <a href="../index.html" class="hover:text-white">Steal An Egg Pets</a> &rsaquo;
      <span class="text-slate-200">{esc_name}</span>
    </div>

    <section class="glass rounded-2xl p-6 flex flex-col sm:flex-row items-center sm:items-start justify-between gap-6">
      <div class="flex flex-col sm:flex-row items-center sm:items-start gap-5 text-center sm:text-left">
        {img_block}
        <div class="space-y-2">
          <div class="flex flex-wrap justify-center sm:justify-start items-center gap-2">
            <span class="text-xs font-bold px-2.5 py-0.5 rounded-md bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">{esc_rarity}</span>
            <span class="text-xs font-semibold px-2.5 py-0.5 rounded-md bg-slate-800 text-slate-300">Biome: {esc_biome}</span>
          </div>
          <h1 class="text-2xl sm:text-3xl font-black text-white">{esc_name} Value &amp; Stats</h1>
          <p class="text-sm text-slate-400">Base Income (1.0kg Normal): <strong class="text-emerald-400 text-base">{esc_income}</strong></p>
        </div>
      </div>

      <div class="flex flex-col gap-2 w-full sm:w-auto shrink-0">
        <a href="../index.html?tab=calculator&pet={q_name}" class="px-4 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs text-center transition">
          ⚖️ Calculate {esc_name} Trade
        </a>
        <a href="../index.html?tab=trades&search={q_name}" class="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs text-center transition">
          🤝 View Live P2P Trades
        </a>
      </div>
    </section>

    <div class="border border-dashed border-slate-700 rounded-xl py-3 px-4 text-center text-xs text-slate-500 bg-slate-900/40">
      [ Display Ad Slot — AdSense / Playwire ]
    </div>

    <section class="glass rounded-2xl p-6 space-y-4">
      <h2 class="text-xl font-bold text-white">🧬 {esc_name} Mutation &amp; Weight Value Chart</h2>
      <p class="text-xs text-slate-400">Estimated $/sec income for {esc_name} across all verified mutations and common pet weights.</p>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs sm:text-sm">
          <thead>
            <tr class="border-b border-slate-700 text-slate-400 text-xs uppercase">
              <th class="py-2 px-3">Mutation</th>
              <th class="py-2 px-3">1.0 kg (Base)</th>
              <th class="py-2 px-3">2.5 kg</th>
              <th class="py-2 px-3">5.0 kg (Huge)</th>
            </tr>
          </thead>
          <tbody>
            {''.join(mut_rows)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="glass rounded-2xl p-6 space-y-4">
      <h2 class="text-xl font-bold text-white">❓ Frequently Asked Questions</h2>
      <div class="space-y-3 text-sm">
        <div>
          <h3 class="font-bold text-slate-200">How do you get {esc_name} in Steal An Egg?</h3>
          <p class="text-slate-400 mt-0.5">{esc_name} is a <strong>{esc_rarity}</strong> pet found in the <strong>{esc_biome}</strong> biome/category.</p>
        </div>
        <div>
          <h3 class="font-bold text-slate-200">How much does a Rainbow {esc_name} make?</h3>
          <p class="text-slate-400 mt-0.5">With the 3.5x Rainbow mutation multiplier at 1.0kg, {esc_name} generates approximately <strong class="text-pink-300">{rainbow_inc}</strong> (and Golden 2.5x generates <strong class="text-amber-300">{golden_inc}</strong>).</p>
        </div>
      </div>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-bold text-white">🔗 Related Pets ({esc_biome} / {esc_rarity})</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
        {rel_cards}
      </div>
    </section>
  </main>

  <footer class="border-t border-slate-800 py-6 text-center text-xs text-slate-500 space-y-2">
    <div class="flex justify-center gap-4 text-slate-400">
      <a href="../about.html" class="hover:text-white">About</a> •
      <a href="../privacy.html" class="hover:text-white">Privacy Policy</a> •
      <a href="../terms.html" class="hover:text-white">Terms</a>
    </div>
    <p>EggVault.gg • Data sourced from Steal An Egg Wiki (CC-BY-SA). Not affiliated with Roblox Corporation.</p>
  </footer>
</body>
</html>"""

        filepath = os.path.join("pets", f"{slug}.html")
        should_write = True
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as existing_f:
                    if existing_f.read() == page_html:
                        should_write = False
            except Exception:
                pass

        if should_write:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(page_html)
            written += 1

    return written


def generate_sitemap(pets, updated_ts):
    lastmod = datetime.fromtimestamp(updated_ts or time.time(), tz=timezone.utc).strftime("%Y-%m-%d")
    urls = [
        f"  <url>\n    <loc>{SITE_URL}/</loc>\n    <changefreq>hourly</changefreq>\n    <priority>1.0</priority>\n  </url>",
        f"  <url>\n    <loc>{SITE_URL}/about.html</loc>\n    <changefreq>monthly</changefreq>\n    <priority>0.5</priority>\n  </url>",
    ]
    for p in pets:
        urls.append(
            f"  <url>\n"
            f"    <loc>{SITE_URL}/pets/{html.escape(p['slug'], quote=True)}.html</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"    <priority>0.8</priority>\n"
            f"  </url>"
        )

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>\n"

    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(xml)


def load_existing_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def main():
    print("🚀 Steal An Egg v4 (SEO Page Generator) 시작...")
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

    pets = existing.get("pets", [])
    pets_updated_ts = existing.get("pets_updated_ts", 0)
    now_ts = int(time.time())

    if not pets or (now_ts - pets_updated_ts) >= 21600:
        print("📚 Fandom Wiki (Module:Pets/Data) 파싱 중...")
        new_pets = fetch_wiki_pets_module()
        if new_pets:
            print(f"🖼️ {len(new_pets)}개 펫 이미지 URL 매칭 중...")
            pets = resolve_wiki_image_urls(new_pets)
            pets_updated_ts = now_ts
        else:
            print("⚠️ 위키 파싱 실패로 기존 데이터를 유지합니다.")
    else:
        print(f"♻️ 위키 펫 데이터 캐시 사용 ({len(pets)}종)")

    if pets:
        pets = assign_slugs(pets)
        written = generate_seo_pages(pets)
        generate_sitemap(pets, pets_updated_ts)
        print(f"📄 SEO 개별 페이지 생성 완료 (신규/변경 {written}개, 총 {len(pets)}개) & sitemap.xml 갱신 완료!")

    output = {
        "stats": live_stats,
        "history": history,
        "pets_updated_ts": pets_updated_ts,
        "pets_count": len(pets),
        "pets": pets,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 전체 작업 완료! 동접자: {live_stats['playing']:,}명")


if __name__ == "__main__":
    main()