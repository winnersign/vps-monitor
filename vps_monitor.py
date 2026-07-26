#!/usr/bin/env python3
"""
CN2/GIA optimized route VPS stock monitor
Data: legacyvps.com API (16 providers, 700+ plans) + teddysun + direct PIDs
Budget: $15-50/year | Restock alerts via QQ email | GitHub Actions
"""

import requests, json, os, re, sys, time, smtplib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "vps_monitor_state.json")
RESULT_FILE = os.path.join(SCRIPT_DIR, "vps_monitor_result.txt")

UA = "Mozilla/5.0 (Win64; x64) AppleWebKit/537.36"
TIMEOUT = 12
CNTZ = timezone(timedelta(hours=8))
BUDGET = (15, 50)

# CN2/GIA/optimized route keywords
CN2_KW = [
    "cn2 gia", "cn2gia", "cn2-gia", "cn2 gt",
    "9929", "cmin2", "cmi",
    "optimized route", "optimized line", "direct route",
    "softbank", "iij",
    "dc6 cn2", "dc9 cn2",
]

# QQ 邮箱
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = os.environ.get("QQMAIL_USER", "")
SMTP_PASS = os.environ.get("QQMAIL_PASS", "")
NOTIFY_TO = os.environ.get("QQMAIL_TO", SMTP_USER)


def fetch(url, timeout=TIMEOUT, **kw):
    return requests.get(url, headers={"User-Agent": UA}, timeout=timeout, **kw)


def is_cn2(name, tags=""):
    t = (name + " " + tags).lower()
    for kw in CN2_KW:
        if kw in t:
            return True
    # Extra: if both "cn2" or "gia" appears and not in common non-optimized contexts
    has_cn2 = "cn2" in t and "cn2 gt" not in t
    has_gia = "gia" in t and "gia-e" not in t
    if has_cn2 or has_gia:
        return True
    # Also check Chinese tags from legacyvps
    chinese_kw = ["优化线路", "三网优化", "回程优化", "直连", "精品线路", "软银"]
    for ck in chinese_kw:
        if ck in t:
            return True
    return False


def est_yearly(price_val, cycle):
    """估算等值年付"""
    if not price_val:
        return None
    try:
        p = float(price_val)
    except:
        return None
    c = str(cycle).lower() if cycle else ""
    if any(x in c for x in ["月", "month"]):
        p *= 12
    elif any(x in c for x in ["季", "quarter"]):
        p *= 4
    elif any(x in c for x in ["半年", "semi"]):
        p *= 2
    # 年付/一次性 -> 不变
    return p if BUDGET[0] <= p <= BUDGET[1] else None


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"stocks": {}, "in_stock": [], "last": None, "initialized": False}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def send_email(subject, body_html):
    if not SMTP_USER or not SMTP_PASS:
        print("[EMAIL] 未配置，跳过")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [NOTIFY_TO], msg.as_string())
        print(f"[EMAIL] 已发送至 {NOTIFY_TO}")
        return True
    except Exception as e:
        print(f"[EMAIL] 失败: {e}")
        return False


# ======================== 来源 1: legacyvps.com API（主力） ========================

def scan_legacyvps():
    """
    传家宝VPS监控 API — 覆盖 16 家商家实时库存
    """
    items = []
    page = 1
    seen = set()
    try:
        while True:
            r = fetch(f"https://legacyvps.com/scanidc/api/stats?page={page}&page_size=200", timeout=15)
            data = r.json()
            page_data = data.get("data", [])
            if not page_data:
                break
            for plan in page_data:
                name = plan.get("plan_name", "")
                tags = plan.get("tags", "")
                if not is_cn2(name, tags):
                    continue

                uid = plan.get("unique_id", f"{plan.get('provider','')}_{plan.get('pid','')}")
                if uid in seen:
                    continue
                seen.add(uid)

                price_val = plan.get("price_val", 0)
                cycle = plan.get("cycle", "")
                provider = plan.get("provider", "未知")
                stock = plan.get("stock", 0)
                yearly = est_yearly(price_val, cycle)

                items.append({
                    "merchant": provider,
                    "plan": name,
                    "price": plan.get("price_display", ""),
                    "yearly": yearly,
                    "stock": "in_stock" if stock == 1 else "out_of_stock",
                    "tags": tags,
                    "source": "legacyvps",
                    "url": f"https://legacyvps.com{plan.get('buy_link','')}" if plan.get("buy_link") else "",
                })

            if page >= data.get("total_pages", 1) or page >= data.get("total", 1):
                break
            page += 1
            # 最多翻30页，防无限循环
            if page > 30:
                break
    except Exception as e:
        print(f"[WARN] legacyvps: {e}")
    return items


# ======================== 来源 2: teddysun 搬瓦工表 ========================

def scan_teddysun():
    items = []
    try:
        r = fetch("https://teddysun.com/bwh.html")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        for tr in soup.select("table tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 9:
                continue
            name = tds[0].get_text(strip=True)
            if not is_cn2(name):
                continue
            price_text = tds[7].get_text(strip=True)
            stock_raw = tds[8].get_text(strip=True)
            dc = tds[6].get_text(strip=True) if len(tds) > 6 else ""
            in_stock = "有货" in stock_raw

            # teddysun 价格列是年付
            nums = re.findall(r'[\d.]+', price_text.replace(",", ""))
            yearly = None
            if nums:
                v = float(nums[0])
                if BUDGET[0] <= v <= BUDGET[1]:
                    yearly = v

            items.append({
                "merchant": "BWH",
                "plan": name,
                "price": price_text,
                "yearly": yearly,
                "stock": "in_stock" if in_stock else "out_of_stock",
                "dc": dc[:80],
                "source": "teddysun",
            })
    except Exception as e:
        print(f"[WARN] teddysun: {e}")
    return items


# ======================== 来源 3: 搬瓦工直接 PID ========================

def scan_bwh_pid(pid, desc):
    try:
        url = f"https://bandwagonhost.com/cart.php?a=add&pid={pid}"
        r = fetch(url, timeout=10)
        oos = any(k in r.text.lower() for k in ["out of stock", "sold out", "缺货"])

        price_str = ""
        yearly = None
        cycles = re.findall(
            r'(?:monthly|quarterly|semi-annually|annually)[^$]*?\$([\d,.]+)',
            r.text, re.I
        )
        if cycles:
            # 找年付价格
            for i, c in enumerate(cycles):
                v = float(c.replace(",", ""))
                if i >= 3 and BUDGET[0] <= v <= BUDGET[1]:
                    yearly = v
                    price_str = f"${c}/年"
                    break
            if yearly is None and cycles:
                # 月付*12
                v = float(cycles[0].replace(",", "")) * 12
                if BUDGET[0] <= v <= BUDGET[1]:
                    yearly = v
                    price_str = f"${cycles[0]}/月 (≈${v:.0f}/年)"

        return {
            "merchant": "BWH",
            "plan": desc,
            "price": price_str,
            "yearly": yearly,
            "stock": "out_of_stock" if oos else "in_stock",
            "source": f"PID{pid}",
            "url": url,
        }
    except Exception as e:
        print(f"[WARN] PID {pid}: {e}")
        return None


def scan_bwh_pids():
    pids = {
        131: "CN2 GIA-E 10G LIMITED",
        132: "CN2 GIA-E 20G LIMITED",
        89:  "CN2 GIA SPECIAL DC9",
        145: "KVM V5 CN2 GIA 20G DC6",
        146: "KVM V5 CN2 GIA 40G DC6",
    }
    items = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(scan_bwh_pid, p, d): p for p, d in pids.items()}
        for f in as_completed(futs):
            r = f.result()
            if r:
                items.append(r)
    return items


# ======================== 主逻辑 ========================

def main():
    now = datetime.now(CNTZ)
    t0 = time.time()
    print(f"\n{'='*55}")
    print(f"CN2/GIA VPS Monitor — {now:%Y-%m-%d %H:%M} CST")
    print(f"Sources: legacyvps (16 providers) + teddysun + PIDs | Budget ${BUDGET[0]}-{BUDGET[1]}/yr")
    print(f"{'='*55}")

    all_items = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {
            ex.submit(scan_legacyvps): "legacyvps",
            ex.submit(scan_teddysun): "teddysun",
            ex.submit(scan_bwh_pids): "bwh_pid",
        }
        for f in as_completed(futs):
            src = futs[f]
            try:
                r = f.result()
                print(f"  [{src}] {len(r)} CN2 plans")
                all_items.extend(r)
            except Exception as e:
                print(f"  [{src}] 失败: {e}")

    elapsed = time.time() - t0

    # 去重
    seen = set()
    uniq = []
    for i in all_items:
        k = f"{i['merchant']}|{i['plan']}"
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    all_items = uniq

    # 分类
    in_stock = [i for i in all_items if i["stock"] == "in_stock"]
    hot = [i for i in in_stock if i.get("yearly") is not None]
    expensive = [i for i in in_stock if i.get("yearly") is None]
    watching = [i for i in all_items if i["stock"] == "out_of_stock" and i.get("yearly") is not None]

    # 按商家统计
    merchants = {}
    for i in all_items:
        m = i["merchant"]
        if m not in merchants:
            merchants[m] = {"total": 0, "in_stock": 0, "in_budget": 0}
        merchants[m]["total"] += 1
        if i["stock"] == "in_stock":
            merchants[m]["in_stock"] += 1
        if i.get("yearly") is not None and i["stock"] == "in_stock":
            merchants[m]["in_budget"] += 1

    # 变更检测
    state = load_state()
    prev_stocks = state.get("stocks", {})

    curr_stocks = {}
    curr_hot_keys = set()
    for i in all_items:
        k = f"{i['merchant']}|{i['plan']}"
        curr_stocks[k] = i["stock"]
        if i in hot:
            curr_hot_keys.add(k)

    restocks = []
    for k in curr_hot_keys:
        prev = prev_stocks.get(k)
        if state.get("initialized") and (prev == "out_of_stock" or prev not in ("in_stock",)):
            item = next((i for i in hot if f"{i['merchant']}|{i['plan']}" == k), None)
            if item:
                restocks.append(item)

    state["last"] = now.isoformat()
    state["stocks"] = curr_stocks
    state["in_stock"] = list(curr_hot_keys)
    state["initialized"] = True
    save_state(state)

    notify = bool(restocks)

    # ======== 报告 ========
    L = []
    L.append(f"## CN2/GIA VPS — {now:%m-%d %H:%M} CST")
    L.append(f"Sources: legacyvps(16 providers) + teddysun + PIDs | Budget ${BUDGET[0]}-{BUDGET[1]}/yr | {elapsed:.1f}s")
    L.append("")

    if restocks:
        L.append(f"### NEW RESTOCKS! ({len(restocks)})")
        for i in restocks:
            L.append(f"- ⚡ **[{i['merchant']}]** {i['plan']} — {i.get('price','?')}")
            if i.get("url"):
                L.append(f"  👉 {i['url']}")
            if i.get("tags"):
                L.append(f"  标签: {i['tags']}")
        L.append("")

    if hot:
        L.append(f"### IN BUDGET ({len(hot)} plans)")
        for i in hot:
            L.append(f"- [{i['merchant']}] {i['plan']} — {i.get('price','?')}")
        L.append("")

    # Merchant summary
    L.append(f"### COVERAGE ({len(merchants)} providers)")
    for m in sorted(merchants.keys()):
        s = merchants[m]
        L.append(f"- {m}: {s['total']}plans, {s['in_stock']}in-stock, {s['in_budget']}in-budget")
    L.append("")

    if watching:
        L.append(f"### WATCHING ({len(watching)} out-of-stock)")
        for i in watching[:15]:
            L.append(f"- [{i['merchant']}] {i['plan']} — {i.get('price','?')}")
        if len(watching) > 15:
            L.append(f"  ...plus {len(watching)-15} more")
        L.append("")

    if not hot and not restocks:
        L.append("No budget matches right now")
        L.append(f"   Watching {len(watching)} plans for restock")
        if expensive:
            try:
                cheapest = min([i for i in expensive if i.get("price")], key=lambda x: float(re.findall(r'[\d.]+', x.get("price","999999").replace(",",""))[0]) if re.findall(r'[\d.]+', x.get("price","999999").replace(",","")) else 999999)
                L.append(f"   Cheapest CN2 in stock: [{cheapest['merchant']}] {cheapest['plan']} — {cheapest.get('price','?')}")
            except:
                pass
        L.append("")

    L.append("---")
    L.append(f"Next: ~1hr | {now:%m-%d %H:%M}")

    text = "\n".join(L)
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Total:{len(all_items)} 