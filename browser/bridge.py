#!/usr/bin/env python3
"""Drive the owner's persistent Chromium; disconnect without closing its tabs."""

import argparse
import atexit
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from runtime import ROOT, endpoint

# A direct CLI invocation uses the stack's private Playwright installation.
if __name__ == '__main__' and Path(sys.prefix) != ROOT / 'venv':
    python = ROOT / 'venv/bin/python'
    if python.exists():
        os.execv(str(python), [str(python), __file__, *sys.argv[1:]])

from playwright.sync_api import Error, TimeoutError, sync_playwright

ENDPOINT = endpoint()
STATE_DIRECTORY = ROOT / 'selections'
_connection = None


def connect():
    """Return (browser, persistent_context). Call disconnect() when finished.

    Uses Playwright's synchronous API. Use in a normal Python thread, outside an
    asyncio event loop. No new browser or incognito context is created.
    """
    global _connection
    if _connection is not None:
        if _connection[1].is_connected():
            return _connection[1:]
        disconnect()
    driver = sync_playwright().start()
    try:
        browser = driver.chromium.connect_over_cdp(
            ENDPOINT, timeout=15000, no_defaults=True,
        )
        if not browser.contexts:
            raise RuntimeError('Chromium has no persistent context. Restart browser-bridge-chromium.')
        context = browser.contexts[0]
        context.set_default_timeout(15000)
        _connection = (driver, browser, context)
        return browser, context
    except BaseException:
        driver.stop()
        raise


def disconnect():
    """Release the connection without closing Chromium or its tabs.

    Call from the same thread that called connect().
    """
    global _connection
    if _connection is not None:
        driver, _, _ = _connection
        _connection = None
        driver.stop()


atexit.register(disconnect)


def record_opener(target_id):
    """Note this tab's opener in agentkit's browser-tabs.json, if a run or seat opened it.

    The bridge does not import agentkit: a seat's environment is enough. A tab opened
    with neither name is left out, and the idle rule is what closes it. Bookkeeping
    must not fail the open itself.
    """
    try:
        if not isinstance(target_id, str) or not target_id:
            return
        run_id = os.environ.get('AK_PARENT_RUN') or ''
        if not run_id:
            run_dir = os.environ.get('AGENTKIT_RUN_DIR') or ''
            run_id = os.path.basename(run_dir) if run_dir else ''
        session = os.environ.get('AGENTKIT_SESSION') or ''
        opener = {}
        if run_id:
            opener['run'] = run_id
        if session:
            opener['session'] = session
        if not opener:
            return
        path = Path.home() / '.agentkit' / 'state' / 'browser-tabs.json'
        try:
            stored = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        record = stored.get(target_id)
        if not isinstance(record, dict):
            record = {}
        previous = record.get('opener') if isinstance(record.get('opener'), dict) else {}
        record['opener'] = {**previous, **opener}
        stored[target_id] = record
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(stored, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
    except (OSError, ValueError):
        return


def selection_path():
    session = os.environ.get('BRIDGE_SESSION', 'default')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', session):
        raise ValueError('BRIDGE_SESSION must be 1–64 letters, digits, dots, underscores, or hyphens.')
    return STATE_DIRECTORY / (session + '.json')


def remember_target(target):
    path = selection_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            json.dump({'target_id': target}, out)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remembered_target():
    try:
        data = json.loads(selection_path().read_text())
    except FileNotFoundError:
        raise ValueError('No selected tab for this BRIDGE_SESSION. Use open <url>, --target ID, or --page N.') from None
    if not isinstance(data, dict) or not isinstance(data.get('target_id'), str):
        raise ValueError('Invalid saved tab selection. Use open <url> to select a new tab.')
    return data['target_id']


def list_pages(context):
    """Read one browser-level snapshot, without attaching to or querying tabs."""
    session = context.browser.new_browser_cdp_session()
    try:
        private_contexts = session.send('Target.getBrowserContexts')['browserContextIds']
        targets = session.send('Target.getTargets')['targetInfos']
    finally:
        with suppress(Error):
            session.detach()
    targets = sorted((target for target in targets
                      if target['type'] == 'page'
                      and target.get('browserContextId') not in private_contexts),
                     key=lambda target: target['targetId'])
    return [{'page': index, 'target_id': target['targetId'],
             'url': target['url'], 'title': target['title']}
            for index, target in enumerate(targets)]


def target_id(context, page):
    session = context.new_cdp_session(page)
    try:
        return session.send('Target.getTargetInfo')['targetInfo']['targetId']
    finally:
        with suppress(Error):
            session.detach()


def page_targets(context):
    """Skip pages that vanish while resolving Playwright objects to target IDs."""
    for page in context.pages:
        if page.is_closed():
            continue
        try:
            target = target_id(context, page)
        except Error as error:
            if not context.browser.is_connected():
                raise
            if page.is_closed() or any(message in str(error).lower() for message in (
                'has been closed', 'session closed', 'no object with guid',
                'no target with given id', 'not attached to an active page',
            )):
                continue
            raise
        yield target, page


def ordered_pages(context):
    """Return surviving Playwright pages sorted by stable target ID."""
    return [page for _, page in sorted(page_targets(context), key=lambda item: item[0])]


def select_page(context, index=None, target=None):
    remembered = index is None and target is None
    if index is not None:
        pages = list_pages(context)
        if index < 0 or index >= len(pages):
            raise ValueError(f'Page {index} does not exist. Use pages for current indices.')
        target = pages[index]['target_id']
    elif target is None:
        target = remembered_target()
    # Resolve only the chosen identity. A disappearing tab never shifts the
    # selection to a different tab, even when a numeric index was supplied.
    for candidate, page in page_targets(context):
        if candidate == target:
            return page
    if remembered:
        raise ValueError('the selected tab was closed (idle tabs are closed after 60 min); use open <url> or --page N')
    raise ValueError('Selected tab is no longer available (closed or browser restarted). Use open <url> or a current --target ID.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('pages', help='List tab indices, stable target IDs, URLs, and titles as JSON')
    opening = commands.add_parser('open', help='Open a URL in a new persistent tab')
    opening.add_argument('url')
    for name, argument in [('screenshot', 'path'), ('eval', 'js'), ('text', None)]:
        sub = commands.add_parser(name)
        if argument:
            sub.add_argument(argument)
        selection = sub.add_mutually_exclusive_group()
        selection.add_argument('--page', type=int, help='Current zero-based index from pages')
        selection.add_argument('--target', help='Stable target_id from pages or open; default is the last tab opened in BRIDGE_SESSION')
    args = parser.parse_args()
    try:
        _, context = connect()
        if args.command == 'pages':
            print(json.dumps(list_pages(context), ensure_ascii=False, indent=2))
        elif args.command == 'open':
            selection_path()  # Validate the session name before opening a tab.
            page = context.new_page()
            target = target_id(context, page)
            remember_target(target)
            record_opener(target)
            page.bring_to_front()
            try:
                page.goto(args.url, wait_until='domcontentloaded', timeout=30000)
            except TimeoutError:
                print('Navigation timed out; the tab remains open. Inspect it with text or screenshot.', file=sys.stderr)
            info = next((item for item in list_pages(context) if item['target_id'] == target), None)
            if info is None:
                raise ValueError('The newly opened tab was closed before navigation completed.')
            print(json.dumps(info, ensure_ascii=False))
        else:
            page = select_page(context, args.page, args.target)
            if args.command == 'screenshot':
                path = Path(args.path).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path), full_page=False, timeout=15000)
                print(path)
            elif args.command == 'eval':
                print(json.dumps(page.evaluate(args.js), ensure_ascii=False))
            elif args.command == 'text':
                print(page.locator('body').inner_text())
        return 0
    except (Error, OSError, ValueError, RuntimeError) as error:
        print(f'bridge: {error}', file=sys.stderr)
        return 1
    finally:
        disconnect()


if __name__ == '__main__':
    sys.exit(main())
