"""U-ST-1..5: the OpenAI stub (DESIGN 4.7), driven through the real openai SDK and over HTTP."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time

import pytest

from tests.conftest import ROOT, need_module

SYSTEM = {"role": "system", "content": "You are a helpful assistant."}


@pytest.fixture(scope="module")
def sdk(stub_url):
    from openai import OpenAI

    return OpenAI(api_key="sk-stub-test", base_url=stub_url, max_retries=0, timeout=10)


@pytest.fixture(scope="module")
def bad_sdk(stub_url):
    from openai import OpenAI

    return OpenAI(api_key="sk-stub-invalid", base_url=stub_url, max_retries=0, timeout=10)


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def embed(sdk, text):
    return sdk.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding


def core_prompt(sources: list[tuple[str, str]], question: str) -> str:
    # Same shape as app.rag.generate_answer builds it.
    context = "\n\n---\n\n".join(f"[Source: {s}]\n{c}" for s, c in sources)
    return f"""Based on these documents:
        {context}

        ---

        Question: {question}

        """


def test_UST0_import_is_side_effect_free():
    code = (
        "import os, sys, json; before = dict(os.environ); import studio.stub as s; "
        "assert hasattr(s, 'app'); "
        "bad = sorted(m for m in sys.modules if m == 'app' or m.startswith('app.') or m == 'studio.bootstrap'); "
        "print(json.dumps({'bad': bad, 'env_changed': dict(os.environ) != before}))"
    )
    need_module("studio.stub")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result == {"bad": [], "env_changed": False}


def test_UST1_embeddings_shape_norm_determinism(sdk):
    r = sdk.embeddings.create(model="text-embedding-3-small", input=["vacation policy days", "remote work"])
    assert [d.index for d in r.data] == [0, 1]
    for d in r.data:
        assert len(d.embedding) == 1536
        assert math.isclose(math.sqrt(sum(v * v for v in d.embedding)), 1.0, rel_tol=1e-5)
    again = embed(sdk, "vacation policy days")
    assert again == pytest.approx(r.data[0].embedding, abs=1e-7)
    assert embed(sdk, "vacation policy days") == pytest.approx(embed(sdk, "vacation policy days"), abs=0)


def test_UST1_python_and_http_vectors_match(sdk):
    stub = need_module("studio.stub")
    text = "Full-time employees accrue twenty days"
    assert embed(sdk, text) == pytest.approx(stub.embed_text(text), abs=1e-6)


def test_UST2_similarity_threshold_property(sdk):
    chunk = "Full-time employees accrue twenty days of paid vacation per calendar year."
    related = "How many paid vacation days do employees accrue?"
    unrelated = "zebra quantum saxophone"
    assert cos(embed(sdk, chunk), embed(sdk, related)) > 0.3
    assert cos(embed(sdk, chunk), embed(sdk, unrelated)) == pytest.approx(0.0, abs=1e-6)


def test_UST2_stopword_only_text_gets_fixed_unit_vector(sdk):
    v1, v2 = embed(sdk, "the and of"), embed(sdk, "!!! ???")
    assert v1 == v2
    assert v1[0] == pytest.approx(1.0) and sum(abs(x) for x in v1[1:]) == 0


def test_UST3_simulated_answer_format(sdk):
    prompt = core_prompt([("a.txt", "Alpha passage text."), ("b.md", "Beta passage.")], "what?")
    r = sdk.chat.completions.create(model="gpt-4o-mini", messages=[SYSTEM, {"role": "user", "content": prompt}])
    assert r.choices[0].message.content == "[Simulated answer] Based on a.txt, b.md: Alpha passage text."


def test_UST3_passage_truncated_to_200_chars(sdk):
    long = "x" * 300
    prompt = core_prompt([("a.txt", long)], "q")
    r = sdk.chat.completions.create(model="gpt-4o-mini", messages=[SYSTEM, {"role": "user", "content": prompt}])
    assert r.choices[0].message.content == f"[Simulated answer] Based on a.txt: {'x' * 200}"


def test_UST3_follow_up_marker_counts_history(sdk):
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
    ]
    prompt = core_prompt([("a.txt", "Alpha.")], "second")
    r = sdk.chat.completions.create(
        model="gpt-4o-mini", messages=[SYSTEM, *history, {"role": "user", "content": prompt}]
    )
    assert r.choices[0].message.content.endswith(" (follow-up, 2 earlier messages)")


def test_UST4_invalid_key_401_on_every_route(bad_sdk):
    import openai

    with pytest.raises(openai.AuthenticationError):
        bad_sdk.models.list()
    with pytest.raises(openai.AuthenticationError):
        bad_sdk.embeddings.create(model="text-embedding-3-small", input="x")
    with pytest.raises(openai.AuthenticationError):
        bad_sdk.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "x"}])


def test_UST4_fail_marker_400(sdk):
    import openai

    with pytest.raises(openai.BadRequestError):
        sdk.embeddings.create(model="text-embedding-3-small", input=["ok", "boom __STUB_FAIL__"])
    with pytest.raises(openai.BadRequestError):
        sdk.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "__STUB_FAIL__"}])


def test_UST4_rate_limit_marker_429_shape(stub_url):
    import httpx

    r = httpx.post(
        f"{stub_url}/embeddings",
        json={"model": "text-embedding-3-small", "input": "x __STUB_RATE_LIMIT__"},
        headers={"Authorization": "Bearer sk-stub-test"},
    )
    assert r.status_code == 429
    assert "retry-after" not in {k.lower() for k in r.headers}
    assert r.json() == {
        "error": {"message": r.json()["error"]["message"], "type": "requests", "param": None, "code": "rate_limit_exceeded"}
    }


def test_UST4_rate_limit_raises_sdk_error(sdk):
    import openai

    with pytest.raises(openai.RateLimitError):
        sdk.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "__STUB_RATE_LIMIT__"}]
        )


@pytest.mark.slow
def test_UST4_slow_marker_delays_about_3s(sdk):
    t0 = time.monotonic()
    embed(sdk, "slow __STUB_SLOW__")
    assert 2.8 <= time.monotonic() - t0 < 6


def test_UST4_models_and_health(sdk, stub_url):
    import httpx

    ids = {m.id for m in sdk.models.list()}
    assert {"text-embedding-3-small", "gpt-4o-mini"} <= ids
    assert httpx.get(stub_url.removesuffix("/v1") + "/health").status_code == 200


def test_UST5_python_m_stub_honours_port_flag_over_env():
    need_module("studio.stub")
    from tests.conftest import _free_port

    flag_port, env_port = _free_port(), _free_port()
    import os

    env = dict(os.environ, STUB_PORT=str(env_port), STUB_HOST="127.0.0.1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "studio.stub", "--host", "127.0.0.1", "--port", str(flag_port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        import httpx

        deadline = time.monotonic() + 20
        ok = False
        while time.monotonic() < deadline and not ok:
            try:
                ok = httpx.get(f"http://127.0.0.1:{flag_port}/health", timeout=1).status_code == 200
            except httpx.HTTPError:
                time.sleep(0.2)
        assert ok, "stub not listening on the --port value"
        with pytest.raises(httpx.HTTPError):
            httpx.get(f"http://127.0.0.1:{env_port}/health", timeout=1)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
