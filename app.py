# -*- coding: utf-8 -*-
"""
全台灣火箭隊即時情報雷達 - Web 應用伺服器
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

# 啟用 Gzip/Brotli 高效壓縮，巨幅降低傳輸頻寬與 Buffer 記憶體
try:
    from flask_compress import Compress
    Compress(app)
except Exception:
    pass

# 雙重防呆模板加載器：優先讀取根目錄 index.html，徹底解決 GitHub 網頁直接上傳根目錄不生效的問題
app.jinja_loader = jinja2.ChoiceLoader([
    jinja2.FileSystemLoader(base_dir),
    jinja2.FileSystemLoader(os.path.join(base_dir, "templates")),
    jinja2.FileSystemLoader(os.getcwd()),
    jinja2.FileSystemLoader(os.path.join(os.getcwd(), "templates")),
])

crawler = RocketCrawler()

# 記憶體快取，全台灣掃描快取 60 秒 (支援 Stale-While-Revalidate 零等待秒開)
ROCKET_CACHE = {}
CACHE_TIMESTAMP = {}
CACHE_LOCK = threading.Lock()
CACHE_TTL = 60

def get_cached_rockets(city_name="全台灣 (全島掃描)", force_refresh=False):
    """取得指定城市或全台灣的火箭隊資料 (帶快取，優先秒開零等待)"""
    import gc
    now = time.time()
    with CACHE_LOCK:
        # 1. 快取未過期，直接回傳 (0.01 秒)
        if not force_refresh and city_name in ROCKET_CACHE and (now - CACHE_TIMESTAMP.get(city_name, 0)) < CACHE_TTL:
            return ROCKET_CACHE[city_name]
        # 2. 若快取稍微過期但有舊資料，直接先秒傳舊資料給使用者 (絕不讓使用者卡住等 15 秒)
        if not force_refresh and city_name in ROCKET_CACHE and ROCKET_CACHE[city_name]:
            return ROCKET_CACHE[city_name]

    # 3. 第一次啟動無快取或背景強制更新時才執行爬蟲
    rockets = crawler.get_rockets_by_city(city_name)
    if rockets:
        with CACHE_LOCK:
            ROCKET_CACHE.clear()
            CACHE_TIMESTAMP.clear()
            ROCKET_CACHE[city_name] = rockets
            CACHE_TIMESTAMP[city_name] = now
        gc.collect()
        return rockets
    else:
        # 若遇上游網路波動，若有舊快取則維持舊快取
        with CACHE_LOCK:
            return ROCKET_CACHE.get(city_name, [])

def background_radar_updater():
    """伺服器啟動後，在背景定期預熱更新全台資料 (每 60 秒一次)，保證使用者連線永遠 0 秒加載"""
    time.sleep(3)
    while True:
        try:
            get_cached_rockets("全台灣 (全島掃描)", force_refresh=True)
        except Exception:
            pass
        time.sleep(60)

threading.Thread(target=background_radar_updater, daemon=True).start()

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
    """取得火箭隊清單 API：支援分縣市、時間最久優先排序、單次 30 筆超省流量模式"""
    city = request.args.get("city", "全台灣 (全島掃描)")
    filter_county = request.args.get("county", "台北市").strip()
    filter_type = request.args.get("type", "").strip()
    filter_gender = request.args.get("gender", "").strip()
    leader_only = request.args.get("leader_only", "").lower() in ["true", "1", "yes"]
    snorlax_only = request.args.get("snorlax_only", "").lower() in ["true", "1", "yes"]
    hot_only = request.args.get("hot_only", "").lower() in ["true", "1", "yes"]
    keyword = request.args.get("q", "").strip().lower()
    limit = request.args.get("limit", default=30, type=int)
    offset = request.args.get("offset", default=0, type=int)

    all_rockets = get_cached_rockets(city)

    # 1. 永遠統計全島各縣市即時真實總數 (排除需黑雷達的偽裝點，供縣市選單顯示各縣市幾處)
    county_counts = {}
    for r in all_rockets:
        if "偽裝" in r.get("type_name", "") or "阪木" in r.get("type_name", ""):
            continue
        c = r.get("county", "其他地區")
        county_counts[c] = county_counts.get(c, 0) + 1

    filtered = []
    hot_types = ["卡比獸", "幹部", "龍", "鋼", "格鬥", "妖精"]
    type_counts = {}
    leader_count = 0
    snorlax_count = 0
    dragon_count = 0
    male_count = 0
    female_count = 0

    # 2. 針對當前所選縣市過濾並計算屬性分佈
    for r in all_rockets:
        # 預設排除需黑雷達才能看見的隱身點 (偽裝小兵/阪木老大)，避免玩家白跑一趟
        if filter_type != "阪木老大" and not keyword:
            if "偽裝" in r.get("type_name", "") or "阪木" in r.get("type_name", ""):
                continue

        # 縣市篩選 (預設台北市，若選全部則為全島)
        if filter_county and filter_county != "全部":
            if r.get("county") != filter_county and r.get("region_group") != filter_county:
                continue

        t = r["type_name"]
        type_counts[t] = type_counts.get(t, 0) + 1
        if t == "幹部":
            leader_count += 1
        if "卡比獸" in t:
            snorlax_count += 1
        if "龍" in t:
            dragon_count += 1
        if "男" in r["gender"]:
            male_count += 1
        elif "女" in r["gender"]:
            female_count += 1

        # 幹部篩選
        if leader_only and not r["is_leader"]:
            continue
            
        # 卡比獸/乘龍女小兵快篩
        if snorlax_only and "卡比獸" not in r["type_name"]:
            continue

        # 高價值神怪快篩
        if hot_only and not (r["is_leader"] or any(k in r["type_name"] for k in hot_types)):
            continue

        # 屬性篩選
        if filter_type and filter_type != "全部":
            if filter_type == "幹部" and not r["is_leader"]:
                continue
            elif filter_type == "卡比獸/乘龍" and "卡比獸" not in r["type_name"]:
                continue
            elif filter_type not in ["幹部", "卡比獸/乘龍"] and filter_type not in r["type_name"]:
                continue

        # 小兵性別篩選
        if filter_gender and filter_gender != "全部":
            if filter_gender not in r["gender"]:
                continue

        # 關鍵字搜尋
        if keyword:
            if (keyword not in r["name"].lower() and 
                keyword not in r["title"].lower() and 
                keyword not in r["first_pokemon_display"].lower() and
                keyword not in r.get("county", "").lower() and
                keyword not in r.get("district", "").lower()):
                continue

        filtered.append(r)

    # 3. ★ 核心關鍵：依剩餘時間最久優先排序 (秒數由大到小)
    filtered.sort(key=lambda x: x.get("remaining_seconds", 0), reverse=True)

    # 4. 超省流量分頁切片：每次只回傳指定筆數 (預設 30 筆，僅約 4KB)
    if limit > 0:
        items_to_send = filtered[offset : offset + limit]
    else:
        items_to_send = filtered

    return jsonify({
        "status": "success",
        "city": city,
        "county": filter_county,
        "total_in_county": sum(type_counts.values()),
        "filtered_total": len(filtered),
        "offset": offset,
        "limit": limit,
        "has_more": len(filtered) > (offset + limit) if limit > 0 else False,
        "leaders_count": leader_count,
        "snorlax_count": snorlax_count,
        "dragon_count": dragon_count,
        "male_count": male_count,
        "female_count": female_count,
        "type_counts": type_counts,
        "county_counts": county_counts,
        "items": items_to_send
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

