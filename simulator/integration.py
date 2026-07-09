from types import SimpleNamespace

import numpy as np
from scipy.integrate import solve_ivp


def integrate(rhs, initial, duration, events, knots):
    """Restart RK45 at trace knots so short pulses cannot fall between solver steps."""
    boundaries = np.unique(np.r_[0.0, np.asarray(knots), duration])
    boundaries = boundaries[(boundaries >= 0) & (boundaries <= duration)]
    pieces, all_times, all_states = [], [0.0], [initial]
    hits = [[] for _ in events]
    success, message = True, ""
    state = initial
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        violated = next((i for i, event in enumerate(events) if event(start, state) <= 0), None)
        if violated is not None:
            hits[violated].append(float(start))
            break
        # A load may jump at the next knot; use its left limit for this segment.
        left_end = np.nextafter(end, start)
        piece = solve_ivp(
            lambda t, y, stop=left_end: rhs(min(t, stop), y),
            (start, end),
            state,
            rtol=1e-7,
            atol=1e-9,
            max_step=1,
            dense_output=True,
            events=events,
        )
        pieces.append(piece)
        all_times.extend(piece.t[1:])
        all_states.extend(piece.y.T[1:])
        state = piece.y[:, -1]
        for target, source in zip(hits, piece.t_events, strict=True):
            target.extend(source)
        if not piece.success or piece.status == 1:
            success, message = piece.success, piece.message
            break

    def dense(times):
        values = np.empty((len(initial), len(times)))
        if not pieces:
            return np.repeat(initial[:, None], len(times), axis=1)
        ends = np.array([piece.t[-1] for piece in pieces])
        indices = np.minimum(np.searchsorted(ends, times, side="left"), len(pieces) - 1)
        for index in np.unique(indices):
            mask = indices == index
            values[:, mask] = pieces[index].sol(np.asarray(times)[mask])
        return values

    return SimpleNamespace(
        t=np.array(all_times),
        y=np.array(all_states).T,
        sol=dense,
        t_events=hits,
        success=success,
        message=message,
    )
