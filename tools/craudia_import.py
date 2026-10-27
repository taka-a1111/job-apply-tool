#!/usr/bin/env python3
"""クラウディア（craudia.com）の募集中の仕事を取得して Cast の importjobs に登録する。

使い方: python3 craudia_import.py [--dry-run] [--limit=N] [--pages=N]
環境変数: CAST_URL（GAS の /exec URL）, CAST_TOKEN（API トークン）
一覧（/work_list/category1/<カテゴリ>/<ページ>）と詳細（/work_detail/<コード>）はログインなしで読める。
ページの取得は 1.5 秒間隔。

取り込む条件（Cast の応募基準に合わせた最低限の絞り込み）
- カテゴリ：システム開発・運用（2）／Webサイト・HP制作、運用管理（3）／デザイン制作（4）／ライティング・翻訳（5）
- 募集中（募集期間「あと◯日」）
- 予算の上限が 5,000 円以上、または「別途相談」
"""
import html
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BASE = "https://www.craudia.com"
WAIT = 1.5
CATEGORIES = {2: "システム開発・運用", 3: "Webサイト・HP制作、運用管理", 4: "デザイン制作", 5: "ライティング・翻訳"}
MIN_BUDGET = 5000

CAST_URL = os.environ.get("CAST_URL", "https://script.google.com/macros/s/AKfycbyKXod-eJoMSsFRLud1QC-OvqmrL4KTxhC9Tvqjp0EeAMwhp1D44hi-yZy6tw-bnsXmJg/exec")
CAST_TOKEN = os.environ.get("CAST_TOKEN", "")


def get(url, tries=3):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read().decode("utf-8", "replace")
            time.sleep(WAIT)
            return body
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(10 * (n + 1))


def text_of(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"</(p|div|li|h\d|dt|dd|span)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t　]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def yen(s):
    return [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", s or "")]


def list_items(page_html):
    out = []
    for it in page_html.split('class="work-list__item"')[1:]:
        code = re.search(r'/work_detail/(\w+)"', it)
        title = re.search(r'class="work-list__title">([^<]+)<', it)
        reward = re.search(r'work-list__reward">([^<]+)<', it)
        period = re.search(r"募集期間</dt>\s*<dd>(.*?)</dd>", it, re.S)
        client = re.search(r'class="work-list__client">.*?<span>([^<]*)</span>', it, re.S)
        if not code:
            continue
        out.append({"code": code.group(1),
                    "title": html.unescape(title.group(1).strip()) if title else "",
                    "reward": html.unescape(reward.group(1).strip()) if reward else "",
                    "period": re.sub(r"<[^>]+>|\s", "", period.group(1)) if period else "",
                    "client": html.unescape(client.group(1).strip()) if client else ""})
    return out


def wanted(item):
    if not re.search(r"あと\d+日", item["period"]):
        return False, "closed"
    r = item["reward"]
    if "別途相談" not in r:
        nums = yen(r)
        if nums and max(nums) < MIN_BUDGET:
            return False, "low_budget"
    return True, ""


def parse_detail(page_html, item, cat):
    t = text_of(page_html)
    start = t.find("お仕事概要")
    end = t.find("参加申請するには", start)
    if end < 0:
        end = t.find("この仕事への参加者", start)
    body = t[start:end if end > start else start + 8000].strip()
    dl = re.search(r"（(\d{4})年(\d{2})月(\d{2})日まで）", t)
    deadline = f"{dl.group(1)}-{dl.group(2)}-{dl.group(3)}" if dl else ""
    apps = re.search(r"参加申請\s*(\d+)\s*件", t)
    hourly = re.search(r"想定時給：\s*([\d,]+)円", t)
    head = (f"【クラウディア #{item['code']}】{item['title']}\n"
            f"依頼者：{item['client']}\n"
            f"カテゴリ：{cat}\n"
            f"予算：{item['reward']}" + (f"（想定時給 {hourly.group(1)}円）" if hourly else "") + "\n")
    entry = f"参加申請 {apps.group(1)}件" if apps else ""
    return deadline, entry, (head + body)[:12000]


def reward_text(r):
    nums = yen(r)
    if "別途相談" in r or not nums:
        return "応相談"
    if len(nums) >= 2:
        return f"{nums[0]:,}円 〜 {nums[1]:,}円"
    return f"{nums[0]:,}円" if not r.strip().startswith("～") else f"〜{nums[0]:,}円"


def cast_known_urls():
    url = f"{CAST_URL}?api=1&action=jobs&token={CAST_TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {j.get("url", "") for j in data.get("jobs", [])}


def cast_import(jobs, tries=3):
    for n in range(tries):
        try:
            payload = json.dumps({"action": "importjobs", "token": CAST_TOKEN, "jobs": jobs}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(f"{CAST_URL}?api=1&token={CAST_TOKEN}", data=payload,
                                         headers={"Content-Type": "text/plain", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", "replace")[:500]
        except Exception as e:
            if n == tries - 1:
                return f"import error: {e}"
            time.sleep(15 * (n + 1))


def main():
    dry = "--dry-run" in sys.argv
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)
    pages = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--pages=")), 3)
    known = set()
    if CAST_TOKEN:
        for n in range(3):
            try:
                known = cast_known_urls()
                break
            except Exception as e:
                if n == 2:
                    print("Cast の一覧を読めなかったため中止:", e, file=sys.stderr)
                    sys.exit(1)
                time.sleep(15)
    elif not dry:
        print("CAST_TOKEN がありません", file=sys.stderr)
        sys.exit(1)
    found, seen, skipped = [], set(), {}
    for cat, cname in CATEGORIES.items():
        for pg in range(1, pages + 1):
            path = f"/work_list/category1/{cat}" + (f"/{pg}" if pg > 1 else "")
            try:
                items = list_items(get(BASE + path))
            except Exception as e:
                print("list error", path, e, file=sys.stderr)
                break
            if not items:
                break
            for it in items:
                if it["code"] in seen:
                    continue
                seen.add(it["code"])
                ok, why = wanted(it)
                if not ok:
                    skipped[why] = skipped.get(why, 0) + 1
                    continue
                if f"{BASE}/work_detail/{it['code']}" in known:
                    skipped["known"] = skipped.get("known", 0) + 1
                    continue
                found.append((it, cname))
    if limit:
        found = found[:limit]
    jobs, sent = [], 0
    for it, cname in found:
        try:
            deadline, entry, full = parse_detail(get(f"{BASE}/work_detail/{it['code']}"), it, cname)
        except Exception as e:  # 1件の失敗で全体を止めない
            print("detail error", it["code"], e, file=sys.stderr)
            continue
        jobs.append({
            "platform": "クラウディア",
            "title": it["title"],
            "url": f"{BASE}/work_detail/{it['code']}",
            "reward": reward_text(it["reward"]),
            "summary": full.split("お仕事詳細", 1)[-1][:120].replace("\n", " "),
            "genre": cname,
            "deadline": deadline,
            "entry": entry,
            "clientName": it["client"],
            "fullText": full,
        })
        if not dry and len(jobs) - sent >= 10:
            print(cast_import(jobs[sent:]), flush=True)
            sent = len(jobs)
    print(json.dumps({"new": len(jobs), "skipped": skipped, "titles": [j["title"][:40] for j in jobs]}, ensure_ascii=False))
    if dry:
        json.dump(jobs, open("craudia_jobs.json", "w"), ensure_ascii=False, indent=1)
        return
    if len(jobs) > sent:
        print(cast_import(jobs[sent:]), flush=True)


if __name__ == "__main__":
    main()
