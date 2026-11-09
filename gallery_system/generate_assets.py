"""
generate_assets.py

Generate audio or transform existing audio using Stability AI.

Install:
    pip install requests python-dotenv

Environment (.env):
    STABILITY_API_KEY=your_api_key

Examples:

    # Generate from a text prompt
    python generate_assets.py generate \
        --prompt "Dark ambient soundscape, deep drones, evolving textures, no vocals" \
        --output assets/storm.mp3 \
        --duration 30

    # Transform an existing audio file
    python generate_assets.py transition \
        --input assets/storm.mp3 \
        --prompt "Introduce mechanical metallic pulses while retaining the dark drone" \
        --output assets/storm_to_machine.mp3 \
        --duration 30 \
        --strength 0.3

    # Generate an emotionally conditioned gallery variation
    python generate_assets.py emotion \
        --input audio/cell_2.mp3 \
        --output audio/generated/cell_2.mp3 \
        --intensity 0.7 \
        --valence -0.4

The source audio is never overwritten. Output is first written to a
temporary file and renamed after the result has been downloaded.

The StabilityAudioClient.transition() method is also used by server.py.
"""

import argparse
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()


class StabilityAudioError(RuntimeError):
    """Raised when Stability AI cannot generate the requested audio."""


class StabilityAudioClient:
    """Generate music or transform existing audio using Stability AI."""

    BASE_URL = "https://api.stability.ai/v2beta/audio"
    RESULTS_URL = f"{BASE_URL}/results"

    def __init__(
        self,
        api_key: Optional[str] = None,
        poll_interval: float = 3,
        timeout: float = 900,
    ):
        self.api_key = api_key or os.getenv("STABILITY_API_KEY")

        if not self.api_key:
            raise ValueError(
                "Missing API key. Set STABILITY_API_KEY in your .env file."
            )

        self.headers = {
            "authorization": f"Bearer {self.api_key}",
            "accept": "audio/*",
        }
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.session = requests.Session()

    def generate(
        self,
        prompt: str,
        output: str | Path = "output.mp3",
        duration: int = 30,
    ) -> Path:
        """Generate audio from a text prompt."""
        self._validate_duration(duration)

        response = self.session.post(
            f"{self.BASE_URL}/stable-audio/text-to-audio",
            headers=self.headers,
            files={"none": ""},
            data={
                "prompt": prompt,
                "output_format": "mp3",
                "duration": duration,
            },
            timeout=180,
        )

        return self._wait_for_result(response, output)

    def transition(
        self,
        source_path: str | Path,
        prompt: str,
        output_path: str | Path = "transition.mp3",
        duration: int = 30,
        strength: float = 0.4,
    ) -> Path:
        """
        Transform an input audio file according to a text prompt.

        Lower strength generally preserves more of the original audio.
        This method is compatible with the gallery server's background worker.
        """
        input_path = Path(source_path)

        if not input_path.is_file():
            raise FileNotFoundError(f"Input audio not found: {input_path}")

        self._validate_duration(duration)

        if not 0.0 <= strength <= 1.0:
            raise ValueError("Strength must be between 0 and 1.")

        output_path = Path(output_path)
        temporary_path = self._temporary_path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with input_path.open("rb") as audio_file:
                response = self.session.post(
                    f"{self.BASE_URL}/stable-audio/audio-to-audio",
                    headers=self.headers,
                    files={
                        "audio": (
                            input_path.name,
                            audio_file,
                            self._content_type(input_path),
                        )
                    },
                    data={
                        "prompt": prompt,
                        "output_format": "mp3",
                        "duration": duration,
                        "strength": strength,
                    },
                    timeout=180,
                )

            return self._wait_for_result(
                response,
                output_path,
                temporary_path=temporary_path,
            )

        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def _wait_for_result(
        self,
        response: requests.Response,
        output: str | Path,
        temporary_path: Optional[Path] = None,
    ) -> Path:
        """Poll the async job and save its completed audio."""
        output_path = Path(output)
        temporary_path = temporary_path or self._temporary_path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Stable Audio's asynchronous endpoint returns 202 and a job ID.
            if response.status_code != 202:
                raise StabilityAudioError(
                    f"Generation request failed ({response.status_code}): "
                    f"{response.text[:2000]}"
                )

            try:
                generation_id = response.json()["id"]
            except (ValueError, KeyError, TypeError) as exc:
                raise StabilityAudioError(
                    f"Could not read generation ID: {response.text[:1000]}"
                ) from exc

            print(f"Generation started: {generation_id}")

            result_url = f"{self.RESULTS_URL}/{generation_id}"
            deadline = time.monotonic() + self.timeout

            while time.monotonic() < deadline:
                time.sleep(self.poll_interval)

                result = self.session.get(
                    result_url,
                    headers=self.headers,
                    timeout=60,
                )

                if result.status_code == 202:
                    print("Generation in progress...")
                    continue

                if result.status_code == 200:
                    if not result.content:
                        raise StabilityAudioError(
                            "Stability returned an empty audio file."
                        )

                    # The result endpoint returns the audio bytes.
                    temporary_path.write_bytes(result.content)
                    temporary_path.replace(output_path)

                    print(f"Audio saved to: {output_path.resolve()}")
                    return output_path

                if result.status_code >= 500:
                    print(
                        f"Temporary result-server error "
                        f"({result.status_code}); retrying..."
                    )
                    continue

                raise StabilityAudioError(
                    f"Generation result failed ({result.status_code}): "
                    f"{result.text[:2000]}"
                )

            raise TimeoutError(
                f"Generation {generation_id} did not finish within "
                f"{self.timeout} seconds."
            )

        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_duration(duration: int):
        if duration < 1:
            raise ValueError("Duration must be at least 1 second.")

    @staticmethod
    def _content_type(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            return "audio/mpeg"
        if suffix == ".wav":
            return "audio/wav"
        if suffix == ".flac":
            return "audio/flac"
        if suffix == ".ogg":
            return "audio/ogg"
        return "application/octet-stream"

    @staticmethod
    def _temporary_path(output_path: Path) -> Path:
        return output_path.with_suffix(output_path.suffix + ".partial")


def build_emotion_prompt(
    base_prompt: str,
    intensity: float,
    valence: float,
) -> str:
    """
    Build a strongly differentiated audio-transition prompt.

    Intensity controls energy, density, rhythmic motion, and transients.
    Valence controls harmonic color, timbre, and emotional character.
    """
    intensity = max(0.0, min(1.0, float(intensity)))
    valence = max(-1.0, min(1.0, float(valence)))

    # INTENSITY: describe audible production and arrangement changes.
    if intensity < 0.2:
        energy = (
            "EXTREMELY LOW ENERGY. Nearly weightless, sparse, and still. "
            "Use long sustained tones, soft rounded attacks, very slow "
            "evolution, large spaces between events, almost no percussion, "
            "no prominent pulse, and very few simultaneous layers. "
            "The sound should feel suspended and motionless."
        )
    elif intensity < 0.4:
        energy = (
            "LOW ENERGY. Slow breathing-like swells, sparse notes, soft "
            "attacks, gentle movement, minimal rhythmic activity, and "
            "widely spaced organic textures. Keep the arrangement open "
            "and spacious, with only occasional subtle pulses."
        )
    elif intensity < 0.6:
        energy = (
            "MODERATE ENERGY. Establish a clearly perceptible, steady pulse. "
            "Use several interacting layers, gentle rhythmic repetition, "
            "noticeable dynamic movement, and evolving patterns. Maintain "
            "a balanced mix of spaciousness and activity."
        )
    elif intensity < 0.8:
        energy = (
            "HIGH ENERGY. Make the increase in energy unmistakable. "
            "Introduce a strong repeating rhythmic pulse, denser overlapping "
            "layers, more frequent events, sharper attacks, faster textural "
            "movement, pronounced swells, and greater dynamic contrast. "
            "The sound should feel active and propulsive, not merely louder."
        )
    else:
        energy = (
            "VERY HIGH ENERGY. Create a dense, animated, rhythmically driven "
            "soundscape with persistent pulsing, rapid repeating patterns, "
            "crisp transients, layered rhythmic details, strong forward "
            "momentum, and dramatic evolving swells. Keep the sound musical "
            "and controlled, but make it dramatically more active than a "
            "low-intensity version."
        )

    # VALENCE: change the emotional color independently of energy.
    if valence < -0.6:
        mood = (
            "VERY DARK AND UNSETTLING. Favor minor-mode or ambiguous harmony, "
            "low resonant tones, hollow and rough timbres, dissonant intervals, "
            "descending gestures, muted colors, and unresolved harmonic "
            "tension. The emotional character should feel ominous, lonely, "
            "and introspective."
        )
    elif valence < -0.2:
        mood = (
            "SOMBER AND MELANCHOLIC. Favor minor-key colors, wistful melodic "
            "fragments, subdued warmth, slightly dissonant harmonies, soft "
            "low-mid textures, and unresolved phrases. The sound should feel "
            "reflective and emotionally heavy rather than frightening."
        )
    elif valence < 0.2:
        mood = (
            "EMOTIONALLY AMBIGUOUS. Use open-ended harmony, balanced timbres, "
            "neither strongly dark nor strongly bright, and a sense of "
            "curiosity without a clear emotional resolution."
        )
    elif valence < 0.6:
        mood = (
            "WARM AND REASSURING. Favor consonant harmony, rounded and mellow "
            "timbres, gentle upper harmonics, smooth rising gestures, a sense "
            "of harmonic resolution, and an inviting, peaceful atmosphere."
        )
    else:
        mood = (
            "STRONGLY BRIGHT AND HOPEFUL. Favor luminous upper-register tones, "
            "clear consonant harmonies, major-key colors, uplifting melodic "
            "gestures, sparkling harmonics, rising phrases, and a feeling of "
            "openness, wonder, and emotional release. The result should sound "
            "noticeably more radiant and optimistic than a dark-valence version."
        )

    return f"""
Create an audio-to-audio transformation of the supplied source.

PRIMARY EMOTIONAL DIRECTION:
{mood}

PRIMARY ENERGY DIRECTION:
{energy}

MAKE THE CHANGE AUDIBLY OBVIOUS:
The emotional direction and energy direction above are the main creative
instructions, not minor background suggestions. Change the musical
arrangement, rhythmic behavior, harmonic color, timbral balance, and
textural density as needed to express them. Do not merely make a small
equalization change or a slight variation of the source.

SOURCE CONTINUITY:
Retain a recognizable connection to the original sound's tonal foundation,
broad sonic palette, and spatial atmosphere. Reinterpret those elements to
express the requested emotion and energy. Preserve continuity without
preserving the original arrangement unchanged.

GALLERY MIX:
Maintain a coherent, immersive ambient soundscape suitable for a continuous
art gallery installation. Use smooth evolution and musical transitions.
No vocals, abrupt cuts, or sudden loud impacts.

BASE SOUNDSCAPE:
{base_prompt.strip()}
""".strip()


def main():
    parser = argparse.ArgumentParser(
        description="Generate or transform audio using Stability AI."
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # Text-to-audio generation.
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate audio from a text prompt.",
    )
    generate_parser.add_argument("--prompt", required=True)
    generate_parser.add_argument("--output", default="output.mp3")
    generate_parser.add_argument("--duration", type=int, default=30)

    # Audio-to-audio transformation.
    transition_parser = subparsers.add_parser(
        "transition",
        help="Transform an existing audio file.",
    )
    transition_parser.add_argument("--input", required=True)
    transition_parser.add_argument("--prompt", required=True)
    transition_parser.add_argument("--output", default="transition.mp3")
    transition_parser.add_argument("--duration", type=int, default=30)
    transition_parser.add_argument("--strength", type=float, default=0.4)

    # Emotion-conditioned transformation for gallery assets.
    emotion_parser = subparsers.add_parser(
        "emotion",
        help="Transform audio using intensity and valence controls.",
    )
    emotion_parser.add_argument("--input", required=True)
    emotion_parser.add_argument("--output", default="emotion.mp3")
    emotion_parser.add_argument("--intensity", type=float, default=0.5)
    emotion_parser.add_argument("--valence", type=float, default=0.0)
    emotion_parser.add_argument("--duration", type=int, default=30)
    emotion_parser.add_argument("--strength", type=float, default=0.35)
    emotion_parser.add_argument(
        "--base-prompt",
        default=(
            "A calming ambient soundscape with a deep drone and evolving "
            "organic textures."
        ),
    )

    args = parser.parse_args()

    try:
        client = StabilityAudioClient()

        if args.command == "generate":
            client.generate(
                prompt=args.prompt,
                output=args.output,
                duration=args.duration,
            )

        elif args.command == "transition":
            client.transition(
                source_path=args.input,
                prompt=args.prompt,
                output_path=args.output,
                duration=args.duration,
                strength=args.strength,
            )

        elif args.command == "emotion":
            prompt = build_emotion_prompt(
                base_prompt=args.base_prompt,
                intensity=args.intensity,
                valence=args.valence,
            )

            print("Emotion-conditioned prompt:")
            print(prompt)

            client.transition(
                input_audio=args.input,
                prompt=prompt,
                output=args.output,
                duration=args.duration,
                strength=args.strength,
            )

    except (
        ValueError,
        FileNotFoundError,
        RuntimeError,
        TimeoutError,
        requests.RequestException,
    ) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()