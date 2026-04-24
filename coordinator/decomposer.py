import os
from typing import Dict, List

from dotenv import load_dotenv

from coordinator.gemini_rest import GeminiRestClient, GeminiRestError

load_dotenv()


VALID_DOMAINS = {"FINANCE", "BIOTECH", "LEGAL", "GENERAL"}


class CoordinatorIntelligence:
    def __init__(self):
        if not os.getenv("GEMINI_API_KEY"):
            raise ValueError("GEMINI_API_KEY is required in .env")

        self.decomposer_model = os.getenv("GEMINI_COORDINATOR_MODEL", "gemini-2.5-pro")
        self.report_model = os.getenv("GEMINI_REPORT_MODEL", self.decomposer_model)

        self.decomposer_client = GeminiRestClient(
            model=self.decomposer_model,
            timeout_seconds=60,
        )
        self.report_client = GeminiRestClient(
            model=self.report_model,
            timeout_seconds=90,
        )

    def model_status(self) -> Dict[str, Dict[str, object]]:
        """Expose model routing details for coordinator health endpoint."""
        return {
            "decomposer": {
                "configured_model": self.decomposer_model,
                "pool_size": len(getattr(self.decomposer_client, "model_pool", [])),
                "max_attempts": int(getattr(self.decomposer_client, "max_attempts", 0)),
                "default_max_output_tokens": int(
                    getattr(self.decomposer_client, "default_max_output_tokens", 0)
                ),
            },
            "report": {
                "configured_model": self.report_model,
                "pool_size": len(getattr(self.report_client, "model_pool", [])),
                "max_attempts": int(getattr(self.report_client, "max_attempts", 0)),
                "default_max_output_tokens": int(
                    getattr(self.report_client, "default_max_output_tokens", 0)
                ),
            },
        }

    def decompose_query(
        self,
        user_query: str,
        min_items: int = 8,
        max_items: int = 15,
    ) -> List[Dict[str, str]]:
        """Decompose query into domain-routed sub-questions."""
        prompt = """
You are NeuroPay's coordinator.

Task:
1) Decompose the user query into {min_items}-{max_items} standalone sub-questions.
2) Assign exactly one domain to each sub-question from: FINANCE, BIOTECH, LEGAL, GENERAL.
3) Keep each question highly specific so it can be answered independently by a specialist.
4) Return only a JSON array. No markdown.

Required object format:
{{"question": "...", "domain": "FINANCE|BIOTECH|LEGAL|GENERAL"}}

User query:
{user_query}
""".strip().format(
            min_items=min_items,
            max_items=max_items,
            user_query=user_query,
        )

        try:
            raw = self.decomposer_client.generate_json(
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=420,
            )
            return self._normalize_sub_questions(raw, user_query, min_items, max_items)
        except (GeminiRestError, ValueError, TypeError) as exc:
            print("Decomposition error: {}".format(exc))
            return [{"question": user_query, "domain": "GENERAL"}]

    def expand_sub_questions(
        self,
        user_query: str,
        existing: List[Dict[str, str]],
        target_count: int,
    ) -> List[Dict[str, str]]:
        """Generate additional unique sub-questions for stress runs."""
        if len(existing) >= target_count:
            return existing[:target_count]

        remaining = target_count - len(existing)
        existing_questions = [item["question"] for item in existing if item.get("question")]
        prompt = """
You are extending an existing decomposition for a high-volume stress run.

Generate {remaining} NEW and non-overlapping sub-questions for this user query.
Every item must include question + domain, where domain is one of FINANCE, BIOTECH, LEGAL, GENERAL.
Do not repeat or paraphrase existing questions.
Return only JSON array.

User query:
{user_query}

Existing questions to avoid:
{existing_questions}
""".strip().format(
            remaining=remaining,
            user_query=user_query,
            existing_questions=existing_questions,
        )

        try:
            extra_raw = self.decomposer_client.generate_json(
                prompt=prompt,
                temperature=0.3,
                max_output_tokens=520,
            )
            extra = self._normalize_sub_questions(extra_raw, user_query, 1, remaining)
            deduped = list(existing)
            seen = {item["question"].strip().lower() for item in deduped if item.get("question")}
            for item in extra:
                key = item["question"].strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
                if len(deduped) >= target_count:
                    break
            if len(deduped) < target_count:
                deduped = self._fallback_expand(user_query, deduped, target_count)
            return deduped[:target_count]
        except (GeminiRestError, ValueError, TypeError) as exc:
            print("Expansion error: {}".format(exc))
            return self._fallback_expand(user_query, existing, target_count)

    def synthesize_report(self, original_query: str, results: List[Dict[str, str]]) -> str:
        evidence = []
        for idx, item in enumerate(results, start=1):
            evidence.append(
                "{}. [{}] Q: {}\nA: {}".format(
                    idx,
                    item.get("domain", "GENERAL"),
                    item.get("question", ""),
                    item.get("answer", ""),
                )
            )

        prompt = """
You are NeuroPay's final report synthesizer.

Create a concise markdown report with sections:
1) Executive Summary
2) Key Findings by Domain
3) Risks and Unknowns
4) Recommended Next Actions

Original query:
{original_query}

Evidence:
{evidence}
""".strip().format(original_query=original_query, evidence="\n\n".join(evidence))

        try:
            return self.report_client.generate_text(
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=600,
            )
        except GeminiRestError as exc:
            print("Report synthesis error: {}".format(exc))
            return "## NeuroPay Report\n\nUnable to synthesize report due to Gemini API error."

    @staticmethod
    def _normalize_sub_questions(
        raw,
        original_query: str,
        min_items: int,
        max_items: int,
    ) -> List[Dict[str, str]]:
        if not isinstance(raw, list):
            raise ValueError("Gemini response is not a JSON array")

        normalized: List[Dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            domain = str(item.get("domain", "GENERAL")).strip().upper()
            if not question:
                continue
            if domain not in VALID_DOMAINS:
                domain = "GENERAL"
            normalized.append({"question": question, "domain": domain})

        if not normalized:
            normalized = [{"question": original_query, "domain": "GENERAL"}]

        if len(normalized) < min_items:
            # Ensure minimum count by appending focused follow-ups.
            for idx in range(min_items - len(normalized)):
                normalized.append(
                    {
                        "question": "Follow-up {} for: {}".format(idx + 1, original_query),
                        "domain": "GENERAL",
                    }
                )

        return normalized[:max_items]

    @staticmethod
    def _fallback_expand(
        user_query: str,
        existing: List[Dict[str, str]],
        target_count: int,
    ) -> List[Dict[str, str]]:
        expanded = list(existing)
        domains = ["FINANCE", "BIOTECH", "LEGAL", "GENERAL"]
        idx = 0
        while len(expanded) < target_count:
            domain = domains[idx % len(domains)]
            expanded.append(
                {
                    "question": "{} | Stress follow-up {} focused on {}".format(
                        user_query,
                        len(expanded) + 1,
                        domain.lower(),
                    ),
                    "domain": domain,
                }
            )
            idx += 1
        return expanded
