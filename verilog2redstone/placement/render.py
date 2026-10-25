"""Dependency-free SVG rendering for placement inspection."""

from __future__ import annotations

from html import escape

from verilog2redstone.graph import ModuleGraph

from .model import BoundingBox, CostBreakdown, PlacedCell, Placement, Vec3


_PALETTE = (
    "#7dd3fc",
    "#86efac",
    "#fca5a5",
    "#c4b5fd",
    "#fcd34d",
    "#f9a8d4",
)


def render_placement_svg(
    graph: ModuleGraph,
    placement: Placement,
    bounds: BoundingBox,
    *,
    cost: CostBreakdown | None = None,
    title: str | None = None,
) -> str:
    """Render three orthographic views of a placement as standalone SVG."""

    title = title or f"Placement: {graph.name}"
    projections = (
        ("Top", 0, 2, "+x", "+z"),
        ("Side", 0, 1, "+x", "+y"),
        ("Front", 2, 1, "+z", "+y"),
    )
    panel_width = 470
    panel_height = 350
    panel_gap = 20
    header_height = 105
    svg_width = len(projections) * panel_width + (len(projections) + 1) * panel_gap
    svg_height = header_height + panel_height + 60

    logical_types = sorted(
        {
            cell.physical_cell.logical_type or cell.physical_cell.cell_id
            for cell in placement.cells.values()
        }
    )
    colors = {
        logical_type: _PALETTE[index % len(_PALETTE)]
        for index, logical_type in enumerate(logical_types)
    }

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" '
        f'height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}">',
        "<defs>",
        '<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" '
        'refY="4" orient="auto" markerUnits="strokeWidth">',
        '<path d="M 0 0 L 8 4 L 0 8 z" fill="#64748b"/>',
        "</marker>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{panel_gap}" y="34" class="title">{escape(title)}</text>',
        f'<text x="{panel_gap}" y="61" class="summary">'
        f'{len(placement.cells)} cells · box {bounds.size[0]} × '
        f'{bounds.size[1]} × {bounds.size[2]} · track pitch '
        f'{placement.track_pitch}</text>',
    ]
    if cost is not None:
        lines.append(
            f'<text x="{panel_gap}" y="84" class="summary">'
            f'cost {cost.total:g} · wire {cost.wire:g} · '
            f'cross-track {cost.cross_track:g} · '
            f'box penalty {cost.bounding_box:g} · '
            f'routing {cost.routing_constraint:g} · overlap {cost.overlap:g} · '
            f'overflow {cost.overflow:g}</text>'
        )

    for panel_index, projection in enumerate(projections):
        panel_x = panel_gap + panel_index * (panel_width + panel_gap)
        lines.extend(
            _render_projection(
                graph,
                placement,
                bounds,
                colors,
                panel_x,
                header_height,
                panel_width,
                panel_height,
                *projection,
            )
        )

    legend_y = header_height + panel_height + 34
    lines.extend(
        (
            f'<line x1="{panel_gap}" y1="{legend_y - 5}" '
            f'x2="{panel_gap + 28}" y2="{legend_y - 5}" stroke="#16a34a" '
            'stroke-width="2"/>',
            f'<text x="{panel_gap + 35}" y="{legend_y}" class="legend">'
            "aligned same-track</text>",
            f'<line x1="{panel_gap + 170}" y1="{legend_y - 5}" '
            f'x2="{panel_gap + 198}" y2="{legend_y - 5}" stroke="#ea580c" '
            'stroke-width="2"/>',
            f'<text x="{panel_gap + 205}" y="{legend_y}" class="legend">'
            "misaligned same-track</text>",
            f'<line x1="{panel_gap + 380}" y1="{legend_y - 5}" '
            f'x2="{panel_gap + 408}" y2="{legend_y - 5}" stroke="#64748b" '
            'stroke-width="2" stroke-dasharray="4 3"/>',
            f'<text x="{panel_gap + 415}" y="{legend_y}" class="legend">'
            "cross-track</text>",
            "<style>",
            ".title { font-family: sans-serif; font-size: 24px; "
            "font-weight: bold; fill: #0f172a; }",
            ".summary { font-family: sans-serif; font-size: 14px; "
            "fill: #475569; }",
            ".panel-title { font-family: sans-serif; font-size: 17px; "
            "font-weight: bold; fill: #1e293b; }",
            ".axis, .legend, .track-label { font-family: sans-serif; "
            "font-size: 12px; fill: #64748b; }",
            ".cell-label { font-family: monospace; font-size: 11px; "
            "font-weight: bold; fill: #0f172a; }",
            "</style>",
            "</svg>",
        )
    )
    return "\n".join(lines) + "\n"


def _render_projection(
    graph: ModuleGraph,
    placement: Placement,
    bounds: BoundingBox,
    colors: dict[str, str],
    panel_x: int,
    panel_y: int,
    panel_width: int,
    panel_height: int,
    name: str,
    horizontal_axis: int,
    vertical_axis: int,
    horizontal_label: str,
    vertical_label: str,
) -> list[str]:
    margin_left = 44
    margin_right = 20
    margin_top = 36
    margin_bottom = 38
    horizontal_size = bounds.size[horizontal_axis]
    vertical_size = bounds.size[vertical_axis]
    scale = min(
        (panel_width - margin_left - margin_right) / horizontal_size,
        (panel_height - margin_top - margin_bottom) / vertical_size,
    )
    plot_width = horizontal_size * scale
    plot_height = vertical_size * scale
    plot_left = panel_x + margin_left
    plot_bottom = panel_y + panel_height - margin_bottom
    plot_top = plot_bottom - plot_height

    def project(position: tuple[float, float, float]) -> tuple[float, float]:
        return (
            plot_left
            + (position[horizontal_axis] - bounds.origin[horizontal_axis]) * scale,
            plot_bottom
            - (position[vertical_axis] - bounds.origin[vertical_axis]) * scale,
        )

    lines = [
        f'<text x="{panel_x}" y="{panel_y + 18}" class="panel-title">'
        f"{name} view</text>",
        f'<rect x="{plot_left:.2f}" y="{plot_top:.2f}" '
        f'width="{plot_width:.2f}" height="{plot_height:.2f}" '
        'fill="#ffffff" stroke="#94a3b8" stroke-width="1.5"/>',
    ]

    if horizontal_axis == 0 and vertical_axis == 2 and placement.track_pitch:
        for track_id in sorted({cell.track_id for cell in placement.cells.values()}):
            track_start = placement.track_origin(track_id)
            track_end = track_start + placement.track_width(track_id) - 1
            visible_start = max(track_start, bounds.origin[2])
            visible_end = min(track_end, bounds.origin[2] + bounds.size[2])
            if visible_start >= visible_end:
                continue
            _, top = project((0.0, 0.0, float(visible_end)))
            _, bottom = project((0.0, 0.0, float(visible_start)))
            fill = "#dbeafe" if track_id % 2 == 0 else "#ede9fe"
            lines.extend(
                (
                    f'<rect x="{plot_left:.2f}" y="{top:.2f}" '
                    f'width="{plot_width:.2f}" height="{bottom - top:.2f}" '
                    f'fill="{fill}" fill-opacity="0.45"/>',
                    f'<text x="{plot_left + 4:.2f}" y="{top + 13:.2f}" '
                    f'class="track-label">T{track_id}</text>',
                )
            )

    grid_step = _grid_step(max(horizontal_size, vertical_size))
    for coordinate in range(grid_step, horizontal_size, grid_step):
        x = plot_left + coordinate * scale
        lines.append(
            f'<line x1="{x:.2f}" y1="{plot_top:.2f}" x2="{x:.2f}" '
            f'y2="{plot_bottom:.2f}" stroke="#e2e8f0"/>'
        )
    for coordinate in range(grid_step, vertical_size, grid_step):
        y = plot_bottom - coordinate * scale
        lines.append(
            f'<line x1="{plot_left:.2f}" y1="{y:.2f}" '
            f'x2="{plot_left + plot_width:.2f}" y2="{y:.2f}" '
            'stroke="#e2e8f0"/>'
        )

    for edge in graph.data_edges:
        source_cell = placement.cells.get(edge.src.node)
        destination_cell = placement.cells.get(edge.dst.node)
        if source_cell is None or destination_cell is None:
            continue
        source_position = _world_pin(source_cell, edge.src.port)
        destination_position = _world_pin(destination_cell, edge.dst.port)
        source = project(source_position)
        destination = project(destination_position)
        same_track = source_cell.track_id == destination_cell.track_id
        dz = destination_position[2] - source_position[2]
        if same_track and dz == 0:
            stroke = "#16a34a"
            dash = ""
        elif same_track:
            stroke = "#ea580c"
            dash = ""
        else:
            stroke = "#64748b"
            dash = ' stroke-dasharray="4 3"'
        lines.extend(
            (
                "<g>",
                f"<title>net {edge.net_id} · track "
                f"{source_cell.track_id}→{destination_cell.track_id} · "
                f"dz {dz:+g}</title>",
                f'<line x1="{source[0]:.2f}" y1="{source[1]:.2f}" '
                f'x2="{destination[0]:.2f}" y2="{destination[1]:.2f}" '
                f'stroke="{stroke}" stroke-width="1.7" opacity="0.8"'
                f'{dash} marker-end="url(#arrow)"/>',
                "</g>",
            )
        )

    cell_labels = {
        graph_cell: f"C{index}"
        for index, graph_cell in enumerate(sorted(placement.cells), start=1)
    }
    for cell in placement.cells.values():
        dimensions = cell.physical_cell.schematic.dimensions
        x = plot_left + (
            cell.origin[horizontal_axis] - bounds.origin[horizontal_axis]
        ) * scale
        y = plot_bottom - (
            cell.origin[vertical_axis]
            - bounds.origin[vertical_axis]
            + dimensions[vertical_axis]
        ) * scale
        width = dimensions[horizontal_axis] * scale
        height = dimensions[vertical_axis] * scale
        logical_type = cell.physical_cell.logical_type or cell.physical_cell.cell_id
        tooltip = (
            f"{cell.graph_cell} · {cell.physical_cell.cell_id} · "
            f"layer {cell.layer_id} · track {cell.track_id} · "
            f"z offset {cell.z_offset} · origin {cell.origin} · size {dimensions}"
        )
        lines.extend(
            (
                "<g>",
                f"<title>{escape(tooltip)}</title>",
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" '
                f'height="{height:.2f}" rx="3" fill="{colors[logical_type]}" '
                'fill-opacity="0.78" stroke="#334155" stroke-width="1.5"/>',
                f'<text x="{x + width / 2:.2f}" y="{y + height / 2 + 4:.2f}" '
                f'text-anchor="middle" class="cell-label">'
                f'{cell_labels[cell.graph_cell]}</text>',
                "</g>",
            )
        )
        for pin in cell.physical_cell.pins:
            pin_x, pin_y = project(
                tuple(
                    origin + offset + 0.5
                    for origin, offset in zip(cell.origin, pin.position)
                )  # type: ignore[arg-type]
            )
            color = "#2563eb" if pin.direction == "input" else "#dc2626"
            lines.append(
                f'<circle cx="{pin_x:.2f}" cy="{pin_y:.2f}" r="3.5" '
                f'fill="{color}" stroke="#ffffff" stroke-width="1.2"/>'
            )

    lines.extend(
        (
            f'<text x="{plot_left + plot_width / 2:.2f}" '
            f'y="{plot_bottom + 27:.2f}" text-anchor="middle" class="axis">'
            f"{horizontal_label}</text>",
            f'<text x="{plot_left - 29:.2f}" y="{plot_top + plot_height / 2:.2f}" '
            'text-anchor="middle" class="axis" '
            f'transform="rotate(-90 {plot_left - 29:.2f} '
            f'{plot_top + plot_height / 2:.2f})">{vertical_label}</text>',
        )
    )
    return lines


def _world_pin(cell: PlacedCell, pin_name: str) -> tuple[float, float, float]:
    pin = next(pin for pin in cell.physical_cell.pins if pin.name == pin_name)
    return tuple(
        origin + offset + 0.5
        for origin, offset in zip(cell.origin, pin.position)
    )  # type: ignore[return-value]


def _grid_step(largest_dimension: int) -> int:
    if largest_dimension <= 30:
        return 5
    if largest_dimension <= 80:
        return 10
    return 20
