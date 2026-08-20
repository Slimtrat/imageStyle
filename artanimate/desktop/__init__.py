"""ArtAnimate desktop client."""


def main() -> int:
    try:
        from .app import main as run
    except ImportError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise SystemExit(
                'Le client desktop nécessite PySide6. Installez-le avec : pip install -e ".[desktop]"'
            ) from exc
        raise
    return run()


__all__ = ["main"]
