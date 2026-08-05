"""Tkinter UI: Width / Height / Profile Series → manufacturing package."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cad_engine.pipeline import export_job_package, generate_job
from cad_engine.profile_loader import DEFAULT_PROFILE_ID, geometry_as_engine_dict, list_profiles, load_profile
from products import ensure_builtin_products


class GeneratorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        ensure_builtin_products()
        self.title("Window CAD — Manufacturing Generator")
        self.geometry("560x520")
        self._build()

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        profiles = list_profiles() or [(DEFAULT_PROFILE_ID, DEFAULT_PROFILE_ID)]
        ttk.Label(frm, text="Profile series").grid(row=0, column=0, sticky="w", **pad)
        self.profile_var = tk.StringVar(value=profiles[0][0])
        cb = ttk.Combobox(frm, textvariable=self.profile_var, values=[p[0] for p in profiles], state="readonly", width=36)
        cb.grid(row=0, column=1, sticky="ew", **pad)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._reload_params())

        self.width_var = tk.StringVar(value="1440")
        self.height_var = tk.StringVar(value="1800")
        ttk.Label(frm, text="Overall Width (mm)").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.width_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(frm, text="Overall Height (mm)").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.height_var).grid(row=2, column=1, sticky="ew", **pad)

        ttk.Separator(frm).grid(row=3, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(frm, text="Geometry overrides (from profile JSON)", font=("", 10, "bold")).grid(
            row=4, column=0, columnspan=2, sticky="w", **pad
        )

        self.param_vars: dict[str, tk.StringVar] = {}
        self._param_widgets: list[ttk.Widget] = []
        self._frm = frm
        self._pad = pad
        self._param_row0 = 5
        self._reload_params()

        row = self._param_row0 + 12
        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Generate package…", command=self._generate).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Quit", command=self.destroy).pack(side=tk.LEFT, padx=4)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(frm, textvariable=self.status).grid(row=row + 1, column=0, columnspan=2, sticky="w")
        frm.columnconfigure(1, weight=1)

    def _reload_params(self) -> None:
        for w in getattr(self, "_param_widgets", []):
            w.destroy()
        self._param_widgets = []
        self.param_vars = {}
        defaults = geometry_as_engine_dict(load_profile(self.profile_var.get()))
        row = self._param_row0
        for key, val in defaults.items():
            if key in ("track_count", "shutter_count", "meeting_gap"):
                continue
            lab = ttk.Label(self._frm, text=key)
            lab.grid(row=row, column=0, sticky="w", **self._pad)
            var = tk.StringVar(value=str(val))
            ent = ttk.Entry(self._frm, textvariable=var)
            ent.grid(row=row, column=1, sticky="ew", **self._pad)
            self.param_vars[key] = var
            self._param_widgets.extend([lab, ent])
            row += 1

    def _generate(self) -> None:
        try:
            width = float(self.width_var.get())
            height = float(self.height_var.get())
            overrides = {k: float(v.get()) for k, v in self.param_vars.items()}
            job = generate_job(width, height, self.profile_var.get(), overrides=overrides)
            folder = filedialog.askdirectory(title="Output folder for DXF + SVG + JSON")
            if not folder:
                return
            paths = export_job_package(job, Path(folder))
            msg = "\n".join(f"{k}: {v}" for k, v in paths.items())
            if job.quotation:
                msg += f"\n\nQuote: {job.quotation.currency} {job.quotation.total:.2f}"
            self.status.set(f"Wrote package to {folder}")
            messagebox.showinfo("Done", msg)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            self.status.set(f"Error: {exc}")


def main() -> None:
    app = GeneratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
