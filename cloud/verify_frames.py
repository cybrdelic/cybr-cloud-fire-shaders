#!/usr/bin/env python3
"""Check the actual PNG bytes before encoding a fixed-rate cloud sequence."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', type=Path)
    ap.add_argument('--count', type=int, default=240)
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    args = ap.parse_args()
    records, hashes, means, small = [], [], [], []
    for i in range(args.count):
        path = args.frames / f'frame{i:06d}.png'
        rec = json.loads(path.with_suffix('.json').read_text())
        with Image.open(path) as im:
            im.load()
            assert im.size == (args.width, args.height), (path, im.size)
            rgb = im.convert('RGB')
            digest = hashlib.sha256(rgb.tobytes()).hexdigest()
            assert digest == rec['pixel_sha256'], path
            small.append(np.asarray(rgb.resize((64, 36), Image.Resampling.BOX), dtype='f4') / 255)
        assert rec['all_finite']
        assert rec['index'] == i
        assert abs(rec['time'] - i / args.fps) < 1e-10
        assert rec['width'] == args.width and rec['height'] == args.height
        records.append(rec)
        hashes.append(digest)
        means.append(rec['mean_rgb'])
    assert len(set(hashes)) == args.count, 'Repeated rendered frames'
    assert len({x['source_sha256'] for x in records}) == 1
    luminance_proxy = np.asarray(means).mean(axis=1)
    first = np.abs(np.diff(luminance_proxy))
    second = np.abs(np.diff(luminance_proxy, n=2))
    pixels = np.stack(small)
    local_first = np.abs(np.diff(pixels, axis=0)).mean(axis=(1, 2, 3))
    report = {
        'frames': args.count, 'fps': args.fps,
        'width': args.width, 'height': args.height,
        'source_sha256': records[0]['source_sha256'],
        'all_pngs_decoded_and_pixel_hash_checked': True,
        'all_finite': True, 'unique_raw_frames': len(set(hashes)),
        'global_mean_rgb_first_difference_max': float(first.max()),
        'global_first_difference_time': float((first.argmax() + 1) / args.fps),
        'global_mean_rgb_second_difference_max': float(second.max()),
        'global_second_difference_time': float((second.argmax() + 1) / args.fps),
        'thumbnail_mean_absolute_frame_change_max': float(local_first.max()),
        'interpretation': 'Motion and fog crossings also change these values; these are diagnostics, not a proof that all temporal aliasing is absent.',
    }
    (args.frames / 'png-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.frames / 'video-frame-records.json').write_text(json.dumps(records, indent=2) + '\n')
    indices = [0, 48, 96, 144, 180, 199, 210, args.count - 1]
    tw, th = 480, 270
    sheet = Image.new('RGB', (tw * 2, (th + 25) * 4), (14, 19, 26))
    draw = ImageDraw.Draw(sheet)
    for n, i in enumerate(indices):
        with Image.open(args.frames / f'frame{i:06d}.png') as im:
            tile = im.resize((tw, th), Image.Resampling.LANCZOS)
        x, y = (n % 2) * tw, (n // 2) * (th + 25)
        sheet.paste(tile, (x, y))
        draw.text((x + 8, y + th + 6), f'{i / args.fps:.2f} s', fill='white')
    sheet.save(args.frames / 'final-contact.jpg', quality=94)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
