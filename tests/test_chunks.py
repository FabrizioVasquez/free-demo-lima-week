import re
from types import SimpleNamespace

from brujula.index import BUDGET, MAX_CHUNKS, OVERLAP, chunks_of


class WordTok:
    """Tokenizador de juguete: 1 palabra = 1 token. Basta para probar la lógica de ventanas sin descargar el modelo."""

    def encode(self, text, add_special_tokens=False):
        spans = [m.span() for m in re.finditer(r"\S+", text)]
        return SimpleNamespace(ids=list(range(len(spans))), offsets=spans)


def ev(words: int, name: str = "Evento de prueba") -> dict:
    return {"name": name, "hosts": ["Org"], "description": " ".join(f"w{i}" for i in range(words))}


def ntok(text: str) -> int:
    return len(text.split())


def test_no_chunk_exceeds_budget():
    for n in (5, 90, 500, 5000):
        for text, _ in chunks_of(ev(n), WordTok()):
            assert ntok(text) <= BUDGET, (n, ntok(text))


def test_long_name_cannot_eat_the_budget():
    for text, _ in chunks_of(ev(400, name="palabra " * 200), WordTok()):
        assert ntok(text) <= BUDGET


def test_windows_overlap_and_cover_the_text():
    parts = [b for _, b in chunks_of(ev(300), WordTok())]
    assert len(parts) > 1
    assert set(parts[0].split()) & set(parts[1].split()), "ventanas vecinas deben compartir texto"
    assert "w299" in parts[-1], "el final de la descripción no puede perderse"
    assert OVERLAP > 0


def test_chunk_cap_and_empty_description():
    assert len(chunks_of(ev(100_000), WordTok())) == MAX_CHUNKS
    only_head = chunks_of({"name": "X", "hosts": [], "description": ""}, WordTok())
    assert only_head == [("X.", "")] or only_head[0][1] == ""


def test_urls_are_stripped_before_embedding():
    d = ev(10)
    d["description"] = "mira https://luma.com/abc ahora"
    assert all("https://" not in t for t, _ in chunks_of(d, WordTok()))
