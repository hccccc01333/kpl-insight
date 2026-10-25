"""Check Git paths against the repository's explicit publication allowlist."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {
    ".git", ".secrets", ".venv", "venv", "__pycache__", "node_modules",
    "output", "logs", "weights", "raw_snapshots", "promo", "reports",
}


def load_policy():
    return json.loads((ROOT / ".public-files.json").read_text(encoding="utf-8"))


def is_allowed(name, policy):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in ("..", ".") for part in path.parts):
        return False
    if any(part.casefold() in PRIVATE_PARTS or part.casefold().startswith(".env") for part in path.parts):
        return False
    normalized = path.as_posix()
    if normalized in policy["files"]:
        return True
    return (
        path.parts[0] in policy["python_roots"]
        and len(path.parts) > 1
        and path.suffix == ".py"
        and not any(part.startswith(".") for part in path.parts)
    )


def git_paths(staged=False, ref=None):
    if ref:
        args = ["ls-tree", "-r", "--name-only", "-z", ref]
    elif staged:
        args = ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    else:
        args = ["ls-files", "-z"]
    output = subprocess.check_output(["git", *args], cwd=ROOT)
    return [name for name in output.decode("utf-8").split("\0") if name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check added/changed staged paths")
    group.add_argument("--ref", help="check paths in a committed Git revision")
    args = parser.parse_args()
    policy = load_policy()
    paths = git_paths(staged=args.staged, ref=args.ref)
    rejected = [name for name in paths if not is_allowed(name, policy)]
    if rejected:
        print("Publication blocked: these files are outside the allowlist:")
        for name in rejected:
            print("  " + name)
        print("Keep internal material local. Add a path to .public-files.json only when intended for publication.")
        raise SystemExit(1)
    print(f"Publication check passed: {len(paths)} paths.")


if __name__ == "__main__":
    main()
