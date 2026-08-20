from __future__ import annotations

from dataclasses import dataclass
import errno
from pathlib import Path
import shutil
from typing import Literal
from uuid import uuid4

from PIL import Image, UnidentifiedImageError


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
MINIMUM_FREE_BYTES = 128 * 1024 * 1024
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
INVALID_WINDOWS_FILENAME_CHARACTERS = set('<>:"/\\|?*')


@dataclass(frozen=True, slots=True)
class UserProblem:
    """A non-technical explanation plus the concrete recovery action."""

    code: str
    title: str
    message: str
    action: str
    technical_details: str = ""

    @property
    def display_text(self) -> str:
        return f"{self.message}\n\nQue faire : {self.action}"


class UserInputError(ValueError):
    """Raised when an operation should stop and display a :class:`UserProblem`."""

    def __init__(self, problem: UserProblem):
        super().__init__(problem.message)
        self.problem = problem


def source_reference_problem(path: Path | None) -> UserProblem | None:
    if path is None:
        return UserProblem(
            "source_missing",
            "Œuvre manquante",
            "Aucune image source n’est sélectionnée.",
            "Glissez une image dans la zone « Œuvre source » ou cliquez sur Parcourir.",
        )
    if not path.exists():
        return UserProblem(
            "source_not_found",
            "Œuvre introuvable",
            f"Le fichier « {path.name} » n’existe plus à l’emplacement sélectionné.",
            "Sélectionnez à nouveau l’image. Elle a peut-être été déplacée, renommée ou supprimée.",
            str(path),
        )
    if not path.is_file():
        return UserProblem(
            "source_not_file",
            "Source incorrecte",
            f'« {path} » est un dossier, pas un fichier image.',
            "Choisissez un fichier PNG, JPEG, WebP, BMP ou TIFF.",
            str(path),
        )
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return UserProblem(
            "source_format",
            "Format d’image non pris en charge",
            f'L’extension « {path.suffix or "aucune"} » ne correspond pas à une image acceptée.',
            "Convertissez l’œuvre en PNG, JPEG, WebP, BMP ou TIFF, puis sélectionnez-la.",
            str(path),
        )
    return None


def destination_reference_problem(path: Path | None) -> UserProblem | None:
    if path is None:
        return UserProblem(
            "destination_missing",
            "Destination manquante",
            "Aucun dossier de destination n’est sélectionné.",
            "Glissez un dossier dans la zone « Dossier de destination » ou cliquez sur Parcourir.",
        )
    if not path.exists():
        return UserProblem(
            "destination_not_found",
            "Dossier de destination introuvable",
            f"Le dossier « {path} » n’existe plus.",
            "Recréez ce dossier ou choisissez un autre dossier existant.",
            str(path),
        )
    if not path.is_dir():
        return UserProblem(
            "destination_not_directory",
            "Destination incorrecte",
            f'« {path} » est un fichier, pas un dossier de destination.',
            "Choisissez un dossier dans lequel ArtAnimate pourra créer la vidéo.",
            str(path),
        )
    return None


def validate_source_path(path: Path | None, verify_image: bool = True) -> Path:
    problem = source_reference_problem(path)
    if problem is not None:
        raise UserInputError(problem)
    assert path is not None
    resolved = path.resolve()
    try:
        with resolved.open("rb") as stream:
            stream.read(1)
        if verify_image:
            with Image.open(resolved) as image:
                image.verify()
    except FileNotFoundError as exc:
        problem = source_reference_problem(resolved)
        assert problem is not None
        raise UserInputError(problem) from exc
    except PermissionError as exc:
        raise UserInputError(
            UserProblem(
                "source_permission",
                "Image inaccessible",
                f"ArtAnimate n’a pas l’autorisation de lire « {resolved.name} ».",
                "Fermez l’application qui verrouille le fichier ou copiez l’image dans un dossier accessible.",
                technical_details=str(exc),
            )
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise UserInputError(
            UserProblem(
                "source_unreadable",
                "Image illisible",
                f"Le fichier « {resolved.name} » existe, mais son contenu n’est pas une image lisible.",
                "Ouvrez-le dans votre logiciel d’image puis enregistrez une nouvelle copie PNG ou JPEG.",
                technical_details=f"{type(exc).__name__}: {exc}",
            )
        ) from exc
    return resolved


def validate_destination_path(
    path: Path | None,
    *,
    check_writable: bool = True,
    check_space: bool = True,
) -> Path:
    problem = destination_reference_problem(path)
    if problem is not None:
        raise UserInputError(problem)
    assert path is not None
    resolved = path.resolve()
    if check_writable:
        probe = resolved / f".artanimate-write-test-{uuid4().hex}.tmp"
        try:
            probe.open("xb").close()
        except FileNotFoundError as exc:
            problem = destination_reference_problem(resolved)
            assert problem is not None
            raise UserInputError(problem) from exc
        except PermissionError as exc:
            raise UserInputError(
                UserProblem(
                    "destination_permission",
                    "Écriture impossible dans ce dossier",
                    f"ArtAnimate ne peut pas créer de fichier dans « {resolved} ».",
                    "Choisissez un dossier où vous avez les droits d’écriture, par exemple Vidéos ou Documents.",
                    technical_details=str(exc),
                )
            ) from exc
        except OSError as exc:
            raise UserInputError(
                translate_exception(exc, "destination", destination=resolved)
            ) from exc
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
    if check_space:
        try:
            free = shutil.disk_usage(resolved).free
        except OSError as exc:
            raise UserInputError(
                translate_exception(exc, "destination", destination=resolved)
            ) from exc
        if free < MINIMUM_FREE_BYTES:
            free_mb = free / (1024 * 1024)
            raise UserInputError(
                UserProblem(
                    "destination_space",
                    "Espace disque insuffisant",
                    f"Il ne reste qu’environ {free_mb:.0f} Mo sur le disque de destination.",
                    "Libérez de l’espace ou choisissez un autre disque avec au moins 128 Mo disponibles.",
                    str(resolved),
                )
            )
    return resolved


def validate_output_name(raw_name: str, suffix: str) -> str:
    name = raw_name.strip()
    if not name or name in {".", ".."}:
        raise UserInputError(
            UserProblem(
                "output_name_missing",
                "Nom de vidéo manquant",
                "Le nom du fichier de sortie est vide.",
                "Saisissez un nom simple, par exemple mon-œuvre-sable.mp4.",
            )
        )
    if Path(name).name != name or any(character in name for character in {"/", "\\"}):
        raise UserInputError(
            UserProblem(
                "output_name_path",
                "Nom de vidéo incorrect",
                "Le champ du nom contient un chemin ou un sous-dossier.",
                "Saisissez uniquement un nom de fichier ; choisissez le dossier dans la zone Destination.",
                name,
            )
        )
    if any(character in INVALID_WINDOWS_FILENAME_CHARACTERS for character in name):
        raise UserInputError(
            UserProblem(
                "output_name_characters",
                "Caractères interdits dans le nom",
                f'Le nom « {name} » contient un caractère que Windows refuse.',
                "Retirez les caractères < > : \" / \\ | ? * du nom de la vidéo.",
                name,
            )
        )
    if name.endswith((" ", ".")):
        raise UserInputError(
            UserProblem(
                "output_name_ending",
                "Fin de nom incorrecte",
                "Windows n’accepte pas un nom de fichier terminé par un espace ou un point.",
                "Retirez le dernier espace ou le dernier point.",
                name,
            )
        )
    candidate = Path(name).with_suffix(suffix).name
    if Path(candidate).stem.upper() in WINDOWS_RESERVED_NAMES:
        raise UserInputError(
            UserProblem(
                "output_name_reserved",
                "Nom réservé par Windows",
                f'« {Path(candidate).stem} » est un nom utilisé par le système Windows.',
                "Choisissez un autre nom, par exemple animation-01.",
                candidate,
            )
        )
    if Path(candidate).suffix.lower() not in VIDEO_EXTENSIONS:
        raise UserInputError(
            UserProblem(
                "output_format",
                "Format vidéo non pris en charge",
                f'Le format « {Path(candidate).suffix or "aucun"} » n’est pas disponible.',
                "Choisissez MP4, WebM ou MOV dans la liste Format.",
                candidate,
            )
        )
    return candidate


def validate_render_paths(
    source: Path | None,
    destination: Path | None,
    raw_name: str,
    suffix: str,
) -> tuple[Path, Path]:
    valid_source = validate_source_path(source)
    valid_destination = validate_destination_path(destination)
    name = validate_output_name(raw_name, suffix)
    output = valid_destination / name
    if output == valid_source:
        raise UserInputError(
            UserProblem(
                "output_overwrites_source",
                "Source et sortie identiques",
                "La vidéo de sortie ne peut pas remplacer l’image source.",
                "Choisissez un autre nom ou un autre dossier de destination.",
                str(output),
            )
        )
    if len(str(output)) > 240:
        raise UserInputError(
            UserProblem(
                "output_path_too_long",
                "Chemin de sortie trop long",
                "Le chemin complet de la vidéo est trop long pour certains composants Windows.",
                "Choisissez un dossier plus proche de la racine ou raccourcissez le nom du fichier.",
                str(output),
            )
        )
    return valid_source, output


def translate_exception(
    exc: BaseException,
    context: Literal["preview", "render", "destination"] = "render",
    *,
    source: Path | None = None,
    destination: Path | None = None,
) -> UserProblem:
    if isinstance(exc, UserInputError):
        return exc.problem
    details = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        destination_problem = destination_reference_problem(destination)
        if destination_problem is not None:
            return destination_problem
        source_problem = source_reference_problem(source)
        if source_problem is not None:
            return source_problem
        target = Path(exc.filename) if exc.filename else None
        if context == "destination":
            return destination_reference_problem(target) or UserProblem(
                "destination_not_found",
                "Dossier introuvable",
                "Le dossier de destination a disparu pendant l’opération.",
                "Choisissez à nouveau un dossier existant puis relancez la création.",
                details,
            )
        return UserProblem(
            "file_not_found",
            "Fichier introuvable",
            "Un fichier nécessaire a disparu pendant l’opération.",
            "Vérifiez l’œuvre et la destination, puis relancez la création.",
            details,
        )
    if isinstance(exc, PermissionError):
        return UserProblem(
            "permission_denied",
            "Accès refusé par Windows",
            "ArtAnimate n’a pas l’autorisation de lire ou d’écrire l’un des fichiers.",
            "Fermez les applications utilisant ce fichier ou choisissez un dossier personnel accessible.",
            details,
        )
    if isinstance(exc, OSError) and (
        exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112
    ):
        return UserProblem(
            "disk_full",
            "Disque plein",
            "Windows indique qu’il n’y a plus assez d’espace pour terminer la vidéo.",
            "Libérez de l’espace ou choisissez un autre disque, puis relancez la création.",
            details,
        )
    message = str(exc)
    if "Aucune zone colorée" in message:
        return UserProblem(
            "analysis_empty",
            "Aucune zone de l’œuvre détectée",
            "Les réglages actuels considèrent presque toute l’image comme du fond ou des contours.",
            "Réduisez le réglage Fond ou Seuil contour, puis regardez le prérendu.",
            details,
        )
    if "Impossible de lire l'image" in message:
        return UserProblem(
            "source_unreadable",
            "Image illisible",
            "L’image sélectionnée ne peut plus être décodée correctement.",
            "Enregistrez une nouvelle copie PNG ou JPEG puis sélectionnez-la.",
            details,
        )
    if isinstance(exc, ValueError):
        return UserProblem(
            "invalid_settings",
            "Réglages incompatibles",
            message or "Une combinaison de réglages ne peut pas être utilisée.",
            "Corrigez le réglage indiqué puis relancez le prérendu.",
            details,
        )
    if context == "destination":
        return UserProblem(
            "destination_unavailable",
            "Dossier de destination inaccessible",
            "Windows ne permet pas d’utiliser ce dossier pour le moment.",
            "Choisissez un autre dossier local accessible, puis réessayez.",
            details,
        )
    if context == "preview":
        return UserProblem(
            "preview_failed",
            "Prérendu impossible",
            "ArtAnimate n’a pas pu calculer l’aperçu avec cette image et ces réglages.",
            "Vérifiez que l’image existe encore, puis consultez les détails dans les Logs.",
            details,
        )
    return UserProblem(
        "render_failed",
        "Création de la vidéo impossible",
        "ArtAnimate n’a pas pu terminer la vidéo.",
        "Vérifiez l’image et le dossier de destination, puis consultez les détails dans les Logs.",
        details,
    )
