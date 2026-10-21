#!/usr/bin/env python3
"""SOKUDAN（sokudan.work）の募集中の案件を取得して Cast の importjobs に登録する。

使い方: python3 sokudan_import.py [--dry-run] [--limit=N]
環境変数: CAST_URL（GAS の /exec URL）, CAST_TOKEN（API トークン）
一覧は職種別・フルリモートの各ページ（新着40件）の __NEXT_DATA__（JSON）から読む。ログインは使わない。ページの取得は 1.5 秒間隔。

取り込む条件（Cast の応募基準に合わせた最低限の絞り込み）
- 募集中（state=opened）
- フルリモート（remote_type=full_remote）
- 稼働が週23時間以下（〜週1日・週1日・週2日）またはスポット案件
- 報酬の上限から出した時給の目安が 3,000 円以上（月額 ÷（週の稼働時間 × 4.3））
"""
import html
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BASE = "https://sokudan.work"
# 職種ID：マーケティング 106、WEBディレクター 116、AIコンサルタント 123（プロフィールで選んだ3職種）
PROFESSIONS = {106, 116, 123}
# 一覧ページは新着40件だけを返す（2ページ目以降は取れない）。1日2回の実行で新着を拾う
LIST_PATHS = [
    "/top/projects/professions/marketing",
    "/top/projects/professions/webdirector",
    "/top/projects/professions/ai_consultant",
    "/top/projects/remote_types/full_remote",
]
WAIT = 1.5
MIN_HOURLY = 3000
# 週の稼働時間の区分（projectAvailableTime.id）→ 時給の目安に使う週の時間
HOURS_BY_TIME_ID = {1: 6, 2: 12, 3: 20}
SPOT_NAMES = {"spot"}

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


def next_data(page_html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.S)
    return json.loads(m.group(1)) if m else {}


def text_of(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"</(p|div|li|h\d|dt|dd|span)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t　]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def week_hours(p):
    m = re.search(r"週(\d+)h", p.get("minWorkingHoursLabel") or "")
    if m:
        return int(m.group(1))
    return HOURS_BY_TIME_ID.get((p.get("projectAvailableTime") or {}).get("id"))


def wanted(p):
    if not PROFESSIONS & {x.get("id") for x in p.get("professions") or []}:
        return False, "other_profession"
    if p.get("state") != "opened":
        return False, "closed"
    if (p.get("remoteType") or {}).get("name") != "full_remote":
        return False, "not_full_remote"
    at = p.get("projectAvailableTime") or {}
    spot = at.get("name") in SPOT_NAMES or "スポット" in (at.get("label") or "")
    if not spot and at.get("id") not in HOURS_BY_TIME_ID:
        return False, "too_many_hours"
    mx = (p.get("maxBudget") or {}).get("id") or 0
    h = week_hours(p)
    if not spot and h and mx and mx / (h * 4.3) < MIN_HOURLY:
        return False, "low_rate"
    return True, ""


def parse_detail(page_html, p):
    t = text_of(page_html)
    start = t.find("必須スキル")
    if start < 0:
        start = t.find("案件詳細")
    end = t.find("この案件をシェアする", start)
    body = t[start:end if end > start else start + 8000].strip()
    corp = (p.get("corporation") or {}).get("name") or ""
    if p.get("corpNameHidden") or set(corp) <= {"＊"}:
        corp = "社名非公開"
    # Cast の単価判定は「◯円」の形で読むため、「8万」ではなく「80,000円」で書く
    mn = (p.get("minBudget") or {}).get("id") or 0
    mx = (p.get("maxBudget") or {}).get("id") or 0
    if mn and mx and mn != mx:
        reward = f"{mn:,}円 〜 {mx:,}円（月額）"
    elif mx or mn:
        reward = f"{(mx or mn):,}円（月額）"
    else:
        reward = "応相談"
    head = (f"【SOKUDAN #{p['id']}】{p.get('title', '')}\n"
            f"企業：{corp}\n"
            f"職種：{'、'.join(x.get('label', '') for x in p.get('professions') or [])}\n"
            f"稼働：{(p.get('projectAvailableTime') or {}).get('label', '')}（最低 {p.get('minWorkingHoursLabel') or '記載なし'}）\n"
            f"報酬：{reward}\n"
            f"勤務：{(p.get('remoteType') or {}).get('label', '')}\n"
            f"契約：{p.get('contractType') or ''}\n")
    return reward, corp, (head + body)[:12000]


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
    for path in LIST_PATHS:
        try:
            data = next_data(get(BASE + path))
            plist = data["props"]["pageProps"]["staticProjectSearchResult"]["projectList"]
        except Exception as e:
            print("list error", path, e, file=sys.stderr)
            continue
        for p in plist:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            ok, why = wanted(p)
            if not ok:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            if f"{BASE}/top/projects/{p['id']}" in known:
                skipped["known"] = skipped.get("known", 0) + 1
                continue
            found.append(p)
    if limit:
        found = found[:limit]
    jobs, sent = [], 0
    for p in found:
        try:
            reward, corp, full = parse_detail(get(f"{BASE}/top/projects/{p['id']}"), p)
        except Exception as e:  # 1件の失敗で全体を止めない
            print("detail error", p["id"], e, file=sys.stderr)
            continue
        jobs.append({
            "platform": "SOKUDAN",
            "title": p.get("title", ""),
            "url": f"{BASE}/top/projects/{p['id']}",
            "reward": reward,
            "summary": full.split("案件概要", 1)[-1][:120].replace("\n", " "),
            "genre": (p.get("primaryProfession") or {}).get("label", ""),
            "deadline": "",
            "entry": f"{(p.get('projectAvailableTime') or {}).get('label', '')}／{(p.get('remoteType') or {}).get('label', '')}",
            "clientName": corp,
            "fullText": full,
        })
        if not dry and len(jobs) - sent >= 10:
            print(cast_import(jobs[sent:]), flush=True)
            sent = len(jobs)
    print(json.dumps({"new": len(jobs), "skipped": skipped, "titles": [j["title"][:40] for j in jobs]}, ensure_ascii=False))
    if dry:
        json.dump(jobs, open("sokudan_jobs.json", "w"), ensure_ascii=False, indent=1)
        return
    if len(jobs) > sent:
        print(cast_import(jobs[sent:]), flush=True)


if __name__ == "__main__":
    main()
