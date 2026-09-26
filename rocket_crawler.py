# -*- coding: utf-8 -*-
"""
報寶貝 (twpkinfo) 火箭隊雷達專用爬蟲模組
功能：
1. 爬取台灣全島/各區域補給站火箭隊佔領資訊 (getgym.ashx)
2. 屬性精確分類 (龍、水、火、草、電、格鬥、惡、飛行、超能、幽靈、地面、岩石、冰、一般、毒、妖精、蟲、鋼等)
3. 標註小兵性別 (男小兵 ♂ / 女小兵 ♀) 或 幹部名稱 (亞洛、克里夫、希爾拉、阪木老大)
4. 深度解析 / 確定對手第一隻出場對戰與可捕捉角色 (100%確定、高機率鎖定、陣容池)
5. 計算即時倒數剩餘時間與 Google 地圖導航連結
"""

import time
import json
import datetime
import requests
from rocket_data import get_rocket_details, TYPE_INFO, LEADER_INFO
from taiwan_geo import resolve_taiwan_location

# 台灣主要涵蓋區域預設經緯度範圍 (含全台灣與各都會區)
PRESET_CITIES = {
    "全台灣 (全島掃描)": {"lat0": 25.35, "lng0": 122.10, "lat1": 21.80, "lng1": 120.00},
    "大台北精華區": {"lat0": 25.12, "lng0": 121.62, "lat1": 25.00, "lng1": 121.46},
    "新北淡水基隆": {"lat0": 25.25, "lng0": 121.80, "lat1": 25.08, "lng1": 121.40},
    "桃園市區": {"lat0": 25.05, "lng0": 121.36, "lat1": 24.93, "lng1": 121.20},
    "新竹市區": {"lat0": 24.86, "lng0": 121.05, "lat1": 24.75, "lng1": 120.90},
    "台中市區": {"lat0": 24.23, "lng0": 120.75, "lat1": 24.08, "lng1": 120.58},
    "彰化南投": {"lat0": 24.10, "lng0": 120.72, "lat1": 23.85, "lng1": 120.48},
    "雲林嘉義": {"lat0": 23.75, "lng0": 120.52, "lat1": 23.40, "lng1": 120.35},
    "台南市區": {"lat0": 23.08, "lng0": 120.30, "lat1": 22.92, "lng1": 120.14},
    "高雄市區": {"lat0": 22.75, "lng0": 120.42, "lat1": 22.56, "lng1": 120.24},
    "屏東市區": {"lat0": 22.72, "lng0": 120.55, "lat1": 22.45, "lng1": 120.42},
    "宜蘭羅東": {"lat0": 24.85, "lng0": 121.85, "lat1": 24.65, "lng1": 121.70},
    "花蓮市區": {"lat0": 24.05, "lng0": 121.65, "lat1": 23.93, "lng1": 121.55},
    "台東市區": {"lat0": 22.82, "lng0": 121.18, "lat1": 22.70, "lng1": 121.10}
}

class RocketCrawler:
    def __init__(self, dict_path="pokemon_dict.json"):
        self.api_url = "https://twpkinfo.com/getgym.ashx"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://twpkinfo.com/igym.aspx",
            "X-Requested-With": "XMLHttpRequest"
        }
        self.pokemon_dict = {}
        try:
            with open(dict_path, "r", encoding="utf-8") as f:
                self.pokemon_dict = json.load(f)
        except Exception:
            pass

    def fetch_raw_stops(self, lat0, lng0, lat1, lng1):
        """向報寶貝 API 發送請求獲取補給站資料"""
        params = {
            "a": str(lat0),
            "b": str(lng0),
            "c": str(lat1),
            "d": str(lng1),
            "e": "0",
            "f": "0",      # f='0' 過濾一般道館，僅保留補給站
            "g": "N",      # g='N' 關閉非火箭隊補給站怪 (變隱龍等)
            "h": "",
            "i": "",
            "j": "765"
        }
        
        for attempt in range(2):
            try:
                resp = requests.get(self.api_url, params=params, headers=self.headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("fp", [])
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                    continue
                print(f"[RocketCrawler] 爬取失敗 ({lat0}, {lng0}): {e}")
        return []

    def parse_rocket_item(self, item):
        """解析單一火箭隊補給站項目"""
        stop_id = item.get("a", "")
        lat_str = item.get("c", "")
        lng_str = item.get("d", "")
        stop_name = item.get("g", "未命名補給站")
        j_val = item.get("j", "")
        v_val = item.get("v", "")
        expire_str = item.get("p", "")
        start_str = item.get("o", "")
        
        # 僅保留火箭隊項目
        if not ("rocket" in j_val.lower() or "^" in v_val):
            return None
            
        try:
            lat = float(lat_str)
            lng = float(lng_str)
        except ValueError:
            return None
            
        # 計算倒數與過期狀態 (強制校準為台灣時間 UTC+8)
        # 報寶貝回傳的是台灣本地時間，雲端伺服器 (Render/Linux) 預設為 UTC，時差剛好 8 小時 (480 分鐘)！
        remaining_seconds = 0
        remaining_text = "即將結束"
        tw_tz = datetime.timezone(datetime.timedelta(hours=8))
        now_tw = datetime.datetime.now(tw_tz).replace(tzinfo=None)
        
        if expire_str:
            try:
                expire_dt = datetime.datetime.strptime(expire_str, "%Y/%m/%d %H:%M:%S")
                diff = (expire_dt - now_tw).total_seconds()
                remaining_seconds = int(diff)
                if remaining_seconds <= 0:
                    return None  # 已過期跳過
                
                hours = remaining_seconds // 3600
                mins = (remaining_seconds % 3600) // 60
                secs = remaining_seconds % 60
                if hours > 0:
                    remaining_text = f"{hours}小時{mins:02d}分"
                else:
                    remaining_text = f"{mins}分{secs:02d}秒"
            except Exception:
                pass

        # 解析 v 欄位: ^GENDER^TYPE^POKE_ID^^^^
        v_parts = v_val.split("^") if v_val else []
        gender_raw = v_parts[1] if len(v_parts) > 1 else ""
        type_raw = v_parts[2] if len(v_parts) > 2 else ""
        poke_id_raw = v_parts[3] if len(v_parts) > 3 and v_parts[3] != "" else None
        
        # 取得完整火箭隊角色細節 (含性別、幹部名稱、第一隻角色預測、確定性)
        details = get_rocket_details(
            type_raw=type_raw,
            gender_raw=gender_raw,
            j_val=j_val,
            pokemon_id_from_api=poke_id_raw,
            pokemon_dict=self.pokemon_dict
        )
        
        first_pokemon_display = details["primary_first"]
        gmaps_url = f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lng:.6f}"
        
        # 精準解析所在縣市、行政區與詳細地址
        loc = resolve_taiwan_location(lat, lng, stop_name)
        
        return {
            "id": stop_id,
            "name": stop_name,
            "lat": lat,
            "lng": lng,
            "county": loc["county"],               # 縣市，例如 "台北市"
            "district": loc["district"],           # 行政區，例如 "中正區"
            "area_name": loc["area_name"],         # "台北市中正區"
            "full_address": loc["full_address"],   # "台北市中正區 · 台北車站"
            "region_group": loc["region_group"],   # "北部" / "中部" / "南部" / "東部" / "離島"
            "category": details["category"],
            "role_type": details["role_type"],     # "幹部" 或 "小兵"
            "type_name": details["type_name"],     # "龍", "水", "火", "幹部", etc.
            "type_color": details["type_color"],
            "gender": details["gender"],           # "男小兵 ♂", "女小兵 ♀", 或幹部性別
            "title": details["name"],              # 如 "龍屬性 女小兵 ♀" 或 "克里夫"
            "is_leader": details["is_leader"],
            "certainty_level": details["certainty_level"],
            "certainty_badge": details["certainty_badge"],
            "certainty_note": details["certainty_note"],
            "first_pokemon_display": first_pokemon_display,
            "first_pokemons_pool": details["first_pokemons_pool"],
            "second_pokemons": details.get("second_pokemons", []),
            "third_pokemons": details.get("third_pokemons", []),
            "catchable": details["catchable"],
            "taunt": details["taunt"],
            "counters": details["counters"],
            "start_time": start_str,
            "expire_time": expire_str,
            "remaining_seconds": remaining_seconds,
            "remaining_text": remaining_text,
            "gmaps_url": gmaps_url
        }

    def get_rockets(self, lat0=25.35, lng0=122.10, lat1=21.80, lng1=120.00):
        """抓取指定經緯度範圍內的所有火箭隊"""
        raw_items = self.fetch_raw_stops(lat0, lng0, lat1, lng1)
        results = []
        for item in raw_items:
            parsed = self.parse_rocket_item(item)
            if parsed:
                results.append(parsed)
                
        # 依剩餘時間排序
        results.sort(key=lambda x: x["remaining_seconds"], reverse=True)
        return results

    def get_rockets_by_city(self, city_name="全台灣 (全島掃描)"):
        """依預設城市/全台灣抓取火箭隊"""
        bounds = PRESET_CITIES.get(city_name, PRESET_CITIES["全台灣 (全島掃描)"])
        return self.get_rockets(bounds["lat0"], bounds["lng0"], bounds["lat1"], bounds["lng1"])

    def group_by_type(self, rocket_list):
        """將火箭隊清單依屬性進行分類彙整"""
        grouped = {}
        for r in rocket_list:
            tname = r["type_name"]
            if tname not in grouped:
                grouped[tname] = []
            grouped[tname].append(r)
        return grouped

    def filter_sure_targets(self, rocket_list):
        """篩選固定第一隻角色的目標 (幹部、阪木、卡比獸女小兵)"""
        return [r for r in rocket_list if r["is_leader"] or "卡比獸" in r["type_name"]]

    def filter_high_value(self, rocket_list):
        """篩選最熱門省時高價值火箭隊 (卡比獸/幹部 + 龍系 + 鋼系 + 格鬥)"""
        hot_types = ["卡比獸", "幹部", "龍", "鋼", "格鬥", "妖精"]
        return [r for r in rocket_list if r["is_leader"] or any(k in r["type_name"] for k in hot_types)]


def format_cli_report(rockets, region_name="全台灣"):
    """產出美觀的終端機分類報告"""
    total = len(rockets)
    lines = []
    lines.append("=" * 75)
    lines.append(f"⚡ 報寶貝火箭隊即時雷達情報 [{region_name}] (共發現 {total} 處火箭隊佔領) ⚡")
    lines.append("=" * 75)
    
    # 幹部專區
    leaders = [r for r in rockets if r["is_leader"]]
    if leaders:
        lines.append(f"\n【👑 火箭隊幹部與首領出沒情報 (共 {len(leaders)} 處)】- 賽季固定第一隻！")
        for idx, l in enumerate(leaders[:10], 1):
            lines.append(f"  [{idx}] {l['title']} | 補給站: {l['name']} | 剩餘: {l['remaining_text']}")
            lines.append(f"      📍 座標: {l['lat']:.5f}, {l['lng']:.5f} | 導航: {l['gmaps_url']}")
            lines.append(f"      🎯 第一隻出場: 【{l['first_pokemon_display']}】 | 捕捉: {', '.join(l['catchable'])}")
    else:
        lines.append("\n【👑 火箭隊幹部情報】目前夜間時段幹部尚未出沒 (幹部開放時段為每日 06:00 ~ 22:00)")
        
    # 屬性統計與分類
    grouped = {}
    for r in rockets:
        t = r["type_name"]
        grouped.setdefault(t, []).append(r)
        
    lines.append("\n【📊 火箭隊屬性分佈排行榜】")
    summary_parts = [f"{t}: {len(items)} 處" for t, items in sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)]
    lines.append("  " + " | ".join(summary_parts[:10]))
    lines.append("  " + " | ".join(summary_parts[10:]))
    
    # 各屬性詳細清單
    lines.append("\n【🎯 火箭隊各屬性男女小兵與第一隻確定性一覽】")
    for t_name, items in sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True):
        lines.append(f"\n▶ [{t_name}屬性] (共 {len(items)} 處):")
        sample = items[0]
        lines.append(f"   💬 台詞: 「{sample['taunt']}」")
        lines.append(f"   🎯 第 1 隻角色: 【{sample['certainty_level']}】 {sample['first_pokemon_display']}")
        lines.append(f"   💡 省時備註: {sample['certainty_note']}")
        lines.append(f"   🎁 可遭遇暗影: {', '.join(sample['catchable'])}")
        lines.append("   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -")
        for idx, r in enumerate(items[:3], 1):
            lines.append(f"   {idx}. 【{r['gender']}】 {r['name']} | 剩餘 {r['remaining_text']} | ({r['lat']:.4f}, {r['lng']:.4f})")
        if len(items) > 3:
            lines.append(f"      ... 尚有 {len(items) - 3} 處")
            
    lines.append("\n" + "=" * 75)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    crawler = RocketCrawler()
    print("正在向報寶貝獲取【全台灣】火箭隊數據 (約需 1~2 秒)...")
    rockets = crawler.get_rockets_by_city("全台灣 (全島掃描)")
    report = format_cli_report(rockets, region_name="全台灣")
    print(report)
