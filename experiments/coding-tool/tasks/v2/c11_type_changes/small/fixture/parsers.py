"""Tiny parsing utilities — untyped on purpose."""


def parse_int(s):
    return int(s.strip())


def parse_floats(items):
    return [float(x) for x in items]


def parse_pair(text, sep):
    a, b = text.split(sep, 1)
    return a.strip(), b.strip()


def parse_kv(lines):
    return dict(parse_pair(ln, "=") for ln in lines)
