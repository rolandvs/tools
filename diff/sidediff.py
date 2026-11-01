#!/usr/bin/env python3
"""
sidediff.py - side-by-side diff of two text files (JSON, .py, anything).
Standard library only (tkinter + difflib).

Usage:
    python3 sidediff.py                 # pick both files with dialogs
    python3 sidediff.py fileA fileB     # open directly

Colors:  red = only left   green = only right   yellow = changed line
         orange = changed characters inside a changed line
Keys:    n / p = next / previous difference,  r = reload
"""
import difflib
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

PREFIX = 8  # width of "12345 │ " line-number gutter
FILETYPES = [("JSON / Python", ("*.json", "*.py")), ("All files", "*")]


def load(path, normalize_json):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if normalize_json and path.lower().endswith(".json"):
        try:
            text = json.dumps(json.loads(text), indent=2, sort_keys=True,
                              ensure_ascii=False)
        except json.JSONDecodeError as e:
            messagebox.showwarning("Invalid JSON",
                                   f"{path}\n\n{e}\n\nShowing raw text instead.")
    return [line.expandtabs(4) for line in text.splitlines()]


def align(a, b, ignore_ws):
    """Return rows: (left_no, left_text, right_no, right_text, tag)."""
    key = (lambda s: " ".join(s.split())) if ignore_ws else (lambda s: s)
    sm = difflib.SequenceMatcher(None, [key(x) for x in a], [key(x) for x in b],
                                 autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append((i1 + k + 1, a[i1 + k], j1 + k + 1, b[j1 + k], "equal"))
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            li = i1 + k if i1 + k < i2 else None
            rj = j1 + k if j1 + k < j2 else None
            if li is not None and rj is not None:
                t = "replace"
            elif li is not None:
                t = "delete"
            else:
                t = "insert"
            rows.append((None if li is None else li + 1, "" if li is None else a[li],
                         None if rj is None else rj + 1, "" if rj is None else b[rj], t))
    return rows


class App:
    def __init__(self, root, path_a=None, path_b=None):
        self.root = root
        self.paths = [path_a, path_b]
        self.hunks, self.hunk_i, self.nrows = [], -1, 1
        root.title("sidediff")
        root.geometry("1400x850")

        mono = tkfont.nametofont("TkFixedFont").copy()
        mono.configure(family="Menlo" if sys.platform == "darwin" else mono.cget("family"),
                       size=12)

        # --- toolbar
        bar = tk.Frame(root)
        bar.pack(fill="x", padx=6, pady=4)
        tk.Button(bar, text="Open left…", command=lambda: self.pick(0)).pack(side="left")
        tk.Button(bar, text="Open right…", command=lambda: self.pick(1)).pack(side="left")
        tk.Button(bar, text="Swap", command=self.swap).pack(side="left", padx=(8, 0))
        tk.Button(bar, text="◀ Prev", command=lambda: self.jump(-1)).pack(side="left", padx=(8, 0))
        tk.Button(bar, text="Next ▶", command=lambda: self.jump(1)).pack(side="left")
        self.norm = tk.BooleanVar(value=True)
        self.ws = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Normalize JSON (sort keys, reindent)", variable=self.norm,
                       command=self.refresh).pack(side="left", padx=(12, 0))
        tk.Checkbutton(bar, text="Ignore whitespace", variable=self.ws,
                       command=self.refresh).pack(side="left")
        self.status = tk.Label(bar, anchor="e")
        self.status.pack(side="right")

        # --- file name labels
        names = tk.Frame(root)
        names.pack(fill="x", padx=6)
        self.lbl = [tk.Label(names, anchor="w", fg="#555"), tk.Label(names, anchor="w", fg="#555")]
        self.lbl[0].pack(side="left", fill="x", expand=True)
        self.lbl[1].pack(side="left", fill="x", expand=True)

        # --- two panes, one shared vertical scrollbar
        body = tk.Frame(root)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self.vsb = tk.Scrollbar(body, orient="vertical", command=self.yview)
        self.vsb.grid(row=0, column=2, sticky="ns")
        self.txt = []
        for col in (0, 1):
            t = tk.Text(body, wrap="none", font=mono, bg="white", fg="black",
                        insertbackground="black", undo=False)
            t.grid(row=0, column=col, sticky="nsew", padx=(0, 2))
            hsb = tk.Scrollbar(body, orient="horizontal", command=t.xview)
            hsb.grid(row=1, column=col, sticky="ew")
            t.configure(xscrollcommand=hsb.set)
            t.tag_configure("gutter", foreground="#999")
            t.tag_configure("delete", background="#ffd7d5")
            t.tag_configure("insert", background="#ccffd8")
            t.tag_configure("replace", background="#fff5b1")
            t.tag_configure("filler", background="#eeeeee")
            t.tag_configure("char", background="#ffb86b")
            t.tag_raise("char")
            self.txt.append(t)
        self.txt[0].configure(yscrollcommand=lambda f, l: self.synced(0, f, l))
        self.txt[1].configure(yscrollcommand=lambda f, l: self.synced(1, f, l))

        for key, fn in (("n", lambda e: self.jump(1)), ("p", lambda e: self.jump(-1)),
                        ("r", lambda e: self.refresh())):
            root.bind(key, fn)

        if not self.paths[0]:
            self.pick(0)
        if self.paths[0] and not self.paths[1]:
            self.pick(1)
        self.refresh()

    # scrolling: keep both panes on the same row
    def yview(self, *args):
        for t in self.txt:
            t.yview(*args)

    def synced(self, src, first, last):
        self.vsb.set(first, last)
        other = self.txt[1 - src]
        if abs(other.yview()[0] - float(first)) > 1e-9:
            other.yview_moveto(first)

    def pick(self, side):
        start = Path(self.paths[side] or self.paths[1 - side] or Path.home())
        p = filedialog.askopenfilename(
            title=f"Choose {'LEFT' if side == 0 else 'RIGHT'} file",
            initialdir=str(start if start.is_dir() else start.parent),
            filetypes=FILETYPES)
        if p:
            self.paths[side] = p
            self.refresh()

    def swap(self):
        self.paths.reverse()
        self.refresh()

    def refresh(self):
        for side in (0, 1):
            self.lbl[side].configure(text=self.paths[side] or "(no file)")
        if not all(self.paths):
            return
        try:
            a = load(self.paths[0], self.norm.get())
            b = load(self.paths[1], self.norm.get())
        except OSError as e:
            messagebox.showerror("Cannot read file", str(e))
            return
        rows = align(a, b, self.ws.get())
        self.render(rows)

    def render(self, rows):
        self.nrows = max(len(rows), 1)
        L, R = self.txt
        texts = ([], [])
        for ln, lt, rn, rt, _ in rows:
            texts[0].append(f"{ln:>5} │ {lt}" if ln else "      │ ")
            texts[1].append(f"{rn:>5} │ {rt}" if rn else "      │ ")
        for t, lines in zip(self.txt, texts):
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.insert("1.0", "\n".join(lines))

        counts = {"replace": 0, "delete": 0, "insert": 0}
        self.hunks, prev = [], "equal"
        for i, (ln, lt, rn, rt, tag) in enumerate(rows, start=1):
            for t in self.txt:
                t.tag_add("gutter", f"{i}.0", f"{i}.{PREFIX}")
            if tag != "equal":
                counts[tag] += 1
                if prev == "equal":
                    self.hunks.append(i)
                if tag == "replace":
                    L.tag_add("replace", f"{i}.0", f"{i}.end+1c")
                    R.tag_add("replace", f"{i}.0", f"{i}.end+1c")
                    sm = difflib.SequenceMatcher(None, lt, rt, autojunk=False)
                    for op, a1, a2, b1, b2 in sm.get_opcodes():
                        if op == "equal":
                            continue
                        if a2 > a1:
                            L.tag_add("char", f"{i}.{PREFIX + a1}", f"{i}.{PREFIX + a2}")
                        if b2 > b1:
                            R.tag_add("char", f"{i}.{PREFIX + b1}", f"{i}.{PREFIX + b2}")
                elif tag == "delete":
                    L.tag_add("delete", f"{i}.0", f"{i}.end+1c")
                    R.tag_add("filler", f"{i}.0", f"{i}.end+1c")
                else:
                    R.tag_add("insert", f"{i}.0", f"{i}.end+1c")
                    L.tag_add("filler", f"{i}.0", f"{i}.end+1c")
            prev = tag
        for t in self.txt:
            t.configure(state="disabled")

        self.hunk_i = -1
        if not self.hunks:
            self.status.configure(text="Identical" + (" (after normalization)" if self.norm.get() or self.ws.get() else ""),
                                  fg="#1a7f37")
        else:
            self.status.configure(
                text=f"{len(self.hunks)} block(s): {counts['replace']} changed, "
                     f"{counts['delete']} only-left, {counts['insert']} only-right lines",
                fg="#cf222e")
            self.jump(1)

    def jump(self, step):
        if not self.hunks:
            return
        self.hunk_i = (self.hunk_i + step) % len(self.hunks)
        line = self.hunks[self.hunk_i]
        frac = max(line - 6, 0) / self.nrows
        for t in self.txt:
            t.yview_moveto(frac)


if __name__ == "__main__":
    args = sys.argv[1:]
    root = tk.Tk()
    App(root, *(args + [None, None])[:2])
    root.mainloop()
