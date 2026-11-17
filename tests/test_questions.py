"""Run: .venv/bin/python tests/test_questions.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tekbro.questions import looks_like_question

SHOULD_ANSWER = [
    "Can you explain how a hash map works and what its time complexity is?",
    "Hi, how are you? Can you explain how a hash map works?",
    "Hey John, so can you reverse a linked list for me?",
    "Okay, great. Let's say you have an array of integers and a target, find two numbers that sum to it.",
    "Given a string, return the longest palindromic substring.",
    "Why?",
    "How so?",
    "What's the time complexity?",
    "Tell me about a time you had a conflict with a teammate.",
    "Design a URL shortener.",
    "Write a function that checks if a binary tree is balanced.",
    "So what would you do if the input doesn't fit in memory?",
    "Você pode explicar a diferença entre processo e thread?",
    "Oi, tudo bem? Como funciona o garbage collector do Java?",
    "Por quê?",
    "Qual a complexidade desse algoritmo?",
    "Dado um array de inteiros, encontre o maior subarray contíguo.",
    "Me fala sobre um projeto difícil que você fez.",
]
SHOULD_IGNORE = [
    "Hi, how are you?",
    "Hello! How's it going?",
    "Good morning, nice to meet you.",
    "Can you hear me?",
    "Can you see my screen?",
    "Is my audio okay?",
    "Are you there?",
    "You're on mute.",
    "Shall we get started?",
    "Are you ready?",
    "Thanks for your time today.",
    "How was your weekend?",
    "Do you have any questions for us?",
    "One second, let me share my screen.",
    "Okay.",
    "Yeah, sure.",
    "Right?",
    "Oi, tudo bem?",
    "Bom dia, tudo bom?",
    "Tá me ouvindo?",
    "Consegue ver minha tela?",
    "Podemos começar?",
    "Prazer, obrigado por participar.",
    "Você me ouve?",
]
fails = 0
for t in SHOULD_ANSWER:
    if not looks_like_question(t): print("MISSED  ", t); fails += 1
for t in SHOULD_IGNORE:
    if looks_like_question(t): print("FALSE+  ", t); fails += 1
print(f"{len(SHOULD_ANSWER)+len(SHOULD_IGNORE)-fails}/{len(SHOULD_ANSWER)+len(SHOULD_IGNORE)} passed")
sys.exit(1 if fails else 0)
