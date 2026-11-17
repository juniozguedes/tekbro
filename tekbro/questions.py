"""Decides whether a transcript line is a real question worth answering (EN + PT).

Each sentence is judged on its own: small talk ("hi, how are you?", "can you hear
me?", "tudo bem?") is ignored, so "Hi, how are you? Can you explain how a hash
map works?" still triggers on the second sentence.
"""
import re
import unicodedata

# Sentences that are only small talk / call logistics. Matched after normalising
# (lowercase, no accents), against the start of each sentence.
SMALL_TALK = [
    # greetings & pleasantries
    r"(hi|hello|hey|hiya|good (morning|afternoon|evening)|oi|ola|e ai|bom dia|boa tarde|boa noite)\b",
    r"how (are|r) (you|u|things)", r"how('s| is) (it going|everything|your day|life)",
    r"how (was|were) your (day|weekend|week|morning)", r"what'?s up\b", r"you doing (ok|well|good)",
    r"nice to (meet|see) you", r"(it'?s )?(great|good|nice) to (meet|see) you", r"pleasure to meet",
    r"thanks?( you)? (for|so much)", r"thank you\b",
    r"tudo (bem|bom|certo|tranquilo)", r"como (vai|voce esta|voce ta|esta|ta|anda)",
    r"(muito )?prazer", r"obrigad[oa]", r"valeu\b", r"beleza\b",
    # call logistics
    r"(can|could|do) (you|everyone|everybody) (hear|see) (me|us|my|it|that|this)",
    r"(is|was) my (audio|mic|microphone|camera|screen|video|connection)",
    r"(am i|are you) (audible|there|on mute|muted|back)", r"(you'?re|you are) (on )?mute",
    r"(is|was) (it|that|this) (loud|clear|visible)",
    r"(are you|is everyone) ready", r"(shall|should|can) we (start|begin|get started|kick off)",
    r"ready to (start|begin|get started)", r"let me (share|stop sharing)", r"one (second|moment|sec)",
    r"(do you|did you) (have|get) (any|some) questions? for (me|us)",
    r"(voce|vc|tu) (me )?(ouve|escuta|ve)\b", r"(consegue|da pra|da para) (me )?(ouvir|ver|escutar)",
    r"(ta|esta|tao|estao) me (ouvindo|escutando|vendo)", r"(ta|esta) (dando para|dando pra) (ouvir|ver)",
    r"(podemos|vamos|bora) (comecar|iniciar)", r"(pronto|preparado) (pra|para) comecar",
    r"(meu|o) (audio|microfone|som) (ta|esta)", r"so um (segundo|minuto|momento)",
]
_SMALL_TALK_RE = re.compile(r"^(?:(?:so|ok|okay|well|alright|great|cool|entao|bom|certo)[, ]+)?(?:" + "|".join(SMALL_TALK) + ")")

QUESTION_STARTS = (
    # en
    "what", "how", "why", "when", "where", "which", "who", "can you", "could you",
    "would you", "do you", "have you", "is it", "is there", "are there", "explain", "tell me",
    "describe", "walk me", "design", "implement", "write", "give me", "let's say", "lets say",
    "suppose", "imagine", "say you", "let's", "lets", "solve", "find", "given",
    # pt
    "o que", "como", "por que", "porque", "quando", "onde", "qual", "quais", "quem",
    "voce pode", "voce poderia", "pode", "poderia", "explique", "explica", "me fala", "fale",
    "descreva", "implemente", "escreva", "me conta", "vamos supor", "suponha", "imagine",
    "dado", "dada", "resolva", "encontre",
)

# Short follow-ups that are real questions despite being 1-2 words.
SHORT_FOLLOWUPS = {"why", "how", "how so", "why not", "and why", "then what", "like what",
                   "por que", "porque", "como assim", "e por que", "por que nao", "tipo o que"}
MIN_WORDS = 3


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[tuple[str, bool]]:
    """Split into (sentence, ended_with_question_mark)."""
    parts = re.findall(r"[^.?!]+[.?!]?", text)
    return [(p.strip(" .!?,"), p.strip().endswith("?")) for p in parts if p.strip(" .!?,")]


def _strip_small_talk(s: str) -> str:
    """Remove leading small-talk clauses ("hi john, so can you…" → "can you…")."""
    while True:
        m = _SMALL_TALK_RE.match(s)
        if not m:
            return s
        rest = s[m.end():]
        # drop the rest of that clause (up to a comma) when it's still chit-chat
        rest = re.sub(r"^[^,]{0,25},\s*", "", rest) if "," in rest[:26] else rest
        rest = rest.lstrip(" ,;-")
        if rest == s:
            return s
        s = rest


def question_sentences(text: str) -> list[str]:
    """The sentences in `text` that look like real questions / tasks."""
    found = []
    for raw, has_qmark in _sentences(_normalise(text)):
        s = _strip_small_talk(raw)
        words = s.split()
        if not words:
            continue
        if s in SHORT_FOLLOWUPS:
            found.append(s)
            continue
        if len(words) < MIN_WORDS:
            continue
        if has_qmark or s.startswith(QUESTION_STARTS):
            found.append(s)
    return found


def looks_like_question(text: str) -> bool:
    return bool(question_sentences(text))
