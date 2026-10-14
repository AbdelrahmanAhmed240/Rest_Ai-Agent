# Module 05 — AI Fundamentals and LLM Integration

## 1. What Role Does the Large Language Model (LLM) Play?
In `Rest_Ai-Agent`, the LLM is **not** an all-knowing database and **not** an unchecked decision maker.
Instead, the LLM functions as:
1. **A natural language understanding (NLU) interface**: Interpreting casual Arabic or English phrasing from customers.
2. **A conversational presenter**: Formatting verified system facts, prices, and summaries into polite, helpful customer service responses.
3. **A guided upselling assistant**: Politely asking if the customer would like fries, a drink, or extra sauces without aggressive pressure.

All calculations, prices, order numbers, and database writes are strictly performed by deterministic Python functions.

---

## 2. Model Client Integration in `app/services/agent.py`

Open [`app/services/agent.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/agent.py#L1-L300).
The application integrates with Google's official **Google GenAI SDK** (`google-genai`):

### Lazy Client Initialization
```python
def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = getattr(config, "GEMINI_API_KEY", "") or ""
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing. Please set it in your .env file.")
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client
```
- **Why lazy?** If someone runs unit tests or offline scripts that don't call the LLM, the application starts without crashing even if the API key is temporarily absent.

---

## 3. The 6-Section Prompt Engineering Structure

Open [`app/services/agent.py#L40-L160`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/agent.py#L40-L160).
To ensure reliable, professional responses, the system prompt follows a strict 6-part prompt architecture:

1. **Role**:
   `You are a professional, courteous, and efficient restaurant ordering and customer service AI assistant...`
2. **Task**:
   Outlines the 6 core responsibilities: Menu & Info, Recommendations, Guided Upselling, Detail Collection, Order Summary & Confirmation, and General Inquiries.
3. **Context**:
   Explicitly instructs the model that backend services and database records are the **authoritative single source of truth**. If info is missing from the provided context, state that you do not have it instead of guessing.
4. **Constraints**:
   - *Authoritative Data Only*: Never invent products, secret recipes, prices, or discounts.
   - *No Hallucinated Confirmations*: NEVER state that an order has been placed or invent an order code (like `ORD-12345`) unless the backend explicitly confirmed it.
   - *Fulfillment Field Rules*: Exact requirements for Delivery, Pickup, and Dine-in.
   - *Single-Detail Prompting*: Ask for missing details one at a time so the customer is not overwhelmed.
5. **Examples**:
   Few-shot examples demonstrating how to answer menu questions, offer upselling politely, collect missing fields, and confirm orders.
6. **Notes**:
   Tone guidelines (polite, welcoming Egyptian hospitality in Arabic and English) and formatting rules.

---

## 4. Guardrails and Reasoning Stripping

### Reasoning / CoT Sanitization (`_strip_reasoning`)
Modern thinking models (such as Gemini 2.5 Flash Thinking) sometimes emit internal thought tags (`<thought>...</thought>` or `<think>...</think>`).
In [`app/services/agent.py#L121-L194`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/agent.py#L121-L194), `_strip_reasoning()` automatically cleans any `<thought>` or `<think>` tags before the text is presented to the user:
```python
def _strip_reasoning(text: str) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<thought>.*?</thought>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()
```

---
👉 **Next**: Continue to [**Module 06: RAG and Vector Search**](./06_rag_and_vector_search.md).