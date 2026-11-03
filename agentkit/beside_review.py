"""A check beside the review: hide its thread, process scope and join.

The caller starts it with the review and joins before recording its result on the
main thread. An interrupted review adopts nothing; a resume starts the check again.
An abnormal exit stops the check's processes before joining.
"""

from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager

from . import gitcall, worker


@contextmanager
def check(name, action):
    if action is None:
        yield None
        return
    state = dict(getattr(gitcall._RUN_CONTEXT, "state", {}))
    suffix = getattr(gitcall._RUN_CONTEXT, "process_suffix", "") + f"/{name}"
    marker, result = None, None

    def run():
        nonlocal marker
        gitcall._RUN_CONTEXT.state = state
        gitcall._RUN_CONTEXT.process_suffix = suffix
        marker = gitcall.run_child_env().get(worker.RUN_MARKER)
        try:
            return action()
        finally:
            worker.kill_marked(marker)

    with ThreadPoolExecutor(max_workers=1) as pool:
        def start():
            nonlocal result
            result = pool.submit(run)

            def joined():
                pool.shutdown(wait=True)
                return result.result()

            return joined

        try:
            yield start
        except BaseException:
            if result is not None:
                result.cancel()
                # A command may be starting as its predecessor dies.
                while not result.done():
                    worker.kill_marked(marker)
                    wait((result,), timeout=0.1)
            raise
