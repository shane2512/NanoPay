"""Gemini client backed by the google-generativeai SDK only."""

import datetime
import json
import os
import random
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set

import google.generativeai as genai
from dotenv import dotenv_values, load_dotenv

load_dotenv(override=True)


class GeminiRestError(RuntimeError):
    """Raised when a Gemini SDK request fails."""


class GeminiRestClient:
    _available_models_cache: Optional[List[str]] = None
    _available_models_logged = False
    _cache_lock = threading.Lock()

    _quota_lock = threading.Lock()
    _request_times: Deque[float] = deque()
    _last_request_at = 0.0
    _daily_output_tokens = 0
    _daily_budget_date = ""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 45.0,
        api_url: Optional[str] = None,
    ):
        del api_url  # Kept for backwards-compatible constructor calls.

        self.api_key = (api_key or self._resolve_api_key() or "").strip()
        self.model = model or os.getenv("GEMINI_COORDINATOR_MODEL", "gemini-2.5-pro")
        self.timeout_seconds = float(timeout_seconds)
        self.default_max_output_tokens = int(
            os.getenv("GEMINI_DEFAULT_MAX_OUTPUT_TOKENS", "220")
        )
        self.hard_max_output_tokens = int(
            os.getenv("GEMINI_HARD_MAX_OUTPUT_TOKENS", "320")
        )
        self.max_prompt_chars = int(os.getenv("GEMINI_MAX_PROMPT_CHARS", "3500"))
        self.max_attempts = max(1, int(os.getenv("GEMINI_MAX_ATTEMPTS", "30")))
        self.model_pool_size = max(30, int(os.getenv("GEMINI_MODEL_POOL_SIZE", "30")))
        self.max_requests_per_minute = max(
            1,
            int(os.getenv("GEMINI_MAX_REQUESTS_PER_MINUTE", "24")),
        )
        self.min_request_interval_seconds = float(
            os.getenv("GEMINI_MIN_REQUEST_INTERVAL_SECONDS", "0.8")
        )
        self.daily_output_token_budget = max(
            0,
            int(os.getenv("GEMINI_DAILY_OUTPUT_TOKEN_BUDGET", "12000")),
        )

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required in environment")

        genai.configure(api_key=self.api_key)
        available = self._get_available_models()
        fallback = self._fallback_model_catalog()
        if not available:
            print("Falling back to static Gemini model catalog: {}".format(", ".join(fallback[:30])))

        self.model_pool = self._build_model_pool(available, fallback, self.model, self.model_pool_size)
        self._disabled_models: Set[str] = set()
        self._cursor_lock = threading.Lock()
        self._cursor = random.randint(0, max(0, len(self.model_pool) - 1))

        print(
            "Rolling Gemini model pool ({} models): {}".format(
                len(self.model_pool),
                ", ".join(self.model_pool),
            )
        )

    @staticmethod
    def _resolve_api_key() -> Optional[str]:
        file_key = ""
        try:
            values = dotenv_values(".env")
            file_key = str(values.get("GEMINI_API_KEY") or "").strip()
        except Exception:
            file_key = ""

        if file_key and file_key != ".":
            return file_key

        runtime_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if runtime_key and runtime_key != ".":
            return runtime_key

        return None

    @classmethod
    def _get_available_models(cls) -> List[str]:
        with cls._cache_lock:
            if cls._available_models_cache is not None:
                return list(cls._available_models_cache)

            available: List[str] = []
            try:
                for model_info in genai.list_models():
                    methods = set(getattr(model_info, "supported_generation_methods", []) or [])
                    if "generateContent" not in methods:
                        continue
                    name = (getattr(model_info, "name", "") or "").replace("models/", "")
                    if name:
                        available.append(name)
            except Exception as exc:
                print("Unable to list Gemini models via SDK: {}".format(exc))
                return []

            deduped = sorted(set(available))
            cls._available_models_cache = deduped

            if not cls._available_models_logged:
                print("Available Gemini models (generateContent): {}".format(", ".join(deduped)))
                cls._available_models_logged = True

            return list(deduped)

    @staticmethod
    def _fallback_model_catalog() -> List[str]:
        return [
            "gemini-2.5-pro-preview-03-25",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash-preview-05-20",
            "gemini-2.5-flash-lite-preview-06-17",
            "gemini-2.0-flash",
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash-exp",
            "gemini-2.0-flash-thinking-exp",
            "gemini-2.0-flash-thinking-exp-1219",
            "gemini-2.0-flash-thinking-exp-01-21",
            "gemini-2.0-pro-exp",
            "gemini-2.0-pro-exp-02-05",
            "gemini-2.0-flash-live-001",
            "gemini-2.0-flash-exp-image-generation",
            "gemini-2.0-flash-preview-image-generation",
            "gemini-2.0-flash-lite-preview-02-05",
            "gemini-1.5-flash",
            "gemini-1.5-flash-001",
            "gemini-1.5-flash-002",
            "gemini-1.5-flash-8b",
            "gemini-1.5-flash-8b-001",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro",
            "gemini-1.5-pro-001",
            "gemini-1.5-pro-002",
            "gemini-1.5-pro-latest",
            "gemini-1.0-pro",
            "gemini-1.0-pro-latest",
            "gemini-exp-1206",
            "gemini-exp-1114",
            "gemini-exp-1121",
            "gemini-ultra",
            "gemini-pro",
            "gemini-pro-vision",
            "learnlm-1.5-pro-experimental",
        ]

    @staticmethod
    def _build_model_pool(
        discovered: List[str],
        fallback: List[str],
        preferred: str,
        min_count: int,
    ) -> List[str]:
        universe = []
        seen = set()

        for item in discovered + fallback:
            if item and item not in seen:
                seen.add(item)
                universe.append(item)

        if preferred and preferred not in seen:
            universe.insert(0, preferred)
            seen.add(preferred)

        if not universe:
            return [preferred] if preferred else []

        if preferred:
            ordered = [preferred] + [item for item in universe if item != preferred]
        else:
            ordered = list(universe)

        tail = ordered[1:] if len(ordered) > 1 else []
        random.shuffle(tail)
        ordered = [ordered[0]] + tail if ordered else tail

        target = max(30, min_count)
        return ordered[: min(target, len(ordered))]

    def _candidate_models_for_request(self) -> List[str]:
        with self._cursor_lock:
            active_pool = [m for m in self.model_pool if m not in self._disabled_models]
            if not active_pool:
                raise GeminiRestError("All models in the Gemini fallback pool have been exhausted")

            if self._cursor >= len(active_pool):
                self._cursor = 0

            start = self._cursor
            self._cursor = (self._cursor + 1) % len(active_pool)

        ordered = active_pool[start:] + active_pool[:start]
        return ordered[: min(max(1, self.max_attempts), len(ordered))]

    @classmethod
    def _reset_daily_budget_if_needed(cls) -> None:
        today = datetime.date.today().isoformat()
        if cls._daily_budget_date != today:
            cls._daily_budget_date = today
            cls._daily_output_tokens = 0

    def _throttle(self) -> None:
        while True:
            sleep_for = 0.0
            with self._quota_lock:
                self._reset_daily_budget_if_needed()
                now = time.time()

                while self._request_times and now - self._request_times[0] >= 60.0:
                    self._request_times.popleft()

                if self.min_request_interval_seconds > 0 and self._last_request_at > 0:
                    gap = self.min_request_interval_seconds - (now - self._last_request_at)
                    if gap > sleep_for:
                        sleep_for = gap

                if len(self._request_times) >= self.max_requests_per_minute:
                    window_wait = 60.0 - (now - self._request_times[0])
                    if window_wait > sleep_for:
                        sleep_for = window_wait

                if sleep_for <= 0:
                    self._last_request_at = now
                    self._request_times.append(now)
                    return

            time.sleep(min(max(sleep_for, 0.05), 5.0))

    def _ensure_budget_available(self) -> None:
        if self.daily_output_token_budget <= 0:
            return

        with self._quota_lock:
            self._reset_daily_budget_if_needed()
            if self._daily_output_tokens >= self.daily_output_token_budget:
                raise GeminiRestError(
                    "Gemini daily token budget reached: {}/{}".format(
                        self._daily_output_tokens,
                        self.daily_output_token_budget,
                    )
                )

    def _record_output_tokens(self, tokens_used: int) -> None:
        with self._quota_lock:
            self._reset_daily_budget_if_needed()
            self._daily_output_tokens += max(0, int(tokens_used))

    def _resolve_token_cap(self, requested: Optional[int]) -> int:
        value = int(requested or self.default_max_output_tokens)
        value = max(64, value)
        return min(value, max(64, self.hard_max_output_tokens))

    @staticmethod
    def _extract_usage_tokens(response: Any, text: str, token_cap: int) -> int:
        usage = getattr(response, "usage_metadata", None)
        if usage:
            attrs = [
                "candidates_token_count",
                "candidate_token_count",
                "output_token_count",
            ]
            for attr in attrs:
                value = getattr(usage, attr, None)
                if isinstance(value, int) and value > 0:
                    return value

            if isinstance(usage, dict):
                for key in attrs:
                    value = usage.get(key)
                    if isinstance(value, int) and value > 0:
                        return value

        estimated = max(1, int(len(text) / 4))
        return min(max(1, token_cap), estimated)

    def _mark_model_if_invalid(self, model_name: str, exc: Exception) -> None:
        msg = str(exc).upper()
        invalid_markers = ["NOT_FOUND", "404", "UNSUPPORTED", "MODEL_NOT_FOUND", "INVALID_ARGUMENT"]
        if any(marker in msg for marker in invalid_markers):
            self._disabled_models.add(model_name)

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).upper()
        markers = [
            "API_KEY_INVALID",
            "API KEY EXPIRED",
            "API_KEY_EXPIRED",
            "UNAUTHENTICATED",
            "PERMISSION_DENIED",
            "INVALID API KEY",
        ]
        return any(marker in msg for marker in markers)

    def generate_text(
        self,
        prompt: str,
        response_mime_type: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        trimmed_prompt = self._trim_prompt(prompt)
        token_cap = self._resolve_token_cap(max_output_tokens)
        candidates = self._candidate_models_for_request()

        last_error: Optional[Exception] = None
        for idx, model_name in enumerate(candidates, start=1):
            self._ensure_budget_available()
            self._throttle()
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    trimmed_prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=token_cap,
                        candidate_count=1,
                        response_mime_type=response_mime_type,
                    ),
                    request_options={"timeout": int(self.timeout_seconds)},
                )
                text = self._extract_text(response)
                self._record_output_tokens(self._extract_usage_tokens(response, text, token_cap))
                return text
            except Exception as exc:
                last_error = exc
                if self._is_auth_error(exc):
                    raise GeminiRestError("Gemini authentication failed: {}".format(exc))
                self._mark_model_if_invalid(model_name, exc)
                message = str(exc)
                # Back off briefly for free-tier rate limits and continue in rollback order.
                if "429" in message or "RESOURCE_EXHAUSTED" in message:
                    sleep_for = min(4.0, 0.6 * idx)
                    time.sleep(sleep_for)
                continue

        raise GeminiRestError("Gemini SDK request failed after {} attempts: {}".format(
            len(candidates),
            last_error,
        ))

    def generate_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> Any:
        raw_text = self.generate_text(
            prompt=prompt,
            response_mime_type="application/json",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        normalized = self._strip_code_fences(raw_text)
        return json.loads(normalized)

    def _trim_prompt(self, prompt: str) -> str:
        if len(prompt) <= self.max_prompt_chars:
            return prompt
        suffix = "\n\n[Prompt truncated for free-tier token savings.]"
        hard_limit = max(200, self.max_prompt_chars - len(suffix))
        return prompt[:hard_limit] + suffix

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if text:
            return text

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                value = getattr(part, "text", None)
                if value:
                    return value

        raise GeminiRestError("Gemini SDK response has no text part")

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return stripped
