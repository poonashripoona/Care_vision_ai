"""
Skin analysis pipeline for CARE VISION AI.

Defines a small CNN-style classifier (NumPy) and a heuristic fallback so
every valid image + symptom payload returns a structured result. This is a
prototype — not a diagnostic model.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

RISK_LEVELS = ("Low", "Moderate", "High")
IMAGE_SIZE = 96

# Words that raise concern in everyday symptom descriptions.
HIGH_CONCERN_TERMS = (
    "bleed",
    "bleeding",
    "pus",
    "fever",
    "spreading",
    "spread",
    "ulcer",
    "open wound",
    "black",
    "mole changing",
    "growing fast",
    "severe pain",
    "swelling",
    "oozing",
)
MODERATE_CONCERN_TERMS = (
    "itch",
    "itchy",
    "pain",
    "painful",
    "red",
    "rash",
    "bump",
    "blister",
    "dry",
    "peeling",
    "warm",
    "tender",
    "spot",
    "mole",
    "scaly",
)


class MiniSkinCNN:
    """
    Tiny convolutional network implemented in NumPy.

    Architecture (prototype, untrained random-but-fixed weights):
        Input 96x96x3
        -> Conv 3x3 (3 filters: redness, edges, texture) + ReLU
        -> 2x2 average pool
        -> Flatten
        -> Dense -> 3 class logits (Low / Moderate / High)

    Without trained weights this is not clinically accurate. Image features
    from the conv stage are combined with a symptom heuristic in
    ``analyze_skin_image`` so outputs stay stable and explainable.
    """

    def __init__(self, seed: int = 42) -> None:
        rng = np.random.default_rng(seed)
        # 3 filters, 3x3, 3 input channels — biased toward redness / edges.
        self.kernels = rng.normal(0, 0.15, size=(3, 3, 3, 3)).astype(np.float32)
        self.kernels[0, :, :, 0] += 0.45  # redness (R channel)
        laplacian = np.array([[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]], dtype=np.float32) * 0.12
        self.kernels[1] = np.stack([laplacian, laplacian, laplacian], axis=2)
        self.dense_w = rng.normal(0, 0.08, size=(3 * 48 * 48, 3)).astype(np.float32)
        self.dense_b = np.array([0.15, 0.05, -0.1], dtype=np.float32)

    def _conv2d(self, image: np.ndarray) -> np.ndarray:
        """Valid-ish same-padded 3x3 convolution over RGB."""
        padded = np.pad(image, ((1, 1), (1, 1), (0, 0)), mode="edge")
        h, w, _ = image.shape
        out = np.zeros((h, w, 3), dtype=np.float32)
        for f in range(3):
            kernel = self.kernels[f]
            acc = np.zeros((h, w), dtype=np.float32)
            for c in range(3):
                k = kernel[:, :, c]
                for i in range(3):
                    for j in range(3):
                        acc += padded[i : i + h, j : j + w, c] * k[i, j]
            out[:, :, f] = acc
        return np.maximum(out, 0.0)

    def forward_features(self, image: np.ndarray) -> dict[str, float]:
        """Run conv + pool and return human-readable visual scores in [0, 1]."""
        conv = self._conv2d(image)
        pooled = conv.reshape(48, 2, 48, 2, 3).mean(axis=(1, 3))
        redness = float(np.clip(pooled[:, :, 0].mean() / 2.5, 0, 1))
        edges = float(np.clip(pooled[:, :, 1].mean() / 2.5, 0, 1))
        texture = float(np.clip(pooled[:, :, 2].std() * 2.0, 0, 1))
        logits = pooled.reshape(-1) @ self.dense_w + self.dense_b
        # Softmax for a model-style class hint (not used as the sole decision).
        shifted = logits - logits.max()
        probs = np.exp(shifted) / np.exp(shifted).sum()
        return {
            "redness": redness,
            "edges": edges,
            "texture": texture,
            "cnn_low": float(probs[0]),
            "cnn_moderate": float(probs[1]),
            "cnn_high": float(probs[2]),
        }


_CNN = MiniSkinCNN()


def _load_image(image_path: str) -> np.ndarray:
    """Load, auto-orient, resize, and normalize an image to [0, 1] RGB."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img = img.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
            array = np.asarray(img, dtype=np.float32) / 255.0
    except UnidentifiedImageError as exc:
        raise ValueError("The uploaded file is not a readable image.") from exc
    except OSError as exc:
        raise ValueError("Could not read the uploaded image.") from exc

    return array


def _color_stats(image: np.ndarray) -> dict[str, float]:
    """Simple color statistics that are easy to explain in plain language."""
    r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    redness = float(np.clip((r.mean() - (g.mean() + b.mean()) / 2.0) * 3.5 + 0.25, 0, 1))
    darkness = float(np.clip(1.0 - image.mean(), 0, 1))
    contrast = float(np.clip(image.std() * 4.0, 0, 1))
    return {"redness": redness, "darkness": darkness, "contrast": contrast}


def _symptom_score(symptoms_data: dict[str, Any]) -> tuple[float, list[str]]:
    """Turn duration, progression, and free-text symptoms into a 0–1 score."""
    text = str(symptoms_data.get("symptoms") or "").lower()
    duration = str(symptoms_data.get("duration") or "")
    progression = str(symptoms_data.get("progression") or "")

    score = 0.15
    notes: list[str] = []

    hits_high = [term for term in HIGH_CONCERN_TERMS if term in text]
    hits_mod = [term for term in MODERATE_CONCERN_TERMS if term in text]
    if hits_high:
        score += 0.38
        notes.append("You mentioned signs that often need a doctor soon.")
    elif hits_mod:
        score += 0.18
        notes.append("Your symptoms match a common skin concern.")
    elif text.strip():
        score += 0.08
        notes.append("Thank you for describing how the skin feels.")
    else:
        notes.append("No extra symptoms were typed, so we relied more on the photo.")

    if duration in {"2 weeks", "1 month", "More than 1 month"}:
        score += 0.12
        notes.append("It has lasted a while, so a check-up is a good idea.")
    elif duration == "1 week":
        score += 0.06

    if progression == "Getting worse":
        score += 0.22
        notes.append("It is getting worse, which raises the urgency.")
    elif progression == "Getting better":
        score -= 0.08
        notes.append("It seems to be improving, which is a reassuring sign.")
    else:
        notes.append("It has stayed about the same.")

    return float(np.clip(score, 0, 1)), notes


def _risk_from_score(score: float) -> str:
    if score >= 0.62:
        return "High"
    if score >= 0.38:
        return "Moderate"
    return "Low"


def _explanation(risk: str, visual: dict[str, float], notes: list[str]) -> str:
    visual_bits = []
    if visual["redness"] >= 0.45:
        visual_bits.append("the photo looks quite red")
    if visual["edges"] >= 0.45 or visual["contrast"] >= 0.5:
        visual_bits.append("the edges or texture look uneven")
    if visual["darkness"] >= 0.55:
        visual_bits.append("some areas look darker than the nearby skin")
    if not visual_bits:
        visual_bits.append("the photo does not show strong warning colors")

    visual_sentence = "From the photo, " + " and ".join(visual_bits) + "."
    note_sentence = " ".join(notes)

    if risk == "High":
        advice = (
            "Please contact a doctor or nearby hospital soon. "
            "This is not a diagnosis, but waiting could miss something important."
        )
    elif risk == "Moderate":
        advice = (
            "It is wise to see a skin doctor (dermatologist) if this does not "
            "settle in a few days, or sooner if it spreads or becomes painful."
        )
    else:
        advice = (
            "This may be a mild issue. Keep the area clean, avoid scratching, "
            "and see a doctor if it changes, spreads, or starts to hurt."
        )

    return f"{visual_sentence} {note_sentence} {advice}"


def analyze_skin_image(image_path: str, symptoms_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Classify a skin photo plus symptoms into Low / Moderate / High risk.

    Always returns a dict with:
        risk_level, explanation, specialist, concern_label, scores
    """
    symptoms_data = symptoms_data or {}

    try:
        image = _load_image(image_path)
        cnn_feats = _CNN.forward_features(image)
        color = _color_stats(image)
        visual = {
            "redness": max(cnn_feats["redness"], color["redness"]),
            "edges": cnn_feats["edges"],
            "texture": cnn_feats["texture"],
            "darkness": color["darkness"],
            "contrast": color["contrast"],
        }
        image_score = float(
            np.clip(
                0.40 * visual["redness"]
                + 0.25 * visual["edges"]
                + 0.20 * visual["contrast"]
                + 0.15 * visual["darkness"],
                0,
                1,
            )
        )
    except Exception as exc:  # noqa: BLE001 — never crash the request path
        logger.warning("Image pipeline fallback: %s", exc)
        visual = {"redness": 0.3, "edges": 0.3, "texture": 0.3, "darkness": 0.3, "contrast": 0.3}
        image_score = 0.35

    symptom_score, notes = _symptom_score(symptoms_data)
    combined = float(np.clip(0.55 * image_score + 0.45 * symptom_score, 0, 1))
    risk = _risk_from_score(combined)

    if risk == "High":
        concern = "Urgent skin concern — please seek care soon"
        specialist = "Dermatologist (and Emergency / General Physician if it is spreading fast, bleeding, or you have fever)"
    elif risk == "Moderate":
        concern = "Skin change that should be checked"
        specialist = "Dermatologist"
    else:
        concern = "Mild or common skin irritation"
        specialist = "Dermatologist (or a local clinic / general physician)"

    return {
        "risk_level": risk,
        "explanation": _explanation(risk, visual, notes),
        "specialist": specialist,
        "concern_label": concern,
        "scores": {
            "combined": round(combined, 3),
            "image": round(image_score, 3),
            "symptoms": round(symptom_score, 3),
            "visual": {k: round(v, 3) for k, v in visual.items()},
        },
    }
