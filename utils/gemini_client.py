"""
utils/gemini_client.py
───────────────────────
Thin wrapper around the Google Generative AI (Gemini) SDK.

• Handles all API calls in a single place so swap-outs are trivial.
• Tracks call count → fed back into WorkflowState.api_call_count.
• Implements configurable retry with exponential back-off for transient errors.
• Never hard-codes the API key (read from env var GEMINI_API_KEY).
"""
from __future__ import annotations

import os
import time
import logging
from typing import Optional

import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)


class GeminiClient:
    """Singleton-like wrapper; one instance shared across all agents."""

    def __init__(
        self,
        model_name: str = "gemini-1.5-pro",
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
    ) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY environment variable is not set. "
                "Export it before running the orchestrator."
            )
        genai.configure(api_key=api_key)

        self._model_name      = model_name
        self._temperature     = temperature
        self._max_output_tokens = max_output_tokens
        self._max_retries     = max_retries
        self._retry_backoff   = retry_backoff
        self._call_count      = 0

        self._generation_config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        # Safety settings — permissive for code-generation use-case
        self._safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }

        self._model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=self._generation_config,
            safety_settings=self._safety_settings,
        )
        logger.info("GeminiClient initialised — model: %s", model_name)

    # ── Public interface ──────────────────────────────────────

    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Send a prompt and return the response text.
        Retries up to max_retries times on transient failures.
        """
        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt

        attempt = 0
        delay   = self._retry_backoff

        while attempt <= self._max_retries:
            try:
                logger.debug("Gemini call attempt %d/%d", attempt + 1, self._max_retries + 1)
                response = self._model.generate_content(full_prompt)
                self._call_count += 1
                text = response.text
                logger.debug("Gemini responded (%d chars)", len(text))
                return text

            except Exception as exc:
                attempt += 1
                logger.warning(
                    "Gemini API error on attempt %d: %s", attempt, exc
                )
                if attempt > self._max_retries:
                    raise RuntimeError(
                        f"Gemini API failed after {self._max_retries} retries: {exc}"
                    ) from exc
                logger.info("Retrying in %.1fs …", delay)
                time.sleep(delay)
                delay *= 2   # exponential back-off

        # unreachable, but satisfies type checkers
        raise RuntimeError("Gemini generate() exited retry loop unexpectedly")

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Like generate() but appends a JSON-enforcement suffix to the prompt.
        The caller is responsible for parsing the returned string.
        """
        json_suffix = (
            "\n\nIMPORTANT: Respond with ONLY valid JSON. "
            "Do NOT include markdown code fences, preamble, or explanation."
        )
        return self.generate(prompt + json_suffix, system_instruction=system_instruction)

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def model_name(self) -> str:
        return self._model_name
