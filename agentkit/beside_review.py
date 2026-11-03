"""A check beside the review: hide its thread, process scope and join.

The caller starts it with the review and joins before recording its result on the
main thread. An interrupted review adopts nothing; a resume starts the check again.
Leaving the context always waits, including when the reviewer raises.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from . import gitcall, worker


@contextmanager
def check(name, action):
    if action is None:
        yield None
        return
    state = dict(getattr(gitcall._RUN_CONTEXT, "state", {}))
    suffix = getattr(gitcall._RUN_CONTEXT, "process_suffix", "") + f"/{name}"

    def run():
        gitcall._RUN_CONTEXT.state = state
        gitcall._RUN_CONTEXT.process_suffix = suffix
        try:
            return action()
        finally:
            worker.kill_marked(gitcall.run_child_env().get(worker.RUN_MARKER))

    with ThreadPoolExecutor(max_workers=1) as pool:
        def start():
            result = pool.submit(run)

            def joined():
                pool.shutdown(wait=True)
                return result.result()

            return joined

        yield start
