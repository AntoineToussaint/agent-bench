"""band_instance_ids: pick SWE-bench ids by band from a difficulty CSV (no network)."""

from __future__ import annotations

from file_localization.difficulty import band_instance_ids


def _csv(tmp_path):
    p = tmp_path / "swebench_verified_difficulty.csv"
    p.write_text(
        "instance_id,repo,n_solved,n_total,pass_rate\n"
        "django__django-1,django/django,0,30,0.00\n"     # unsolved
        "django__django-2,django/django,3,30,0.10\n"      # hard
        "astropy__astropy-3,astropy/astropy,6,30,0.20\n"   # hard
        "sympy__sympy-4,sympy/sympy,15,30,0.50\n"          # medium
        "requests__requests-5,psf/requests,29,30,0.97\n"   # easy
    )
    return p


def test_hard_band_ids(tmp_path):
    ids = band_instance_ids(_csv(tmp_path), "hard")
    assert ids == ["django__django-2", "astropy__astropy-3"]  # sorted by pass_rate


def test_unsolved_and_easy(tmp_path):
    csv = _csv(tmp_path)
    assert band_instance_ids(csv, "unsolved") == ["django__django-1"]
    assert band_instance_ids(csv, "easy") == ["requests__requests-5"]


def test_n_caps_and_is_deterministic(tmp_path):
    csv = _csv(tmp_path)
    a = band_instance_ids(csv, "hard", 1, seed=3)
    b = band_instance_ids(csv, "hard", 1, seed=3)
    assert len(a) == 1 and a == b


def test_custom_hard_threshold(tmp_path):
    # tighten "hard" to <=0.10 → only the 0.10 task qualifies (0.20 drops to medium)
    ids = band_instance_ids(_csv(tmp_path), "hard", hard_max=0.10)
    assert ids == ["django__django-2"]
