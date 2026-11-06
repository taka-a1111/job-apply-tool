#!/bin/bash
# ロゴ作成の作業環境を用意する（定時タスク・チャットの両方で、ロゴを作る前に1回実行する）
# 使い方：bash tools/logo/setup.sh
# 描画の部品（glyphs.py・common.py）を /home/claude/logo に置き、フォントと描画ライブラリを入れる。
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p /home/claude/logo/fonts /home/claude/logo/out /home/claude/logo/att
cp "$HERE/glyphs.py" "$HERE/common.py" /home/claude/logo/
python3 -c "import cairosvg, fontTools, PIL" 2>/dev/null || pip install -q --break-system-packages cairosvg fonttools brotli pillow
cd /home/claude/logo/fonts
# 商用利用・ロゴ使用が認められたフリーフォント（SIL OFL）。中国語フォントは入れない
for f in cinzel cormorant-garamond m-plus-rounded-1c montserrat shippori-mincho-b1 zen-maru-gothic zen-kaku-gothic-new dela-gothic-one quicksand nunito kiwi-maru; do
  if ! ls -d fontsource-$f-*/ >/dev/null 2>&1; then
    tgz=$(npm pack "@fontsource/$f" --silent 2>/dev/null | tail -1)
    mkdir -p "fontsource-$f-x" && tar -xzf "$tgz" -C "fontsource-$f-x" && rm -f "$tgz"
  fi
done
ls /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc >/dev/null 2>&1 || echo "注意：Noto Sans CJK JP が見つかりません（日本語ゴシックは使えません）"
echo "ok: /home/claude/logo の準備ができました"
