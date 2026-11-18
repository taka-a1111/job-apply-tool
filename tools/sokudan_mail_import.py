#!/usr/bin/env python3
"""SOKUDAN の通知メールに載った案件を Cast に platform「SOKUDAN」で登録する（2026-11-18〜）。

使い方:
  CAST_TOKEN=... python3 -I sokudan_mail_import.py [--dry-run] [--text メール本文.txt] [案件番号 ...]
  --text には Gmail から集めた件名・本文をそのまま書いたファイルを渡す。
  sokudan.work/top/projects/<番号> と「案件No.<番号>」を拾う。番号を直接並べてもよい。

募集中（state=opened）のものだけを登録する。応募するかの判定はしない（Claude が全文を読んで決める）。
Cast に登録済みの URL は読まない。ページの取得は sokudan_import.py と同じく 1.5 秒間隔・ログインなし。
最後の行に {"new":件数,"rows":[{"row","id","title"}],"skipped":{...}} を出す。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sokudan_import as S  # noqa: E402


def ids_from_text(text):
    found = re.findall(r"sokudan\.work/top/projects/(\d+)", text)
    found += re.findall(r"案件No\.?\s*(\d+)", text)
    return found


def main():
    dry = "--dry-run" in sys.argv
    ids = [a for a in sys.argv[1:] if a.isdigit()]
    if "--text" in sys.argv:
        path = sys.argv[sys.argv.index("--text") + 1]
        ids += ids_from_text(open(path, encoding="utf-8").read())
    ids = list(dict.fromkeys(ids))
    if not S.CAST_TOKEN and not dry:
        print("CAST_TOKEN がありません", file=sys.stderr)
        sys.exit(1)
    known = S.cast_known_urls() if S.CAST_TOKEN else set()
    jobs, skipped = [], {}
    for i in ids:
        url = f"{S.BASE}/top/projects/{i}"
        if url in known:
            skipped["known"] = skipped.get("known", 0) + 1
            continue
        try:
            page = S.get(url)
            p = S.next_data(page)["props"]["pageProps"]["staticProject"]
        except Exception as e:  # 1件の失敗で全体を止めない
            print("detail error", i, e, file=sys.stderr)
            skipped["error"] = skipped.get("error", 0) + 1
            continue
        if p.get("state") != "opened":
            skipped["closed"] = skipped.get("closed", 0) + 1
            continue
        reward, corp, full = S.parse_detail(page, p)
        at = (p.get("projectAvailableTime") or {}).get("label", "")
        rt = (p.get("remoteType") or {}).get("label", "")
        jobs.append({"platform": "SOKUDAN", "title": p.get("title", ""), "url": url, "reward": reward,
                     "summary": full.split("案件概要", 1)[-1][:120].replace("\n", " "),
                     "genre": (p.get("primaryProfession") or {}).get("label", ""), "deadline": "",
                     "entry": f"{at}／{rt}", "clientName": corp, "fullText": full})
    rows = []
    if dry:
        json.dump(jobs, open("sokudan_mail_jobs.json", "w"), ensure_ascii=False, indent=1)
    else:
        for k in range(0, len(jobs), 10):
            res = S.cast_import(jobs[k:k + 10])
            try:
                for r in json.loads(res).get("rows", []):
                    if r.get("status") != "added":  # 登録済み（一覧に出ない記録済みの行を含む）
                        skipped["exists"] = skipped.get("exists", 0) + 1
                        continue
                    rows.append({"row": r.get("row"), "id": r.get("url", "").rsplit("/", 1)[-1]})
            except Exception:
                print(res, file=sys.stderr)
    titles = {j["url"].rsplit("/", 1)[-1]: j["title"] for j in jobs}
    for r in rows:
        r["title"] = titles.get(r["id"], "")[:60]
    print(json.dumps({"new": len(rows) if not dry else len(jobs), "rows": rows, "skipped": skipped}, ensure_ascii=False))


if __name__ == "__main__":
    main()
