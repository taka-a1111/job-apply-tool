#!/usr/bin/env python3
"""Workship（goworkship.com）の募集中の案件を取得して Cast の importjobs に登録する。

使い方: python3 workship_import.py [--dry-run] [--limit=N] [--pages=N] [--full]
環境変数: CAST_URL（GAS の /exec URL）, CAST_TOKEN（API トークン）
一覧と詳細はログインなしで読める公開ページ（HTML）から読む。ページの取得は 1.5 秒間隔。
- 通常：募集検索 /portal/search の新しい順 N ページ（既定 8 ページ＝160件）
- --full：職種別の一覧（マーケティング・編集ライター・デザイナー・プランナーディレクター）を全ページ（初回の取り込み用）

取り込む条件（Cast の応募基準に合わせた最低限の絞り込み）
- 職種がマーケティング／編集・ライター／デザイナー／プランナー・ディレクター／フロントエンドエンジニア
- 募集終了でない
- リモートの記載があり、出社必須・常駐・派遣・正社員募集ではない
- 週4〜5日・フルタイム相当だけの案件ではない
"""
import html
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BASE = "https://goworkship.com"
WAIT = 1.5
PROFESSIONS = {"マーケティング", "編集・ライター", "デザイナー", "プランナー・ディレクター", "フロントエンドエンジニア"}
FULL_LISTS = ["occupation-marketing", "occupation-writer", "occupation-designer", "occupation-director"]

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


def list_cards(page_html):
    """一覧ページの案件カード → [(path, id, title, professions, company)]"""
    out = []
    for block in page_html.split('class="projects_item"')[1:]:
        m = re.search(r'href="(/portal/[^"/]+/job/(\d+))"', block)
        if not m:
            continue
        title = re.search(r'class="projects_item_ttl">(.*?)</h3>', block, re.S)
        prof = re.search(r'class="projects_item_profession">(.*?)</div>', block, re.S)
        comp = re.search(r'<span class="name">(.*?)</span>', block, re.S)
        out.append((m.group(1), int(m.group(2)),
                    html.unescape(re.sub(r"<[^>]+>|\s+", " ", title.group(1)).strip()) if title else "",
                    set(re.findall(r"<span>([^<]+)</span>", prof.group(1))) if prof else set(),
                    html.unescape(comp.group(1).strip()) if comp else ""))
    return out


def judge(t, whole):
    """t は案件本文（タイトル〜募集詳細情報の手前）。ページ下部の検索条件の一覧（常駐・フルタイム等）を拾わないため"""
    if "募集終了" in whole or "募集は終了" in whole:
        return "closed"
    if "派遣" in t[:400] or "派遣社員" in t or "正社員募集" in t[:400]:
        return "not_contract"
    if re.search(r"出社(頻度|必須|あり|もあり|が必要)|週\d日(程度)?の?出社|常駐|オフィス出社|一部リモ|[＠@]東京", t) and "フルリモート" not in t[:400]:
        return "office"
    if not re.search(r"リモート|リモ可|フルリモ|在宅", t):
        return "not_remote"
    if re.search(r"週[45]日|週[45]稼働|週5|100[%％]稼働|160時間|フルタイム|フルコミット", t) and not re.search(r"週[1-3]日|週[1-3]〜|週\s?(10|15|20)時間|副業", t):
        return "too_many_hours"
    return ""


def parse_detail(page_html, card):
    path, jid, title, profs, company = card
    t = text_of(page_html)
    m = re.search(r'"minValue":\s*(\d+)', page_html)
    unit = re.search(r'"unitText":\s*"(\w+)"', page_html)
    wage = int(m.group(1)) if m else 0
    if wage and unit and unit.group(1) == "HOUR":
        reward = f"{wage:,}円〜（時給）"
    elif wage:
        reward = f"{wage:,}円〜"
    else:
        reward = "応相談"
    loc = re.search(r'"addressRegion":\s*"([^"]*)"', page_html)
    start = t.find("何をやっているか")
    end = t.find("募集詳細情報", start)
    body = t[start:end if end > start else start + 8000].strip()
    top = t.find(title[:15]) if title else 0
    main = t[max(top, 0):end if end > start else start + 8000]
    tags = [x for x in ("フルリモートOK", "リモート可", "副業OK", "土日週末OK", "オンライン面談OK", "スポット案件（1ヶ月）") if x in t[max(top, 0):start]]
    head = (f"【Workship #{jid}】{title}\n"
            f"企業：{company}\n"
            f"職種：{'、'.join(sorted(profs))}\n"
            f"報酬：{reward}\n"
            f"所在地：{loc.group(1) if loc else ''}\n"
            f"特徴：{'、'.join(tags)}\n"
            "※応募条件の詳細はログイン後に表示される\n")
    return reward, (head + body)[:12000], judge(main, t)


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
    full = "--full" in sys.argv
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)
    pages = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--pages=")), 8)
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

    lists = [(f"/portal/{p}", 60) for p in FULL_LISTS] if full else [("/portal/search", pages)]
    cards, seen, skipped = [], set(), {}
    for path, maxp in lists:
        for pg in range(1, maxp + 1):
            try:
                ph = get(f"{BASE}{path}" + (f"?page={pg}" if pg > 1 else ""))
            except Exception as e:
                print("list error", path, pg, e, file=sys.stderr)
                break
            got = list_cards(ph)
            if not got:
                break
            for c in got:
                if c[1] in seen:
                    continue
                seen.add(c[1])
                if not PROFESSIONS & c[3]:
                    skipped["other_profession"] = skipped.get("other_profession", 0) + 1
                    continue
                if "SEOディレクター" in c[2]:
                    skipped["seo_director"] = skipped.get("seo_director", 0) + 1
                    continue
                if BASE + c[0] in known:
                    skipped["known"] = skipped.get("known", 0) + 1
                    continue
                cards.append(c)
            if f"?page={pg + 1}" not in ph:
                break

    jobs, sent = [], 0
    for c in cards:
        if limit and len(jobs) >= limit:
            break
        try:
            reward, fulltext, why = parse_detail(get(BASE + c[0]), c)
        except Exception as e:  # 1件の失敗で全体を止めない
            print("detail error", c[1], e, file=sys.stderr)
            continue
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        jobs.append({
            "platform": "Workship",
            "title": c[2],
            "url": BASE + c[0],
            "reward": reward,
            "summary": fulltext.split("何をやっているか", 1)[-1][:120].replace("\n", " "),
            "genre": "、".join(sorted(c[3])),
            "deadline": "",
            "entry": reward,
            "clientName": c[4],
            "fullText": fulltext,
        })
        if not dry and len(jobs) - sent >= 10:
            print(cast_import(jobs[sent:]), flush=True)
            sent = len(jobs)
    print(json.dumps({"new": len(jobs), "checked": len(cards), "skipped": skipped,
                      "titles": [j["title"][:40] for j in jobs]}, ensure_ascii=False))
    if dry:
        json.dump(jobs, open("workship_jobs.json", "w"), ensure_ascii=False, indent=1)
        return
    if len(jobs) > sent:
        print(cast_import(jobs[sent:]), flush=True)


if __name__ == "__main__":
    main()
