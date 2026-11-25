"""What a million of each model's tokens take of a plan's week, fitted from the plan's days: it
hides how rates are fitted.  A rate is a plan's own meters' answer, never a price, one a model
whatever the kind of token.  The fit is exact, in fractions of what it is handed, so no tolerance
decides it: the models are a handful and the days some hundreds.
"""

from fractions import Fraction

MILLION = 1_000_000


def fitted(days):
    """{(provider, plan): {model: the points of its week a million of its tokens take}} of each
    plan of `days`, [(provider, plan, points, {model: tokens})] as `week_meters.days` gives them:
    the rates, none below zero, with the least sum over the plan's days of the squared difference
    between a day's points and what its tokens take at them, so a day with no token changes none.
    {} where the days cannot tell the plan's models apart, their tokens by model linearly
    dependent, as then no one answer fits best."""
    plans = {}
    for provider, plan, points, tokens in days:
        plans.setdefault((provider, plan), []).append((Fraction(points), tokens))
    return {plan: _least(found) for plan, found in plans.items()}


def _least(days):
    """`fitted`'s rates of one plan's [(points, {model: tokens})], by Lawson and Hanson's
    non-negative least squares: free one rate at a time, the one whose rise lowers the sum most,
    fit the free ones, and walk back to zero any that fit below it, until no held rate's rise
    lowers the sum.  Exact, so each step lowers the sum and it ends."""
    models = sorted({model for _, tokens in days for model in tokens})
    # The sum's normal equations: gram[i][j] the days' tokens of models i and j multiplied and
    # summed, aimed[i] their points by model i's tokens; the sum's slope along rate i is twice
    # gram[i] by the rates less aimed[i].
    gram = [[Fraction(sum(tokens.get(one, 0) * tokens.get(other, 0) for _, tokens in days))
             for other in models] for one in models]
    aimed = [sum(points * tokens.get(model, 0) for points, tokens in days) for model in models]
    if _solved(gram, aimed, range(len(models))) is None:
        return {}
    rates, free = [Fraction(0)] * len(models), []
    while True:
        downhill = [aim - sum(g * rate for g, rate in zip(row, rates))
                    for row, aim in zip(gram, aimed)]
        held = [i for i in range(len(models)) if i not in free and downhill[i] > 0]
        if not held:
            return {model: rate * MILLION for model, rate in zip(models, rates)}
        free.append(max(held, key=downhill.__getitem__))
        while True:
            best = _solved(gram, aimed, free)
            if all(best[i] > 0 for i in free):
                break
            # toward the free rates' best as far as none falls below zero; those it brings to
            # zero are held there
            step = min(rates[i] / (rates[i] - best[i]) for i in free if best[i] <= 0)
            rates = [rate + step * (best.get(i, 0) - rate) for i, rate in enumerate(rates)]
            free = [i for i in free if rates[i] > 0]
        rates = [best.get(i, Fraction(0)) for i in range(len(models))]


def _solved(gram, aimed, free):
    """{i: rate} of each of `free` solving the normal equations of those rates alone, the rest at
    zero, by Gauss-Jordan elimination; None where they have no one solution."""
    rows = [[gram[i][j] for j in free] + [aimed[i]] for i in free]
    for col in range(len(rows)):
        pivot = next((n for n in range(col, len(rows)) if rows[n][col]), None)
        if pivot is None:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for n, row in enumerate(rows):
            if n != col and row[col]:
                rows[n] = [a - row[col] / rows[col][col] * b for a, b in zip(row, rows[col])]
    return {i: row[-1] / row[n] for n, (i, row) in enumerate(zip(free, rows))}
