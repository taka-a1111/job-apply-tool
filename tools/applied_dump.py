#!/usr/bin/env python3
"""Cast の応募済みの行と応募文をまとめて取り出す（月1回の結果分析用）。

使い方: CAST_TOKEN=... python3 -I tools/applied_dump.py 出力先.json
出力: [{row, platform, title, url, reward, genre, client, body}, ...]
結果（契約・返信）は、スプレッドシートの「契約履歴」「契約クライアント」と
メモリの案件ファイルから照らし合わせる（案件DBの「結果」列は使わない）。
"""
import json, os, sys, urllib.request, concurrent.futures as cf

EXEC = "https://script.google.com/macros/s/AKfycbyKXod-eJoMSsFRLud1QC-OvqmrL4KTxhC9Tvqjp0EeAMwhp1D44hi-yZy6tw-bnsXmJg/exec"
TOKEN = os.environ["CAST_TOKEN"]


def get(url):
    for _ in range(3):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=200).read())
        except Exception as e:  # 一時的な失敗は3回まで試す
            err = e
    raise err


def main(out):
    base = f"{EXEC}?api=1&token={TOKEN}"
    first = get(f"{base}&action=rowdump&from=2&n=300")
    last = int(first["last"])
    rows = list(first["rows"])
    with cf.ThreadPoolExecutor(4) as ex:
        for part in ex.map(lambda f: get(f"{base}&action=rowdump&from={f}&n=300")["rows"],
                           range(302, last + 1, 300)):
            rows += part
    applied = [r for r in rows if r.get("status") == "応募済み"]

    def body(r):
        r = dict(r)
        r["body"] = get(f"{base}&action=savedResult&row={r['row']}").get("body", "")
        return r

    with cf.ThreadPoolExecutor(8) as ex:
        applied = list(ex.map(body, applied))
    json.dump(applied, open(out, "w"), ensure_ascii=False)
    print(json.dumps({"rows": len(rows), "applied": len(applied)}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "applied.json")
