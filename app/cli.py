"""CLI: Width × Height × Profile Series → DXF + SVG + JSON manufacturing package.

Also: Learning Engine propose / approve / list-pending (never auto-writes production).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cad_engine.pipeline import export_job_package, generate_job
from cad_engine.profile_loader import DEFAULT_PROFILE_ID, list_profiles
from products import ensure_builtin_products, list_products


def build_parser() -> argparse.ArgumentParser:
    ensure_builtin_products()
    p = argparse.ArgumentParser(
        description=(
            "Manufacturing AI Platform — aluminium windows/doors/facades. "
            "Engineering rules live in profiles/<series>.json only."
        ),
    )
    p.add_argument("--width", type=float, default=None, help="Overall width mm")
    p.add_argument("--height", type=float, default=None, help="Overall height mm")
    p.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_ID,
        help=f"Profile series id (default: {DEFAULT_PROFILE_ID}). See --list-profiles",
    )
    p.add_argument("-o", "--output", type=Path, default=None, help="Output DXF path (SVG/JSON written alongside)")
    p.add_argument("--outdir", type=Path, default=Path("output"), help="Directory for package exports")
    p.add_argument(
        "--set",
        dest="set_args",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override profile value, e.g. --set trackWidth=32 --set geometry.interlockWidth=26",
    )
    p.add_argument("--dump-layout", action="store_true")
    p.add_argument("--dump-bom", action="store_true")
    p.add_argument("--dump-params", action="store_true")
    p.add_argument("--list-profiles", action="store_true")
    p.add_argument("--list-products", action="store_true")

    # Learning Engine (approval-gated)
    p.add_argument(
        "--learn-propose",
        type=Path,
        default=None,
        metavar="SOURCE",
        help="Extract rules from DXF/JSON (PDF stub) → pending proposal only (no production write)",
    )
    p.add_argument(
        "--learn-profile-id",
        default=None,
        help="Force profile series id for --learn-propose",
    )
    p.add_argument(
        "--learn-approve",
        default=None,
        metavar="PROPOSAL_ID",
        help="Approve a pending proposal id → version snapshot + write profiles/",
    )
    p.add_argument(
        "--learn-reject",
        default=None,
        metavar="PROPOSAL_ID",
        help="Reject and archive a pending proposal",
    )
    p.add_argument(
        "--learn-list-pending",
        action="store_true",
        help="List pending learning proposals",
    )
    p.add_argument(
        "--confirmed-by",
        default="user",
        help="Attribution for approve confirmations (default: user)",
    )
    return p


def _parse_sets(items: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--set expects KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = float(v)
    return out


def _run_learning(args: argparse.Namespace) -> int:
    from learning.ingest import approve, pending_proposals, propose, reject

    if args.learn_list_pending:
        pending = pending_proposals()
        if not pending:
            print("No pending proposals.")
        for pid in pending:
            print(pid)
        return 0

    if args.learn_propose is not None:
        proposal = propose(args.learn_propose, profile_id=args.learn_profile_id)
        print(json.dumps(
            {
                "proposal_id": proposal["proposal_id"],
                "action": proposal["action"],
                "profile_id": proposal["profile_id"],
                "pending_path": proposal.get("pending_path"),
                "safety": proposal["safety"],
                "review_count": len(proposal.get("review") or []),
                "review": proposal.get("review"),
            },
            indent=2,
        ))
        print("\nProduction profiles NOT modified. Review then: --learn-approve", proposal["proposal_id"])
        return 0

    if args.learn_approve is not None:
        result = approve(args.learn_approve, confirmed_by=args.confirmed_by)
        print(json.dumps(result, indent=2))
        return 0

    if args.learn_reject is not None:
        result = reject(args.learn_reject)
        print(json.dumps(result, indent=2))
        return 0

    return -1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_builtin_products()

    if args.list_profiles:
        for pid, name in list_profiles():
            print(f"{pid}\t{name}")
        return 0
    if args.list_products:
        for pid, name in list_products():
            print(f"{pid}\t{name}")
        return 0

    learn_rc = _run_learning(args)
    if learn_rc >= 0:
        return learn_rc

    overrides = _parse_sets(args.set_args)

    if args.dump_params:
        job = generate_job(1440, 1800, args.profile, overrides=overrides or None)
        print(json.dumps({"profile_id": job.profile_id, "geometry": job.geometry_params, "path": job.profile_path}, indent=2))
        return 0

    if args.width is None or args.height is None:
        parser.error("--width and --height are required (or use a --learn-* / --list-* command)")

    job = generate_job(args.width, args.height, args.profile, overrides=overrides or None)

    if args.dump_layout:
        print(json.dumps({"geometry": job.geometry_params, "layout": job.layout_meta, "glass": [g.as_dict() for g in job.glass]}, indent=2))
    if args.dump_bom:
        print(json.dumps({"bom": [b.as_dict() for b in job.bom], "weight": job.weight.as_dict() if job.weight else None, "quotation": job.quotation.as_dict() if job.quotation else None}, indent=2))

    if args.output:
        out_dxf = Path(args.output)
        out_dir = out_dxf.parent
        base = out_dxf.stem
    else:
        out_dir = Path(args.outdir)
        base = f"{job.profile_id}_{int(args.width)}x{int(args.height)}"

    paths = export_job_package(job, out_dir, basename=base)
    for kind, path in paths.items():
        print(f"Wrote {kind.upper()}: {path.resolve()}")
    if job.quotation:
        q = job.quotation
        print(
            f"Quotation: subtotal {q.currency} {q.subtotal:.2f} + markup {q.markup_percent}% "
            f"+ GST {q.gst_percent}% = {q.currency} {q.total:.2f}"
        )
    if job.weight:
        print(f"Weight total: {job.weight.total_kg:.3f} kg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
