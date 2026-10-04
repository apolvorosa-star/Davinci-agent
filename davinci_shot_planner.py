from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SCENE_HEADING_RE = re.compile(
    r"^(?P<place>INT\.?|EXT\.?|INT\.?/EXT\.?|EXT\.?/INT\.?)\s+(?P<location>.+?)(?:\s*[-–—]\s*(?P<time>.+))?$",
    re.IGNORECASE,
)
CHARACTER_RE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ0-9 ._()'-]{1,40}$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
ACTION_WORDS = {
    "abre",
    "avanza",
    "camina",
    "corre",
    "entra",
    "gira",
    "mira",
    "sale",
    "salta",
    "sube",
    "baja",
    "cruza",
    "descubre",
    "cae",
    "levanta",
    "huye",
}
EMOTIONAL_WORDS = {
    "llora",
    "sonríe",
    "susurra",
    "tiembla",
    "miedo",
    "lágrima",
    "silencio",
    "respira",
    "rostro",
    "ojos",
    "recuerda",
    "duda",
}
ESTABLISHING_WORDS = {
    "ciudad",
    "edificio",
    "calle",
    "paisaje",
    "montaña",
    "habitación",
    "casa",
    "noche",
    "amanecer",
    "atardecer",
    "exterior",
    "interior",
}


@dataclass(frozen=True)
class Scene:
    number: int
    heading: str
    place: str
    location: str
    time_of_day: str
    body: str


@dataclass(frozen=True)
class Shot:
    shot_number: int
    scene_number: int
    shot_in_scene: int
    shot_type: str
    visual_description: str
    camera_movement: str
    estimated_duration_seconds: float
    audio_notes: str
    source_text: str


class ScreenplayParser:
    def parse(self, text: str) -> list[Scene]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("El guión está vacío")

        scenes: list[Scene] = []
        heading = "ESCENA 1"
        place = "NO ESPECIFICADO"
        location = "Sin localización especificada"
        time_of_day = "NO ESPECIFICADO"
        body: list[str] = []

        def flush() -> None:
            nonlocal body
            content = "\n".join(body).strip()
            if content or not scenes:
                scenes.append(
                    Scene(
                        number=len(scenes) + 1,
                        heading=heading,
                        place=place,
                        location=location,
                        time_of_day=time_of_day,
                        body=content,
                    )
                )
            body = []

        for raw_line in normalized.splitlines():
            line = raw_line.strip()
            match = SCENE_HEADING_RE.match(line)
            if match:
                if body or scenes:
                    flush()
                heading = line
                place = match.group("place").upper().replace(".", "")
                location = match.group("location").strip()
                time_of_day = (match.group("time") or "NO ESPECIFICADO").strip()
            else:
                body.append(raw_line.rstrip())
        flush()
        return scenes


class CinematicPlanner:
    def __init__(self, words_per_second: float = 2.4, max_shot_seconds: float = 12.0):
        if words_per_second <= 0 or max_shot_seconds <= 0:
            raise ValueError("Los parámetros de duración deben ser mayores que cero")
        self.words_per_second = words_per_second
        self.max_shot_seconds = max_shot_seconds

    def plan(self, scenes: Iterable[Scene]) -> list[Shot]:
        shots: list[Shot] = []
        for scene in scenes:
            beats = self._extract_beats(scene)
            for shot_in_scene, beat in enumerate(beats, start=1):
                shot_type = self._choose_shot_type(beat, shot_in_scene)
                movement = self._choose_camera_movement(beat, shot_type)
                shots.append(
                    Shot(
                        shot_number=len(shots) + 1,
                        scene_number=scene.number,
                        shot_in_scene=shot_in_scene,
                        shot_type=shot_type,
                        visual_description=self._visual_description(beat, scene, shot_type),
                        camera_movement=movement,
                        estimated_duration_seconds=self._estimate_duration(beat, shot_type),
                        audio_notes=self._audio_notes(beat),
                        source_text=beat,
                    )
                )
        return shots

    def _extract_beats(self, scene: Scene) -> list[str]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", scene.body) if part.strip()]
        beats: list[str] = []
        for paragraph in paragraphs:
            lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            if lines and CHARACTER_RE.fullmatch(lines[0]) and len(lines) > 1:
                beats.append(f"{lines[0]}: {' '.join(lines[1:])}")
                continue
            for sentence in SENTENCE_RE.split(" ".join(lines)):
                sentence = sentence.strip()
                if sentence:
                    beats.append(sentence)
        if not beats:
            beats.append(f"Plano de establecimiento de {scene.location}")
        return self._merge_short_beats(beats)

    @staticmethod
    def _merge_short_beats(beats: list[str]) -> list[str]:
        merged: list[str] = []
        for beat in beats:
            if merged and len(beat.split()) < 4 and len(merged[-1].split()) < 24:
                merged[-1] = f"{merged[-1]} {beat}"
            else:
                merged.append(beat)
        return merged

    @staticmethod
    def _contains(text: str, vocabulary: set[str]) -> bool:
        words = set(re.findall(r"[a-záéíóúüñ]+", text.lower()))
        return bool(words & vocabulary)

    def _choose_shot_type(self, beat: str, position: int) -> str:
        lower = beat.lower()
        if position == 1 or self._contains(lower, ESTABLISHING_WORDS):
            return "Gran plano general" if position == 1 else "Plano general"
        if CHARACTER_RE.match(beat.split(":", 1)[0]) and ":" in beat:
            return "Plano medio"
        if self._contains(lower, EMOTIONAL_WORDS):
            return "Primer plano"
        if self._contains(lower, ACTION_WORDS):
            return "Plano entero"
        if any(word in lower for word in ("mano", "objeto", "teléfono", "carta", "llave")):
            return "Plano detalle"
        return "Plano medio"

    def _choose_camera_movement(self, beat: str, shot_type: str) -> str:
        lower = beat.lower()
        if any(word in lower for word in ("corre", "huye", "persigue", "avanza", "camina")):
            return "Travelling de seguimiento"
        if any(word in lower for word in ("descubre", "revela", "aparece", "entra")):
            return "Dolly in suave"
        if any(word in lower for word in ("mira", "gira", "cruza")):
            return "Paneo controlado"
        if shot_type in {"Primer plano", "Plano detalle"}:
            return "Cámara fija con respiración orgánica"
        if shot_type == "Gran plano general":
            return "Travelling de establecimiento lento"
        return "Cámara fija"

    def _estimate_duration(self, beat: str, shot_type: str) -> float:
        words = max(1, len(beat.split()))
        base = words / self.words_per_second
        if ":" in beat:
            base += 1.5
        if shot_type == "Gran plano general":
            base += 2.0
        return round(min(self.max_shot_seconds, max(2.0, base)), 1)

    @staticmethod
    def _visual_description(beat: str, scene: Scene, shot_type: str) -> str:
        clean = re.sub(r"\s+", " ", beat).strip()
        return f"{shot_type} en {scene.location}: {clean}"

    @staticmethod
    def _audio_notes(beat: str) -> str:
        if ":" in beat and CHARACTER_RE.match(beat.split(":", 1)[0]):
            return "Diálogo directo y ambiente de la localización"
        if any(word in beat.lower() for word in ("silencio", "calla", "quietud")):
            return "Silencio dramático con ambiente tenue"
        return "Sonido ambiente y efectos sincronizados con la acción"


def build_production_document(
    source: Path, scenes: list[Scene], shots: list[Shot]
) -> dict[str, object]:
    total_duration = round(sum(shot.estimated_duration_seconds for shot in shots), 1)
    return {
        "schema_version": "1.0",
        "project": {
            "title": source.stem,
            "source_file": str(source.resolve()),
            "generated_at": datetime.now(UTC).isoformat(),
            "generator": "Davinci-agent / Orizon Studio",
        },
        "production_summary": {
            "scene_count": len(scenes),
            "shot_count": len(shots),
            "estimated_total_duration_seconds": total_duration,
        },
        "scenes": [
            {
                **asdict(scene),
                "shots": [asdict(shot) for shot in shots if shot.scene_number == scene.number],
            }
            for scene in scenes
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte un guión literario en un desglose cinematográfico JSON."
    )
    parser.add_argument("script", type=Path, help="Guión de entrada en TXT, MD o FOUNTAIN")
    parser.add_argument("-o", "--output", type=Path, help="Ruta del JSON de producción")
    parser.add_argument("--words-per-second", type=float, default=2.4)
    parser.add_argument("--max-shot-seconds", type=float, default=12.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source: Path = args.script
    output: Path = args.output or source.with_name(f"{source.stem}_shot_list.json")

    if not source.is_file():
        print(f"Error: no existe el guión: {source}", file=sys.stderr)
        return 2

    try:
        text = source.read_text(encoding="utf-8-sig")
        scenes = ScreenplayParser().parse(text)
        shots = CinematicPlanner(
            words_per_second=args.words_per_second,
            max_shot_seconds=args.max_shot_seconds,
        ).plan(scenes)
        document = build_production_document(source, scenes, shots)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Desglose creado: {output.resolve()}")
    print(f"Escenas: {len(scenes)} | Tomas: {len(shots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
