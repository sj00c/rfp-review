#!/bin/bash
set -u
m=$1 s=$2 r=$3
E=$(cd "$(dirname "$0")" && pwd)
SKILL=$(dirname "$E")
D="$E/runs/$s-$m-$r"
rm -rf "$D" && mkdir -p "$D" "$E/runs/.empty-guides"
cp "$E/data/$s"/*.hwpx "$E/data/$s"/*.xlsx "$D/"
cd "$D" || exit 1
start=$(date +%s)
printf '%s' "스킬 파일 $SKILL/SKILL.md 를 먼저 읽고 그 절차를 그대로 따라 줘(<skill-dir>는 $SKILL). 지침은 $D/체크리스트.xlsx 하나, RFP는 $D/제안요청서.hwpx 하나야. 검토해 줘. 평가용이니 마지막에 작업 폴더는 지우지 말고 남겨 둬." |
  RFP_GUIDES="$E/runs/.empty-guides" claude -p --model "$m" --output-format json \
    --dangerously-skip-permissions --add-dir "$SKILL" > result.json 2> err.log
echo "$?" > rc.txt
echo "$(( $(date +%s) - start ))" > wall.txt
