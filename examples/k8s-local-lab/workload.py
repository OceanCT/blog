import json
import os
import time
from pathlib import Path


def read(name):
    p = Path('/sys/fs/cgroup') / name
    return p.read_text().strip() if p.exists() else 'unavailable (requires cgroup v2)'

mode = os.environ['MODE']
print(json.dumps({'mode': mode, 'cpu.max': read('cpu.max'), 'memory.max': read('memory.max')}), flush=True)
if mode == 'cpu':
    before = read('cpu.stat')
    started, cpu_started = time.monotonic(), time.process_time()
    count = 0
    while time.monotonic() - started < 12:
        for _ in range(10000):
            count += 1
    wall, cpu = time.monotonic() - started, time.process_time() - cpu_started
    print(json.dumps({'iterations': count, 'wall_seconds': wall, 'cpu_seconds': cpu,
                      'average_cpu_cores': cpu / wall, 'cpu_stat_before': before,
                      'cpu_stat_after': read('cpu.stat')}), flush=True)
elif mode == 'memory':
    blocks = []
    for n in range(24):
        block = bytearray(8 * 1024 * 1024)
        for offset in range(0, len(block), 4096):
            block[offset] = 1
        blocks.append(block)
        print(json.dumps({'allocated_mib': (n + 1) * 8}), flush=True)
        time.sleep(0.1)
    print(json.dumps({'result': 'allocated 192 MiB successfully'}), flush=True)
    time.sleep(1)
