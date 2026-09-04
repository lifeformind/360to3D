#!/usr/bin/env bash
# Patch run_pilot.sh to a file-based derotation wait and relaunch it.
set -u
cd /home/ldrgx10/360_to_3D
RP=/tmp/claude-1000/-home-ldrgx10-360-to-3D/8e4e0b1c-3988-474a-9c5d-9ebe44d2b15e/scratchpad/run_pilot.sh

# replace the process-scan wait block (lines between the wait echo and the
# frame-count check) with a file-existence wait
python3 - "$RP" << 'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
s2 = re.sub(r'echo "\[pilot\] waiting for derotation.*?done\n',
            'echo "[pilot] waiting for derotation (file marker)"\n'
            'until [ -f frames/amanorth10v/c04/hull_yaw_px.npy ]; do sleep 60; done\n',
            s, flags=re.S)
open(p, 'w').write(s2)
print("patched:", "file marker" in s2)
PYEOF

setsid nohup "$RP" >> logs/pilot.log 2>&1 < /dev/null &
echo relaunched
