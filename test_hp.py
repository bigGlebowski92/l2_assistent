"""Synthetic BGRA tests for hp_percent (mss-style, no numpy)."""

from bot import bgra_to_ppm, hp_percent, mask_strip_ppm, preview_ppms, red_column_mask


def bar(width, height, fill, red=(20, 30, 200, 255), bg=(80, 70, 50, 255), mid_only=False):
    """Build BGRA bytes. red/bg are (B, G, R, A). fill is 0..1 from the left."""
    fill_w = int(round(width * fill))
    rows = []
    mid = height // 2
    for y in range(height):
        row = bytearray()
        use_red = (not mid_only) or (y == mid)
        for x in range(width):
            pix = red if (use_red and x < fill_w) else bg
            row.extend(pix)
        rows.append(bytes(row))
    return b"".join(rows)


def expect(got, want, label):
    if got != want:
        raise SystemExit(f"FAIL {label}: got {got}, want {want}")
    print(f"OK   {label}: {got}")


def main():
    # Full red bar -> 100%
    expect(hp_percent(bar(100, 8, 1.0), 100, 8), 100, "full bar")
    # Empty / no red -> 0%
    expect(hp_percent(bar(100, 8, 0.0), 100, 8), 0, "empty bar")
    # Half fill -> 50%
    expect(hp_percent(bar(100, 8, 0.5), 100, 8), 50, "half bar")
    # 1% (first column only)
    expect(hp_percent(bar(100, 8, 0.01), 100, 8), 1, "one column")
    # Channel order: if RGB were read as BGRA, this "red" (high R in byte 2) would look dim
    raw = bar(40, 5, 0.5, red=(10, 10, 220, 255), bg=(40, 40, 40, 255))
    expect(hp_percent(raw, 40, 5), 50, "BGRA red (R in byte 2)")
    # Same pixels interpreted wrongly would fail; a green-ish high-B pixel is not red
    not_red = bar(40, 5, 1.0, red=(220, 10, 10, 255), bg=(40, 40, 40, 255))
    expect(hp_percent(not_red, 40, 5), 0, "high B / low R is not red")
    # Mid-row scan: red only on the middle row still counts
    expect(hp_percent(bar(80, 7, 0.25, mid_only=True), 80, 7), 25, "middle row only")
    # Thresholds from config defaults: r=121, g=0, b=0 is red; r=120 is not
    px_yes = bytes([0, 0, 121, 255] * 10 * 3)
    px_no = bytes([0, 0, 120, 255] * 10 * 3)
    expect(hp_percent(px_yes, 10, 3), 100, "r=121 crosses red_min")
    expect(hp_percent(px_no, 10, 3), 0, "r=120 fails red_min")
    # ratio: r=200, g=120 -> 200 > 120*1.8 (216)? no
    weak = bytes([0, 120, 200, 255] * 10 * 3)
    expect(hp_percent(weak, 10, 3), 0, "fails r > g*1.8")
    strong = bytes([0, 100, 200, 255] * 10 * 3)
    expect(hp_percent(strong, 10, 3), 100, "passes r > g*1.8")
    # empty / zero size
    expect(hp_percent(b"", 0, 0), 0, "zero size")

    # BGRA -> PPM: header + RGB order (R is byte 2 of BGRA)
    ppm = bgra_to_ppm(bytes([10, 20, 30, 255, 40, 50, 60, 255]), 2, 1)
    header, _, pixels = ppm.partition(b"\n255\n")
    if not header.startswith(b"P6") or b"2 1" not in header:
        raise SystemExit(f"FAIL ppm header: {header!r}")
    if pixels != bytes([30, 20, 10, 60, 50, 40]):
        raise SystemExit(f"FAIL ppm RGB order: {list(pixels)}")
    print("OK   bgra_to_ppm header and RGB order")

    # Column mask + strip: left half red, right half not; mid-row only still counts
    raw = bar(40, 7, 0.5, mid_only=True)
    mask = red_column_mask(raw, 40, 7)
    if mask != [True] * 20 + [False] * 20:
        raise SystemExit(f"FAIL red_column_mask: {mask.count(True)} true of {len(mask)}")
    expect(hp_percent(raw, 40, 7), 50, "hp matches mask rightmost")
    strip = mask_strip_ppm(mask, strip_h=2)
    _, _, spix = strip.partition(b"\n255\n")
    if len(spix) != 40 * 2 * 3:
        raise SystemExit(f"FAIL strip size: {len(spix)}")
    # first col red (220,30,30), last col gray (160,160,160), both rows
    if spix[0:3] != bytes((220, 30, 30)) or spix[39 * 3 : 40 * 3] != bytes((160, 160, 160)):
        raise SystemExit(f"FAIL strip colors start={list(spix[0:3])} end={list(spix[39*3:40*3])}")
    if spix[40 * 3 : 40 * 3 + 3] != bytes((220, 30, 30)):
        raise SystemExit("FAIL strip row 2 not repeated")
    print("OK   red_column_mask and mask_strip_ppm")

    cap, mppm, hp = preview_ppms(raw, 40, 7)
    if hp != 50 or not cap.startswith(b"P6") or not mppm.startswith(b"P6"):
        raise SystemExit(f"FAIL preview_ppms: hp={hp} cap={cap[:16]!r}")
    print("OK   preview_ppms")

    print("All hp_percent tests passed.")


if __name__ == "__main__":
    main()
