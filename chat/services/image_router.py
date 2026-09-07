
import time
from chat.providers.pollinations_image_provider import PollinationsImageProvider

provider = PollinationsImageProvider()


def generate_image(prompt, seed=None, aspect_ratio="1:1", width=None, height=None, **kwargs):
    start_time = time.time()
    result = provider.generate(
        prompt=prompt,
        seed=seed,
        aspect_ratio=aspect_ratio,
        width=width,
        height=height,
        **kwargs
    )
    result["generation_time"] = round(time.time() - start_time, 2)
    return result


