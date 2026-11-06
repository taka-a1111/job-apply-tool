#!/usr/bin/env python3
"""Cast のロゴコンペ用の小さな道具（2026-11-06）。環境変数 CAST_TOKEN に Cast の API トークンを入れて使う。

  queue [件数]                       作成キュー（未作成・修正メモ未反映）を /home/claude/logo/queue.json に保存して要点を表示
  attach <行>                        募集の添付ファイル（クラウドワークス）を /home/claude/logo/att/<行>/ に保存
  save <行> --sheet a.png --mark a_mark.png --svg a.svg --text 提案文.txt --price "33,000円（税込・コンペ報酬）" [--memo-done]
                                     画像（カード用の縮小版も自動で作る）を Cast に保存し、提案文と報酬を下書きに保存
  get <行> <sheet|mark|svg|thumb> <保存先>   保存した画像を取り出す（送信の添付・商標照合用）
  check <行> "結果"                  商標照合の結果を記録
  reject <行> "理由"                 作らない理由を記録（「対象外：〜」は一覧から消える、「要情報：〜」は残る）
"""
import base64, io, json, os, re, subprocess, sys

EXEC = "https://script.google.com/macros/s/AKfycbyKXod-eJoMSsFRLud1QC-OvqmrL4KTxhC9Tvqjp0EeAMwhp1D44hi-yZy6tw-bnsXmJg/exec"
TOKEN = os.environ.get("CAST_TOKEN", "")
BASE = "/home/claude/logo"


def _curl(args, data=None, timeout=200):
    cmd = ["curl", "-sL", "--max-time", str(timeout)] + args
    r = subprocess.run(cmd, input=data, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"通信エラー（curl {r.returncode}）")
    return r.stdout


def get(action, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    out = _curl([f"{EXEC}?api=1&action={action}&token={TOKEN}" + (f"&{qs}" if qs else "")])
    return json.loads(out)


def post(payload, timeout=280):
    payload = dict(payload, token=TOKEN)
    out = _curl(["--data-binary", "@-", f"{EXEC}?api=1&token={TOKEN}"], json.dumps(payload).encode(), timeout)
    return json.loads(out)


def cmd_queue(limit="5"):
    d = get("logoqueue", limit=limit)
    os.makedirs(BASE, exist_ok=True)
    json.dump(d, open(f"{BASE}/queue.json", "w"), ensure_ascii=False, indent=1)
    print(f"作成待ち {d.get('waiting', 0)} 件（このうち {len(d.get('jobs', []))} 件を {BASE}/queue.json に保存）")
    for j in d.get("jobs", []):
        tag = "修正メモの反映" if j.get("rework") else "新規"
        print(f"- 行{j['row']}［{tag}］{j['platform']}｜{j['title'][:40]}｜{j['reward']}｜締切 {j['deadline']}（残り約{j.get('hoursLeft')}時間）")
        if j.get("rework"):
            print(f"    修正メモ：{j['memo']}")


def cmd_attach(row):
    d = json.load(open(f"{BASE}/queue.json"))
    job = next((j for j in d["jobs"] if str(j["row"]) == str(row)), None)
    if not job:
        raise SystemExit("queue.json にその行がありません（先に queue を実行）")
    urls = re.findall(r"https://crowdworks\.jp/attachments/[^\s]+", job.get("body", ""))
    out = f"{BASE}/att/{row}"
    os.makedirs(out, exist_ok=True)
    for i, u in enumerate(urls, 1):
        name = f"{out}/{i}_" + u.rsplit("/", 1)[-1]
        _curl(["-A", "Mozilla/5.0", "-o", name, u], timeout=60)
        print("保存：", name)
    if not urls:
        print("添付ファイルはありません（ランサーズの添付は Chrome で見る）")


def _b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()


def _thumb(path, width=640):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "PNG", optimize=True)
    return base64.b64encode(b.getvalue()).decode()


def cmd_save(row, *rest):
    a = {}
    i = 0
    while i < len(rest):
        k = rest[i]
        if k == "--memo-done":
            a["memo_done"] = True; i += 1; continue
        a[k.lstrip("-")] = rest[i + 1]; i += 2
    sheet = a.get("sheet")
    if not sheet or not a.get("text") or not a.get("price"):
        raise SystemExit("--sheet・--text・--price は必須です")
    files = [{"kind": "sheet", "name": os.path.basename(sheet), "mime": "image/png", "data": _b64(sheet)},
             {"kind": "thumb", "name": "thumb_" + os.path.basename(sheet), "mime": "image/png", "data": _thumb(sheet)}]
    if a.get("mark"):
        files.append({"kind": "mark", "name": os.path.basename(a["mark"]), "mime": "image/png", "data": _b64(a["mark"])})
    if a.get("svg"):
        files.append({"kind": "svg", "name": os.path.basename(a["svg"]), "mime": "image/svg+xml", "data": _b64(a["svg"])})
    r = post({"action": "savelogo", "row": int(row), "files": files, "memoDone": bool(a.get("memo_done"))})
    print("画像：", json.dumps(r, ensure_ascii=False))
    if not r.get("ok"):
        raise SystemExit("画像の保存に失敗したので、提案文は保存していません")
    text = open(a["text"], encoding="utf-8").read().strip()
    r2 = post({"action": "savedraft", "row": int(row), "body": text, "price": a["price"]})
    print("提案文：", json.dumps(r2, ensure_ascii=False))


def cmd_get(row, kind, dest):
    d = get("logoimg", row=row, kind=kind)
    if not d.get("data"):
        raise SystemExit("画像がありません：" + json.dumps(d, ensure_ascii=False))
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    open(dest, "wb").write(base64.b64decode(d["data"]))
    print("保存：", dest, d.get("name", ""))


def cmd_check(row, text):
    print(json.dumps(post({"action": "logocheck", "row": int(row), "text": text}), ensure_ascii=False))


def cmd_reject(row, reason):
    print(json.dumps(post({"action": "draftskip", "rows": [int(row)], "reason": reason}), ensure_ascii=False))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("環境変数 CAST_TOKEN を設定してください")
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    fn = {"queue": cmd_queue, "attach": cmd_attach, "save": cmd_save, "get": cmd_get, "check": cmd_check, "reject": cmd_reject}.get(sys.argv[1])
    if not fn:
        raise SystemExit(__doc__)
    fn(*sys.argv[2:])
