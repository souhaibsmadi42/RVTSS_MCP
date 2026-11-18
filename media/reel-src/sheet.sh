#!/bin/sh
# sheet.sh out.jpg cols files... -> contact sheet, 360x640 tiles labelled with their file name
out=$1; cols=$2; shift 2; n=$#; ins=""; fc=""; i=0
for f in "$@"; do ins="$ins -i $f"; lab=$(basename $f .png | sed 's/t_//'); fc="$fc[$i]scale=360:640,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text=$lab:fontcolor=yellow:fontsize=22:x=8:y=610[v$i];"; i=$((i+1)); done
lay=$(python3 -c "print('|'.join(f'{(k%$cols)*360}_{(k//$cols)*640}' for k in range($n)))")
ffmpeg -y -v error $ins -filter_complex "$fc$(for k in $(seq 0 $((n-1))); do printf "[v%d]" $k; done)xstack=inputs=$n:layout=$lay:fill=black" -frames:v 1 $out
