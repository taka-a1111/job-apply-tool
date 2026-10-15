#!/usr/bin/env python3
"""ココナラ公開依頼（募集中）を取得して Cast の importjobs に登録する。

使い方: python3 coconala_import.py [--dry-run]
環境変数: CAST_URL（GAS の /exec URL）, CAST_TOKEN（API トークン）
ページの取得は 2 秒間隔（人と同じペース）。ログインは使わない。
"""
import html
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BASE = "https://coconala.com"
# 親カテゴリ（募集中のみ）: IT相談・システム開発, ビジネス代行・事務代行, 集客・マーケティング相談,
# デザイン制作, ライティング・翻訳, Web制作・HP作成・EC構築, コンサルティング・士業,
# 生成AI活用・開発・制作, イラスト作成, 動画編集・映像制作
PARENTS = [11, 13, 16, 18, 19, 22, 27, 28, 9, 10]
# 単価が低すぎる予算帯は取り込まない（見積り希望は残す）
SKIP_BUDGET = re.compile(r"^5千円未満$")
MIN_FIXED_BUDGET = 3000  # 金額が1つだけの予算でこれ未満は取り込まない
# Cast の対象外ルールに当たるカテゴリ（SNS運用代行・テレアポ・現地作業・資格が要るもの等）
EXCLUDE_GENRES = {
    "SNSアカウント運用・作成代行", "営業代行・テレアポ相談", "小説・シナリオ制作", "ハードウェア設計・電子工作",
    "建築・パース作成・インテリア", "製品設計・プロダクトデザイン", "経理・財務・税務代行", "士業専門家への相談",
    "採用代行・労務支援・代行", "カスタマーサポート代行", "Vtuberイラスト・モデリング", "TRPGイラスト・立ち絵作成",
    "ミュージックビデオ・MV制作", "アニメーション制作", "動画撮影・素材提供", "結婚式アイテム作成・記念日デザイン",
}


def low_budget(b):
    if SKIP_BUDGET.match(b):
        return True
    m = re.fullmatch(r"([\d,]+)円", b)
    return bool(m) and int(m.group(1).replace(",", "")) < MIN_FIXED_BUDGET
WAIT = 1.5

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
    t = re.sub(r"</(p|div|li|h\d)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t　]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def parse_list(page_html):
    items = []
    for b in page_html.split('class="c-searchItemWrapper')[1:]:
        m = re.search(r'href="/requests/(\d+)"', b)
        if not m:
            continue
        cat = re.search(r'c-itemInfo_category[^>]*>\s*([^<]+?)\s*<', b)
        title = re.search(r'c-itemInfo_title[^>]*>\s*<a[^>]*>\s*([^<]+?)\s*<', b)
        flat = re.sub(r"\s+", " ", text_of(b))
        budget = re.search(r"予算 (.+?) 応募者数", flat)
        entry = re.search(r"応募者数 (\d+)", flat)
        client = re.search(r"(\S+) 投稿日時：", flat)
        items.append({
            "id": m.group(1),
            "category": html.unescape(cat.group(1)) if cat else "",
            "title": html.unescape(title.group(1)) if title else "",
            "budget": budget.group(1).replace(" ", "") if budget else "",
            "entry": entry.group(1) if entry else "",
            "client": client.group(1) if client else "",
        })
    return items


def parse_detail(page_html, item):
    t = text_of(page_html)
    flat = re.sub(r"\s+", " ", t)
    start = flat.find("予算")
    end_candidates = [flat.find(k, start) for k in ("募集内容の追記", "応募者一覧", "この仕事の内容に似ている仕事")]
    end_candidates = [e for e in end_candidates if e > start]
    body = flat[start:min(end_candidates)] if end_candidates else flat[start:start + 6000]
    body = body.replace("続きを読む", "").strip()
    dl = re.search(r"締切日 (\d{4})年(\d{1,2})月(\d{1,2})日", flat)
    deadline = f"{dl.group(1)}-{int(dl.group(2)):02d}-{int(dl.group(3)):02d}" if dl else ""
    due = re.search(r"納品希望日 (\S+)", flat)
    # 読みやすく区切る
    for k in ("納品希望日", "募集期限", "締切日", "応募状況", "開発言語", "募集内容", "添付ファイル", "参考URL", "求めるスキル", "特記事項"):
        body = body.replace(" " + k + " ", "\n" + k + "：", 1)
    body = re.sub(r"募集内容：募集内容 ", "募集内容：\n", body)
    full = (f"【ココナラ公開依頼 #{item['id']}】{item['title']}\n"
            f"カテゴリ：{item['category']}\n依頼者：{item['client']}\n{body}")
    return deadline, (due.group(1) if due else ""), full[:12000]


def cast_known_urls():
    url = f"{CAST_URL}?api=1&action=jobs&token={CAST_TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {j.get("url", "") for j in data.get("jobs", [])}


def cast_import(jobs, tries=3):
    for n in range(tries):
        try:
            return _cast_import(jobs)
        except Exception as e:
            if n == tries - 1:
                return f"import error: {e}"
            time.sleep(15 * (n + 1))


def _cast_import(jobs):
    payload = json.dumps({"action": "importjobs", "token": CAST_TOKEN, "jobs": jobs}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{CAST_URL}?api=1", data=payload, headers={"Content-Type": "text/plain", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")[:500]


def main():
    dry = "--dry-run" in sys.argv
    known = set()
    if not (dry and not CAST_TOKEN):
        for n in range(3):
            try:
                known = cast_known_urls()
                break
            except Exception as e:
                if n == 2:
                    print("Cast の一覧を読めなかったため中止:", e, file=sys.stderr)
                    sys.exit(1)
                time.sleep(15)
    found, skipped_budget = [], 0
    seen = set()
    for p in PARENTS:
        for page in range(1, 6):
            url = f"{BASE}/requests/categories/{p}?recruiting=true" + (f"&page={page}" if page > 1 else "")
            try:
                items = parse_list(get(url))
            except Exception as e:
                print("list error", p, page, e, file=sys.stderr)
                break
            for it in items:
                if it["id"] in seen:
                    continue
                seen.add(it["id"])
                if it["category"] in EXCLUDE_GENRES:
                    continue
                if low_budget(it["budget"]):
                    skipped_budget += 1
                    continue
                if f"{BASE}/requests/{it['id']}" in known:
                    continue
                found.append(it)
            if len(items) < 40:
                break
    jobs, sent = [], 0
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)
    if limit:
        found = found[:limit]
    for it in found:
        try:
            deadline, due, full = parse_detail(get(f"{BASE}/requests/{it['id']}"), it)
        except Exception as e:  # 1件の失敗で全体を止めない
            print("detail error", it["id"], e, file=sys.stderr)
            continue
        jobs.append({
            "platform": "ココナラ",
            "title": it["title"],
            "url": f"{BASE}/requests/{it['id']}",
            "reward": it["budget"] or "見積り希望",
            "summary": full.split("募集内容：", 1)[-1][:120].replace("\n", " "),
            "genre": it["category"],
            "deadline": deadline,
            "entry": f"応募 {it['entry']}人" + (f"／納品希望 {due}" if due else ""),
            "clientName": it["client"],
            "fullText": full,
        })
        if not dry and len(jobs) - sent >= 10:
            print(cast_import(jobs[sent:]), flush=True)
            sent = len(jobs)
    print(json.dumps({"new": len(jobs), "skipped_low_budget": skipped_budget,
                      "titles": [j["title"][:40] for j in jobs]}, ensure_ascii=False))
    if dry or not jobs:
        if dry:
            json.dump(jobs, open("coconala_jobs.json", "w"), ensure_ascii=False, indent=1)
        return
    if len(jobs) > sent:
        print(cast_import(jobs[sent:]), flush=True)


if __name__ == "__main__":
    main()
