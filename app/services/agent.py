from openai import OpenAI, RateLimitError
from config import config

_client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)

# In-memory conversation state keyed by session ID.
# This is intentionally simple; it can be replaced with LangGraph state later.
_conversations: dict[str, list] = {}


def get_history(session_id: str) -> list:
    if session_id not in _conversations:
        _conversations[session_id] = []
    return _conversations[session_id]


_SYSTEM_PROMPT = (
    "You are a concise restaurant assistant. "
    "Answer the customer's question directly and briefly. "
    "Never include any analysis, reasoning, chain-of-thought, internal steps, or meta-commentary in your response. "
    "Your response must contain ONLY the final answer suitable for a customer to read. "
    "Do not output numbered steps, section headers like 'Analyze User Input' or 'Determine Response Strategy', or any thinking process. "
    "If you need to reason, do it silently — the customer never sees it. "
    "Use ONLY the provided context or tool results. Never invent menu items, prices, offers, branches, hours, or order records. "
    "Keep replies short and customer-friendly. "
    "For recommendations, base suggestions on actual product data provided in context. "
    "Never reveal database details, credentials, internal systems, revenue, or other customers' orders. "
    "If a request is outside the menu/restaurant scope, politely stay within restaurant assistance."
)


def _strip_reasoning(text: str) -> str:
    """Remove reasoning/analysis from model output.

    Strategy (applied in priority order):
    0. If the text contains quoted strings or Arabic script, join ALL such
       chunks and return the combined result — this prevents truncating
       multi-item answers like menu lists to only the last item.
    1. Drop any leading reasoning-header block.
    2. Remove numbered bolded steps, short bullet lines, rule-echo bullets,
       and self-referential/meta lines.
    3. From what remains, keep the longest clean suffix.
    """
    if not text or not text.strip():
        return "I'm here to help with your restaurant questions."

    import re

    # ------------------------------------------------------------------
    # PHASE 0 — extract the likely answer from quotes or Arabic text.
    # ------------------------------------------------------------------

    # Find all double-quoted chunks (non-greedy, handles escaped quotes).
    quoted = re.findall(r'\"((?:[^\"\\]|\\.)*)\"', text)

    # Find Arabic-script regions (Unicode Arabic block + common extended).
    # Match Arabic script (Unicode Arabic block + extended) so multi-word
    # Arabic answers are captured as one region, not split into fragments.
    arabic_regions = re.findall(
        '(?:[\\u0600-\\u06FF\\u0750-\\u077F\\u08A0-\\u08FF\\uFB50-\\uFDFF\\uFE70-\\uFEFF]\\s*)+',
        text,
    )
    # Trim trailing whitespace from each region.
    arabic_regions = [r.strip() for r in arabic_regions if len(r.strip()) >= 3]

    answer_candidates: list[str] = []

    for q in quoted:
        q = q.strip()
        # Skip quotes that are obviously reasoning markers.
        low = q.lower()
        if any(low.startswith(p) for p in (
            "if ", "the ", "this ", "that ", "these ", "those ",
            "i ", "we ", "you ", "he ", "she ", "it ",
            "no ", "not ", "don't", "doesn't", "can't", "won't",
            "as ", "to ", "in ", "on ", "at ", "for ", "with ", "from ",
        )):
            continue
        if len(q) < 3:
            continue
        # Skip quotes that look like system-prompt fragments.
        if any(word in low for word in (
            "analysis", "reasoning", "chain-of-thought", "meta-commentary",
            "thinking process", "numbered steps", "section headers",
            "concise", "direct", "brief", "only the final",
        )):
            continue
        answer_candidates.append(q)

    for a in arabic_regions:
        a = a.strip()
        if len(a) >= 2:
            answer_candidates.append(a)

    if answer_candidates:
        # PHASE 0 FIXED: join ALL candidates so multi-item answers (e.g. menu
        # lists with multiple Arabic product names) are not truncated to only
        # the last fragment. Previously only answer_candidates[-1] was kept,
        # which caused "can i see the menu" to return only one product.
        if len(answer_candidates) > 1:
            # Check if the candidates look like list fragments.
            all_short = all(len(c.strip()) < 200 for c in answer_candidates)
            if all_short:
                result = "\n".join(c.strip() for c in answer_candidates)
                result = result.strip("\"'").strip()
                result = re.sub(r'\s+', ' ', result)
                result = re.sub(r'\n', ' ', result)
                if result and len(result) >= 2:
                    return result
        result = answer_candidates[-1].strip()
        result = result.strip("\"'").strip()
        result = re.sub(r'\s+', ' ', result)
        if result and len(result) >= 2:
            return result

    # ------------------------------------------------------------------
    # PHASE 1 — drop a leading reasoning-header block.
    # ------------------------------------------------------------------
    REASONING_HEADERS = [
        "analyze user input", "analyze the", "analyze the request",
        "check context", "evaluate available",
        "determine response strategy", "thinking process",
        "here's a thinking", "here is a thinking", "identify core",
        "identify intent", "identify persona", "consider", "plan",
    ]

    def _looks_like_reasoning_header(line: str) -> bool:
        low = line.lower().strip()
        # Strip leading "Word N:" or "N." or "N. **" patterns so that
        # "Step 1: Analyze..." → "analyze..." and matches the headers.
        stripped = re.sub(r'^[A-Za-z]+\s+\d+[:\s]*\s*\*?\*?\s*', '', low)
        stripped = re.sub(r'^\d+\.\s*\*?\*?\s*', '', stripped)
        return any(stripped.startswith(h) for h in REASONING_HEADERS)

    lines = text.splitlines()
    first = 0
    while first < len(lines) and not lines[first].strip():
        first += 1
    if first < len(lines) and _looks_like_reasoning_header(lines[first]):
        j = first + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines):
            # Reasoning headers are typically followed by self-referential
            # elaboration (e.g. "Here is my analysis..."). Skip that too.
            if _is_meta_line(lines[j]):
                j += 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
            lines = lines[j:]
        else:
            lines = []

    if not lines:
        return "I'm here to help with your restaurant questions."

    # ------------------------------------------------------------------
    # PHASE 2 — remove lines that are clearly reasoning.
    # ------------------------------------------------------------------
    BULLET_RE = re.compile(r'^\s*[-*•>]\s')

    # Rule-echo prefixes — fragments of the system prompt being repeated.
    RULE_ECHO_PREFIXES = [
        "must be concise", "must be direct", "must contain only",
        "no analysis", "no numbered steps", "no section headers",
        "no thinking process", "no chain-of-thought", "no meta-commentary",
        "do not output", "do not include", "never include",
        "keep replies short", "keep replies brief",
        "use only provided context", "use only the provided",
        "never invent", "never reveal",
        "answer directly", "answer the customer",
        "be concise", "be brief",
        "for recommendations",
        "if a request is outside", "if outside",
        "if the knowledge does not contain",
        "final answer only", "customer-readable", "customer-facing",
        "only the final answer", "suitable for a customer",
        "contain only the final", "response must contain only",
    ]

    def _is_bullet(line: str) -> bool:
        return bool(BULLET_RE.match(line))

    def _is_rule_echo(line: str) -> bool:
        s = line.strip().lstrip("- *•>").strip().strip('"').strip("'").strip()
        low = s.lower()
        if len(s) > 250:
            return False
        return any(low.startswith(p) for p in RULE_ECHO_PREFIXES)

    # Short non-bullet meta lines — self-referential talk about the response.
    # These are fragments like "Check constraints:", "Actually, re-reading:",
    # "But to be extremely concise:", "So just...", "But wait — ...".
    NON_BULLET_META_PREFIXES = [
        "check constraints:", "actually,", "actually ",
        "but wait", "but to be", "but to", "but i",
        "so just", "so i", "so the", "so my", "so we",
        "re-reading:", "re reading:", "re-read:",
        "re-reading the", "re reading the", "re-read the",
        "wait, let me", "wait, i need to",
        "actually, let me", "actually i need to",
        "let me re-read", "let me re read",
        "by the way", "on second thought", "on second thoughts",
        "scratch that", "never mind that", "nvm",
        "i'll output", "i will output", "i'll go with", "i will go with",
        "let's just", "i'll stick to", "i will stick to",
        "i'll provide", "i will provide", "i'll give", "i will give",
        "i'll write", "i will write", "i'll send", "i will send",
        "my response is", "the response is", "my answer is", "the answer is",
        "my reply is", "final answer is", "final output is",
        "my final answer is", "my final response is", "my final output is",
        "the final answer is", "the final response is", "the final output is",
        "this is my final", "this is my response", "this is my answer",
        "here's my response", "here's the response", "here's my answer",
        "here is my response", "here is the response", "here is my answer",
        "here's my final", "here is my final",
        "what i'll say", "what i will say", "what i'll output",
        "what i will output", "what i'll go with", "what i will go with",
        "what i choose", "what i'll respond", "what i will respond",
        "possible responses", "obvious responses", "possible answers",
        "possible replies", "good responses", "best response",
        "good options", "best options", "viable options",
        "my best option", "the best option", "the best answer",
        "my best answer", "my best reply", "the best reply",
        "best approach", "my approach", "the approach",
        "way to respond", "a good way", "good way to",
        "simple response", "simple answer", "simple reply",
        "the response should be", "the answer should be",
        "the reply should be", "the output should be",
        "should be a", "should be the",
        "i think i should", "i believe i should", "i feel i should",
        "it seems i should", "it appears i should",
        "i'd say", "i would say", "i'd respond", "i would respond",
        "i'd respond with", "i'd go with", "i would go with",
        "i'd choose", "i would choose", "i'd pick", "i would pick",
        "i'd select", "i would select",
        "i think the", "i believe the", "i feel the", "i reckon the",
        "i think that", "i believe that", "i feel that", "i reckon that",
        "i opine that", "i maintain that", "i hold that",
        "i'm of the opinion", "i am of the opinion",
        "in my opinion", "in my view", "in my mind",
        "from my perspective", "from my point of view",
        "as i see it", "as i understand it",
        "as far as i know", "as far as i can tell",
        "as far as i'm aware", "as far as i am aware",
        "to my knowledge", "to the best of my knowledge",
        "i don't have full", "i don't have the full",
        "i don't have complete", "i don't have all",
        "i lack", "i'm lacking", "i am lacking",
        "i'm missing", "i am missing",
        "i don't know everything", "i don't know all",
        "i can't see everything", "i can't see all",
        "i can't access everything", "i can't access all",
        "i only have", "i've only got", "i only got",
        "i have access to", "i've access to",
        "i can see", "i can access", "i can retrieve", "i can look up",
        "based on what i have", "based on what i can see",
        "based on available", "based on the available",
        "given what i have", "given what's available",
        "given the available", "given the information",
        "with the information", "with the data",
        "using the context", "using the provided",
        "from the context", "from the provided",
        "from the information", "from the data",
        "according to the context", "according to the data",
        "as shown in the context", "as indicated in the context",
        "i have a preference for", "i've a preference for",
        "my preference is", "my preferred",
        "i'm partial to", "i am partial to",
        "i'm inclined to", "i am inclined to",
        "i'm tempted to", "i am tempted to",
        "i'm leaning", "i am leaning",
        "this seems like", "this seems to be",
        "this appears to be", "this looks like",
        "this looks to be", "this looks as",
        "seems like a good", "appears to be a good",
        "looks like a good", "looks to be a good",
        "seems like the best", "appears to be the best",
        "looks like the best", "looks to be the best",
        "seems the most", "appears the most",
        "looks the most", "seems most likely",
        "appears most likely", "looks most likely",
        "most likely", "most appropriate", "most suitable",
        "most fitting", "most relevant",
        "best suited", "best fit", "best match",
        "best option is", "best choice is",
        "best answer is", "best response is",
        "best reply is", "best solution is",
        "i was thinking", "i'm thinking", "i am thinking",
        "i was wondering", "i'm wondering", "i am wondering",
        "it occurs to me", "it occurred to me",
        "i just realized", "i just noticed",
        "i had forgotten", "i almost forgot",
        "i should mention", "i should note",
        "i should add", "i should point out",
        "i want to make sure", "i want to ensure",
        "just to be safe", "just to be sure",
        "to be safe", "to be sure",
        "to avoid any confusion", "to avoid confusion",
        "to clarify", "to be clear",
        "in other words", "in short", "in brief",
        "to put it simply", "to put it briefly",
        "simply put", "simply stated",
        "put simply", "put briefly",
        "long story short", "long story short:",
        "bottom line", "the bottom line",
        "the key point", "the main point",
        "the important thing", "the crucial thing",
        "what matters is", "what's important is",
        "the thing is", "the issue is",
        "the problem is", "the challenge is",
        "the difficulty is", "the concern is",
        "i'm concerned that", "i'm worried that",
        "i'm afraid that", "i'm concerned about",
        "i need to be careful", "i should be careful",
        "i must be careful", "i have to be careful",
        "to be honest", "to tell the truth",
        "honestly", "frankly", "truthfully",
        "i realize", "i notice", "i observe",
        "i see that", "i see the", "i see an",
        "i understand now", "now i understand",
        "now i see", "now i realize",
        "i need to check", "i need to verify", "i need to confirm",
        "i need to make sure", "i need to ensure",
        "i need to look at", "i need to examine",
        "i need to consider", "i need to think about",
        "i should check", "i should verify",
        "i should consider", "i should think about",
        "i need to use only", "i should use only",
        "i must be concise", "i must be direct",
        "i must not", "i should not",
        "i will not", "i won't",
        "i cannot", "i can't",
        "i should follow", "i should stick",
        "i'll stick to", "i will stick to",
        "i'll adhere to", "i will adhere to",
        "i must follow", "i have to follow",
        "i need to follow", "i should follow the",
        "the rule says", "the rules say",
        "the instruction says", "the instructions say",
        "the prompt says", "the system says",
        "as per the rule", "as per the rules",
        "according to the rule", "according to the rules",
        "according to the instruction", "as instructed",
        "as required", "as specified",
        "to comply with", "in order to comply",
        "in line with", "consistent with the rule",
        "following the rule", "following the instruction",
        "the system prompt says", "the system instruction says",
        "i'm going to pick", "i am going to pick",
        "i'm going to choose", "i am going to choose",
        "i'm going to go with", "i am going to go with",
        "i'll pick", "i will pick",
        "i'll choose", "i will choose",
        "i'll select", "i will select",
        "i just", "i almost", "i was", "i am going", "i have got",
        "i only need", "i just need", "simply need to",
        "don't need to", "do not need to",
        "no need for", "there's no need", "there is no need",
        "nothing complex", "nothing complicated",
        "it's simple", "it is simple", "this is simple",
        "this is straightforward", "it's straightforward",
        "the solution is simple", "solution is simple",
        "just a", "this is a", "that's a", "that is a",
        "i'll keep it simple", "i'll keep it short",
        "keep it simple", "keep it short", "keep it brief",
        "not overcomplicate", "not over-complicate",
        "answer is straightforward", "response is straightforward",
        "straightforward response", "straightforward answer",
        "the response is simple", "the answer is simple",
        "simple and direct", "direct and simple",
        "just answer", "simply answer", "just respond",
        "only need to", "just need to",
        "the response is straightforward", "response is straightforward",
        "i think the best", "i believe the best",
        "i feel the best", "i reckon the best",
        "i think the", "i believe the", "i feel the",
        "i'm of the opinion", "i am of the opinion",
        "i have a preference", "i've a preference",
        "i'm partial", "i am partial",
        "i'm inclined", "i am inclined",
        "i'm tempted", "i am tempted",
        "i'm leaning towards", "i am leaning towards",
        "i'm leaning toward", "i am leaning toward",
        "i'm in favor", "i am in favor",
        "i favor", "i prefer",
        "i'm going to", "i am going to",
        "i'll", "i will", "i shall", "i should", "i must",
        "i need", "i have to", "i've", "i am", "i'm",
        "we'll", "we will", "we shall", "we should", "we must",
        "we need", "we have to", "we've", "we are", "we're",
        "it's", "it is", "that's", "that is", "there's", "there is",
        "here's", "here is", "what's", "what is", "let's", "let us",
        "i'd", "i would", "i could", "i can", "i may", "i might",
        "he's", "she's", "they're", "we're", "you're",
    ]

    def _is_meta_line(line: str) -> bool:
        stripped = line.strip()
        low = stripped.lower()
        if len(low) < 5:
            return False
        # Only flag as meta when the prefix appears at the START of the line
        # (after stripping bullets). Substring match across the whole line is
        # too aggressive — real answers like "here is the answer" would be lost.
        return any(low.startswith(p) for p in NON_BULLET_META_PREFIXES)

    kept_lines: list[str] = []
    for line in lines:
        low = line.lower().strip()

        # Numbered bolded reasoning steps.
        if re.match(r'^\d+\.\s*\*\*', low):
            continue

        # Bullet lines: skip short ones (< 300 chars) or rule-echo ones.
        if _is_bullet(line):
            if _is_rule_echo(line) or len(line.strip()) < 300:
                continue

        # Non-bullet meta lines.
        if _is_meta_line(line):
            continue

        kept_lines.append(line)

    cleaned = "\n".join(kept_lines).strip()
    if not cleaned:
        return "I'm here to help with your restaurant questions."

    # ------------------------------------------------------------------
    # PHASE 3 — keep the longest clean suffix.
    # ------------------------------------------------------------------
    SEGMENTS_SPLIT = re.compile(r'(?<=[.!?؟])\\s+')
    segments = SEGMENTS_SPLIT.split(cleaned)
    if len(segments) <= 1:
        segments = [cleaned]

    def _segment_clean(seg: str) -> bool:
        s = seg.strip()
        if len(s) < 3:
            return False
        low = s.lower()
        if _is_rule_echo(s):
            return False
        if _is_meta_line(s):
            return False
        if _is_bullet(s):
            stripped = s.lstrip("- *•>").strip().strip('"').strip("'").strip()
            if len(stripped) < 30:
                return False
        return True

    best: list[str] = []
    for i in range(len(segments) - 1, -1, -1):
        seg = segments[i]
        if _segment_clean(seg):
            best.insert(0, seg)
        else:
            if best:
                break

    if best:
        result = " ".join(best).strip()
    else:
        result = cleaned.strip()

    # Final cleanup.
    result = result.strip().strip('"').strip("'").strip()
    result = re.sub(r'\s+', ' ', result)

    if not result or len(result) < 2:
        return "I'm here to help with your restaurant questions."

    return result


def _try_fallback(messages: list[dict[str, str]], history: list) -> str | None:
    """Attempt to get a response from fallback free models.

    Called when the primary model hits a RateLimitError. Each fallback model
    is tried at most once. Only rate-limit/availability errors trigger fallback;
    other errors (auth, invalid request) are NOT retried and cause immediate failure.

    Returns a customer-facing response string, or None if no fallback succeeded.
    """
    fallbacks = config.get_fallback_models()
    if not fallbacks:
        return None

    last_rate_limit = None
    for model in fallbacks:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=config.AGENT_TEMPERATURE,
                timeout=90.0,
            )
            content = response.choices[0].message.content or ""
            history.append({"role": "user", "content": messages[-1]["content"]})
            history.append({"role": "assistant", "content": content})
            stripped = _strip_reasoning(content)
            return stripped
        except RateLimitError as e:
            # Remember the last rate-limit error for the final message.
            last_rate_limit = e
            continue
        except Exception:
            # Non-rate-limit error (auth, invalid request, etc.) — do NOT
            # fall back; return the generic error immediately.
            return "Sorry, I'm having trouble responding right now. Please try again in a moment."

    # All fallback models exhausted. Use the last rate-limit error for the message.
    if last_rate_limit is not None:
        daily_limit = "daily" in str(last_rate_limit).lower()
        if daily_limit:
            return "Sorry, the AI service has reached its daily usage limit. Please try again later."
        else:
            return "Sorry, the AI service is temporarily unavailable. Please try again in a moment."
    return None


def reply(session_id: str, user_message: str, context: str = "") -> str:
    history = get_history(session_id)
    system_prompt = _SYSTEM_PROMPT
    if context:
        system_prompt = (
            "Use the following retrieved knowledge to answer accurately. "
            "If the knowledge does not contain the answer, say you do not have that information.\n\n"
            f"{context}\n\n"
            f"{_SYSTEM_PROMPT}"
        )

    # Build messages: system + capped history + user message.
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    MAX_HISTORY = 20  # 10 user/assistant pairs
    for msg in history[-MAX_HISTORY:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = _client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=messages,
            temperature=config.AGENT_TEMPERATURE,
            timeout=90.0,
        )
        content = response.choices[0].message.content or ""
    except RateLimitError as e:
        # Free-model quota/rate-limit hit — try fallback models.
        result = _try_fallback(messages, history)
        if result is not None:
            return result
        daily_limit = "daily" in str(e).lower()
        if daily_limit:
            return "Sorry, the AI service has reached its daily usage limit. Please try again later."
        else:
            return "Sorry, the AI service is temporarily unavailable. Please try again in a moment."
    except Exception:
        return "Sorry, I'm having trouble responding right now. Please try again in a moment."

    # Store raw LLM output in history (as-is, before stripping).
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": content})

    stripped = _strip_reasoning(content)
    return stripped
