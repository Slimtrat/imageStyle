from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event

import numpy as np
import numpy.fft as np_fft
import numpy.linalg as np_linalg
import numpy.ma as np_ma  # noqa: F401 - preload NumPy's lazy median dependency

from .audio_decode import AudioDecodeCancelled, decode_mono_audio
from .clock import StudioClock
from .model import StudioProject
from .semantic import FrozenJsonObject


MUSIC_ANALYSIS_SCHEMA_VERSION = 1
MUSIC_ANALYSIS_ALGORITHM_VERSION = 1
MUSIC_ANALYSIS_EXTENSION = "music_analysis"


class MusicAnalysisCancelled(RuntimeError):
    pass


class MusicEventKind(StrEnum):
    BEAT = "beat"
    DOWNBEAT = "downbeat"
    DROP = "drop"


@dataclass(frozen=True, slots=True)
class MusicAnalysisSettings:
    sensitivity: float = 0.55

    def validate(self) -> MusicAnalysisSettings:
        if (
            isinstance(self.sensitivity, bool)
            or not isinstance(self.sensitivity, int | float)
            or not 0.0 <= float(self.sensitivity) <= 1.0
        ):
            raise ValueError(
                "music_analysis.sensitivity doit être comprise entre 0 et 1"
            )
        return self

    @property
    def candidate_threshold(self) -> float:
        return 0.72 - 0.42 * float(self.sensitivity)

    @property
    def signature(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, int | float]:
        self.validate()
        return {
            "schema_version": MUSIC_ANALYSIS_SCHEMA_VERSION,
            "sensitivity": round(float(self.sensitivity), 4),
        }

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, object] | None
    ) -> MusicAnalysisSettings:
        values = payload or {}
        version = values.get("schema_version", MUSIC_ANALYSIS_SCHEMA_VERSION)
        if (
            isinstance(version, bool)
            or version != MUSIC_ANALYSIS_SCHEMA_VERSION
        ):
            raise ValueError(f"Version d’analyse musicale inconnue : {version}")
        sensitivity = values.get("sensitivity", 0.55)
        if isinstance(sensitivity, bool) or not isinstance(
            sensitivity, int | float
        ):
            raise TypeError("music_analysis.sensitivity doit être un nombre")
        return cls(float(sensitivity)).validate()

    @classmethod
    def from_project(cls, project: StudioProject) -> MusicAnalysisSettings:
        payload = project.extensions.to_dict().get(MUSIC_ANALYSIS_EXTENSION, {})
        if not isinstance(payload, Mapping):
            raise TypeError("L’extension music_analysis doit être un objet")
        return cls.from_mapping(payload)


def set_music_analysis_settings(
    project: StudioProject,
    settings: MusicAnalysisSettings,
) -> StudioProject:
    values = project.extensions.to_dict()
    values[MUSIC_ANALYSIS_EXTENSION] = settings.validate().to_dict()
    return replace(
        project,
        extensions=FrozenJsonObject(values, where="project.extensions"),
    ).validate()


@dataclass(frozen=True, slots=True)
class MusicEvent:
    kind: MusicEventKind
    frame: int
    source_sample: int
    confidence: float
    uncertain: bool

    def validate(self, *, clock: StudioClock, sample_count: int) -> MusicEvent:
        if not isinstance(self.kind, MusicEventKind):
            raise TypeError("Le type d’événement musical est invalide")
        clock.validate_frame(self.frame)
        if (
            isinstance(self.source_sample, bool)
            or not isinstance(self.source_sample, int)
            or not 0 <= self.source_sample <= sample_count
        ):
            raise ValueError("La position source de l’événement musical est invalide")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, int | float)
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("La confiance musicale doit être comprise entre 0 et 1")
        if not isinstance(self.uncertain, bool):
            raise TypeError("music_event.uncertain doit être un booléen")
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "frame": self.frame,
            "source_sample": self.source_sample,
            "confidence": round(float(self.confidence), 6),
            "uncertain": self.uncertain,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> MusicEvent:
        uncertain = payload["uncertain"]
        if not isinstance(uncertain, bool):
            raise TypeError("music_event.uncertain doit être un booléen")
        return cls(
            MusicEventKind(str(payload["kind"])),
            int(payload["frame"]),
            int(payload["source_sample"]),
            float(payload["confidence"]),
            uncertain,
        )


@dataclass(frozen=True, slots=True)
class MusicAnalysis:
    source_fingerprint: str
    settings: MusicAnalysisSettings
    fps: int
    sample_rate: int
    sample_count: int
    tempo_bpm: float | None
    tempo_confidence: float
    events: tuple[MusicEvent, ...]
    cache_hit: bool = field(default=False, compare=False)

    def validate(self) -> MusicAnalysis:
        if not self.source_fingerprint:
            raise ValueError("L’analyse musicale exige une empreinte audio")
        self.settings.validate()
        clock = StudioClock(self.fps)
        if self.sample_rate <= 0 or self.sample_count < 0:
            raise ValueError("La durée PCM de l’analyse musicale est invalide")
        if self.tempo_bpm is not None and not 40.0 <= self.tempo_bpm <= 240.0:
            raise ValueError("Le tempo musical est hors limites")
        if not 0.0 <= float(self.tempo_confidence) <= 1.0:
            raise ValueError("La confiance du tempo est hors limites")
        order = {kind: index for index, kind in enumerate(MusicEventKind)}
        previous: tuple[int, int] | None = None
        identities: set[tuple[MusicEventKind, int]] = set()
        for event in self.events:
            event.validate(clock=clock, sample_count=self.sample_count)
            identity = (event.kind, event.frame)
            if identity in identities:
                raise ValueError("Un événement musical est dupliqué")
            identities.add(identity)
            position = (event.frame, order[event.kind])
            if previous is not None and position < previous:
                raise ValueError("Les événements musicaux doivent être triés")
            previous = position
        return self

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate

    def events_of(self, kind: MusicEventKind) -> tuple[MusicEvent, ...]:
        return tuple(item for item in self.events if item.kind == kind)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": MUSIC_ANALYSIS_SCHEMA_VERSION,
            "algorithm_version": MUSIC_ANALYSIS_ALGORITHM_VERSION,
            "source_fingerprint": self.source_fingerprint,
            "settings": self.settings.to_dict(),
            "fps": self.fps,
            "sample_rate": self.sample_rate,
            "sample_count": self.sample_count,
            "tempo_bpm": self.tempo_bpm,
            "tempo_confidence": round(float(self.tempo_confidence), 6),
            "events": [item.to_dict() for item in self.events],
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> MusicAnalysis:
        if payload.get("schema_version") != MUSIC_ANALYSIS_SCHEMA_VERSION:
            raise ValueError("Version de cache d’analyse musicale inconnue")
        if payload.get("algorithm_version") != MUSIC_ANALYSIS_ALGORITHM_VERSION:
            raise ValueError("Version d’algorithme musical inconnue")
        raw_events = payload.get("events", [])
        if not isinstance(raw_events, list):
            raise TypeError("music_analysis.events doit être une liste")
        if not all(isinstance(item, Mapping) for item in raw_events):
            raise TypeError("Chaque événement musical doit être un objet")
        settings = payload.get("settings", {})
        if not isinstance(settings, Mapping):
            raise TypeError("music_analysis.settings doit être un objet")
        return cls(
            source_fingerprint=str(payload["source_fingerprint"]),
            settings=MusicAnalysisSettings.from_mapping(settings),
            fps=int(payload["fps"]),
            sample_rate=int(payload["sample_rate"]),
            sample_count=int(payload["sample_count"]),
            tempo_bpm=(
                float(payload["tempo_bpm"])
                if payload.get("tempo_bpm") is not None
                else None
            ),
            tempo_confidence=float(payload.get("tempo_confidence", 0.0)),
            events=tuple(
                MusicEvent.from_mapping(item)
                for item in raw_events
            ),
        ).validate()


class _FeatureBuilder:
    def __init__(self, sample_rate: int, cancelled: Event) -> None:
        self.sample_rate = sample_rate
        self.cancelled = cancelled
        self.frame_size = max(256, int(round(sample_rate * 0.046)))
        self.hop_size = max(128, int(round(sample_rate * 0.0115)))
        self.window = np.hanning(self.frame_size).astype(np.float32)
        self.frequencies = np_fft.rfftfreq(
            self.frame_size, d=1.0 / sample_rate
        )
        self.buffer = np.empty(0, dtype=np.float32)
        self.buffer_start_sample = 0
        self.previous_spectrum: np.ndarray | None = None
        self.rms: list[float] = []
        self.flux: list[float] = []
        self.low: list[float] = []
        self.centers: list[int] = []

    def consume(self, samples: np.ndarray) -> None:
        if self.cancelled.is_set():
            raise MusicAnalysisCancelled("Analyse musicale annulée")
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if self.buffer.size:
            values = np.concatenate((self.buffer, values))
        offset = 0
        while offset + self.frame_size <= len(values):
            if len(self.rms) % 128 == 0 and self.cancelled.is_set():
                raise MusicAnalysisCancelled("Analyse musicale annulée")
            frame = values[offset : offset + self.frame_size]
            spectrum = np.abs(np_fft.rfft(frame * self.window)).astype(np.float32)
            power = spectrum * spectrum
            self.rms.append(float(np.sqrt(np.mean(frame * frame))))
            if self.previous_spectrum is None:
                self.flux.append(0.0)
            else:
                self.flux.append(
                    float(
                        np.maximum(
                            spectrum - self.previous_spectrum, 0.0
                        ).sum()
                    )
                )
            total = max(float(power.sum()), 1e-12)
            self.low.append(
                float(power[self.frequencies < 180.0].sum()) / total
            )
            self.centers.append(
                self.buffer_start_sample + offset + self.frame_size // 2
            )
            self.previous_spectrum = spectrum
            offset += self.hop_size
        self.buffer_start_sample += offset
        self.buffer = values[offset:].copy()


def _unit_scale(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values.astype(np.float64)
    baseline = float(np.median(values))
    upper = float(np.percentile(values, 95))
    scale = max(
        upper - baseline,
        float(np.std(values)) * 0.25,
        1e-9,
    )
    return np.clip(
        (values.astype(np.float64) - baseline) / scale,
        0.0,
        1.0,
    )


def _tempo_from_onsets(
    onset: np.ndarray,
    frames_per_second: float,
) -> tuple[float | None, float, int | None]:
    if (
        len(onset) < max(12, int(frames_per_second * 2.0))
        or float(onset.max()) < 0.08
    ):
        return None, 0.0, None
    minimum_lag = max(
        1, int(round(frames_per_second * 60.0 / 180.0))
    )
    maximum_lag = min(
        len(onset) - 2,
        int(round(frames_per_second * 60.0 / 65.0)),
    )
    if maximum_lag <= minimum_lag:
        return None, 0.0, None
    signal = onset - float(np.median(onset))
    scores: list[tuple[float, int]] = []
    lag_span = max(1, maximum_lag - minimum_lag)
    for lag in range(minimum_lag, maximum_lag + 1):
        left = signal[:-lag]
        right = signal[lag:]
        denominator = float(np_linalg.norm(left) * np_linalg.norm(right))
        correlation = (
            float(np.dot(left, right) / denominator)
            if denominator
            else 0.0
        )
        faster_bias = 1.0 + 0.08 * (maximum_lag - lag) / lag_span
        scores.append((max(0.0, correlation) * faster_bias, lag))
    score, lag = max(scores)
    ranked = sorted((item[0] for item in scores), reverse=True)
    contrast = score - ranked[min(4, len(ranked) - 1)]
    confidence = float(
        np.clip(score * 0.72 + contrast * 1.8, 0.0, 1.0)
    )
    tempo = 60.0 * frames_per_second / lag
    return round(tempo, 3), confidence, lag


def _beat_indices(
    onset: np.ndarray,
    period: int,
) -> tuple[list[int], list[float]]:
    if period <= 0 or onset.size == 0:
        return [], []
    best_phase = max(
        range(period),
        key=lambda phase: float(onset[phase::period].sum()),
    )
    indices: list[int] = []
    strengths: list[float] = []
    radius = max(1, int(round(period * 0.22)))
    expected = best_phase
    while expected < len(onset):
        left = max(0, expected - radius)
        right = min(len(onset), expected + radius + 1)
        local = onset[left:right]
        index = left + int(np.argmax(local))
        if not indices or index - indices[-1] >= max(1, period // 2):
            indices.append(index)
            strengths.append(float(onset[index]))
        expected += period
    return indices, strengths


def _drop_candidates(
    onset: np.ndarray,
    rms: np.ndarray,
    low: np.ndarray,
    frames_per_second: float,
) -> list[tuple[int, float]]:
    before = max(3, int(round(frames_per_second * 1.2)))
    after = max(3, int(round(frames_per_second * 0.8)))
    guard = max(1, int(round(frames_per_second * 0.12)))
    candidates: list[tuple[int, float]] = []
    for index in range(before, len(onset) - after):
        if (
            onset[index] < 0.35
            or onset[index] < onset[index - 1]
            or onset[index] < onset[index + 1]
        ):
            continue
        quiet = float(np.mean(rms[index - before : index - guard]))
        arrival = float(np.mean(rms[index + guard : index + after]))
        if arrival <= quiet + 0.04:
            continue
        jump = float(
            np.clip(
                (arrival - quiet) / max(0.12, quiet + 0.04),
                0.0,
                1.0,
            )
        )
        bass = float(np.mean(low[index : index + after]))
        confidence = float(
            np.clip(
                0.48 * jump + 0.30 * onset[index] + 0.22 * bass,
                0.0,
                1.0,
            )
        )
        if (
            candidates
            and index - candidates[-1][0] < int(frames_per_second * 2.0)
        ):
            if confidence > candidates[-1][1]:
                candidates[-1] = (index, confidence)
        else:
            candidates.append((index, confidence))
    return candidates


def analyze_music(
    path: str | Path,
    source_fingerprint: str,
    *,
    fps: int,
    settings: MusicAnalysisSettings | None = None,
    cancelled: Event | None = None,
) -> MusicAnalysis:
    source = Path(os.path.abspath(path))
    clock = StudioClock(fps)
    options = (settings or MusicAnalysisSettings()).validate()
    cancellation = cancelled or Event()
    builder: _FeatureBuilder | None = None

    def consume(samples: np.ndarray) -> None:
        assert builder is not None
        builder.consume(samples)

    try:
        if source.suffix.casefold() == ".wav":
            import wave

            with wave.open(str(source), "rb") as stream:
                sample_rate = stream.getframerate()
        else:
            sample_rate = 22_050
        builder = _FeatureBuilder(sample_rate, cancellation)
        info = decode_mono_audio(
            source,
            consume,
            cancelled=cancellation,
            ffmpeg_sample_rate=sample_rate,
        )
    except (AudioDecodeCancelled, MusicAnalysisCancelled) as exc:
        raise MusicAnalysisCancelled("Analyse musicale annulée") from exc
    if cancellation.is_set():
        raise MusicAnalysisCancelled("Analyse musicale annulée")
    assert builder is not None
    if not builder.centers:
        return MusicAnalysis(
            source_fingerprint,
            options,
            fps,
            info.sample_rate,
            info.sample_count,
            None,
            0.0,
            (),
        ).validate()

    rms = _unit_scale(np.asarray(builder.rms, dtype=np.float64))
    flux = _unit_scale(np.asarray(builder.flux, dtype=np.float64))
    low = _unit_scale(np.asarray(builder.low, dtype=np.float64))
    onset = np.clip(
        0.72 * flux
        + 0.28 * np.maximum(np.diff(rms, prepend=rms[0]), 0.0),
        0.0,
        1.0,
    )
    frames_per_second = info.sample_rate / builder.hop_size
    tempo, tempo_confidence, period = _tempo_from_onsets(
        onset, frames_per_second
    )
    candidates: list[tuple[MusicEventKind, int, float]] = []
    beat_indices: list[int] = []
    beat_strengths: list[float] = []
    if period is not None:
        beat_indices, beat_strengths = _beat_indices(onset, period)
        for index, strength in zip(
            beat_indices, beat_strengths, strict=True
        ):
            confidence = float(
                np.clip(
                    0.62 * strength + 0.38 * tempo_confidence,
                    0.0,
                    1.0,
                )
            )
            candidates.append((MusicEventKind.BEAT, index, confidence))

        if len(beat_indices) >= 4:
            accent = np.clip(
                0.44 * low + 0.34 * rms + 0.22 * onset,
                0.0,
                1.0,
            )
            phase_scores = [
                float(
                    np.mean(
                        [accent[index] for index in beat_indices[phase::4]]
                    )
                )
                if beat_indices[phase::4]
                else 0.0
                for phase in range(4)
            ]
            phase = int(np.argmax(phase_scores))
            ranked = sorted(phase_scores, reverse=True)
            separation = ranked[0] - ranked[1]
            for position in range(phase, len(beat_indices), 4):
                index = beat_indices[position]
                confidence = float(
                    np.clip(
                        0.44 * beat_strengths[position]
                        + 0.30 * tempo_confidence
                        + 0.26 * (phase_scores[phase] + separation),
                        0.0,
                        1.0,
                    )
                )
                candidates.append(
                    (MusicEventKind.DOWNBEAT, index, confidence)
                )

    for index, confidence in _drop_candidates(
        onset, rms, low, frames_per_second
    ):
        candidates.append((MusicEventKind.DROP, index, confidence))

    events: list[MusicEvent] = []
    seen: set[tuple[MusicEventKind, int]] = set()
    for kind, index, confidence in candidates:
        if confidence < options.candidate_threshold:
            continue
        source_sample = min(
            info.sample_count, max(0, builder.centers[index])
        )
        frame = clock.seconds_to_frame(
            source_sample / info.sample_rate,
            rounding="nearest",
        )
        identity = (kind, frame)
        if identity in seen:
            continue
        seen.add(identity)
        events.append(
            MusicEvent(
                kind,
                frame,
                source_sample,
                round(confidence, 6),
                confidence < 0.62,
            )
        )
    order = {
        kind: index for index, kind in enumerate(MusicEventKind)
    }
    events.sort(key=lambda item: (item.frame, order[item.kind]))
    return MusicAnalysis(
        source_fingerprint,
        options,
        fps,
        info.sample_rate,
        info.sample_count,
        tempo,
        round(tempo_confidence, 6),
        tuple(events),
    ).validate()


class MusicAnalysisCache:
    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = 32 * 1024 * 1024,
        max_entries: int = 64,
    ) -> None:
        self.root = Path(root)
        self.max_bytes = max(1, int(max_bytes))
        self.max_entries = max(1, int(max_entries))

    def _path(
        self,
        fingerprint: str,
        settings: MusicAnalysisSettings,
        fps: int,
    ) -> Path:
        key = sha256(
            (
                f"{MUSIC_ANALYSIS_SCHEMA_VERSION}\0"
                f"{MUSIC_ANALYSIS_ALGORITHM_VERSION}\0{fingerprint}\0"
                f"{settings.signature}\0{fps}"
            ).encode("utf-8")
        ).hexdigest()
        return self.root / f"{key}.json"

    def load(
        self,
        fingerprint: str,
        settings: MusicAnalysisSettings,
        fps: int,
    ) -> MusicAnalysis | None:
        path = self._path(fingerprint, settings, fps)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                return None
            result = MusicAnalysis.from_mapping(payload)
            if (
                result.source_fingerprint != fingerprint
                or result.settings != settings
                or result.fps != fps
            ):
                return None
            os.utime(path, None)
            return replace(result, cache_hit=True)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            return None

    def store(self, analysis: MusicAnalysis) -> Path:
        analysis.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._path(
            analysis.source_fingerprint,
            analysis.settings,
            analysis.fps,
        )
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                prefix="music-analysis-",
                suffix=".json",
                dir=self.root,
                delete=False,
                mode="w",
                encoding="utf-8",
            ) as handle:
                temporary = Path(handle.name)
                json.dump(
                    analysis.to_dict(),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.prune(keep=(destination,))
        return destination

    def load_or_analyze(
        self,
        path: str | Path,
        fingerprint: str,
        *,
        fps: int,
        settings: MusicAnalysisSettings,
        cancelled: Event,
    ) -> MusicAnalysis:
        cached = self.load(fingerprint, settings, fps)
        if cached is not None:
            return cached
        result = analyze_music(
            path,
            fingerprint,
            fps=fps,
            settings=settings,
            cancelled=cancelled,
        )
        if cancelled.is_set():
            raise MusicAnalysisCancelled("Analyse musicale annulée")
        self.store(result)
        return result

    def prune(self, *, keep: tuple[Path, ...] = ()) -> None:
        if not self.root.exists():
            return
        preserved = {item.resolve(strict=False) for item in keep}
        entries = sorted(
            (
                item
                for item in self.root.glob("*.json")
                if item.is_file()
            ),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        total = sum(item.stat().st_size for item in entries)
        for index, path in enumerate(entries):
            if index < self.max_entries and total <= self.max_bytes:
                continue
            if path.resolve(strict=False) in preserved:
                continue
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
