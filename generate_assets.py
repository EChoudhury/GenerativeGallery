
import os
import time
import argparse
from pathlib import Path

import requests
from dotenv import load_dotenv


"""
Example Generation Usage:
python generate_assets.py generate --prompt "Dark ambient soundscape, deep drones, evolving textures, subtle metallic percussion, no vocals" --output assets/storm.mp3 --duration 30

Example Transition Usage:
python generate_assets.py transition --input storm_drone.wav --prompt "Transform the drone into a mechanical soundscape with precise metallic pulses, retaining its dark low-frequency atmosphere" --output assets/storm_to_machine.mp3 --duration 30
"""

class StabilityAudioClient:
    """Generate music or transform existing audio using Stability AI."""

    BASE_URL = "https://api.stability.ai/v2beta/audio"

    def __init__(self, api_key=None, poll_interval=10, timeout=600):
        load_dotenv()

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

    def generate(self, prompt, output="output.mp3", duration=30):
        """Generate audio from a text prompt."""
        response = requests.post(
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
        input_audio,
        prompt,
        output="transition.mp3",
        duration=30,
        strength=0.4,
    ):
        """Transform an input audio file according to a text prompt."""
        input_path = Path(input_audio)

        if not input_path.is_file():
            raise FileNotFoundError(f"Input audio not found: {input_path}")

        with input_path.open("rb") as audio_file:
            response = requests.post(
                f"{self.BASE_URL}/stable-audio/audio-to-audio",
                headers=self.headers,
                files={"audio": audio_file},
                data={
                    "prompt": prompt,
                    "output_format": "mp3",
                    "duration": duration,
                    "strength": strength,
                },
                timeout=180,
            )

        return self._wait_for_result(response, output)

    def _wait_for_result(self, response, output):
        """Poll the asynchronous generation job and save its audio."""
        if response.status_code != 202:
            raise RuntimeError(
                f"Generation request failed ({response.status_code}): "
                f"{response.text}"
            )

        generation_id = response.json()["id"]
        print(f"Generation started: {generation_id}")

        result_url = f"{self.BASE_URL}/results/{generation_id}"
        deadline = time.monotonic() + self.timeout

        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)

            result = requests.get(
                result_url,
                headers=self.headers,
                timeout=60,
            )

            if result.status_code == 202:
                print("Generation in progress...")
                continue

            if result.status_code == 200:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(result.content)
                print(f"Audio saved to: {output_path.resolve()}")
                return output_path

            raise RuntimeError(
                f"Generation result failed ({result.status_code}): "
                f"{result.text}"
            )

        raise TimeoutError(
            f"Generation did not finish within {self.timeout} seconds."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Generate or transform audio using Stability AI."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate", help="Generate audio from a text prompt."
    )
    generate_parser.add_argument("--prompt", required=True)
    generate_parser.add_argument("--output", default="output.mp3")
    generate_parser.add_argument("--duration", type=int, default=30)

    transition_parser = subparsers.add_parser(
        "transition", help="Transform an existing audio file."
    )
    transition_parser.add_argument("--input", required=True)
    transition_parser.add_argument("--prompt", required=True)
    transition_parser.add_argument("--output", default="transition.mp3")
    transition_parser.add_argument("--duration", type=int, default=30)
    transition_parser.add_argument("--strength", type=float, default=0.4)

    args = parser.parse_args()

    try:
        client = StabilityAudioClient()

        if args.command == "generate":
            client.generate(args.prompt, args.output, args.duration)
        else:
            client.transition(
                args.input, args.prompt, args.output, args.duration, args.strength
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
