"""
Ceylon Compass - AI Sri Lanka Travel Guide (Flask backend)

Flow:
  1. User asks about a place, itinerary, or travel topic
  2. Groq (LLM) generates a clear, structured travel answer
  3. If the user's wording asks for a visual, Groq is called AGAIN to
     describe the topic as Mermaid.js flowchart syntax (text-based
     diagram definition) - not an image-generation prompt. For trip
     questions this becomes an itinerary/route flow (e.g. Colombo ->
     Kandy -> Ella); for other topics it's a general step diagram.
     Diffusion image models are unreliable at rendering readable
     labels/text, so diagrams are rendered client-side by Mermaid.js
     instead, which is deterministic and always legible.
  4. Both the answer and the Mermaid diagram source are returned to
     the frontend, which renders the diagram in the browser.
"""

import os
import requests
import re
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

# Keep network calls from hanging the whole request forever
REQUEST_TIMEOUT = 20  # seconds


def call_groq(messages, max_tokens=600):
    """
    Thin wrapper around the Groq chat-completions endpoint.
    Groq mirrors the OpenAI API shape, so this is a plain REST call -
    no special SDK needed, which keeps the dependency list tiny.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Check your .env file.")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }

    response = requests.post(
        GROQ_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()  # turns 4xx/5xx into a Python exception
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


# Word-count ceiling + a matching max_tokens budget for each length preset.
# max_tokens is set generously above the word target since tokens != words
# and we don't want the model getting cut off mid-sentence.
LENGTH_PRESETS = {
    "short":  {"word_limit": 100,  "max_tokens": 350},
    "medium": {"word_limit": 200,  "max_tokens": 600},
    "long":   {"word_limit": 400,  "max_tokens": 1000},
}

DEFAULT_PROMPT_TEMPLATE = """<role>
You are Ceylon Compass, a friendly and knowledgeable Sri Lanka travel
guide. You help travelers discover places, plan visits, and understand
the culture, history, food, and practicalities of visiting Sri Lanka.
</role>
<task>
Respond to the following from a traveler:
{user_topic}
</task>
<format>
- If the traveler's message explicitly asks for a specific format or
  length (e.g. "in one sentence", "briefly", "just give me the highlights"),
  follow THAT instruction exactly instead of the format below — the
  traveler's own request always takes priority.
- Otherwise, use this default format:
  - Start with a 1-2 sentence plain-language summary
  - Follow with 3-5 bullet points covering key practical details
    (what to see/do, best time to visit, how to get there, cost/entry
    info, or cultural notes — whichever are most relevant)
  - End with EXACTLY ONE closing line starting with "Insider tip:" —
    do not add any other closing sections (no separate "Best time",
    "Practical tip", or similar extra bullets after the main list;
    fold any such detail into the 3-5 bullets above instead)
  - Keep the total response under {word_limit} words
- Always avoid unnecessary jargon; briefly explain any local term
  (e.g. "tuk-tuk", "poya day") you use
  - ALWAYS use Sri Lankan Rupees for any price/cost mentioned. Write
  amounts as "LKR 2,500" or "Rs. 2,500" — never the ₹ symbol (that is
  India's currency, not Sri Lanka's) and never USD/EUR/other symbols
  unless the traveler specifically asks for a different currency.
- Do NOT include ASCII art, box-drawing characters, code blocks, or
  hand-drawn-style diagrams in this text response. Describe routes and
  itineraries in plain words only — a separate feature renders an actual
  diagram/itinerary flow when the traveler asks for one, so a text
  diagram here would just be redundant and hard to read.
</format>"""


GREETINGS = {
    "hi", "hello", "hey", "hiya", "yo", "sup", "howdy",
    "good morning", "good afternoon", "good evening",
    "thanks", "thank you", "ok", "okay", "bye", "goodbye",
}


def is_smalltalk(topic: str) -> bool:
    """
    Catches greetings/small talk so they don't get forced through the
    full explanation template (which would produce a weirdly formal
    "travel guide" response to the word "hi"). Kept as a plain set
    lookup - no API call needed, which also saves a Groq request on
    every "hi".
    """
    return topic.strip().lower().rstrip("!.?") in GREETINGS


def get_explanation(topic: str, length: str = "medium", custom_prompt: str = None) -> str:
    """
    Step 1: ask Groq for a clear, structured explanation.

    - `length` picks a word-limit/token-budget preset (short/medium/long).
    - `custom_prompt` lets the caller fully override the template (must
      contain "{user_topic}"; "{word_limit}" is optional). This is what
      powers the "edit prompt" advanced option in the UI.
    """
    preset = LENGTH_PRESETS.get(length, LENGTH_PRESETS["medium"])
    template = custom_prompt if custom_prompt else DEFAULT_PROMPT_TEMPLATE

    if "{user_topic}" not in template:
        raise ValueError("Custom prompt must include a {user_topic} placeholder.")

    prompt = template.format(
        user_topic=topic,
        word_limit=preset["word_limit"],
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Follow the user's instructions exactly, including any "
                "format, tone, or length constraints they specify."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    return call_groq(messages, max_tokens=preset["max_tokens"])


def get_diagram_mermaid(topic: str, explanation: str) -> str:
    """
    Step 2: ask Groq to describe the topic as a Mermaid.js flowchart
    (text-based diagram syntax), NOT as an image-generation prompt.

    For a travel guide, this is most useful as a trip itinerary flow
    (Morning -> Afternoon -> Evening, or Place A -> Place B -> Place C)
    rather than an abstract concept diagram - so the instructions steer
    the model toward that when the topic is itinerary/route-shaped, but
    still fall back to a general step diagram for other topics (e.g.
    "how to get a Sri Lanka visa on arrival").

    Why Mermaid instead of an image-generation model: diffusion image
    models (like the free Pollinations API) are unreliable at rendering
    readable text and structured boxes/arrows - they tend to hallucinate
    loosely related pictures instead of an actual labeled diagram.
    Mermaid.js renders deterministically from text, so the diagram is
    always accurate and legible; the LLM only has to describe structure,
    not pixels.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You output ONLY valid Mermaid.js flowchart syntax describing "
                "the given travel topic as a step-by-step diagram. Rules:\n"
                "- Start with 'flowchart TD' (top-down).\n"
                "- If the topic is a trip/itinerary/route, make nodes the "
                "stops or time-of-day segments in visiting order (e.g. "
                "Colombo -> Kandy -> Ella). Otherwise, make nodes the "
                "logical steps of the process (e.g. visa steps, how to "
                "reach a site).\n"
                "- Use short, clear node labels (2-5 words each).\n"
                "- 4-8 nodes is ideal - enough to be useful, not cluttered.\n"
                "- Use --> for normal steps and -->|label| for a branch "
                "(e.g. a day-trip option or alternate route).\n"
                "- Do NOT include markdown code fences, the word 'mermaid', "
                "or any explanation - output raw flowchart syntax only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Topic: {topic}\nExplanation: {explanation}\n\n"
                f"Write a Mermaid flowchart that diagrams {topic}."
            ),
        },
    ]
    raw = call_groq(messages, max_tokens=250)
    cleaned = clean_mermaid_output(raw)

    # Groq occasionally returns an empty/near-empty completion for this
    # call (observed in testing - not a code bug, just LLM flakiness).
    # Retry once before giving up, since a second attempt usually succeeds.
    if not cleaned:
        raw = call_groq(messages, max_tokens=250)
        cleaned = clean_mermaid_output(raw)

    if not cleaned:
        # Raising here (instead of returning "") ensures the caller's
        # try/except sets a visible diagram_error instead of silently
        # returning an empty diagram with no explanation at all.
        raise RuntimeError("Groq returned an empty diagram response.")

    return cleaned


def clean_mermaid_output(raw: str) -> str:
    """
    Groq sometimes wraps output in ```mermaid fences despite instructions
    not to. Strip those defensively so the frontend always gets raw syntax.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening ```mermaid or ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # drop closing ```
        text = "\n".join(lines).strip()
    return text


# Keywords that signal the user explicitly wants a visual, not just an
# explanation. Kept simple (substring match) on purpose - a portfolio
# project doesn't need an ML classifier for this, and it's easy to explain
# in an interview. Extend this list if you find real requests slipping through.
DIAGRAM_REQUEST_KEYWORDS = (
    "draw", "diagram", "image", "picture", "illustrate", "illustration",
    "visualize", "visualise", "visual", "show me", "sketch", "chart",
    "graphic", "photo", "generate an image", "create an image",
    "flowchart", "flow chart", "itinerary", "route", "trip plan",
    "day plan", "map out", "plan a trip", "plan my trip", "day trip",
    "days in", "trip from", "journey from",
)

_DAY_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|\\d+"
)
DAY_TRIP_PATTERN = re.compile(
    rf"\b({_DAY_NUMBER_WORDS})\s*-?\s*days?\b", re.IGNORECASE
)

def wants_diagram(topic: str) -> bool:
    lowered = topic.lower()
    if any(keyword in lowered for keyword in DIAGRAM_REQUEST_KEYWORDS):
        return True
    return bool(DAY_TRIP_PATTERN.search(lowered))

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    length = (data.get("length") or "medium").strip().lower()
    custom_prompt = data.get("custom_prompt")  # optional advanced override
    if custom_prompt is not None:
        custom_prompt = custom_prompt.strip() or None

    # --- basic input validation ---
    if not topic:
        return jsonify({"error": "Please enter a topic or question."}), 400
    if len(topic) > 4000:
        return jsonify({"error": "That's too long — please shorten it a bit."}), 400

    # Small talk short-circuits everything below: no template, no image,
    # no wasted Groq call for the heavy explanation prompt.
    if is_smalltalk(topic):
        return jsonify(
            {
                "topic": topic,
                "explanation": "Ayubowan! 🙏 Ask me about any place, "
                "itinerary, or travel topic in Sri Lanka — add a word "
                "like \"itinerary\" or \"draw\" if you'd also like a "
                "route/trip diagram.",
                "diagram": None,
                "diagram_error": None,
            }
        )

    try:
        explanation = get_explanation(topic, length=length, custom_prompt=custom_prompt)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except requests.exceptions.Timeout:
        return jsonify({"error": "The AI service timed out. Please try again."}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to reach Groq API: {e}"}), 502
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    # Diagram generation only runs when the user's wording asks for a visual.
    # It's still treated as "nice to have" - if it fails, we still return
    # the text explanation rather than failing the whole request.
    diagram = None
    diagram_error = None
    if wants_diagram(topic):
        try:
            diagram = get_diagram_mermaid(topic, explanation)
        except Exception as e:
            diagram_error = f"Diagram could not be generated: {e}"

    return jsonify(
        {
            "topic": topic,
            "explanation": explanation,
            "diagram": diagram,
            "diagram_error": diagram_error,
        }
    )


if __name__ == "__main__":
    app.run(port=5000)