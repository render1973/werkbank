"""
Lokale Transkription mit faster-whisper (CTranslate2-Backend, GPU-fähig).

WICHTIG: Falls du bereits ein funktionierendes Whisper-Setup hast (z.B. das
venv, das du für dein ROG-Laptop mit der RTX-GPU eingerichtet hast), kannst
du dieses Modul anpassen, um dein bestehendes Setup zu nutzen, statt eine
zweite Installation zu pflegen. Die einzige Anforderung an dieses Modul:

    transcribe_audio(path) -> {"text": str, "language": str, "duration": float}

Alles andere ist austauschbar.
"""

import contextlib
import time
import os
from pathlib import Path

import job_status

# Modellgröße per Umgebungsvariable steuerbar, Default: "medium"
# Optionen: tiny, base, small, medium, large-v3
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")

# "cuda" nutzt deine GPU. Falls faster-whisper die GPU nicht findet
# (fehlende cuDNN/CUDA-Libs), auf "cpu" zurückfallen — deutlich langsamer,
# aber funktioniert immer.
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")  # "int8" für CPU

_model = None  # Lazy Loading — Modell erst beim ersten Aufruf laden, nicht beim Start
_model_device = None  # tatsächlich verwendetes Gerät nach dem ersten Laden ("cuda"/"cpu") -
                       # kann von WHISPER_DEVICE abweichen, falls der GPU-Fallback unten griff


def _get_model():
    global _model, _model_device
    if _model is None:
        job_status.set_phase("modell_laden")
        from faster_whisper import WhisperModel
        print(f"Lade Whisper-Modell '{WHISPER_MODEL_SIZE}' "
              f"(device={WHISPER_DEVICE}, compute_type={WHISPER_COMPUTE_TYPE}) ...")
        try:
            _model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
            _model_device = WHISPER_DEVICE
        except Exception as exc:
            print(f"GPU-Laden fehlgeschlagen ({exc}). Fallback auf CPU.")
            _model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8",
            )
            _model_device = "cpu"
    return _model


# --- GPU-Sperre ------------------------------------------------------------
# Gleicher Mechanismus wie im Anonymisierungs-Sidecar (apps/anonymisierung/
# anonymize_service.py): datei-basierte Sperre unter shared/gpu.lock,
# exklusives Anlegen, Stale-Lock-Erkennung nach GPU_LOCK_STALE_SECONDS,
# Freigabe im finally-Block.
#
# Unterschied zum Sidecar: dort schlägt die Sperre sofort fehl, wenn belegt
# (der Aufrufer entscheidet selbst, ob er wartet). Hier wartet die Sperre
# kurz mit Retry, bevor sie aufgibt — der Nutzer wartet ohnehin schon auf
# die Verarbeitung seines Uploads, ein kurzes Warten ist sinnvoller als ein
# sofortiger Fehler. WICHTIG: Bleibt das Lock nach der Wartezeit belegt,
# wirft gpu_lock() eine RuntimeError, BEVOR das Modell überhaupt angefasst
# wird — der bestehende CPU-Fallback in _get_model() (oben, für echte
# GPU-Hardwareprobleme gedacht) wird dadurch NICHT ausgelöst. Sonst würde
# GPU-Konkurrenz mit dem Sidecar zu einer stillen Verlangsamung statt einer
# klaren Fehlermeldung führen.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GPU_LOCK_PATH = Path(os.getenv("GPU_LOCK_PATH", str(PROJECT_ROOT / "shared" / "gpu.lock")))
GPU_LOCK_STALE_SECONDS = 600  # identisch zu anonymize_service.py
GPU_LOCK_WAIT_SECONDS = int(os.getenv("GPU_LOCK_WAIT_SECONDS", "60"))
GPU_LOCK_RETRY_INTERVAL_SECONDS = 5


@contextlib.contextmanager
def gpu_lock():
    GPU_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + GPU_LOCK_WAIT_SECONDS

    while True:
        if GPU_LOCK_PATH.exists():
            age = time.time() - GPU_LOCK_PATH.stat().st_mtime
            if age > GPU_LOCK_STALE_SECONDS:
                GPU_LOCK_PATH.unlink(missing_ok=True)

        try:
            # "x" = exklusiv anlegen, schlägt fehl wenn Datei schon existiert -> atomar
            with open(GPU_LOCK_PATH, "x") as f:
                f.write(f"hub_transcribe pid={os.getpid()} ts={time.time()}")
            break  # Sperre erfolgreich angelegt
        except FileExistsError:
            remaining = deadline - time.time()
            if remaining <= 0:
                job_status.set_phase("idle")
                raise RuntimeError(
                    "GPU aktuell durch PDF-Anonymisierung belegt, bitte in "
                    "ein paar Minuten erneut versuchen."
                )
            job_status.set_phase("wartet_auf_gpu")
            time.sleep(min(GPU_LOCK_RETRY_INTERVAL_SECONDS, remaining))

    try:
        yield
    finally:
        GPU_LOCK_PATH.unlink(missing_ok=True)


def transcribe_audio(audio_path: str) -> dict:
    """Transkribiert eine Audiodatei lokal. Gibt Text, erkannte Sprache und
    Dauer zurück. Läuft komplett offline nach dem ersten Modell-Download.

    Belegt für die Dauer der Transkription (inkl. eines evtl. ersten
    Modell-Ladens) die gemeinsame GPU-Sperre, sofern überhaupt GPU genutzt
    wird — reines CPU-Setup (WHISPER_DEVICE=cpu oder nach einem bereits
    erfolgten GPU-Fallback) braucht keine Sperre und wartet nie darauf."""

    # Vor dem ersten Laden ist das tatsächliche Gerät noch unbekannt - dann
    # nach WHISPER_DEVICE richten. Danach zählt das tatsächlich verwendete
    # Gerät (kann nach einem Fallback von WHISPER_DEVICE abweichen).
    braucht_gpu = (_model_device or WHISPER_DEVICE) != "cpu"
    lock_ctx = gpu_lock() if braucht_gpu else contextlib.nullcontext()

    with lock_ctx:
        model = _get_model()
        start = time.time()

        segments, info = model.transcribe(
            audio_path,
            language="de",
            vad_filter=True,      # Stille/Pausen herausfiltern, verbessert Qualität
            beam_size=5,
            condition_on_previous_text=False,  # verhindert Wiederholungsschleifen
            # ("..."-Halluzination) bei Stille/Rauschen/undeutlichen Passagen —
            # ohne das kann sich das Modell bei langen Aufnahmen minutenlang in
            # derselben Phrase verhaken (GPU bleibt dabei sichtbar ausgelastet,
            # arbeitet aber nutzlos im Kreis statt voranzukommen).
        )

        # segments ist ein Generator — faster-whisper transkribiert Segment für
        # Segment on-the-fly. Nach jedem Segment kennen wir dessen Endzeit
        # (segment.end) und damit den ungefähren Fortschritt durch die
        # Audiodatei (info.duration ist die Gesamtdauer, schon vor der
        # Iteration bekannt).
        job_status.set_phase("transkribiert", current=0.0, total=info.duration)
        texts = []
        for segment in segments:
            texts.append(segment.text.strip())
            job_status.set_phase("transkribiert", current=segment.end, total=info.duration)

        full_text = " ".join(texts)
        elapsed = time.time() - start

        print(f"Transkription fertig in {elapsed:.1f}s. "
              f"Sprache erkannt: {info.language} (Konfidenz {info.language_probability:.2f})")

        return {
            "text": full_text.strip(),
            "language": info.language,
            "duration": info.duration,
        }
