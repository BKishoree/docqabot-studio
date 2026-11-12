"""U-CH: characterisation of the frozen app.chunker.chunk_document.

These tests pin the core's current behaviour (quirks included) so any change to it
is visible. They do not ask for behaviour changes: the core is frozen.
"""

from __future__ import annotations

from app.chunker import chunk_document


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_UCH1_empty_input_returns_one_empty_chunk():
    # Quirk: the core returns [""] and process_document filters empty chunks itself.
    assert chunk_document("") == [""]
    assert chunk_document("   ") == [" "]


def test_UCH2_short_text_is_one_chunk_unchanged():
    text = "One paragraph.\n\nSecond paragraph with\na single newline."
    assert chunk_document(text) == [text]


def test_UCH3_whitespace_normalisation():
    assert chunk_document("a    b") == ["a b"]
    assert chunk_document("a\n\n\n\n\nb") == ["a\n\nb"]
    assert chunk_document("a\tb") == ["a\tb"]  # tabs are not normalised


def test_UCH4_400_word_limit_counts_whole_paragraphs():
    paras = [words(100, f"p{i}_") for i in range(10)]
    chunks = chunk_document("\n\n".join(paras))
    # 4 paragraphs of 100 words fill the first chunk exactly
    assert chunks[0] == "\n\n".join(paras[:4])
    assert len(chunks[0].split()) == 400
    # later chunks: 50 overlap words + 3 paragraphs (350 <= 400): p4-p6, p7-p9
    assert len(chunks) == 3
    for c in chunks[1:]:
        assert len(c.split()) <= 400


def test_UCH5_overlap_is_last_50_words_of_previous_chunk():
    paras = [words(100, f"p{i}_") for i in range(10)]
    chunks = chunk_document("\n\n".join(paras))
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.split()[:50] == prev.split()[-50:]
        # overlap is its own leading paragraph
        assert cur.split("\n\n")[0] == " ".join(prev.split()[-50:])


def test_UCH6_paragraphs_are_never_split():
    paras = [words(70 + i * 13, f"p{i}_") for i in range(12)]
    chunks = chunk_document("\n\n".join(paras))
    for p in paras:
        holders = [c for c in chunks if p in c.split("\n\n")]
        assert len(holders) == 1, f"paragraph starting {p[:10]} found in {len(holders)} chunks"


def test_UCH7_all_text_kept_in_order():
    paras = [words(90, f"p{i}_") for i in range(9)]
    chunks = chunk_document("\n\n".join(paras))
    rebuilt = []
    for i, c in enumerate(chunks):
        parts = c.split("\n\n")
        rebuilt += parts if i == 0 else parts[1:]  # drop the overlap paragraph
    assert rebuilt == paras


def test_UCH8_oversize_single_paragraph_is_not_split():
    big = words(1000)
    assert chunk_document(big) == [big]


def test_UCH9_oversize_paragraph_after_others_gets_overlap_and_stays_whole():
    small, big = words(10, "s"), words(900, "b")
    chunks = chunk_document(small + "\n\n" + big)
    assert chunks == [small, small + "\n\n" + big]  # previous chunk has < 50 words, all used as overlap


def test_UCH10_custom_sizes_and_no_overlap():
    paras = [words(5, f"p{i}_") for i in range(6)]
    chunks = chunk_document("\n\n".join(paras), chunk_size=10, overlap=0)
    assert chunks == ["\n\n".join(paras[i : i + 2]) for i in range(0, 6, 2)]


def test_UCH11_deterministic():
    text = "\n\n".join(words(120, f"p{i}_") for i in range(7))
    assert chunk_document(text) == chunk_document(text)


def test_UCH12_returns_list_of_str():
    out = chunk_document("hello world")
    assert isinstance(out, list) and all(isinstance(c, str) for c in out)
