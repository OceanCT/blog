"""A running process with independently controllable live/ready state."""
import time
from pathlib import Path

# /tmp is reset here on each process start so injected faults clear on restart.
for name in ['live', 'ready']:
    Path('/tmp/' + name).touch()
while True:
    print('live={} ready={}'.format(Path('/tmp/live').exists(), Path('/tmp/ready').exists()), flush=True)
    time.sleep(1)
