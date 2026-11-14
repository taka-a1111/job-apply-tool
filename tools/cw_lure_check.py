#!/usr/bin/env python3
"""クラウドワークスの勧誘目的と思われる募集を Cast から外す。

対象：Cast の未処理の行（クラウドワークス・未応募・応募文なし・記録なし・募集中。ロゴコンペは除く）
判定：次のどれかに当たったら「対象外：勧誘の疑い（…）」として draftskip で記録する（一覧から消える）
  A. 極端に安い報酬：次の2つがそろう
     1. 報酬が100円未満：公開ページの「契約金額（目安）」、または本文のテスト・トライアルの報酬
     2. クライアントが本人確認未提出
  B. 副業ライター勧誘型：ライティングの募集で、次の3つがそろう
     1. クライアントが本人確認未提出
     2. クライアントのレビューが0〜1件
     3. 募集人数3人以上／応募期限が掲載から3日以内／報酬欄が定型の幅（30,000〜50,000円・50,000〜100,000円）
        ／本文に未経験・初心者・好きな方・マニュアル完備・ジャンル多数 のどれか
  C. 過去に勧誘の返信（年齢・職業・副業・スクール経験・今後の目標・生活スタイル＋面談日程）を送ってきた
     クライアント（BLOCK_CLIENTS）、またはクライアント名に「20代」を含む

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
RE_REVIEWS = re.compile(r"\((\d+)件のレビュー\)")
RE_WANT = re.compile(r"募集人数\s*(\d+)\s*人")
RE_DATES = re.compile(r"掲載日\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*応募期限\s*(\d{4})年(\d{1,2})月(\d{1,2})日")
RE_RANGE = re.compile(r"固定報酬制\s*(?:30,000円\s*〜\s*50,000円|50,000円\s*〜\s*100,000円)")
RE_CLIENT = re.compile(r"の仕事の依頼\s+(.{1,40}?)\s+(?:[\d.]+|-)\s*\(\d+件のレビュー\)")
BEGINNER_WORDS = ["未経験", "初心者", "好きな方", "マニュアル完備", "ジャンル多数", "複数ジャンル", "ジャンルは幅広"]

# 応募後に勧誘の定型質問（年齢・職業・副業・スクール経験・今後の目標・生活スタイル＋面談日程）を送ってきたクライアント。
# 新しく見つかったら足す（cast-apply スキルの対象外22）。
BLOCK_CLIENTS = [
    "みみ20代コンテンツ", "luna.mist", "WEB-arke", "OLIVE03", "Nexova Inc.", "くまさん-B",
    "jjajajj", "rbk15qzn", "m9-1", "Natural-read", "League1", "mainkanrihtc", "株式会社HATCH",
]


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


def blocked_client(name):
    name = (name or "").strip()
    if not name:
        return ""
    if "20代" in name:
        return name
    for b in BLOCK_CLIENTS:
        if b.lower() in name.lower():
            return b
    return ""


def judge(page, client=""):
    """(勧誘の疑いか, 理由) を返す。client は Cast の clientName（なければ公開ページから読む）。"""
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"\s+", " ", text)
    unverified = "not-identity_verified" in page or "本人確認未提出" in text

    # C. 過去に勧誘の返信を送ってきたクライアント
    m = RE_CLIENT.search(text)
    page_client = m.group(1) if m else ""
    hit = blocked_client(client) or blocked_client(page_client)
    if hit:
        return True, f"過去に勧誘の返信があったクライアント（{hit}）"

    # A. 極端に安い報酬＋本人確認未提出
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

    # B. 副業ライター勧誘型
    head = text[:4000]
    writing = "ライティング" in head or "記事" in head
    m = RE_REVIEWS.search(text)
    reviews = int(m.group(1)) if m else -1
    if writing and unverified and 0 <= reviews <= 1:
        signs = []
        m = RE_WANT.search(text)
        if m and int(m.group(1)) >= 3:
            signs.append(f"募集{m.group(1)}人")
        m = RE_DATES.search(text)
        if m:
            import datetime
            a = datetime.date(*map(int, m.group(1, 2, 3)))
            b = datetime.date(*map(int, m.group(4, 5, 6)))
            if (b - a).days <= 3:
                signs.append(f"応募期限{(b - a).days}日")
        if RE_RANGE.search(text):
            signs.append("報酬欄が定型の幅")
        i = text.find("仕事の詳細")
        body = text[i:i + 3000] if i >= 0 else text
        words = [w for w in BEGINNER_WORDS if w in body]
        if words:
            signs.append("・".join(words[:2]))
        if signs:
            return True, "ライター勧誘型・本人確認未提出・レビュー" + str(reviews) + "件・" + "・".join(signs)
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
        bad, why = judge(page, j.get("clientName", ""))
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
