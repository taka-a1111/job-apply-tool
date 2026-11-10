#!/usr/bin/env python3
"""クラウドワークスの勧誘目的と思われる募集を Cast から外す。

対象：Cast の未処理の行（クラウドワークス・未応募・応募文なし・記録なし・募集中。ロゴコンペは除く）
判定：次の2つがそろったら「対象外：勧誘の疑い（…）」として draftskip で記録する（一覧から消える）
  1. 報酬が100円未満：公開ページの「契約金額（目安）」、または本文のテスト・トライアルの報酬
  2. クライアントが本人確認未提出

使い方: python3 -I cw_lure_check.py [--dry-run]
環境変数: CAST_URL（GAS の /exec URL）, CAST_TOKEN（API トークン）
公開ページはログインなしで 1.5 秒間隔で読む。
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
CAST_URL = os.environ.get("CAST_URL", "https://script.google.com/macros/s/AKfycbyKXod-eJoMSsFRLud1QC-OvqmrL4KTxhC9Tvqjp0EeAMwhp1D44hi-yZy6tw-bnsXmJg/exec")
CAST_TOKEN = os.environ.get("CAST_TOKEN", "")
WAIT = 1.5
LOW_YEN = 100  # これ未満の報酬を「極端に低い」とみなす

RE_MEYASU = re.compile(r"契約金額（目安）[:：]\s*([\d,]+)円")
RE_TEST = re.compile(r"(?:テスト|トライアル)[^。\n]{0,40}?([\d,]+)円")


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


def cast_get(action):
    url = f"{CAST_URL}?api=1&action={action}&token={CAST_TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def cast_post(payload):
    payload = dict(payload, token=CAST_TOKEN)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{CAST_URL}?api=1&token={urllib.parse.quote(CAST_TOKEN)}"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "text/plain", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")[:300]


def yen(s):
    return int(s.replace(",", ""))


def judge(page):
    """(勧誘の疑いか, 理由) を返す。"""
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    unverified = "not-identity_verified" in page or "本人確認未提出" in text
    lows = []
    m = RE_MEYASU.search(text)
    if m and yen(m.group(1)) < LOW_YEN:
        lows.append(f"契約金額の目安{m.group(1)}円")
    for t in RE_TEST.finditer(text):
        if yen(t.group(1)) < LOW_YEN:
            lows.append(f"テスト報酬{t.group(1)}円")
            break
    if unverified and lows:
        return True, "・".join(lows) + "・本人確認未提出"
    return False, ""


def targets(jobs):
    for j in jobs:
        if j.get("platform") != "クラウドワークス" or j.get("genre") == "ロゴコンペ":
            continue
        if j.get("status") == "応募済み" or j.get("body") or j.get("draftSkip"):
            continue
        if j.get("expired") or j.get("closed"):
            continue
        if "/public/jobs/" not in (j.get("url") or ""):
            continue
        yield j


def main():
    dry = "--dry-run" in sys.argv
    if not CAST_TOKEN:
        print("CAST_TOKEN が未設定です")
        return 1
    jobs = cast_get("jobs").get("jobs", [])
    checked, hits, errors = 0, [], 0
    for j in targets(jobs):
        try:
            page = get(j["url"])
        except Exception:
            errors += 1
            continue
        checked += 1
        bad, why = judge(page)
        if bad:
            hits.append((j["row"], j.get("title", ""), why))
    for row, title, why in hits:
        reason = f"対象外：勧誘の疑い（{why}）"
        res = "dry-run" if dry else cast_post({"action": "draftskip", "rows": [row], "reason": reason})
        print(f"row {row}｜{title[:40]}｜{reason}｜{res[:80]}")
    print(json.dumps({"checked": checked, "excluded": len(hits), "errors": errors, "dry_run": dry}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
