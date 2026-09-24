#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
perf_monitor.py -- live view of n-back performance, in its own process.

Reads the trial file a paradigm appends to (auxfunc/perf_stream.py) and draws
two strips that scroll together:

    accuracy   one marker per trial on a fixed line. Check = correct, cross =
               incorrect; a FILLED box means a response was expected (target),
               a HOLLOW box means it was not. So hit / miss / false alarm /
               correct rejection are all readable without a second symbol set.
    reaction   the response time of each trial as a dot on a common scale,
               joined by a line. Trials with no response leave a gap.

Runs as a separate process on purpose: it only ever reads the file, and the
paradigm never waits for it, so nothing here can add a millisecond to the
stimulus loop. Opening it late is fine -- it reads the file from the start.

    python auxfunc/perf_monitor.py --file <run>.trials.jsonl
    python auxfunc/perf_monitor.py --file <old run>.trials.jsonl   # replay
"""

import argparse
import math
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from auxfunc.perf_stream import JsonlTail
except Exception:
    from perf_stream import JsonlTail


# Palette, matching the control panel's.
C_OK      = "#27ae60"
C_BAD     = "#e74c3c"
C_MUTED   = "#95a5a6"
C_INK     = "#2c3e50"
C_GRID    = "#e4e8eb"
C_BRIDGE  = "#c3ccd3"
C_LINE    = "#7f8c8d"
C_BG      = "#ffffff"

OUTCOME_COLOR = {'hit': C_OK, 'cr': C_OK, 'miss': C_BAD, 'fa': C_BAD}
OUTCOME_LABEL = {'hit': 'hit', 'miss': 'miss', 'fa': 'false alarm', 'cr': 'correct rej.'}


class PerfMonitor(object):
    def __init__(self, root, path, window=32, poll_ms=200):
        self.root     = root
        self.path     = path
        self.window   = max(4, int(window))
        self.poll_ms  = max(50, int(poll_ms))
        self.tail     = JsonlTail(path)

        self.trials   = []          # every trial record, in arrival order
        self.meta     = {}          # the run record
        self.complete = False
        self.rt_window = 2.0        # initial y range, widened by the data

        root.title("Live performance — " + os.path.basename(path or ''))
        root.configure(bg=C_BG)
        root.minsize(340, 230)

        self._build_ui()
        self._tick()

    # ---- layout --------------------------------------------------------- #
    def _build_ui(self):
        # Two text lines and two plots, nothing else: this window sits beside
        # the control panel during a run and must not take a screen with it.
        head = tk.Frame(self.root, bg=C_BG, padx=8, pady=4)
        head.pack(fill="x")

        self.title_label = tk.Label(head, text="waiting for trials…", bg=C_BG,
                                    fg=C_INK, anchor="w",
                                    font=("TkDefaultFont", 9, "bold"))
        self.title_label.pack(fill="x")

        self.stat_label = tk.Label(head, text="", bg=C_BG, fg=C_MUTED, anchor="w",
                                   justify="left", font=("TkDefaultFont", 8))
        self.stat_label.pack(fill="x")

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=8)

        # The section captions live inside the canvases rather than in their own
        # packed rows -- two label rows cost more height than the strip itself.
        self.acc_canvas = tk.Canvas(self.root, height=48, bg=C_BG,
                                    highlightthickness=0)
        self.acc_canvas.pack(fill="x", padx=8, pady=(4, 2))

        self.rt_canvas = tk.Canvas(self.root, height=120, bg=C_BG,
                                   highlightthickness=0)
        self.rt_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        for canvas in (self.acc_canvas, self.rt_canvas):
            canvas.bind("<Configure>", lambda _event: self._redraw())

    # ---- data ----------------------------------------------------------- #
    def _tick(self):
        try:
            records = self.tail.poll()
        except Exception:
            records = []
        if records:
            self._ingest(records)
            self._redraw()
        self.root.after(self.poll_ms, self._tick)

    def _ingest(self, records):
        for record in records:
            kind = record.get('type')
            if kind == 'run':
                if record.get('event') == 'end':
                    self.complete = True
                else:
                    self.meta = record
                    try:
                        self.rt_window = max(1.0, float(record.get('rt_window', 2.0)))
                    except (TypeError, ValueError):
                        pass
            elif kind == 'trial':
                self.trials.append(record)

    # ---- drawing -------------------------------------------------------- #
    def _visible(self):
        return self.trials[-self.window:]

    def _redraw(self):
        self._draw_header()
        self._draw_accuracy()
        self._draw_rt()

    def _draw_header(self):
        subject = self.meta.get('subject')
        profile = self.meta.get('profile')
        if subject or profile:
            title = " · ".join(str(x) for x in (subject, profile) if x)
        else:
            title = "waiting for trials…" if not self.trials else "trials"
        if self.complete:
            title += "  — run complete"
        self.title_label.config(text=title)

        scored = [t for t in self.trials if not t.get('skipped')]
        if not scored:
            self.stat_label.config(text="")
            return

        correct = [t for t in scored if t.get('outcome') in ('hit', 'cr')]
        rts = [t['rt'] for t in scored
               if isinstance(t.get('rt'), (int, float)) and t.get('rt') is not None]

        # Current block, so a drift within the run is visible as it happens.
        last_block = scored[-1].get('block')
        in_block = [t for t in scored if t.get('block') == last_block]
        block_correct = [t for t in in_block if t.get('outcome') in ('hit', 'cr')]

        overall = 100.0 * len(correct) / len(scored)
        block_pct = 100.0 * len(block_correct) / len(in_block) if in_block else 0.0
        mean_rt = (sum(rts) / len(rts)) if rts else None

        block_name = scored[-1].get('name', last_block)
        self.title_label.config(
            text=f"{title}   ·   {len(scored)} trials · {overall:.1f}% correct")

        counts = {key: 0 for key in ('hit', 'miss', 'fa', 'cr')}
        for trial in scored:
            if trial.get('outcome') in counts:
                counts[trial['outcome']] += 1
        self.stat_label.config(
            text=f"{block_name}: {block_pct:.0f}%  ·  "
                 + (f"RT {mean_rt*1000:.0f} ms  ·  " if mean_rt is not None
                    else "no responses  ·  ")
                 + f"H {counts['hit']}  M {counts['miss']}  "
                   f"FA {counts['fa']}  CR {counts['cr']}")

    def _geometry(self, canvas, left=34, right=8):
        width  = max(canvas.winfo_width(), 80)
        height = max(canvas.winfo_height(), 40)
        return width, height, left, width - right

    def _x_for(self, index, x0, x1):
        """Centre of slot `index` (0..window-1) in the plotting area."""
        step = (x1 - x0) / float(self.window)
        return x0 + (index + 0.5) * step, step

    def _draw_accuracy(self):
        canvas = self.acc_canvas
        canvas.delete('all')
        width, height, x0, x1 = self._geometry(canvas)
        visible = self._visible()

        row_y = height * 0.50
        canvas.create_line(x0, row_y, x1, row_y, fill=C_GRID)
        canvas.create_text(x0, 1, anchor="nw", text="accuracy · filled = target",
                           fill=C_MUTED, font=("TkDefaultFont", 7))

        if not visible:
            canvas.create_text((x0 + x1) / 2, row_y, text="no trials yet",
                               fill=C_MUTED, font=("TkDefaultFont", 9))
            return

        first_index = len(self.trials) - len(visible)
        previous_block = None
        for slot, trial in enumerate(visible):
            x, step = self._x_for(slot, x0, x1)
            box = min(13.0, step * 0.78) / 2.0

            block = trial.get('block')
            if previous_block is not None and block != previous_block:
                # Just the rule: the header already names the current block, and
                # a label here would collide with the caption at this height.
                edge = x - step / 2.0
                canvas.create_line(edge, 10, edge, height - 11,
                                   fill=C_MUTED, dash=(2, 3))
            previous_block = block

            if trial.get('skipped'):
                canvas.create_line(x - box, row_y, x + box, row_y,
                                   fill=C_MUTED, width=2)
                continue

            outcome = trial.get('outcome', 'cr')
            color   = OUTCOME_COLOR.get(outcome, C_MUTED)
            target  = bool(trial.get('target'))
            correct = outcome in ('hit', 'cr')

            if target:
                canvas.create_rectangle(x - box, row_y - box, x + box, row_y + box,
                                        fill=color, outline=color)
                glyph = "#ffffff"
            else:
                canvas.create_rectangle(x - box, row_y - box, x + box, row_y + box,
                                        fill=C_BG, outline=color, width=1.6)
                glyph = color

            inner = box * 0.55
            if correct:                                   # check
                canvas.create_line(x - inner, row_y,
                                   x - inner * 0.15, row_y + inner,
                                   x + inner, row_y - inner,
                                   fill=glyph, width=1.8, joinstyle="round")
            else:                                         # cross
                canvas.create_line(x - inner, row_y - inner, x + inner, row_y + inner,
                                   fill=glyph, width=1.8)
                canvas.create_line(x - inner, row_y + inner, x + inner, row_y - inner,
                                   fill=glyph, width=1.8)

        # Trial numbers under the strip: first, last, and a few in between.
        label_y = height - 5
        for slot in range(len(visible)):
            number = first_index + slot + 1
            if slot == 0 or slot == len(visible) - 1 or number % 8 == 0:
                x, _ = self._x_for(slot, x0, x1)
                canvas.create_text(x, label_y, text=str(number), fill=C_MUTED,
                                   font=("TkDefaultFont", 7))

    def _draw_rt(self):
        canvas = self.rt_canvas
        canvas.delete('all')
        width, height, x0, x1 = self._geometry(canvas)
        visible = self._visible()

        top, bottom = 14, height - 6
        values = [t.get('rt') for t in visible
                  if isinstance(t.get('rt'), (int, float)) and not t.get('skipped')]
        # Scale to what is on screen, rounded up to a quarter second so the
        # axis does not twitch on every new trial. The full response window is
        # only the starting scale: 400 ms responses plotted against a 2 s
        # window sit in the bottom fifth and no drift is visible.
        if values:
            y_max = math.ceil(max(max(values) * 1.15, 0.5) / 0.25) * 0.25
        else:
            y_max = self.rt_window
        y_max = max(0.5, y_max)

        def y_for(seconds):
            return bottom - (seconds / y_max) * (bottom - top)

        # Gridlines every 0.5 s, or every 0.25 s on a short scale.
        stepping = 0.25 if y_max <= 1.2 else 0.5
        grid = stepping
        canvas.create_line(x0, bottom, x1, bottom, fill=C_GRID)
        while grid <= y_max + 1e-9:
            y = y_for(grid)
            canvas.create_line(x0, y, x1, y, fill=C_GRID)
            canvas.create_text(x0 - 4, y, anchor="e", text=f"{grid:.2f}".rstrip('0').rstrip('.'),
                               fill=C_MUTED, font=("TkDefaultFont", 7))
            grid += stepping
        canvas.create_text(x0 - 4, bottom, anchor="e", text="0", fill=C_MUTED,
                           font=("TkDefaultFont", 7))

        canvas.create_text(x0, 1, anchor="nw",
                           text=f"reaction time, seconds · last {self.window} trials",
                           fill=C_MUTED, font=("TkDefaultFont", 7))

        if not visible:
            canvas.create_text((x0 + x1) / 2, (top + bottom) / 2,
                               text="no responses yet", fill=C_MUTED,
                               font=("TkDefaultFont", 9))
            return

        # Mean of what is on screen, as a reference line.
        if values:
            mean = sum(values) / len(values)
            y = y_for(mean)
            canvas.create_line(x0, y, x1, y, fill=C_LINE, dash=(3, 4))
            canvas.create_text(x1, y - 7, anchor="e", text=f"mean {mean*1000:.0f} ms",
                               fill=C_LINE, font=("TkDefaultFont", 7))

        points = []
        for slot, trial in enumerate(visible):
            rt = trial.get('rt')
            if (isinstance(rt, (int, float)) and rt is not None
                    and not trial.get('skipped')):
                x, _ = self._x_for(slot, x0, x1)
                points.append((slot, x, y_for(min(rt, y_max))))

        # Most trials are non-targets with no response, so this series is
        # sparse by nature. A faint dashed bridge keeps the trend readable
        # across the gaps; a solid segment means two responses in a row.
        if len(points) > 1:
            canvas.create_line([value for _, x, y in points for value in (x, y)],
                               fill=C_BRIDGE, width=1.2, dash=(2, 3))
        for (slot_a, xa, ya), (slot_b, xb, yb) in zip(points, points[1:]):
            if slot_b - slot_a == 1:
                canvas.create_line(xa, ya, xb, yb, fill=C_LINE, width=1.6)

        for slot, trial in enumerate(visible):
            rt = trial.get('rt')
            if not isinstance(rt, (int, float)) or trial.get('skipped'):
                continue
            x, _ = self._x_for(slot, x0, x1)
            y = y_for(min(rt, y_max))
            color = OUTCOME_COLOR.get(trial.get('outcome'), C_MUTED)
            canvas.create_oval(x - 2.8, y - 2.8, x + 2.8, y + 2.8,
                               fill=color, outline=color)


def main():
    parser = argparse.ArgumentParser(description="Live n-back performance monitor.")
    parser.add_argument('--file', help="trial file to follow (.trials.jsonl)")
    parser.add_argument('--window', type=int, default=32,
                        help="how many trials stay on screen (default 32)")
    parser.add_argument('--poll', type=int, default=200,
                        help="refresh interval in ms (default 200)")
    parser.add_argument('--geometry', help="Tk geometry, e.g. 460x560+470+450")
    parser.add_argument('--start-dir', dest='start_dir',
                        help="folder the file picker opens in when --file is omitted")
    args = parser.parse_args()

    root = tk.Tk()

    path = args.file
    if not path:
        path = filedialog.askopenfilename(
            title="Open a trial file",
            initialdir=args.start_dir or os.getcwd(),
            filetypes=[("Trial files", "*.trials.jsonl"), ("All files", "*.*")])
        if not path:
            return 1

    if args.geometry:
        root.geometry(args.geometry)
    else:
        root.geometry("460x300")

    PerfMonitor(root, path, window=args.window, poll_ms=args.poll)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
