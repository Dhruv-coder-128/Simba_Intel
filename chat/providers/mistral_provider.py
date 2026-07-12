import os
from typing import Generator, Dict, Any

from openai import OpenAI

from .base import BaseProvider


class MistralProvider(BaseProvider):

    provider_name = "mistral"

    supported_models = [
        "mistral-medium-latest",
        "mistral-large-latest",
        "ministral-8b-latest",
        "pixtral-large-latest",
    ]

    def _initialize_client(self):   
        self.client = OpenAI(
            api_key=os.getenv("MISTRAL_API_KEY"),
            base_url="https://api.mistral.ai/v1",
        )

    def chat(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        **kwargs,
    ) -> str:

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            **kwargs,
        )

        return response.choices[0].message.content

    def chat_stream(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        **kwargs,
    ) -> Generator[str, None, None]:

        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            **kwargs,
        )

        for chunk in stream:

            if (
                chunk.choices
                and chunk.choices[0].delta
                and chunk.choices[0].delta.content
            ):
                yield chunk.choices[0].delta.content

    def vision(
        self,
        messages,
        model="pixtral-large-latest",
        **kwargs,
    ):

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )

        return response.choices[0].message.content

    def generate_image(
        self,
        prompt,
        model=None,
        **kwargs,
    ):
        raise NotImplementedError(
            "Image Generation will be added in the next update."
        )