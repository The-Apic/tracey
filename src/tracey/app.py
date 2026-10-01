import argparse
import struct
from collections.abc import Callable, Iterator
from itertools import count
from typing import Protocol

import numpy as np
from PIL import Image
from PIL.TiffImagePlugin import TiffImageFile
from potrace import (  # `potracer` library
    POTRACE_TURNPOLICY_MINORITY,
    Bitmap,
    Curve,
    Path,
)
from potrace.potrace import findnext, findpath, process_path, xor_path

PHOTOSHOP_TAG = 34377  # TIFF tag holding the Photoshop image resource blocks
PATH_IDS = range(2000, 2998)  # resource ids Photoshop reserves for saved paths
CLIPPING_PATH_ID = 2999  # names the saved path that is the clipping path
# The spec leaves open whether the name in the clipping path resource is padded
# (GIMP pads when writing but not when reading). An odd length needs no padding.
CLIPPING_PATH_NAME = "Clipping Path"


class Point(Protocol):
    """The points potrace hands out (`potrace.potrace._Point`)."""

    x: float
    y: float


type XY = tuple[float, float]
type Knot = tuple[XY, XY, XY]  # handle in, anchor, handle out
type Subpath = list[Knot]  # closed

MITER_LIMIT = 4  # spiking corners move at most this many times the offset


def trace(
    image: Image.Image,
    alphamax: float = 1,
    threshold: float = 0.5,
    tolerance: float = 0.2,
) -> Path:
    """Trace the dark parts of `image`, darker than `threshold` (0..1)."""
    bm = Bitmap(image, blacklevel=threshold)

    return bm.trace(
        turdsize=2,
        turnpolicy=POTRACE_TURNPOLICY_MINORITY,
        alphamax=alphamax,
        opticurve=tolerance > 0,
        opttolerance=tolerance,
    )


def load_mask(
    image: Image.Image, invert: bool = False, threshold: float = 0.5
) -> np.ndarray:
    """Boolean coverage of an alpha mask, True where the shape is.

    Uses the alpha channel when the image has one, its luminance otherwise.
    Pixels at or above `threshold` (0..1) count as inside, so on soft edges a
    lower threshold moves the edge outwards and a higher one inwards.
    """
    if image.mode in ("RGBA", "LA", "PA", "La", "RGBa"):
        band = image.getchannel("A")
    elif image.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N", "F"):
        band = image  # high bit depth grayscale, keep the precision
    else:
        band = image.convert("L")

    data = np.asarray(band)
    if data.dtype == np.uint8:
        scale = 255
    elif image.mode == "F":
        scale = 1
    else:
        scale = 65535
    mask = data >= scale * threshold
    return ~mask if invert else mask


def trace_mask(
    mask: np.ndarray,
    alphamax: float = 1,
    turdsize: int = 2,
    tolerance: float = 0.2,
    progress: Callable[[float], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """Same as `trace`, but reports progress (0..1) and can be interrupted.

    `tolerance` is how far joined curves may stray from the traced outline:
    higher values give fewer anchor points, 0 keeps every segment.

    Mirrors `potrace.potrace.bm_to_pathlist` / `Bitmap.trace` so that the
    decomposition and the curve optimisation can report back in between.
    """
    bm = np.pad(mask, [(0, 1), (0, 1)], mode="constant")
    original = bm.copy()
    height = bm.shape[0]

    # decomposition: findnext scans bottom up, so the row tells how far we are
    paths = []
    while (n := findnext(bm)) is not None:
        if cancelled():
            raise InterruptedError
        y, x = n
        path = findpath(bm, x, y + 1, original[y][x], POTRACE_TURNPOLICY_MINORITY)
        if path is None:
            raise ValueError("potrace could not decompose the mask")
        xor_path(bm, path)
        if path.area > turdsize:
            paths.append(path)
        progress(0.5 * (1 - y / height))

    # curve optimisation, path by path
    for i, path in enumerate(paths):
        if cancelled():
            raise InterruptedError
        process_path(
            [path],
            alphamax=alphamax,
            opticurve=tolerance > 0,
            opttolerance=tolerance,
        )
        progress(0.5 + 0.5 * (i + 1) / len(paths))

    progress(1)
    return Path(paths)


def write_svg(
    image: Image.Image, plist: Path, filename: str, offset: float = 0
) -> None:
    parts: list[str] = []
    for knots in subpaths(plist, offset):
        parts.append("M{},{}".format(*knots[0][1]))
        # each knot pair is a cubic, corners just have their handles on the anchor
        for (_, _, (ax, ay)), ((bx, by), (cx, cy), _) in zip(
            knots, knots[1:] + knots[:1], strict=True
        ):
            parts.append(f"C{ax},{ay} {bx},{by} {cx},{cy}")
        parts.append("z")

    with open(filename, "w") as fp:
        fp.write(
            f'''<svg version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{image.width}" height="{image.height}" viewBox="0 0 {image.width} {image.height}">'''
        )
        fp.write(
            f'<path stroke="none" fill="black" fill-rule="evenodd" d="{"".join(parts)}"/>'
        )
        fp.write("</svg>")


def _xy(p: Point) -> XY:
    return (p.x, p.y)


def _knots(curve: Curve) -> Subpath:
    """Photoshop stores a path as knots of (handle in, anchor, handle out)."""
    start = curve.start_point
    assert start is not None  # only empty curves lack one, potrace never returns those
    p = _xy(start)
    knots: list[list[XY]] = [[p, p, p]]
    for segment in curve.segments:
        if segment.is_corner:
            knots.append([_xy(segment.c)] * 3)
            knots.append([_xy(segment.end_point)] * 3)
        else:
            knots[-1][2] = _xy(segment.c1)
            end = _xy(segment.end_point)
            knots.append([_xy(segment.c2), end, end])
    # the curve is closed, so the last anchor is the start point again
    knots[0][0] = knots.pop()[0]
    return [(a, b, c) for a, b, c in knots]


def _offset(knots: Subpath, distance: float) -> Subpath:
    """Move a closed path `distance` px outwards (negative: inwards).

    Tiller-Hanson: every edge of the control polygon (anchors and handles) is
    shifted along its normal, the points move to where the shifted edges meet.
    Exact for straight edges, a close approximation for curves as long as the
    distance stays below their radius.
    """
    points = np.array([p for knot in knots for p in knot], dtype=float)
    # corner knots repeat their anchor as handles: work on the distinct points
    distinct = np.any(points != np.roll(points, 1, axis=0), axis=1)
    if distinct.sum() < 3:
        return knots  # degenerate, nothing to offset
    run = (np.cumsum(distinct) - 1) % distinct.sum()  # point → its distinct point
    unique = points[distinct]

    def normals(edges: np.ndarray) -> np.ndarray:
        edges = edges / np.hypot(edges[:, 0], edges[:, 1])[:, None]
        return np.stack([edges[:, 1], -edges[:, 0]], axis=1)  # potrace fills left

    n_in = normals(unique - np.roll(unique, 1, axis=0))
    n_out = normals(np.roll(unique, -1, axis=0) - unique)
    cos = np.sum(n_in * n_out, axis=1)
    # meet point of both shifted edges; n_out alone where the polygon doubles back
    doubles_back = cos < -0.999
    scale = distance / np.where(doubles_back, 1, 1 + cos)
    shift = np.where(doubles_back[:, None], n_out, n_in + n_out) * scale[:, None]
    length = np.hypot(shift[:, 0], shift[:, 1])
    # cap corners that would spike out of the shape; corners pulled into it must
    # move all the way, or the shifted edges cross and leave a loop behind
    spikes = (n_in[:, 0] * n_out[:, 1] - n_in[:, 1] * n_out[:, 0]) * distance > 0
    limit = MITER_LIMIT * abs(distance)
    cap = np.minimum(1, limit / np.maximum(length, 1e-12))
    shift *= np.where(spikes, cap, 1)[:, None]

    moved = _untangle(unique, unique + shift)[run]
    xy = [(float(x), float(y)) for x, y in moved]
    return [(xy[i], xy[i + 1], xy[i + 2]) for i in range(0, len(xy), 3)]


def _untangle(before: np.ndarray, after: np.ndarray, rounds: int = 32) -> np.ndarray:
    """Collapse edges the offset turned around, the loops it leaves at sharp tips.

    A valid offset keeps every edge pointing the same way, so a reversed edge
    is always an artefact: both its ends move to its middle.
    """
    edges = np.roll(before, -1, axis=0) - before
    after = after.copy()
    for _ in range(rounds):
        flipped = np.sum((np.roll(after, -1, axis=0) - after) * edges, axis=1) < 0
        if not flipped.any():
            break
        for i in np.flatnonzero(flipped):
            j = (i + 1) % len(after)
            after[i] = after[j] = (after[i] + after[j]) / 2
    return after


def subpaths(plist: Path, offset: float = 0) -> list[Subpath]:
    """The traced curves as Photoshop knots, grown by `offset` px if given."""
    knots = [_knots(curve) for curve in plist]
    return [_offset(k, offset) for k in knots] if offset else knots


def _record(selector: int, payload: bytes = b"") -> bytes:
    return struct.pack(">H24s", selector, payload)  # always 26 bytes, zero padded


def _path_resource(paths: list[Subpath], width: float, height: float) -> bytes:
    def point(p: XY) -> bytes:
        # y before x, as 8.24 fixed point fractions of the image size
        x, y = p
        return struct.pack(
            ">ii", round(y / height * (1 << 24)), round(x / width * (1 << 24))
        )

    records = [_record(6), _record(8)]  # fill rule, initial fill
    for knots in paths:
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


def _split_resources(data: bytes) -> list[tuple[int, bytes]]:
    """Photoshop image resource blocks as (id, whole block) pairs."""
    blocks = []
    i = 0
    while i + 12 <= len(data) and data[i : i + 4] == b"8BIM":
        (resource_id,) = struct.unpack_from(">H", data, i + 4)
        name = 1 + data[i + 6]
        name += name % 2
        (size,) = struct.unpack_from(">I", data, i + 6 + name)
        end = i + 6 + name + 4 + size + size % 2
        blocks.append((resource_id, data[i:end]))
        i = end
    return blocks


def _block_name(block: bytes) -> str:
    return block[7 : 7 + block[6]].decode("latin-1")


def _clipping_names() -> Iterator[str]:
    """Names for the clipping path, odd lengths only (see CLIPPING_PATH_NAME)."""
    yield CLIPPING_PATH_NAME
    for n in count(2):
        if len(name := f"{CLIPPING_PATH_NAME} {n}") % 2:
            yield name


def _clipping_path(name: str) -> bytes:
    """Resource data marking the path called `name` as the clipping path."""
    assert len(name) % 2, "odd length keeps the name unpadded, see CLIPPING_PATH_NAME"
    pascal = struct.pack("B", len(name)) + name.encode("ascii")
    # flatness as 16.16 fixed point (0: the output device's default), fill rule
    # (1: even-odd, which Photoshop ignores)
    return pascal + struct.pack(">iH", 0, 1)


def write_tiff(
    image: Image.Image,
    plist: Path,
    filename: str,
    name: str = "Path 1",
    size: tuple[int, int] | None = None,
    offset: float = 0,
    clipping: bool = False,
) -> None:
    """Save `image` as TIFF with `plist` embedded as a Photoshop path.

    `size` is the size of the bitmap that was traced, if it differs from the
    image (e.g. a half resolution mask); the path is scaled to fit.
    `offset` grows (positive) or shrinks (negative) the path, in traced pixels.
    `clipping` makes it the image's clipping path, named `CLIPPING_PATH_NAME`
    (numbered if taken), in place of a clipping path the image already had.
    """
    # keep the resources of a TIFF that already went through Photoshop
    tags = getattr(image, "tag_v2", {})
    resources = bytes(tags.get(PHOTOSHOP_TAG, b""))
    used = image.get_photoshop_blocks() if isinstance(image, TiffImageFile) else {}
    path_id = next(i for i in PATH_IDS if i not in used)
    if clipping:
        blocks = _split_resources(resources)
        resources = b"".join(b for i, b in blocks if i != CLIPPING_PATH_ID)
        # Photoshop finds the clipping path by name, so it has to be unique
        taken = {_block_name(b) for i, b in blocks if i in PATH_IDS}
        name = next(n for n in _clipping_names() if n not in taken)
    resources += _resource_block(
        path_id, name, _path_resource(subpaths(plist, offset), *(size or image.size))
    )
    if clipping:
        resources += _resource_block(CLIPPING_PATH_ID, "", _clipping_path(name))
    if PHOTOSHOP_TAG in tags:
        tags[PHOTOSHOP_TAG] = resources  # Pillow prefers this over `tiffinfo`
    image.save(
        filename,
        format="TIFF",
        tiffinfo={PHOTOSHOP_TAG: resources},
        dpi=image.info.get("dpi"),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace an image into a TIFF path")
    parser.add_argument("file", help="image to trace")
    parser.add_argument("-o", "--output", help="output name, without extension")
    parser.add_argument("-a", "--alphamax", type=float, default=1)
    parser.add_argument(
        "-g", "--grow", type=float, default=0, help="px to grow (negative: shrink)"
    )
    parser.add_argument(
        "-t", "--threshold", type=float, default=0.5, help="darkness cutoff, 0..1"
    )
    parser.add_argument(
        "-s", "--simplify", type=float, default=0.2, help="curve tolerance, 0..1"
    )
    parser.add_argument(
        "-c", "--clipping-path", action="store_true", help="mark as clipping path"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        image = Image.open(args.file)
    except OSError:
        print(f"Image ({args.file}) could not be loaded.")
        return

    out_name = args.output if args.output else args.file

    plist = trace(image, args.alphamax, args.threshold, args.simplify)
    write_tiff(
        image,
        plist,
        f"{out_name}.tif",
        offset=args.grow,
        clipping=args.clipping_path,
    )
