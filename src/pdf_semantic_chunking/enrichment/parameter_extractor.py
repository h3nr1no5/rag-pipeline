import re

from .model import ComDocumentElement

PARAM_DIRECTION_PATTERN = re.compile(r"\[(in|out|in\s*,\s*out|in,out)\]", re.IGNORECASE)
PARAM_SIG_PATTERN = re.compile(
    r"(?:\[(?:in|out|in\s*,\s*out|in,out)\]\s*)?"
    r"(\w+(?:\[\])?(?:<[^>]+>)?)\s+(\w+)\s*"
    r"(?:=\s*([^,)]+))?"
)


class ParameterExtractor:
    def extract_from_signature(self, signature: str) -> list[dict]:
        params: list[dict] = []
        sig_clean = signature.strip()
        paren_start = sig_clean.find("(")
        paren_end = sig_clean.rfind(")")
        if paren_start == -1 or paren_end == -1 or paren_end <= paren_start:
            return params
        param_str = sig_clean[paren_start + 1:paren_end].strip()
        if not param_str:
            return params
        for part in self._split_params(param_str):
            param = self._parse_single_param(part)
            if param:
                params.append(param)
        return params

    def _split_params(self, param_str: str) -> list[str]:
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in param_str:
            if ch == '<':
                depth += 1
                current.append(ch)
            elif ch == '>':
                depth = max(depth - 1, 0)
                current.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(current).strip())
                current = []
            else:
                current.append(ch)
        remaining = ''.join(current).strip()
        if remaining:
            parts.append(remaining)
        return parts

    def _parse_single_param(self, part: str) -> dict | None:
        direction = "in"
        dir_m = PARAM_DIRECTION_PATTERN.search(part)
        if dir_m:
            direction = dir_m.group(1).lower().replace(" ", "")
            cleaned = PARAM_DIRECTION_PATTERN.sub("", part).strip()
        else:
            cleaned = part.strip()
        m = PARAM_SIG_PATTERN.search(cleaned)
        if m:
            return {
                "name": m.group(2),
                "direction": direction,
                "type": m.group(1),
                "description": None,
            }
        cleaned_no_default = re.sub(r"\s*=\s*[^,)]+", "", cleaned).strip()
        m2 = re.match(r"(\w+(?:\[\])?(?:<[^>]+>)?)\s+(\w+)", cleaned_no_default)
        if m2:
            return {
                "name": m2.group(2),
                "direction": direction,
                "type": m2.group(1),
                "description": None,
            }
        return None

    def associate_descriptions(
        self, params: list[dict], description_text: str
    ) -> list[dict]:
        if not description_text or not params:
            return params
        param_names = {p["name"].lower(): p for p in params}
        lines = description_text.strip().split("\n")
        for line in lines:
            line = line.strip().strip("-").strip().strip("*").strip()
            if not line:
                continue
            for pname in param_names:
                if line.lower().startswith(pname.lower()):
                    desc = line[len(pname):].strip().lstrip(":").strip().lstrip("-").strip()
                    if desc:
                        param_names[pname]["description"] = desc
                    break
        return params

    def extract_from_bullet_list(self, element: ComDocumentElement) -> list[dict]:
        content = element.content
        params: list[dict] = []
        bullet_pattern = re.compile(r"^[\s]*[-*]\s+(\w+(?:\[\])?(?:<[^>]+>)?)\s+(\w+)\s*(.*)$", re.MULTILINE)  # noqa: E501
        for m in bullet_pattern.finditer(content):
            params.append({
                "name": m.group(2),
                "direction": "in",
                "type": m.group(1),
                "description": m.group(3).strip() or None,
            })
        return params
