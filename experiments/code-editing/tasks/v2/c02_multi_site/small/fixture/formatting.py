"""Small indentation helpers.

`INDENT` is the project-wide indentation unit. Two of the helpers below
forgot to use it and hardcode a four-space literal directly — they should
use the constant too.
"""

INDENT = "    "


def indent_line(line):
    return INDENT + line


def indent_block(lines):
    return "\n".join(INDENT + line for line in lines)


def indent_twice(line):
    return INDENT + INDENT + line


def bullet(line):
    return INDENT + "- " + line


def section(title, lines):
    return title + "\n" + "\n".join(INDENT + line for line in lines)


def numbered(lines):
    out = []
    for i, line in enumerate(lines, start=1):
        out.append("    " + f"{i}. " + line)
    return "\n".join(out)


def quoted_block(lines):
    return "\n".join("    " + "> " + line for line in lines)
