"""Tasks return results; an actor holds state until it is reconstructed."""
import json
import os
import time
import ray

@ray.remote(num_cpus=1)
def count_words(text):
    return {'count': len(text.split()), 'pid': os.getpid()}

@ray.remote(num_cpus=1, max_restarts=1, max_task_retries=-1)
class Counter:
    def __init__(self):
        self.total = 0
    def add(self, value):
        self.total += value
        return self.total
    def inspect(self):
        return {'total': self.total, 'pid': os.getpid()}

ray.init(num_cpus=2, include_dashboard=False, object_store_memory=128 * 1024 * 1024)
try:
    tasks = ray.get([count_words.remote(s) for s in ['hello ray', 'one two three', 'kubernetes']], timeout=60)
    counts = [t['count'] for t in tasks]
    assert counts == [2, 3, 1]
    counter = Counter.remote()
    for value in counts:
        ray.get(counter.add.remote(value), timeout=30)
    before = ray.get(counter.inspect.remote(), timeout=30)
    assert before['total'] == 6
    ray.kill(counter, no_restart=False)
    # kill is asynchronous; an immediate method call may reach the old actor.
    deadline = time.monotonic() + 60
    while True:
        after = ray.get(counter.inspect.remote(), timeout=60)
        if after['pid'] != before['pid']:
            break
        if time.monotonic() > deadline:
            raise RuntimeError('Actor did not restart')
        time.sleep(0.2)
    assert after['total'] == 0
    print(json.dumps({'counts': counts, 'tasks': tasks, 'before_restart': before,
                      'after_restart': after, 'logical_cpus': ray.cluster_resources()['CPU']}, indent=2))
    print('PASS Ray: task results, actor accumulation, actor restart resets in-memory state')
finally:
    ray.shutdown()
