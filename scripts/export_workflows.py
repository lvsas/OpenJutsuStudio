#!/usr/bin/env python3
"""Export the API-format graphs the app submits.

The competition asks for a working app *and* its workflow files. This project builds its
graphs in code so they stay testable, pinned to the frozen recipe and free of hand-edited
drift; this script writes those same graphs out so the repository ships the workflows too.

Every asset is a named placeholder. The app replaces each one with an uploaded asset
before submitting, so the substitution points are visible rather than buried.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from graphs import build_frame_edit, build_ripple
from h3_graphs import build_h3_recast
from h3_recipe import bind_frames, make_recipe

OUT = ROOT / 'workflows'


def write(name, graph):
    OUT.mkdir(exist_ok=True)
    destination = OUT / name
    destination.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + '\n')
    print(f'{name}: {len(graph)} nodes')


def main():
    write('ltx-frame-edit.api.json', build_frame_edit(
        'og-source-frame-placeholder.png',
        'Replace the main performer with the character shown in the reference image.',
        reference_image='og-character-reference-placeholder.png'))

    write('ltx-ripple.api.json', build_ripple(
        'og-source-video-placeholder.mp4',
        'og-edited-frame-placeholder.png'))

    # The H3 graph is exported exactly as it is frozen for a take: same canvases, same
    # frame grid, same conditioning, so what ships is what runs.
    recipe = bind_frames(make_recipe(source_width=1920, source_height=1080), 56, source_audio=True)
    write('h3-recast.api.json', recipe['graph_template'])
    print(f"h3 canvas: {recipe['width']}x{recipe['height']} -> "
          f"{recipe['output_width']}x{recipe['output_height']}, frames {recipe['inference_frames']}")


if __name__ == '__main__':
    main()
