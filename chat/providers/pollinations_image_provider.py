
import time
import urllib.parse
import random

from chat.utils.logger import SimbaLogger

logger = SimbaLogger()

# The only model Pollinations' /prompt endpoint currently serves (verified
# against https://image.pollinations.ai/models). Requesting an unsupported
# model name (e.g. the old "flux") is silently ignored by the API and it
# falls back to this anyway - so it must be explicit and correct here.
MODEL_NAME = "sana"


class PollinationsImageProvider:
    ASPECT_RATIO_SIZES = {
        "1:1": (1024, 1024),
        "16:9": (1344, 768),
        "9:16": (768, 1344)
    }

    # Light, natural-language quality cues. Modern models (this one included)
    # respond better to a few well-chosen descriptors than to a long list of
    # stacked buzzwords, which tends to push the model toward an oversaturated
    # macro crop instead of a well-composed scene. The heavy lifting for
    # quality comes from Pollinations' own `enhance=true` LLM prompt rewrite.
    QUALITY_SUFFIX = "high quality, detailed, natural lighting"

    NEGATIVE_PROMPT_KEYWORDS = [
        "blurry",
        "low quality",
        "deformed",
        "watermark",
        "text",
        "low resolution",
    ]

    def generate(self, prompt: str, seed=None, aspect_ratio="1:1"):
        start_time = time.time()

        try:
            if aspect_ratio not in self.ASPECT_RATIO_SIZES:
                aspect_ratio = "1:1"
            width, height = self.ASPECT_RATIO_SIZES[aspect_ratio]

            if not seed:
                seed = random.randint(0, 999999)

            # Enhanced prompt is kept server-side only, never shown to the user.
            enhanced_prompt = f"{prompt}, {self.QUALITY_SUFFIX}"
            negative_prompt = ', '.join(self.NEGATIVE_PROMPT_KEYWORDS)

            encoded_prompt = urllib.parse.quote(enhanced_prompt)
            encoded_negative = urllib.parse.quote(negative_prompt)

            image_url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width={width}&height={height}&seed={seed}&model={MODEL_NAME}"
                f"&negative={encoded_negative}"
                f"&nologo=true&enhance=true&safe=true"
            )

            generation_time = round(time.time() - start_time, 2)

            result = {
                "success": True,
                "image_url": image_url,
                "model_used": "Pollinations AI",
                "prompt": prompt,
                "enhanced_prompt": enhanced_prompt,
                "width": width,
                "height": height
            }
            logger.log_request(
                provider="pollinations",
                latency=generation_time,
                prompt_length=len(prompt),
                response_length=len(image_url)
            )

            return result
        except Exception as e:
            logger.log_request(
                provider="pollinations",
                latency=round(time.time() - start_time, 2),
                prompt_length=len(prompt),
                response_length=0,
                error=str(e)
            )
            return {
                "success": False,
                "error": "Unable to generate image."
            }
