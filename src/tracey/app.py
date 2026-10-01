import struct

from PIL import Image
from potrace import POTRACE_TURNPOLICY_MINORITY, Bitmap, Path  # `potracer` library

PHOTOSHOP_TAG = 34377  # TIFF tag holding the Photoshop image resource blocks
PATH_IDS = range(2000, 2998)  # resource ids Photoshop reserves for saved paths


def trace(image: Image.Image, alphamax: float = 1) -> Path:
    bm = Bitmap(image, blacklevel=0.5)

    print(f"tracing with alphamax value: {alphamax}")
    return bm.trace(
        turdsize=2,
        turnpolicy=POTRACE_TURNPOLICY_MINORITY,
        alphamax=alphamax,
        opticurve=True,
        opttolerance=0.2,
    )


def write_svg(image: Image.Image, plist, filename: str):
    with open(filename, "w") as fp:
        fp.write(
            f'''<svg version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{image.width}" height="{image.height}" viewBox="0 0 {image.width} {image.height}">'''
        )
        parts = []
        for curve in plist:
            fs = curve.start_point
            parts.append(f"M{fs.x},{fs.y}")
            for segment in curve.segments:
                if segment.is_corner:
                    a = segment.c
                    b = segment.end_point
                    parts.append(f"L{a.x},{a.y}L{b.x},{b.y}")
                else:
                    a = segment.c1
                    b = segment.c2
                    c = segment.end_point
                    parts.append(f"C{a.x},{a.y} {b.x},{b.y} {c.x},{c.y}")
            parts.append("z")
        fp.write(
            f'<path stroke="none" fill="black" fill-rule="evenodd" d="{"".join(parts)}"/>'
        )
        fp.write("</svg>")


def _knots(curve):
    """Photoshop stores a path as knots of (handle in, anchor, handle out)."""
    p = curve.start_point
    knots = [[p, p, p]]
    for segment in curve.segments:
        if segment.is_corner:
            knots.append([segment.c] * 3)
            knots.append([segment.end_point] * 3)
        else:
            knots[-1][2] = segment.c1
            knots.append([segment.c2, segment.end_point, segment.end_point])
    # the curve is closed, so the last anchor is the start point again
    knots[0][0] = knots.pop()[0]
    return knots


def _record(selector: int, payload: bytes = b"") -> bytes:
    return struct.pack(">H24s", selector, payload)  # always 26 bytes, zero padded


def _path_resource(plist, width: int, height: int) -> bytes:
    def point(p):
        # y before x, as 8.24 fixed point fractions of the image size
        return struct.pack(
            ">ii", round(p.y / height * (1 << 24)), round(p.x / width * (1 << 24))
        )

    records = [_record(6), _record(8)]  # fill rule, initial fill
    for curve in plist:
        knots = _knots(curve)
        records.append(_record(0, struct.pack(">H", len(knots))))  # closed subpath
        for knot in knots:
            smooth = knot[0] != knot[1] and knot[2] != knot[1]
            records.append(_record(1 if smooth else 2, b"".join(map(point, knot))))
    return b"".join(records)


def _resource_block(resource_id: int, name: str, data: bytes) -> bytes:
    pascal = struct.pack("B", len(name)) + name.encode("ascii")
    pascal += b"\0" * (len(pascal) % 2)
    header = b"8BIM" + struct.pack(">H", resource_id) + pascal
    return header + struct.pack(">I", len(data)) + data + b"\0" * (len(data) % 2)


def write_tiff(image: Image.Image, plist, filename: str, name: str = "Path 1"):
    # keep the resources of a TIFF that already went through Photoshop
    tags = getattr(image, "tag_v2", {})
    resources = bytes(tags.get(PHOTOSHOP_TAG, b""))
    used = image.get_photoshop_blocks() if resources else {}
    path_id = next(i for i in PATH_IDS if i not in used)
    resources += _resource_block(
        path_id, name, _path_resource(plist, image.width, image.height)
    )
    if PHOTOSHOP_TAG in tags:
        tags[PHOTOSHOP_TAG] = resources  # Pillow prefers this over `tiffinfo`
    image.save(
        filename,
        format="TIFF",
        tiffinfo={PHOTOSHOP_TAG: resources},
        dpi=image.info.get("dpi"),
    )


def main():
    args = parse_args()
    try:
        image = Image.open(args.file)
    except OSError:
        print(f"Image ({args.file}) could not be loaded.")
        return

    out_name = args.output if args.output else args.file

    plist = trace(image, args.alphamax)
    write_tiff(image, plist, f"{out_name}.tif")
