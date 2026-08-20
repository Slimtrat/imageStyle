from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys
import time
from typing import Any

from .analysis import analyze_artwork
from .config import DIRECTIONS, EFFECTS, ORDERS, OUTLINE_MODES, RenderConfig
from .renderer import ArtworkRenderer
from .video import encode_video


def _add_configuration_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="preset JSON à charger")
    parser.add_argument("--effect", choices=EFFECTS, default=None, help="moteur de révélation")
    parser.add_argument("--order", choices=ORDERS, default=None, help="ordre des familles")
    parser.add_argument("--outline", choices=OUTLINE_MODES, default=None, help="moment des contours")
    parser.add_argument("--direction", choices=DIRECTIONS, default=None, help="direction de la vague")
    parser.add_argument("--duration", type=float, default=None, help="durée totale en secondes")
    parser.add_argument("--fps", type=int, default=None, help="images par seconde")
    parser.add_argument("--width", type=int, default=None, help="largeur de sortie")
    parser.add_argument("--colors", type=int, default=None, help="centres de quantification (2–64)")
    parser.add_argument("--hold-start", type=float, default=None, help="pause initiale en secondes")
    parser.add_argument("--hold-end", type=float, default=None, help="pause finale en secondes")
    parser.add_argument("--overlap", type=float, default=None, help="chevauchement des familles (0–0.9)")
    parser.add_argument("--start-hue", type=float, default=None, help="teinte de départ en degrés")
    parser.add_argument(
        "--background-tolerance",
        type=float,
        default=None,
        help="tolérance Delta E pour le fond",
    )
    parser.add_argument("--outline-luma", type=float, default=None, help="seuil L* des contours")
    parser.add_argument("--outline-chroma", type=float, default=None, help="chroma maximal des contours")
    parser.add_argument("--wave-amplitude", type=float, default=None, help="amplitude du front de vague")
    parser.add_argument("--wave-frequency", type=float, default=None, help="fréquence du front de vague")
    parser.add_argument("--turbulence", type=float, default=None, help="irrégularité du front")
    parser.add_argument("--soft-edge", type=float, default=None, help="largeur du bord progressif")
    parser.add_argument("--grain-density", type=float, default=None, help="densité des grains volants")
    parser.add_argument("--grain-size", type=float, default=None, help="taille des grains")
    parser.add_argument("--seed", type=int, default=None, help="graine du rendu")
    parser.add_argument("--crf", type=int, default=None, help="qualité vidéo H.264/VP9 (0–51)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artanimate",
        description="Transforme une œuvre statique en animation chromatique sable ou vague.",
    )
    parser.add_argument("--version", action="version", version="ArtAnimate 1.0.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="analyser puis encoder une vidéo")
    render.add_argument("input", type=Path, help="image source")
    render.add_argument("-o", "--output", type=Path, required=True, help="vidéo .mp4, .mov ou .webm")
    render.add_argument("--manifest", type=Path, help="manifeste d'analyse JSON")
    _add_configuration_options(render)

    analyze = subparsers.add_parser("analyze", help="inspecter palette, fond et contours")
    analyze.add_argument("input", type=Path, help="image source")
    analyze.add_argument("--json", type=Path, help="destination du manifeste JSON")
    analyze.add_argument("--preview", type=Path, help="planche palette PNG")
    _add_configuration_options(analyze)
    return parser


def _config_from_namespace(namespace: argparse.Namespace) -> RenderConfig:
    base = RenderConfig.from_json(namespace.config) if namespace.config else RenderConfig()
    config_keys = {field.name for field in fields(RenderConfig)}
    overrides: dict[str, Any] = {
        key: value
        for key, value in vars(namespace).items()
        if key in config_keys and value is not None
    }
    return base.with_overrides(overrides)


def _palette_summary(analysis: Any, config: RenderConfig) -> str:
    ordered = analysis.ordered_layers(config.order, config.start_hue)
    names = " -> ".join(layer.label for layer in ordered)
    if analysis.outline:
        if config.outline == "first":
            names = "contours -> " + names
        elif config.outline == "last":
            names = names + " -> contours"
        else:
            names = names + " + contours progressifs"
    return names


def _render(namespace: argparse.Namespace) -> int:
    config = _config_from_namespace(namespace)
    analysis = analyze_artwork(namespace.input, config)
    print(f"Analyse : {analysis.size[0]}x{analysis.size[1]} px, fond {analysis.manifest(config)['background']}")
    print(f"Séquence : {_palette_summary(analysis, config)}")
    renderer = ArtworkRenderer(analysis, config)
    started = time.monotonic()
    last_percent = -1

    def progress(done: int, total: int) -> None:
        nonlocal last_percent
        percent = int(done * 100 / total)
        if percent != last_percent:
            elapsed = time.monotonic() - started
            print(f"\rEncodage : {percent:3d}%  ({done}/{total})  {elapsed:5.1f}s", end="", flush=True)
            last_percent = percent

    destination = encode_video(renderer, namespace.output, progress)
    print()
    if namespace.manifest:
        analysis.save_manifest(namespace.manifest, config)
        print(f"Manifeste : {namespace.manifest.resolve()}")
    print(f"Vidéo prête : {destination.resolve()}")
    return 0


def _analyze(namespace: argparse.Namespace) -> int:
    config = _config_from_namespace(namespace)
    analysis = analyze_artwork(namespace.input, config)
    manifest = analysis.manifest(config)
    if namespace.json:
        analysis.save_manifest(namespace.json, config)
        print(f"Manifeste : {namespace.json.resolve()}")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if namespace.preview:
        analysis.save_preview(namespace.preview, config)
        print(f"Planche : {namespace.preview.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    namespace = parser.parse_args(argv)
    try:
        if namespace.command == "render":
            return _render(namespace)
        return _analyze(namespace)
    except KeyboardInterrupt:
        print("\nRendu interrompu.", file=sys.stderr)
        return 130
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
