import base64
import io
import json
import logging
import os
from pathlib import Path
from typing import override
from pprint import pformat

import ollama
from PIL.Image import Image

from processor import ImageProcessor
from api import Labels, NSFW

logger = logging.getLogger(__name__)

caption_prompt = os.environ.get('OLLAMA_CAPTION_PROMPT', 'Write a natural-sounding caption that briefly describes the main content of the image in up to 3 sentences. It should begin directly with the type and number of subjects and action, such as "Two sleeping cats," "A bright poppy flower," or "Police officers drinking coffee next to a farmhouse." Omit text formatting and avoid any meta-language or phrases such as "This picture," "The picture," "The photo," "There are," "Here is," or "A picture of".')
labels_prompt = os.environ.get('OLLAMA_LABELS_PROMPT', 'Generate from 1 to 2 worded labels for given images.')
# minicpm-v generates usable output for NSFW detection, but it's not guaranteed to be accurate.
nsfw_prompt = os.environ.get('OLLAMA_NSFW_PROMPT',
                             'Analyze this image and return probabilities in the following categories between 0 and 1 '
                             '(higher value means more likely):\n'
                             'Neutral: For non-sensitive content (>0.25 means not NSFW)\n'
                             'Drawing: Likelihood the image is an illustration/drawing\n'
                             'Hentai: Likelihood the image contains anime/manga adult content\n'
                             'Porn: Likelihood the image contains explicit adult content\n'
                             'Sexy: Likelihood the image contains suggestive adult content'
                             )


class OllamaImageProcessor(ImageProcessor):
    def __init__(self):
        self._models_cache = self._load_models()
        logger.info(f'{self.__class__.__name__} supports the following models:\n{pformat(self._models_cache)}')

    def can_process(self, model_name: str, model_version: str) -> bool:
        model_name = self._get_model_name(model_name, model_version)
        cached_model = model_name in self._models_cache

        if not cached_model:
            return model_name in self._load_models()
        return cached_model

    @override
    def generate_caption(self, model_name: str, model_version: str, image: Image) -> tuple[str, str]:
        return self._generate_with_prompt(model_name, model_version, [image], caption_prompt)

    @override
    def generate_labels(self, model_name: str, model_version: str, images: list[Image]) -> tuple[str, Labels | str]:
        schema = Labels.model_json_schema()
        status, result = self._generate_with_prompt(model_name, model_version, images, labels_prompt, schema=schema)
        if status == 'ok':
            try:
                labels = Labels.model_validate_json(result)
                return status, labels
            except Exception as e:
                return 'error', f'Failed to parse labels JSON: {str(e)}'
        return status, result

    @override
    def detect_nsfw(self, model_name: str, model_version: str, images: Image) -> tuple[str, NSFW | str]:
        """
        Tries to detect if the image is NSFW. Accurate detection is not guaranteed.
        """
        schema = NSFW.model_json_schema()
        status, result = self._generate_with_prompt(model_name, model_version, [images], nsfw_prompt, schema=schema)
        if status == 'ok':
            try:
                probabilities = NSFW.model_validate_json(result)
                return status, probabilities
            except Exception as e:
                return 'error', f'Failed to parse labels JSON: {str(e)}'
        return status, result

    def _generate_with_prompt(
            self,
            model_name: str,
            model_version: str,
            images: list[Image],
            prompt: str,
            schema=None
    ) -> tuple[str, any]:
        if logger.getEffectiveLevel() <= logging.DEBUG:
            try:
                b64_image_str = images[0] if len(images) else None
                logger.debug(
                    f'{self.__class__.__name__} using model "{model_name}" version "{model_version}" with image '
                    f' of {b64_image_str} and prompt:\n{prompt}')

                save_path = Path(os.getenv('PV_DEBUG_SAVE_FIRST_IMAGE_PATH', './'))

                with open(save_path.joinpath("ollama_last_request.json"), "w") as outfile:
                    ollama_request_data = {
                        'model_name': self._get_model_name(model_name, model_version),
                        'prompt': prompt,
                        'images': [self._convert_image_to_base64(image) for image in images],
                        'format': schema
                    }
                    json.dump(ollama_request_data, outfile, indent=4)
            except Exception as e:
                logger.exception("Debug mode failed to save last Ollama request", exc_info=e)
        try:
            options = {
                'num_predict': 512
            }
            base64_images = [self._convert_image_to_base64(image) for image in images]
            response = ollama.generate(
                model=self._get_model_name(model_name, model_version),
                prompt=prompt,
                images=base64_images,
                format=schema,
                options=options
            )
            return self._process_ollama_response(response)
        except Exception as e:
            return 'error', f'Ollama processing error: {str(e)}'

    @staticmethod
    def _load_models():
        models = {}
        try:
            logger.debug('Loading Ollama models')
            models = ollama.list()['models']
        except Exception as e:
            logger.error('Failed to load Ollama models: %s', str(e))

        return {model['model'] for model in models}

    @staticmethod
    def _get_model_name(model_name: str, model_version: str) -> str:
        return f'{model_name}:{model_version}'

    @staticmethod
    def _convert_image_to_base64(image: Image) -> str:
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='JPEG')
        img_byte_arr = img_byte_arr.getvalue()

        return base64.b64encode(img_byte_arr).decode('utf-8')

    @staticmethod
    def _process_ollama_response(response) -> tuple[str, str]:
        logger.debug(response)

        if response and response.response:
            return 'ok', response.response.strip()
        return 'error', 'No response from Ollama'

    @override
    def list_models(self):
        return self._models_cache