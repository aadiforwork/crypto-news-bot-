"""Merge is run ki processed.json ko repo ke latest processed.json ke saath.

Problem: news-bot aur digest dono processed.json likhte hain. Agar dono saath
chalein (ya push race ho), ek ki state doosre ko overwrite kar deti hai ->
purani news dobara bhej di jaati hai (duplicate).

Solution: dono files ka UNION lo (hashes, headlines, stories), phir commit.
Ye script run ke baad aati hai:
    python merge_processed_state.py /tmp/processed_run.json

Repo me checked-out processed.json = origin/main ka latest (workflow reset karta hai),
aur argument = is run ne jo state banayi.
"""

import json
import os
import sys


def _load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _dedupe_stories(stories):
    out, seen = [], set()
    for s in stories:
        key = tuple(sorted(s))
        if key and key not in seen:
            seen.add(key)
            out.append(sorted(s))
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: merge_processed_state.py <run_processed.json>")
        return 2

    run_file = sys.argv[1]
    repo_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed.json")

    run_state = _load(run_file)
    repo_state = _load(repo_file)

    hashes = sorted(set(run_state.get("hashes", [])) | set(repo_state.get("hashes", [])))
    titles = sorted(set(run_state.get("titles", [])) | set(repo_state.get("titles", [])))[-2000:]
    stories = _dedupe_stories(
        list(run_state.get("stories", [])) + list(repo_state.get("stories", []))
    )[-2000:]

    # Macro cache: repo (fresh) par run ki entries chadhao (is run ki latest hai)
    macro = dict(repo_state.get("macro_cache") or {})
    macro.update(run_state.get("macro_cache") or {})

    merged = {
        "hashes": hashes,
        "stories": stories,
        "titles": titles,
        "last_digest": run_state.get("last_digest") or repo_state.get("last_digest") or "",
        "macro_cache": macro,
    }

    with open(repo_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(
        f"Merged state: {len(hashes)} hashes, {len(titles)} headlines, "
        f"{len(stories)} stories, {len(macro)} macro events"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
