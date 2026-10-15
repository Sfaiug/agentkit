"""What the `ak` screen says of each subscription, for the tests that read it."""

from agentkit import menu, terminal


def said(cfg):
    """{label: what its cell on the grid says, then what the line under the grid says with the
    pointer on it, where it has a meter}: `52% left · resets Fri 14:00 · Fable 41%`."""
    found = {}
    for number, (_, label, left, cell) in enumerate(menu.usage_cells(cfg), 1):
        rest = terminal.plain(menu.usage_detail(cfg, number)).removeprefix(label)
        found[label] = cell + (" ·" + rest if left and rest else "")
    return found


def number(cfg, label):
    """The place of the subscription `label` on the grid, from 1."""
    return [shown for _, shown, _, _ in menu.usage_cells(cfg)].index(label) + 1
