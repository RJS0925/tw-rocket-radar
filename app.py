# -*- coding: utf-8 -*-
"""
報寶貝火箭隊雷達 - 本地 Web 應用伺服器
提供全台灣/分區快速掃描、屬性分類、卡比獸/乘龍專屬快篩、幹部快篩與導航地圖。
"""

import time
import threading
from flask import Flask, render_template, jsonify, request
from rocket_crawler import RocketCrawler, PRESET_CITIES
from rocket_data import TYPE_INFO, LEADER_INFO, ROCKET_ROSTER, LEADER_ROSTER

import os
import jinja2

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(base_dir, "templates"))

# 雙重防呆模板加載器：同時支援 templates 目錄與根目錄，解決 GitHub 網頁上傳目錄層級問題
app.jinja_loader = jinja2.ChoiceLoader([
    jinja2.FileSystemLoader(os.path.join(base_dir, "templates")),
    jinja2.FileSystemLoader(base_dir),
    jinja2.FileSystemLoader(os.getcwd()),
    jinja2.FileSystemLoader(os.path.join(os.getcwd(), "templates")),
])

crawler = RocketCrawler()

# 記憶體快取，全台灣掃描快取 45 秒
ROCKET_CACHE = {}
CACHE_TIMESTAMP = {}
CACHE_LOCK = threading.Lock()
CACHE_TTL = 45

def get_cached_rockets(city_name="全台灣 (全島掃描)"):
    """取得指定城市或全台灣的火箭隊資料 (帶 45 秒快取)"""
    now = time.time()
    with CACHE_LOCK:
        if city_name in ROCKET_CACHE and (now - CACHE_TIMESTAMP.get(city_name, 0)) < CACHE_TTL:
            return ROCKET_CACHE[city_name]

    rockets = crawler.get_rockets_by_city(city_name)
    with CACHE_LOCK:
        ROCKET_CACHE[city_name] = rockets
        CACHE_TIMESTAMP[city_name] = now
    return rockets

@app.route("/ping")
@app.route("/healthz")
def ping():
    """雲端健康檢查與保活端點 (超輕量 200 OK，不觸發爬蟲)"""
    return "pong", 200

@app.route("/")
def index():
    """主儀表板畫面"""
    return render_template("index.html", cities=list(PRESET_CITIES.keys()))

@app.route("/api/rockets")
def api_rockets():
    """取得火箭隊清單 API，支援卡比獸、幹部、屬性、性別快篩"""
    city = request.args.get("city", "全台灣 (全島掃描)")
    filter_type = request.args.get("type", "").strip()
    filter_gender = request.args.get("gender", "").strip()
    leader_only = request.args.get("leader_only", "").lower() in ["true", "1", "yes"]
    snorlax_only = request.args.get("snorlax_only", "").lower() in ["true", "1", "yes"] # 只看卡比獸/乘龍女小兵
    hot_only = request.args.get("hot_only", "").lower() in ["true", "1", "yes"]
    keyword = request.args.get("q", "").strip().lower()

    all_rockets = get_cached_rockets(city)

    filtered = []
    hot_types = ["卡比獸", "幹部", "龍", "鋼", "格鬥", "妖精"]
    
    for r in all_rockets:
        # 過濾幹部
        if leader_only and not r["is_leader"]:
            continue
            
        # 專屬卡比獸/乘龍女小兵快篩
        if snorlax_only and "卡比獸" not in r["type_name"]:
            continue

        # 高價值神怪快篩
        if hot_only and not (r["is_leader"] or any(k in r["type_name"] for k in hot_types)):
            continue

        # 過濾屬性
        if filter_type and filter_type != "全部":
            if filter_type == "幹部" and not r["is_leader"]:
                continue
            elif filter_type != "幹部" and filter_type not in r["type_name"]:
                continue

        # 過濾小兵性別
        if filter_gender and filter_gender != "全部":
            if filter_gender not in r["gender"]:
                continue

        # 關鍵字搜尋
        if keyword:
            if (keyword not in r["name"].lower() and 
                keyword not in r["title"].lower() and 
                keyword not in r["first_pokemon_display"].lower()):
                continue

        filtered.append(r)

    # 全域屬性與縣市統計
    type_counts = {}
    county_counts = {}
    leader_count = 0
    snorlax_count = 0
    dragon_count = 0
    male_count = 0
    female_count = 0

    for r in all_rockets:
        t = r["type_name"]
        c = r.get("county", "其他地區")
        county_counts[c] = county_counts.get(c, 0) + 1
        type_counts[t] = type_counts.get(t, 0) + 1
        if r["is_leader"]:
            leader_count += 1
        if "卡比獸" in t:
            snorlax_count += 1
        if "龍" in t:
            dragon_count += 1
        if "男" in r["gender"]:
            male_count += 1
        elif "女" in r["gender"]:
            female_count += 1

    return jsonify({
        "status": "success",
        "city": city,
        "total": len(all_rockets),
        "filtered_total": len(filtered),
        "leaders_count": leader_count,
        "snorlax_count": snorlax_count,
        "dragon_count": dragon_count,
        "male_count": male_count,
        "female_count": female_count,
        "type_counts": type_counts,
        "county_counts": county_counts,
        "items": filtered
    })

@app.route("/api/roster")
def api_roster():
    """回傳完整的火箭隊對戰手冊"""
    roster_list = []
    for (t_key, g_key), data in ROCKET_ROSTER.items():
        type_meta = TYPE_INFO.get(t_key, TYPE_INFO["unknown"])
        roster_list.append({
            "key": f"{t_key}_{g_key}",
            "type_key": t_key,
            "type_name": type_meta["name_ch"],
            "type_color": type_meta["color"],
            "gender": "男小兵 ♂" if g_key == "MALE" else "女小兵 ♀",
            "title": data["title"],
            "taunt": data["taunt"],
            "certainty_level": data["certainty_level"],
            "certainty_note": data["certainty_note"],
            "primary_first": data["primary_first"],
            "first_pokemons": data.get("first_pokemons", []),
            "second_pokemons": data.get("second_pokemons", []),
            "third_pokemons": data.get("third_pokemons", []),
            "catchable": data.get("catchable", []),
            "counters": data.get("counters", [])
        })
    return jsonify({
        "grunts": roster_list,
        "leaders": LEADER_ROSTER
    })

def background_season_checker():
    """背景定時檢查最新賽季陣容 (每 24 小時一次)，換季時自動無感熱更新"""
    from rocket_data import sync_latest_season_from_leekduck
    time.sleep(5)
    sync_latest_season_from_leekduck()
    while True:
        time.sleep(86400)
        try:
            sync_latest_season_from_leekduck()
        except Exception:
            pass

# 啟動換季自動同步守護執行緒
threading.Thread(target=background_season_checker, daemon=True).start()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    print(f"啟動火箭隊全台灣雷達 Web 服務: http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

